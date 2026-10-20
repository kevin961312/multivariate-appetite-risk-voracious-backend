"""Comprueba que ninguna ruta de negocio de la API responde sin token (paso E, E9).

Es la puerta de ``scripts/deploy.sh`` antes de abrir el 443: se ejecuta dentro del contenedor de
la API, contra ``127.0.0.1`` (exento del límite de peticiones), leyendo el script por la entrada
estándar::

    docker compose exec -T api python - --base-url http://127.0.0.1:8000 \
        < scripts/check_auth_surface.py
    uv run python scripts/check_auth_surface.py --base-url http://127.0.0.1:8000

Lee las operaciones del OpenAPI de la propia API (``/openapi.json``; con
``VORACIOUS_API_DOCS=false`` no se sirve y hay que pasar ``--openapi FICHERO``) y prueba cada una
salvo ``GET /health`` y ``GET /ready``: los parámetros de ruta valen ``auth-check``, sin
``Authorization``, con ``X-Tenant-ID: demo`` (que la API ignora) y con cuerpo ``{}`` en los
``POST``. Cada una debe dar ``401`` con ``WWW-Authenticate: Bearer…``. Además prueba ``OPTIONS``
en cada ruta **sin** cabeceras de *preflight*: también debe dar ``401`` (CORS solo intercepta los
*preflight*, nunca abre el ``OPTIONS`` normal). Nunca envía ``Origin``. ``GET /health`` debe dar
``200``.

Salida: ``0`` si todo da lo esperado; ``1`` si alguna ruta responde sin exigir token (o
``/health`` no da ``200``); ``2`` por uso incorrecto, OpenAPI ilegible o fallo de conexión. No
maneja ningún secreto: no hay token que imprimir. Solo usa la biblioteca estándar de Python 3.12
(corre en la imagen de runtime, sin el proyecto).
"""

import argparse
import http.client
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

PUBLIC_OPERATIONS: Final = frozenset({("GET", "/health"), ("GET", "/ready")})
"""Operaciones que no exigen token y no se prueban (salvo ``/health``, que debe dar ``200``)."""

PLACEHOLDER: Final = "auth-check"
"""Valor de cada parámetro de ruta (``{model_id}`` → ``auth-check``)."""

TENANT_HEADER: Final = {"X-Tenant-ID": "demo"}
"""Cabecera que un cliente antiguo mandaría; la API la ignora (el tenant sale del token)."""

_METHODS: Final = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
_PARAM: Final = re.compile(r"\{[^{}/]+\}")


class UsageError(Exception):
    """Argumentos u OpenAPI inválidos, o la API no responde (salida ``2``)."""


@dataclass(frozen=True)
class Target:
    """Base de la API.

    Attributes:
        scheme: ``http`` o ``https``.
        netloc: ``host[:puerto]``.
        prefix: Ruta base sin barra final (``""`` si la API está en la raíz).
        timeout: Segundos máximos por petición.
    """

    scheme: str
    netloc: str
    prefix: str
    timeout: float


@dataclass(frozen=True)
class Probe:
    """Resultado de una petición sin token.

    Attributes:
        method: Método HTTP.
        template: Plantilla de la ruta (la del OpenAPI).
        status: Estado HTTP recibido.
        challenge: Valor de ``WWW-Authenticate`` (``""`` si no vino).
    """

    method: str
    template: str
    status: int
    challenge: str

    @property
    def guarded(self) -> bool:
        """Indica si la API exigió el token (``401`` con reto ``Bearer``)."""
        return self.status == http.HTTPStatus.UNAUTHORIZED and self.challenge.startswith("Bearer")


def parse_target(base_url: str, timeout: float) -> Target:
    """Valida la URL base.

    Args:
        base_url: URL base (``http://127.0.0.1:8000``).
        timeout: Segundos máximos por petición.

    Returns:
        La base.

    Raises:
        UsageError: Si no es ``http``/``https`` con host, o lleva query o fragmento.
    """
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.query or parts.fragment:
        msg = f"--base-url no válida: {base_url!r} (esperaba http[s]://host[:puerto])"
        raise UsageError(msg)
    return Target(parts.scheme, parts.netloc, parts.path.rstrip("/"), timeout)


def request(
    target: Target, method: str, path: str, body: bytes | None = None
) -> tuple[int, str, bytes]:
    """Hace una petición sin ``Authorization`` y sin seguir redirecciones.

    Args:
        target: Base de la API.
        method: Método HTTP.
        path: Ruta concreta (sin la base).
        body: Cuerpo JSON, si lo hay.

    Returns:
        ``(estado, WWW-Authenticate, cuerpo)``.

    Raises:
        UsageError: Si no se puede conectar o la respuesta no es HTTP.
    """
    kind = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
    conn = kind(target.netloc, timeout=target.timeout)
    headers = dict(TENANT_HEADER)
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, f"{target.prefix}{path}", body=body, headers=headers)
        response = conn.getresponse()
        content = response.read()
        challenge = response.getheader("WWW-Authenticate") or ""
    except (OSError, http.client.HTTPException) as exc:
        msg = f"{method} {path}: sin respuesta de la API ({type(exc).__name__}: {exc})"
        raise UsageError(msg) from exc
    finally:
        conn.close()
    return response.status, challenge, content


