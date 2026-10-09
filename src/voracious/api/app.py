"""Fábrica de la aplicación FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from voracious.api.errors import install_error_handlers
from voracious.api.routers import datasets, health, t2mrcd_lifecycle, t2mrcd_phase1
from voracious.container import Container, build_container

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


def create_app(container: Container | None = None) -> FastAPI:
    """Crea la aplicación FastAPI.

    Se puede invocar sin argumentos para ``uvicorn voracious.api.app:create_app --factory``. Al
    cerrarse (``lifespan``) apaga la cola de trabajos esperando a los que estén en curso.

    Args:
        container: Dependencias ya cableadas; si es ``None`` se construyen desde el entorno.

    Returns:
        La aplicación con los routers registrados y el contenedor en ``app.state.container``.
    """
    resolved = container if container is not None else build_container()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        resolved.shutdown(wait=True)

    app = FastAPI(title="Voracious", version="0.1.0", openapi_tags=OPENAPI_TAGS, lifespan=lifespan)
    app.state.container = resolved
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(datasets.router)
    app.include_router(t2mrcd_phase1.router)
    app.include_router(t2mrcd_lifecycle.router)
    return app
