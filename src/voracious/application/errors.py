"""Errores de la capa de aplicación con el formato uniforme ``{code, message, details}``."""

from collections.abc import Mapping

__all__ = [
    "ApplicationError",
    "ModelNotFoundError",
    "ModelNotReadyError",
    "MonitoringNotFoundError",
    "UnknownChartError",
]


class ApplicationError(Exception):
    """Error base de los casos de uso.

    Attributes:
        code: Código estable.
        message: Mensaje legible.
        details: Datos adicionales serializables.
    """

    code: str = "APPLICATION_ERROR"

    def __init__(self, message: str, details: Mapping[str, object] | None = None) -> None:
        """Construye el error.

        Args:
            message: Mensaje legible.
            details: Datos adicionales; se copian.
        """
        super().__init__(message)
        self.message = message
        self.details: dict[str, object] = dict(details) if details is not None else {}


class UnknownChartError(ApplicationError):
    """La carta pedida no está registrada (``CHART_NOT_FOUND``)."""

    code = "CHART_NOT_FOUND"


class ModelNotFoundError(ApplicationError):
    """El modelo no existe, es de otra carta o de otro tenant (``MODEL_NOT_FOUND``)."""

    code = "MODEL_NOT_FOUND"


class ModelNotReadyError(ApplicationError):
    """El modelo existe pero no está en ``succeeded`` (``MODEL_NOT_READY``)."""

    code = "MODEL_NOT_READY"


class MonitoringNotFoundError(ApplicationError):
    """El monitoreo no existe o no pertenece al tenant/modelo (``MONITORING_NOT_FOUND``)."""

    code = "MONITORING_NOT_FOUND"