def load_spec(target: Target, openapi: Path | None) -> dict[str, object]:
    """OpenAPI de la API: el del fichero, o ``/openapi.json`` de la propia API.

    Args:
        target: Base de la API.
        openapi: Fichero con el OpenAPI, o ``None`` para pedirlo a la API.

    Returns:
        El documento.

    Raises:
        UsageError: Si no se puede leer o no es un objeto JSON con ``paths``.
    """
    if openapi is not None:
        try:
            raw = openapi.read_bytes()
        except OSError as exc:
            msg = f"no se puede leer {openapi}: {exc}"
            raise UsageError(msg) from exc
    else:
        status, _, raw = request(target, "GET", "/openapi.json")
        if status != http.HTTPStatus.OK:
            msg = (
                f"GET /openapi.json -> {status}: ¿documentación apagada "
                "(VORACIOUS_API_DOCS=false)? Pasa --openapi FICHERO"
            )
            raise UsageError(msg)
    try:
        spec = json.loads(raw)
    except ValueError as exc:
        msg = f"el OpenAPI no es JSON válido: {exc}"
        raise UsageError(msg) from exc
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        msg = "el OpenAPI no tiene 'paths'"
        raise UsageError(msg)
    return spec


def operations(spec: dict[str, object]) -> list[tuple[str, str]]:
    """Operaciones del OpenAPI que exigen token.

    Args:
        spec: Documento OpenAPI.

    Returns:
        ``(método, plantilla)`` ordenadas, sin ``PUBLIC_OPERATIONS``.

    Raises:
        UsageError: Si no tiene ``paths`` o no queda ninguna operación (la comprobación no
            probaría nada).
    """
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        msg = "el OpenAPI no tiene 'paths'"
        raise UsageError(msg)
    found = sorted(
        (method.upper(), str(template))
        for template, item in paths.items()
        if isinstance(item, dict)
        for method in item
        if str(method).lower() in _METHODS
    )
    private = [op for op in found if op not in PUBLIC_OPERATIONS]
    if not private:
        msg = "el OpenAPI no tiene operaciones de negocio que probar"
        raise UsageError(msg)
    return private


def concrete(template: str) -> str:
    """Ruta concreta de una plantilla.

    Args:
        template: Plantilla (``/v1/datasets/{dataset_id}``).

    Returns:
        La ruta con ``PLACEHOLDER`` en cada parámetro.
    """
    return _PARAM.sub(PLACEHOLDER, template)


def probe(target: Target, method: str, template: str) -> Probe:
    """Pide una operación sin token.

    Args:
        target: Base de la API.
        method: Método HTTP.
        template: Plantilla de la ruta.

    Returns:
        El resultado.
    """
    body = b"{}" if method == "POST" else None
    status, challenge, _ = request(target, method, concrete(template), body)
    return Probe(method, template, status, challenge)


def check(target: Target, openapi: Path | None) -> int:
    """Ejecuta todas las comprobaciones e imprime una línea por cada una.

    Args:
        target: Base de la API.
        openapi: Fichero con el OpenAPI, o ``None`` para pedirlo a la API.

    Returns:
        ``0`` si todo da lo esperado; ``1`` si no.

    Raises:
        UsageError: Si el OpenAPI no se puede leer o la API deja de responder.
    """
    private = operations(load_spec(target, openapi))
    health, _, _ = request(target, "GET", "/health")
    failures = 0 if health == http.HTTPStatus.OK else 1
    print(f"{'OK   ' if not failures else 'FALLO'} {health} GET /health")
    probes = [probe(target, method, template) for method, template in private]
    # OPTIONS sin cabeceras de preflight: CORS no debe abrirlo (sigue exigiendo token).
    probes += [probe(target, "OPTIONS", t) for t in sorted({t for _, t in private})]
    for result in probes:
        mark = "OK   " if result.guarded else "FALLO"
        print(f"{mark} {result.status} {result.method} {result.template}")
    open_routes = sum(not result.guarded for result in probes)
    failures += open_routes
    if failures:
        print(
            f"FALLO: {open_routes} de {len(probes)} peticiones sin token no dieron 401 con "
            "WWW-Authenticate Bearer, o /health no dio 200",
        )
        return 1
    print(
        f"superficie de autenticación cerrada: {len(private)} operaciones y "
        f"{len(probes) - len(private)} sondas OPTIONS, todas 401 sin token",
    )
    return 0


def main(argv: Sequence[str]) -> int:
    """Punto de entrada.

    Args:
        argv: Argumentos (sin el nombre del programa).

    Returns:
        ``0`` bien; ``1`` si alguna ruta responde sin token; ``2`` por uso o conexión.
    """
    parser = argparse.ArgumentParser(
        prog="check_auth_surface.py",
        description="Comprueba que ninguna ruta de negocio de la API responde sin token.",
    )
    parser.add_argument("--base-url", required=True, help="URL base, p. ej. http://127.0.0.1:8000")
    parser.add_argument(
        "--openapi", type=Path, help="OpenAPI en un fichero (si la API no sirve /openapi.json)"
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="segundos por petición")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:  # argparse sale con 2 en un uso incorrecto (y 0 con --help)
        return exc.code if isinstance(exc.code, int) else 2
    try:
        return check(parse_target(args.base_url, args.timeout), args.openapi)
    except UsageError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
