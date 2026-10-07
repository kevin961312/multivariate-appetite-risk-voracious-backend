"""Configuración de logging estructurado en JSON con structlog."""

import logging

import structlog


def configure_logging(level: str) -> None:
    """Configura structlog para emitir una línea JSON por evento en stdout.

    Es idempotente: llamarla varias veces reemplaza la configuración anterior sin acumular
    procesadores.

    Args:
        level: Nombre del nivel mínimo (``"DEBUG"``, ``"INFO"``, ``"WARNING"`` o ``"ERROR"``).

    Raises:
        ValueError: Si ``level`` no es un nivel de logging conocido.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.upper())
    if numeric_level is None:
        msg = f"Nivel de logging desconocido: {level!r}"
        raise ValueError(msg)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
