"""Schemas HTTP de la recalibración paso a paso de T²MRCD (vuelta 3.4).

``POST …/recalibrations`` en modo ``stepwise`` (``201``), ``…/comparisons`` y ``…/versions``.
Solo referencias por id: ningún dato ni parámetro estadístico viaja en estos cuerpos.
"""

from datetime import datetime
from typing import Literal

from pydantic import Field

from voracious.api.schemas.common import ErrorBody, JobState, RequestModel, ResponseModel
from voracious.api.schemas.t2mrcd import ComparisonOut, error_body
from voracious.application.records import ComparisonRecord
from voracious.domain.charts.t2mrcd import ComparisonResult

__all__ = [
    "ComparisonRequest",
    "ComparisonResponse",
    "StepwiseRecalibrationOut",
    "VersionProposalRequest",
]


class StepwiseRecalibrationOut(ResponseModel):
    """Respuesta ``201`` de una recalibración paso a paso: la sesión abierta.

    Attributes:
        recalibration_id: Recalibración (``running`` mientras admita pasos).
        candidates_dataset_id: Dataset ``recalibration_candidates`` (raíz del primer ajuste).
        status: Siempre ``running``.
    """

    recalibration_id: str
    candidates_dataset_id: str
    status: Literal["running"] = "running"


class ComparisonRequest(RequestModel):
    """Comparación de la base vigente con las filas nuevas conservadas tras la exclusión humana.

    Attributes:
        recalibration_id: Recalibración en curso.
        fit_id: Ajuste de las filas nuevas conservadas (``μ₁``, ``S₁``).
        limits_id: Límites de ese ajuste (operación ``new_rows``).
    """

    recalibration_id: str = Field(min_length=1)
    fit_id: str = Field(min_length=1)
    limits_id: str = Field(min_length=1)


class VersionProposalRequest(RequestModel):
    """Propuesta de versión de una recalibración.

    Attributes:
        recalibration_id: Recalibración en curso.
        comparison_id: Comparación (obligatoria salvo reemplazo forzado, en el que se omite).
        fit_id: Ajuste final: el del dataset de extensión (EXTEND) o el de las filas nuevas
            conservadas (REPLACE).
        limits_id: Límites de ese ajuste.
    """

    recalibration_id: str = Field(min_length=1)
    comparison_id: str | None = Field(default=None, min_length=1)
    fit_id: str = Field(min_length=1)
    limits_id: str = Field(min_length=1)


class ComparisonResponse(ResponseModel):
    """Estado de una comparación y, si terminó bien, su resultado y su decisión."""

    id: str
    model_id: str
    recalibration_id: str
    fit_id: str
    limits_id: str
    status: JobState
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    decision: str | None
    extension_dataset_id: str | None
    result: ComparisonOut | None = None
    error: ErrorBody | None = None

    @classmethod
    def of(cls, record: ComparisonRecord) -> "ComparisonResponse":
        """Convierte el registro.

        Args:
            record: Comparación.

        Returns:
            La respuesta.

        Raises:
            TypeError: Si el resultado no es una comparación de T²MRCD.
        """
        result = record.result
        if result is not None and not isinstance(result, ComparisonResult):
            msg = "la comparación no es de T²MRCD"
            raise TypeError(msg)
        return cls(
            id=record.comparison_id,
            model_id=record.model_id,
            recalibration_id=record.recalibration_id,
            fit_id=record.fit_id,
            limits_id=record.limits_id,
            status=record.status.value,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            decision=None if record.decision is None else record.decision.value,
            extension_dataset_id=record.extension_dataset_id,
            result=None if result is None else ComparisonOut.of(result),
            error=error_body(record.error),
        )
