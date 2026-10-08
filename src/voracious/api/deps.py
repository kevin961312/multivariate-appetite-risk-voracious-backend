"""Dependencias de FastAPI compartidas por los routers."""

from fastapi import Request

from voracious.container import Container

__all__ = ["get_container"]


def get_container(request: Request) -> Container:
    """Contenedor del proceso guardado en ``app.state``.

    Args:
        request: Petición.

    Returns:
        El contenedor.

    Raises:
        TypeError: Si ``app.state.container`` no es un ``Container``.
    """
    container = request.app.state.container
    if not isinstance(container, Container):
        msg = "app.state.container no es un Container"
        raise TypeError(msg)
    return container
