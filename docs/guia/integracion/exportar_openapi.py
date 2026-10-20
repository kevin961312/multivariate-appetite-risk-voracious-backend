r"""Exporta el OpenAPI de la API real de Voracious con los roles exigidos por cada operación.

Construye la aplicación de verdad (``create_app`` sobre ``build_container`` en modo memoria) con
un JWKS **temporal** (la API no arranca sin verificador de tokens), lee su esquema OpenAPI y añade
a cada operación la extensión ``x-voracious-roles`` con los roles que la permiten. Los roles no se
copian de ninguna tabla: se obtienen **introspeccionando las dependencias** de cada ruta (la
dependencia que crea ``voracious.api.auth.require_roles``, la de los alias ``Reader``,
``Operator`` y ``Decider``). Las rutas públicas (``/health``, ``/ready``) quedan sin roles.

La matriz obtenida se contrasta con ``tests/support/routes.py`` (``ROUTE_ROLES``) y el script falla
si no coinciden, para que la guía nunca documente permisos distintos de los que prueba la suite.

Uso (desde la raíz del repositorio; necesita el entorno del proyecto)::

    uv run python docs/guia/integracion/exportar_openapi.py

Escribe ``docs/guia/integracion/openapi.json`` (indentado; claves ordenadas salvo las de
``properties``, que conservan el orden de declaración de los schemas).
"""

import inspect
import json
import runpy
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import fastapi.routing
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from voracious.api import auth
from voracious.api.app import create_app
from voracious.application.auth import Role
from voracious.config import Settings
from voracious.container import build_container, generate_signing_key

INTEGRACION = Path(__file__).resolve().parent
RAIZ = INTEGRACION.parents[2]
SALIDA = INTEGRACION / "openapi.json"
RUTAS_DE_TESTS = RAIZ / "tests" / "support" / "routes.py"
EXTENSION_ROLES = "x-voracious-roles"
"""Extensión de OpenAPI con los roles que permiten la operación (lista vacía = pública)."""
ORDEN_ROLES = tuple(Role)
"""Orden canónico de los roles en la extensión (el del enum: analyst, approver, admin)."""
ISSUER = "voracious-openapi-export"
AUDIENCE = "voracious-openapi-export"
KID = "openapi-export"
METODOS_HTTP = frozenset({"get", "post", "put", "patch", "delete"})

Matriz = dict[tuple[str, str], frozenset[Role]]


def _es_dependencia_de_roles(llamable: Callable[..., Any] | None) -> bool:
    """Indica si ``llamable`` es la dependencia que fabrica ``require_roles``.

    Args:
        llamable: La función de una dependencia de FastAPI.

    Returns:
        ``True`` si es el cierre ``require_roles.<locals>.dependency`` de ``voracious.api.auth``.
    """
    return (
        llamable is not None
        and getattr(llamable, "__module__", None) == auth.__name__
        and getattr(llamable, "__qualname__", "")
        == f"{auth.require_roles.__name__}.<locals>.dependency"
    )


def _roles_de(dependant: Dependant) -> frozenset[Role] | None:
    """Roles exigidos por un árbol de dependencias de FastAPI.

    Recorre el árbol completo; si aparece más de una dependencia de roles, los roles admitidos son
    la intersección (todas deben cumplirse).

    Args:
        dependant: Árbol de dependencias de la ruta.

    Returns:
        Los roles, o ``None`` si ninguna dependencia exige roles (ruta pública).

    Raises:
        RuntimeError: Si la dependencia de roles no lleva los roles en su cierre.
    """
    encontrados: list[frozenset[Role]] = []
    pendientes = [dependant]
    while pendientes:
        actual = pendientes.pop()
        if _es_dependencia_de_roles(actual.call):
            libres = inspect.getclosurevars(actual.call).nonlocals  # type: ignore[arg-type]
            aceptados = libres.get("accepted")
            if not isinstance(aceptados, frozenset) or not all(
                isinstance(r, Role) for r in aceptados
            ):
                msg = f"la dependencia de roles no expone 'accepted': {actual.call!r}"
                raise RuntimeError(msg)
            encontrados.append(aceptados)
        pendientes.extend(actual.dependencies)
    if not encontrados:
        return None
    resultado = encontrados[0]
    for otro in encontrados[1:]:
        resultado &= otro
    return resultado


def _rutas_de_api(app: FastAPI) -> Iterator[Any]:
    """Rutas de la API tal como las recorre el generador de OpenAPI de FastAPI.

    Desde FastAPI 0.14x los routers incluidos quedan anidados (``_IncludedRouter``) y
    ``fastapi.routing.iter_route_contexts`` los aplana con el prefijo y las dependencias del
    ``include_router``; en versiones anteriores ``app.routes`` ya trae cada ``APIRoute``.

    Args:
        app: Aplicación construida.

    Yields:
        Cada ruta de la API (``APIRoute`` o su contexto efectivo) incluida en el esquema.
    """
    aplanar = getattr(fastapi.routing, "iter_route_contexts", None)
    rutas = aplanar(app.routes) if aplanar is not None else app.routes
    for ruta in rutas:
        original = getattr(ruta, "original_route", ruta)
        if isinstance(original, APIRoute) and ruta.include_in_schema:
            yield ruta


