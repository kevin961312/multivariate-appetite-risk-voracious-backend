"""Errores de la capa de aplicación con el formato uniforme ``{code, message, details}``."""

from collections.abc import Mapping

__all__ = [
    "ApplicationError",
    "ComparisonNotFoundError",
    "ComparisonNotReadyError",
    "DatasetNotFoundError",
    "EffectiveFromNotAfterScoredError",
    "ExclusionNotFoundError",
    "FitNotFoundError",
    "FitNotReadyError",
    "LimitsFitMismatchError",
    "LimitsNotFoundError",
    "LimitsNotReadyError",
    "ModelNotFoundError",
    "ModelNotReadyError",
    "MonitoringNotFoundError",
    "NotASignalError",
    "ObservationBeforeFirstVersionError",
    "ObservationNotFoundError",
    "PipelineNotFoundError",
    "ProposalPendingError",
    "RangeBeforeStructuralEventError",
    "RecalibrationDecisionPendingError",
    "RecalibrationInProgressError",
    "RecalibrationInsufficientObservationsError",
    "RecalibrationMismatchError",
    "RecalibrationNotFoundError",
    "RecalibrationNotInProgressError",
    "UnknownChartError",
    "VariablesMismatchError",
    "VersionInputsMismatchError",
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


class DatasetNotFoundError(ApplicationError):
    """El dataset no existe o es de otro tenant (``DATASET_NOT_FOUND``)."""

    code = "DATASET_NOT_FOUND"


class FitNotFoundError(ApplicationError):
    """El ajuste no existe, es de otra carta o de otro tenant (``FIT_NOT_FOUND``)."""

    code = "FIT_NOT_FOUND"


class FitNotReadyError(ApplicationError):
    """El ajuste existe pero no está en ``succeeded`` (``FIT_NOT_READY``)."""

    code = "FIT_NOT_READY"


class LimitsNotFoundError(ApplicationError):
    """Los límites no existen, son de otra carta o de otro tenant (``LIMITS_NOT_FOUND``)."""

    code = "LIMITS_NOT_FOUND"


class LimitsNotReadyError(ApplicationError):
    """Los límites existen pero no están en ``succeeded`` (``LIMITS_NOT_READY``)."""

    code = "LIMITS_NOT_READY"


class LimitsFitMismatchError(ApplicationError):
    """Los límites no se calibraron sobre el ajuste indicado (``LIMITS_FIT_MISMATCH``)."""

    code = "LIMITS_FIT_MISMATCH"


class ExclusionNotFoundError(ApplicationError):
    """La exclusión no existe, es de otra carta o de otro tenant (``EXCLUSION_NOT_FOUND``)."""

    code = "EXCLUSION_NOT_FOUND"


class PipelineNotFoundError(ApplicationError):
    """La tubería no existe, es de otra carta o de otro tenant (``PIPELINE_NOT_FOUND``)."""

    code = "PIPELINE_NOT_FOUND"


class RecalibrationNotInProgressError(ApplicationError):
    """La recalibración ya terminó (o tiene ya su propuesta pedida) y no admite más pasos.

    Código ``RECALIBRATION_NOT_IN_PROGRESS`` (vuelta 3.4).
    """

    code = "RECALIBRATION_NOT_IN_PROGRESS"


class RecalibrationMismatchError(ApplicationError):
    """Un paso referencia recursos que no pertenecen a esa recalibración (o a ninguna).

    Código ``RECALIBRATION_MISMATCH`` (vuelta 3.4): p. ej. límites de la Fase I sobre un dataset de
    candidatas, o una recalibración distinta de la del dataset.
    """

    code = "RECALIBRATION_MISMATCH"


class ComparisonNotFoundError(ApplicationError):
    """La comparación no existe, es de otro modelo o de otro tenant (``COMPARISON_NOT_FOUND``)."""

    code = "COMPARISON_NOT_FOUND"


class ComparisonNotReadyError(ApplicationError):
    """La comparación existe pero no está en ``succeeded`` (``COMPARISON_NOT_READY``)."""

    code = "COMPARISON_NOT_READY"


class VersionInputsMismatchError(ApplicationError):
    """Los pasos pedidos para la versión no son los que exige la decisión de la recalibración.

    Código ``VERSION_INPUTS_MISMATCH`` (vuelta 3.4): EXTEND exige el ajuste y los límites del
    dataset de extensión; REPLACE, los de las filas nuevas (los comparados); sin reemplazo
    forzado hace falta la comparación. ``details.reason`` dice cuál falló.
    """

    code = "VERSION_INPUTS_MISMATCH"


class VariablesMismatchError(ApplicationError):
    """Las variables de la entrada no son las del modelo (número o nombres; Paso 4.2).

    ``VARIABLES_MISMATCH`` (422): una puntuación o una recalibración con otras columnas que las
    del dataset raíz del modelo.
    """

    code = "VARIABLES_MISMATCH"
