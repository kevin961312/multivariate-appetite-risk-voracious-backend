"""Raíz de composición: construye y cablea las dependencias del proceso."""

from dataclasses import dataclass

from voracious.config import Settings
from voracious.infrastructure.logging import configure_logging


@dataclass(frozen=True)
class Container:
    """Dependencias ya construidas que comparten la API y los workers.

    Attributes:
        settings: Configuración del proceso.
    """

    settings: Settings


def build_container(settings: Settings | None = None) -> Container:
    """Construye el contenedor y configura el logging.

    Args:
        settings: Configuración a usar; si es ``None`` se lee del entorno ``VORACIOUS_*``.

    Returns:
        El contenedor con todas las dependencias cableadas.
    """
    resolved = settings if settings is not None else Settings()
    configure_logging(resolved.log_level)
    return Container(settings=resolved)
