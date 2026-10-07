"""Fábrica de la aplicación FastAPI."""

from fastapi import FastAPI

from voracious.api.routers import health
from voracious.container import Container, build_container


def create_app(container: Container | None = None) -> FastAPI:
    """Crea la aplicación FastAPI.

    Se puede invocar sin argumentos para ``uvicorn voracious.api.app:create_app --factory``.

    Args:
        container: Dependencias ya cableadas; si es ``None`` se construyen desde el entorno.

    Returns:
        La aplicación con los routers registrados y el contenedor en ``app.state.container``.
    """
    resolved = container if container is not None else build_container()
    app = FastAPI(title="Voracious", version="0.1.0")
    app.state.container = resolved
    app.include_router(health.router)
    return app
