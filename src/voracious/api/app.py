"""Fábrica de la aplicación FastAPI."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from voracious.api.access_log import AccessLogMiddleware
from voracious.api.auth import PROBE_PATHS, PUBLIC_PATHS, AuthenticationMiddleware
from voracious.api.errors import ErrorBoundaryMiddleware, install_error_handlers
from voracious.api.rate_limit import RateLimitMiddleware
from voracious.api.routers import datasets, health, t2mrcd_lifecycle, t2mrcd_phase1
from voracious.api.schemas.common import ErrorResponse
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

CORS_ALLOW_METHODS: Final = ("GET", "POST")
"""Métodos admitidos por CORS: la API solo tiene ``GET`` y ``POST``."""

CORS_ALLOW_HEADERS: Final = ("Authorization", "Content-Type")
"""Cabeceras de petición admitidas por CORS (``Content-Type`` para JSON, CSV y multipart)."""

CORS_EXPOSE_HEADERS: Final = ("Retry-After", "WWW-Authenticate")
"""Cabeceras de respuesta que un front en otro origen puede leer."""

CORS_MAX_AGE: Final = 600
"""Segundos que el navegador puede guardar un *preflight* (``Access-Control-Max-Age``)."""

TOO_MANY_REQUESTS_RESPONSE: Final[dict[int | str, dict[str, object]]] = {
    429: {
        "model": ErrorResponse,
        "description": "Demasiadas peticiones desde la IP del cliente (`RATE_LIMITED`, con "
        "`Retry-After`) o demasiados trabajos de cómputo en cola o en curso del tenant "
        "(`TOO_MANY_JOBS`).",
        "headers": {
            "Retry-After": {
                "description": "Segundos que hay que esperar (solo en `RATE_LIMITED`).",
                "schema": {"type": "integer", "minimum": 1},
            }
        },
    }
}
"""Respuesta ``429`` declarada en todas las operaciones (sin tocar los routers)."""


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
    audiencia) lanza ``ConfigurationError``. Pila de middlewares, de fuera adentro:

    1. ``ProxyHeadersMiddleware`` (solo con ``VORACIOUS_TRUSTED_PROXIES``): toma la IP y el
       esquema del cliente de ``X-Forwarded-For`` y ``X-Forwarded-Proto``, solo si la conexión
       viene de un proxy de confianza.
    2. ``AccessLogMiddleware``: registra toda petición, también los ``401``, los ``429`` y los
       *preflight* (estos a nivel ``debug``).
    3. ``CORSMiddleware`` (solo con ``VORACIOUS_CORS_ALLOWED_ORIGINS``): resuelve el *preflight*
       antes del límite y de la autenticación (no gasta cupo ni pide token) y añade sus
       cabeceras a toda respuesta de dentro, también a los ``401``, ``429`` y ``500``. Con
       ``*`` responde ``Access-Control-Allow-Origin: *``; con una lista, el origen pedido si está
       en ella. Nunca con credenciales: el token va en ``Authorization``, no en cookies.
    4. ``ErrorBoundaryMiddleware``: una excepción inesperada sale como ``500 INTERNAL_ERROR``
       dentro de CORS.
    5. ``RateLimitMiddleware``: cubo de fichas por IP de cliente, antes de autenticar.
    6. ``AuthenticationMiddleware``: exige ``Authorization: Bearer`` fuera de las rutas públicas
       antes de leer el cuerpo.

    Con ``VORACIOUS_API_DOCS=false`` no se sirven ``/docs``, ``/redoc`` ni ``/openapi.json`` y
    solo ``/health`` y ``/ready`` quedan públicas; ``app.openapi()`` sigue disponible.

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

    settings = resolved.settings
    docs = settings.api_docs
    public_paths = PUBLIC_PATHS if docs else PROBE_PATHS
    app = FastAPI(
        title="Voracious",
        version="0.1.0",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        # Las rutas por defecto de FastAPI (DOCS_PATHS), o ninguna con VORACIOUS_API_DOCS=false.
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        swagger_ui_oauth2_redirect_url="/docs/oauth2-redirect" if docs else None,
    )
    app.state.container = resolved
    install_error_handlers(app)
    for router in (health.router, datasets.router, t2mrcd_phase1.router, t2mrcd_lifecycle.router):
        app.include_router(router, responses=TOO_MANY_REQUESTS_RESPONSE)
    # El último añadido es el más exterior (ver la pila en la docstring).
    app.add_middleware(AuthenticationMiddleware, verifier=verifier, public_paths=public_paths)
    app.add_middleware(
        RateLimitMiddleware,
        per_minute=settings.rate_limit_per_minute,
        burst=settings.rate_limit_burst,
    )
    app.add_middleware(ErrorBoundaryMiddleware)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=CORS_ALLOW_METHODS,
            allow_headers=CORS_ALLOW_HEADERS,
            expose_headers=CORS_EXPOSE_HEADERS,
            allow_credentials=False,
            max_age=CORS_MAX_AGE,
        )
    app.add_middleware(AccessLogMiddleware, routes=_route_table(app), public_paths=public_paths)
    if settings.trusted_proxies:
        app.add_middleware(
            ProxyHeadersMiddleware,
            trusted_hosts=[str(network) for network in settings.trusted_proxies],
        )
    return app
