"""Registro de acceso por petición (mejora M2): quién, qué ruta, con qué resultado y cuánto tardó.

Una línea JSON ``http_request`` por petición HTTP con ``method``, ``route`` (la **plantilla**,
p. ej. ``/v1/charts/t2mrcd/models/{model_id}``: sin identificadores), ``status``,
``duration_ms`` y ``client`` (la IP del cliente sin puerto, la real si llegó por el proxy de
confianza; paso E); si el token fue válido, ``sub``, ``tenant`` y ``jti``, y si no,
``auth_failure`` con el motivo del ``401``. Nunca el token, la query, las cabeceras ni los
cuerpos. Es una auditoría ligera, no la auditoría completa del paso de seguridad grande. La IP es
un dato personal: la retención la acota la rotación de logs del despliegue.

Las rutas públicas (``/health``, ``/ready`` y la documentación) y los *preflight* de CORS van a
nivel ``debug``: el ``HEALTHCHECK`` de Docker pide ``/health`` cada 30 s y un front en navegador
manda un *preflight* antes de casi cada petición; llenarían el registro.
"""

import re
import time
from collections.abc import Callable, Collection, Mapping
from typing import Final

import structlog
from starlette.routing import compile_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from voracious.api.auth import AUTH_FAILURE_STATE, PRINCIPAL_STATE, PUBLIC_PATHS
from voracious.application.auth import Principal

__all__ = ["ACCESS_EVENT", "UNMATCHED_ROUTE", "AccessLogMiddleware", "RouteTable", "is_preflight"]

_log = structlog.get_logger(__name__)

ACCESS_EVENT: Final = "http_request"
"""Nombre del evento del registro de acceso."""

UNMATCHED_ROUTE: Final = "<unmatched>"
"""``route`` de una petición que no corresponde a ninguna ruta (nunca se registra la ruta cruda)."""

RouteTable = Callable[[], Mapping[str, Collection[str]]]
"""Plantillas de las rutas de la aplicación y sus métodos (las de OpenAPI)."""

_SERVER_ERROR: Final = 500


def is_preflight(scope: Scope) -> bool:
    """Indica si la petición es un *preflight* de CORS.

    Args:
        scope: Scope HTTP.

    Returns:
        ``True`` si es ``OPTIONS`` con ``Origin`` y ``Access-Control-Request-Method`` (el criterio
        de ``CORSMiddleware``).
    """
    if scope.get("method") != "OPTIONS":
        return False
    names = {name.lower() for name, _ in scope.get("headers", ())}
    return b"origin" in names and b"access-control-request-method" in names


class AccessLogMiddleware:
    """Middleware ASGI exterior que registra cada petición HTTP al terminar.

    Va **fuera** de ``AuthenticationMiddleware``: así registra también los ``401``, con el motivo
    que ese middleware deja en ``scope["state"]``. La plantilla se resuelve con la tabla de rutas
    (la de OpenAPI) y no con el enrutado, porque un ``401`` responde antes de enrutar.
    """

    def __init__(
        self, app: ASGIApp, routes: RouteTable, public_paths: frozenset[str] = PUBLIC_PATHS
    ) -> None:
        """Construye el middleware.

        Args:
            app: Aplicación ASGI interior.
            routes: Tabla de rutas (plantilla → métodos); se lee y compila en la primera
                petición, cuando ya están registrados todos los routers.
            public_paths: Rutas públicas (las de ``AuthenticationMiddleware``): se registran tal
                cual y a nivel ``debug``.
        """
        self.app = app
        self._routes = routes
        self._public_paths = public_paths
        self._compiled: list[tuple[re.Pattern[str], str, frozenset[str]]] | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Atiende una conexión ASGI y registra la petición al terminar.

        Args:
            scope: Scope.
            receive: Canal de entrada.
            send: Canal de salida.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status: list[int] = []

        async def record_status(message: Message) -> None:
            if message["type"] == "http.response.start":
                status.append(int(message["status"]))
            await send(message)

        try:
            await self.app(scope, receive, record_status)
        except Exception:
            if not status:
                status.append(_SERVER_ERROR)
            raise
        finally:
            self._log(scope, status[0] if status else None, time.perf_counter() - started)

    def _table(self) -> list[tuple[re.Pattern[str], str, frozenset[str]]]:
        """Plantillas compiladas, las más literales primero.

        Así ``/pipelines/phase1`` gana a ``/pipelines/{pipeline_id}``.

        Returns:
            ``(expresión, plantilla, métodos)`` de cada ruta.
        """
        if self._compiled is None:
            compiled = [
                (compile_path(template)[0], template, frozenset(m.upper() for m in methods))
                for template, methods in self._routes().items()
            ]
            compiled.sort(key=lambda entry: entry[1].count("{"))
            self._compiled = compiled
        return self._compiled

    def _route(self, scope: Scope) -> str:
        """Plantilla de la ruta de la petición.

        Args:
            scope: Scope.

        Returns:
            La plantilla (la ruta tal cual si es pública), o ``UNMATCHED_ROUTE``.
        """
        path = scope.get("path")
        if not isinstance(path, str):
            return UNMATCHED_ROUTE
        if path in self._public_paths:
            return path
        method = scope.get("method")
        other_method: str | None = None
        for regex, template, methods in self._table():
            if regex.match(path) is None:
                continue
            if method in methods:
                return template
            other_method = other_method or template
        return other_method or UNMATCHED_ROUTE

    def _log(self, scope: Scope, status: int | None, elapsed: float) -> None:
        """Escribe la línea del registro de acceso.

        Args:
            scope: Scope.
            status: Estado HTTP de la respuesta (``None`` si no llegó a responderse).
            elapsed: Segundos transcurridos.
        """
        state = scope.get("state", {})
        client = scope.get("client")
        fields: dict[str, object] = {
            "method": scope.get("method"),
            "route": self._route(scope),
            "status": status,
            "duration_ms": round(elapsed * 1000, 1),
            "client": str(client[0]) if client else None,
        }
        principal = state.get(PRINCIPAL_STATE)
        if isinstance(principal, Principal):
            fields.update(sub=principal.subject, tenant=principal.tenant_id, jti=principal.token_id)
        failure = state.get(AUTH_FAILURE_STATE)
        if isinstance(failure, str):
            fields["auth_failure"] = failure
        if scope.get("path") in self._public_paths or is_preflight(scope):
            _log.debug(ACCESS_EVENT, **fields)
        else:
            _log.info(ACCESS_EVENT, **fields)
