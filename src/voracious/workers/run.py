"""Punto de entrada de los workers: ejecuta un ``JobRequest`` con el manejador del contenedor.

Sin lógica: el adaptador de cola (``CeleryJobQueue`` en el futuro) deserializa la petición y
llama a ``handle``. Solo importa ``container`` y ``application`` (contrato de import-linter).
"""

from functools import cache

from voracious.application.ports import JobRequest
from voracious.container import Container, build_container

__all__ = ["handle"]


@cache
def _default_container() -> Container:
    """Contenedor del proceso worker, construido una vez desde el entorno.

    Returns:
        El contenedor.
    """
    return build_container()


def handle(job: JobRequest, container: Container | None = None) -> None:
    """Ejecuta un trabajo.

    Args:
        job: Petición.
        container: Contenedor; ``None`` usa el del proceso (desde el entorno).
    """
    (container if container is not None else _default_container()).handle(job)
