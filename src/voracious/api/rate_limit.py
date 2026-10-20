"""Límite de peticiones por IP de cliente (paso E): cubo de fichas en memoria, ASGI puro.

Va **antes** de la autenticación, así que también acota las ráfagas de ``401``, y nunca lee el
cuerpo. La clave es la IP de ``scope["client"]``, que ``ProxyHeadersMiddleware`` (la capa más
exterior) ya reescribió con la del cliente real cuando la petición llega del proxy de confianza.
Al agotarse el cubo responde ``429 RATE_LIMITED`` con ``Retry-After`` y
``details.retry_after_seconds`` en el formato uniforme.

El estado vive en el proceso: es exacto con un solo worker de uvicorn (la imagen arranca uno) y se
pierde al reiniciar. No hace falta candado: la cuenta de cada petición se hace sin ``await``, de
una vez, en el bucle de eventos (un solo hilo).
"""

import ipaddress
import math
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Final

from starlette.types import ASGIApp, Receive, Scope, Send

from voracious.api.errors import error_response

__all__ = ["RATE_LIMITED", "RateLimitMiddleware", "is_loopback"]

RATE_LIMITED: Final = "RATE_LIMITED"
"""Código de error: demasiadas peticiones desde la misma IP de cliente (``429``)."""

DEFAULT_MAX_KEYS: Final = 10_000
"""IP distintas que se recuerdan a la vez; al pasarse se olvida la menos reciente (LRU)."""

_UNKNOWN_CLIENT: Final = ""
"""Clave común de las peticiones sin ``client`` (p. ej. por un socket Unix): un solo cubo."""


def is_loopback(host: str) -> bool:
    """Indica si ``host`` es una IP de loopback (``127.0.0.0/8``, ``::1`` o ``::ffff:127.x``).

    Args:
        host: Host de ``scope["client"]``.

    Returns:
        ``True`` solo si es una IP de loopback; un nombre o un texto que no es IP da ``False``
        (falla cerrado: se limita como cualquier otro cliente).
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


@dataclass(slots=True)
class _Bucket:
    """Cubo de fichas de una IP.

    Attributes:
        tokens: Fichas disponibles (fraccionarias: se rellenan de forma continua).
        updated: Instante (reloj del middleware) de la última cuenta.
    """

    tokens: float
    updated: float


class RateLimitMiddleware:
    """Middleware ASGI que limita las peticiones HTTP por IP de cliente.

    Cada IP tiene un cubo de capacidad ``burst`` que se rellena a ``per_minute / 60`` fichas por
    segundo; cada petición gasta una. Quedan exentas las IP de loopback: el ``HEALTHCHECK`` de la
    imagen y el comprobador de la puerta de despliegue (``scripts/check_auth_surface.py``) llaman
    desde dentro del contenedor. Solo cuenta ``http``: ``lifespan`` y WebSocket pasan intactos.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        per_minute: int,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = DEFAULT_MAX_KEYS,
    ) -> None:
        """Construye el middleware.

        Args:
            app: Aplicación ASGI interior.
            per_minute: Peticiones por minuto sostenidas por IP (``>= 1``).
            burst: Capacidad del cubo, la ráfaga admitida por IP (``>= 1``).
            clock: Reloj monótono en segundos (inyectable en los tests).
            max_keys: IP recordadas a la vez (``>= 1``). Olvidar una le devuelve el cubo lleno:
                una ráfaga desde más de ``max_keys`` IP distintas no se acota aquí (eso lo filtra
                la red), pero la memoria sí queda acotada.

        Raises:
            ValueError: Si algún límite es menor que 1.
        """
        if per_minute < 1 or burst < 1 or max_keys < 1:
            msg = "per_minute, burst y max_keys deben ser >= 1"
            raise ValueError(msg)
        self.app = app
        self._rate = per_minute / 60.0
        self._burst = float(burst)
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Atiende una conexión ASGI.

        Args:
            scope: Scope.
            receive: Canal de entrada (nunca se lee aquí).
            send: Canal de salida.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        host = str(client[0]) if client else _UNKNOWN_CLIENT
        if is_loopback(host):
            await self.app(scope, receive, send)
            return
        wait = self._take(host)
        if wait is None:
            await self.app(scope, receive, send)
            return
        response = error_response(
            HTTPStatus.TOO_MANY_REQUESTS,
            RATE_LIMITED,
            "demasiadas peticiones; espera antes de reintentar",
            {"retry_after_seconds": wait},
            headers={"Retry-After": str(wait)},
        )
        await response(scope, receive, send)

    def _take(self, key: str) -> int | None:
        """Gasta una ficha del cubo de ``key``.

        Args:
            key: IP del cliente.

        Returns:
            ``None`` si había ficha; si no, los segundos enteros (``>= 1``) hasta la siguiente.
        """
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self._burst, updated=now)
            self._buckets[key] = bucket
            if len(self._buckets) > self._max_keys:
                self._buckets.popitem(last=False)
        else:
            self._buckets.move_to_end(key)
            elapsed = max(0.0, now - bucket.updated)
            bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._rate)
            bucket.updated = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return None
        return max(1, math.ceil((1.0 - bucket.tokens) / self._rate))