def matriz_de_roles(app: FastAPI) -> Matriz:
    """Matriz (método, plantilla) → roles, introspeccionando las dependencias de cada ruta.

    Solo cuentan las rutas incluidas en el esquema (las de documentación no lo están).

    Args:
        app: Aplicación construida.

    Returns:
        La matriz; una ruta pública tiene el conjunto vacío.

    Raises:
        RuntimeError: Si una ruta no tiene árbol de dependencias.
    """
    matriz: Matriz = {}
    for ruta in _rutas_de_api(app):
        dependant = getattr(ruta, "dependant", None) or ruta.original_route.dependant
        if not isinstance(dependant, Dependant):
            msg = f"ruta sin dependencias introspeccionables: {ruta.path_format}"
            raise RuntimeError(msg)
        roles = _roles_de(dependant)
        for metodo in ruta.methods:
            matriz[(metodo.upper(), ruta.path_format)] = roles or frozenset()
    return matriz


def _comprobar_contra_tests(matriz: Matriz) -> None:
    """Contrasta la matriz con ``ROUTE_ROLES`` de ``tests/support/routes.py``.

    Args:
        matriz: Matriz introspeccionada.

    Raises:
        SystemExit: Si las rutas o los roles no coinciden.
    """
    esperada: Mapping[tuple[str, str], frozenset[Role]] = runpy.run_path(str(RUTAS_DE_TESTS))[
        "ROUTE_ROLES"
    ]
    errores: list[str] = []
    for clave in sorted(set(esperada) - set(matriz)):
        errores.append(f"falta en la app: {clave[0]} {clave[1]}")
    for clave in sorted(set(matriz) - set(esperada)):
        errores.append(f"no está en tests/support/routes.py: {clave[0]} {clave[1]}")
    for clave in sorted(set(matriz) & set(esperada)):
        if matriz[clave] != esperada[clave]:
            obtenidos = sorted(r.value for r in matriz[clave])
            previstos = sorted(r.value for r in esperada[clave])
            errores.append(f"{clave[0]} {clave[1]}: app {obtenidos} != tests {previstos}")
    if errores:
        lineas = "\n  ".join(errores)
        msg = f"la matriz de roles no coincide con tests/support/routes.py:\n  {lineas}"
        raise SystemExit(msg)


def _ordenar(valor: Any, *, conservar: bool = False) -> Any:  # noqa: ANN401
    """Ordena las claves de un JSON de forma recursiva, salvo las de ``properties``.

    Args:
        valor: Nodo del JSON.
        conservar: Mantener el orden de las claves de este nodo (es un ``properties``).

    Returns:
        El nodo con las claves ordenadas.
    """
    if isinstance(valor, dict):
        claves = list(valor) if conservar else sorted(valor)
        return {k: _ordenar(valor[k], conservar=(k == "properties")) for k in claves}
    if isinstance(valor, list):
        return [_ordenar(v) for v in valor]
    return valor


def construir_openapi() -> dict[str, Any]:
    """Construye la app en modo memoria con un JWKS temporal y devuelve su OpenAPI con roles.

    Returns:
        El esquema OpenAPI con ``x-voracious-roles`` en cada operación.

    Raises:
        SystemExit: Si la matriz de roles no coincide con la de los tests.
        RuntimeError: Si una operación del esquema no tiene ruta en la app.
    """
    with tempfile.TemporaryDirectory(prefix="voracious-openapi-") as carpeta:
        _, jwks = generate_signing_key(KID, None)
        fichero = Path(carpeta) / "jwks.json"
        fichero.write_text(jwks, encoding="utf-8")
        settings = Settings(
            repository="memory",
            storage="memory",
            log_level="WARNING",
            jwt_jwks_file=fichero,
            jwt_issuer=ISSUER,
            jwt_audience=AUDIENCE,
        )
        container = build_container(settings)
        try:
            app = create_app(container)
            esquema: dict[str, Any] = app.openapi()
            matriz = matriz_de_roles(app)
        finally:
            container.shutdown(wait=True)
    _comprobar_contra_tests(matriz)
    for plantilla, operaciones in esquema["paths"].items():
        for metodo, operacion in operaciones.items():
            if metodo not in METODOS_HTTP:
                continue
            clave = (metodo.upper(), plantilla)
            if clave not in matriz:
                msg = f"operación sin ruta en la app: {metodo.upper()} {plantilla}"
                raise RuntimeError(msg)
            operacion[EXTENSION_ROLES] = [r.value for r in ORDEN_ROLES if r in matriz[clave]]
    ordenado: dict[str, Any] = _ordenar(esquema)
    return ordenado


def main() -> None:
    """Escribe ``openapi.json`` junto a este script e informa del número de operaciones."""
    esquema = construir_openapi()
    texto = json.dumps(esquema, ensure_ascii=False, indent=2) + "\n"
    SALIDA.write_text(texto, encoding="utf-8")
    operaciones = sum(
        1 for ops in esquema["paths"].values() for metodo in ops if metodo in METODOS_HTTP
    )
    sys.stdout.write(f"{SALIDA} ({operaciones} operaciones)\n")


if __name__ == "__main__":
    main()
