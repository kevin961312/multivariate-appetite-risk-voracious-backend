"""Errores de la capa de aplicación con el formato uniforme ``{code, message, details}``."""

from collections.abc import Mapping

__all__ = [
    "ApplicationError",
    "EffectiveFromNotAfterScoredError",
    "ModelNotFoundError",
    "ModelNotReadyError",
    "MonitoringNotFoundError",
    "NotASignalError",
    "ObservationBeforeFirstVersionError",
    "ObservationNotFoundError",
    "ProposalPendingError",
    "RangeBeforeStructuralEventError",
    "RecalibrationDecisionPendingError",
    "RecalibrationInProgressError",
    "RecalibrationInsufficientObservationsError",
    "RecalibrationNotFoundError",
    "UnknownChartError",
    "VersionNotFoundError",
    "VersionNotProposedError",
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


class VersionNotFoundError(ApplicationError):
    """La versión no existe, es de otro modelo o de otro tenant (``VERSION_NOT_FOUND``)."""

    code = "VERSION_NOT_FOUND"


class VersionNotProposedError(ApplicationError):
    """Se aprueba o rechaza una versión que no está ``proposed`` (``VERSION_NOT_PROPOSED``).

    También cuando otra decisión concurrente ganó el comparar-y-cambiar.
    """

    code = "VERSION_NOT_PROPOSED"


class ProposalPendingError(ApplicationError):
    """Ya hay una propuesta sin resolver (``PROPOSAL_PENDING``)."""

    code = "PROPOSAL_PENDING"


class RecalibrationInProgressError(ApplicationError):
    """Ya hay una recalibración en curso para el modelo (``RECALIBRATION_IN_PROGRESS``)."""

    code = "RECALIBRATION_IN_PROGRESS"


class RecalibrationNotFoundError(ApplicationError):
    """La recalibración no existe o es ajena (``RECALIBRATION_NOT_FOUND``)."""

    code = "RECALIBRATION_NOT_FOUND"


class ObservationNotFoundError(ApplicationError):
    """La observación no existe o es ajena (``OBSERVATION_NOT_FOUND``)."""

    code = "OBSERVATION_NOT_FOUND"


class NotASignalError(ApplicationError):
    """Se anota una observación sin señal (``NOT_A_SIGNAL``, Q12)."""

    code = "NOT_A_SIGNAL"


class RangeBeforeStructuralEventError(ApplicationError):
    """El rango incluye datos anteriores al evento estructural sin resolver.

    Código ``RANGE_BEFORE_STRUCTURAL_EVENT``.
    """

    code = "RANGE_BEFORE_STRUCTURAL_EVENT"


class RecalibrationInsufficientObservationsError(ApplicationError):
    """Hay menos observaciones candidatas que el mínimo de la recalibración.

    Código ``RECALIBRATION_INSUFFICIENT_OBSERVATIONS``.
    """

    code = "RECALIBRATION_INSUFFICIENT_OBSERVATIONS"


class RecalibrationDecisionPendingError(ApplicationError):
    """La recalibración tiene decisiones estadísticas pendientes y no se forzó el reemplazo.

    Código ``RECALIBRATION_DECISION_PENDING``; ``details["pending"]`` lista los campos. Es la
    validación síncrona previa a encolar; si llegara a ejecutarse, la carta fallaría con su propio
    código (``T2MRCD_DECISION_PENDING`` en T²MRCD).
    """

    code = "RECALIBRATION_DECISION_PENDING"


class EffectiveFromNotAfterScoredError(ApplicationError):
    """``effective_from`` no es posterior a la última observación puntuada (Q6).

    Código ``EFFECTIVE_FROM_NOT_AFTER_SCORED``.
    """

    code = "EFFECTIVE_FROM_NOT_AFTER_SCORED"


class ObservationBeforeFirstVersionError(ApplicationError):
    """Una observación es anterior a la primera versión vigente.

    Código ``OBSERVATION_BEFORE_FIRST_VERSION``.
    """

    code = "OBSERVATION_BEFORE_FIRST_VERSION"
