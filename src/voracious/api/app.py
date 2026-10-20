"""Fábrica de la aplicación FastAPI."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from voracious.api.access_log import AccessLogMiddleware
from voracious.api.auth import AuthenticationMiddleware
from voracious.api.errors import install_error_handlers
from voracious.api.routers import datasets, health, t2mrcd_lifecycle, t2mrcd_phase1
from voracious.container import ConfigurationError, Container, build_container

OPENAPI_TAGS = [
    {"name": "health", "description": "Vida y disponibilidad del proceso."},
    {
        "name": "datasets",
        "description": "Datasets n x p (JSON, CSV o multipart) con su linaje.",
    },
    {
        "name": "t2mrcd-phase1",
        "description": "Pasos encadenables de la Fase I de T²MRCD: exclusión, ajuste y límites.",
    },
    {
        "name": "t2mrcd-pipelines",
        "description": "Fase I completa por pasos (orquestación de los pasos encadenables).",
    },
    {
        "name": "t2mrcd-models",
        "description": "Modelos de la carta T²MRCD (Fase I) y estado de la carta.",
    },
    {"name": "t2mrcd-scores", "description": "Puntuación de observaciones (Fase II), asíncrona."},
    {
        "name": "t2mrcd-observations",
        "description": "Observaciones registradas, anotaciones de señales y eventos estructurales.",
    },
    {
        "name": "t2mrcd-versions",
        "description": "Versiones inmutables: consulta, aprobación y rechazo.",
    },
    {
        "name": "t2mrcd-recalibrations",
        "description": "Recalibración a petición (asíncrona); produce una versión propuesta.",
    },
]
"""Etiquetas de OpenAPI, en el orden en que se muestran."""

_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def _route_table(app: FastAPI) -> Callable[[], dict[str, frozenset[str]]]:
    """Tabla de rutas para el registro de acceso: plantilla de OpenAPI → métodos.

    Args:
        app: Aplicación.

    Returns:
        Función que la calcula (en la primera petición, con todos los routers ya incluidos).
    """

    def table() -> dict[str, frozenset[str]]:
        paths: dict[str, dict[str, object]] = app.openapi()["paths"]
        return {
            template: frozenset(m.upper() for m in ops if m.upper() in _HTTP_METHODS)
            for template, ops in paths.items()
        }

    return table


def create_app(container: Container | None = None) -> FastAPI:
    """Crea la aplicación FastAPI.

    Se puede invocar sin argumentos para ``uvicorn voracious.api.app:create_app --factory``. Al
    arrancar (``lifespan``) cierra ``failed / JOB_INTERRUPTED`` los trabajos que un reinicio dejó
    en curso; al cerrarse apaga la cola esperando a los que estén en curso y cierra el pool.

    **No arranca sin autenticación** (falla cerrado): sin verificador de tokens (JWKS, emisor y
    audiencia) lanza ``ConfigurationError``. Instala el registro de acceso (exterior) y el
    middleware de autenticación (interior), que exige ``Authorization: Bearer`` fuera de las rutas
    públicas antes de leer el cuerpo.

    Args:
        container: Dependencias ya cableadas; si es ``None`` se construyen desde el entorno.

    Returns:
        La aplicación con los routers registrados y el contenedor en ``app.state.container``.

    Raises:
        ConfigurationError: Si el contenedor no tiene verificador de tokens.
    """
    resolved = container if container is not None else build_container()
    verifier = resolved.token_verifier
    if verifier is None:
        if container is None:
            resolved.shutdown(wait=False)
        msg = (
            "la API exige autenticación: define VORACIOUS_JWT_JWKS_FILE, VORACIOUS_JWT_ISSUER y "
            "VORACIOUS_JWT_AUDIENCE"
        )
        raise ConfigurationError(msg)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        resolved.startup()
        yield
        resolved.shutdown(wait=True)

    app = FastAPI(title="Voracious", version="0.1.0", openapi_tags=OPENAPI_TAGS, lifespan=lifespan)
    app.state.container = resolved
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(datasets.router)
    app.include_router(t2mrcd_phase1.router)
    app.include_router(t2mrcd_lifecycle.router)
    # El último añadido es el más exterior: acceso → autenticación → aplicación.
    app.add_middleware(AuthenticationMiddleware, verifier=verifier)
    app.add_middleware(AccessLogMiddleware, routes=_route_table(app))
    return app
