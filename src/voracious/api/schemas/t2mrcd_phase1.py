"""Schemas HTTP de los pasos de la Fase I de T²MRCD (vuelta 3.3).

``/fits``, ``/limits``, ``/depurations``, ``/models`` (solo referencias) y
``/pipelines/phase1``. Como en ``t2mrcd.py``, lo que el cliente omite no se rellena aquí: lo
decide la carta con sus defaults citados (``alpha`` de MRCD 0.75, P2).
"""

from collections.abc import Collection
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from voracious.api.schemas.common import ErrorBody, JobState, RequestModel, ResponseModel
from voracious.api.schemas.t2mrcd import (
    LifecyclePolicyIn,
    LimitsOut,
    MRCDFitOut,
    MRCDIn,
    T2MRCDParamsIn,
    error_body,
)
from voracious.application.records import (
    AssignableCause,
    DepurationRecord,
    FitRecord,
    LimitsRecord,
    PipelineRecord,
)
from voracious.domain.common import RowDisposition

__all__ = [
    "AssignableCauseIn",
    "DepurationInclude",
    "DepurationRequest",
    "DepurationResponse",
    "FitInclude",
    "FitRequest",
    "FitResponse",
    "LimitsInclude",
    "LimitsRequest",
    "LimitsResponse",
    "ModelFromRefsRequest",
    "Phase1PipelineRequest",
    "PipelineResponse",
]

FitInclude = Literal["covariance"]
"""Partes grandes opcionales de ``GET /fits/{id}``."""

LimitsInclude = Literal["clean_rows"]
"""Partes grandes opcionales de ``GET /limits/{id}``."""

DepurationInclude = Literal["row_disposition"]
"""Partes grandes opcionales de ``GET /depurations/{id}``."""


# --- peticiones -----------------------------------------------------------------------------------


class FitRequest(RequestModel):
    """Ajuste MRCD bajo la carta.

    Attributes:
        dataset_id: Dataset a ajustar.
        mrcd: Parámetros de MRCD (omitidos: los de la carta, ``alpha`` 0.75).
    """

    dataset_id: str = Field(min_length=1)
    mrcd: MRCDIn | None = None


class LimitsRequest(RequestModel):
    """Límites bootstrap sobre un ajuste: ``{fit_id, params?}`` o ``{fit_id, recalibration_id}``.

    Attributes:
        fit_id: Ajuste ``succeeded``; sus parámetros de MRCD deben ser los que usará la carta.
        params: Parámetros de la carta (Fase I). Obligatorios si el dataset del ajuste no viene
            de una ronda automática; si viene, se heredan de los límites que lo produjeron y, si
            se mandan, deben ser iguales (``LIMITS_PARAMS_MISMATCH``).
        recalibration_id: Recalibración del dataset del ajuste: los parámetros se heredan de la
            versión base (Q8) con la semilla de la recalibración.
    """

    fit_id: str = Field(min_length=1)
    params: T2MRCDParamsIn | None = None
    recalibration_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _one_form(self) -> Self:
        """Rechaza ``params`` y ``recalibration_id`` a la vez.

        Returns:
            El modelo validado.

        Raises:
            ValueError: Si llegan los dos.
        """
        if self.params is not None and self.recalibration_id is not None:
            msg = "se pide con {fit_id, params?} o con {fit_id, recalibration_id}, no ambos"
            raise ValueError(msg)
        return self


class AssignableCauseIn(RequestModel):
    """Fila excluida por una persona.

    Attributes:
        row: Índice de la fila en el dataset del ajuste (base 0).
        cause: Cuál fue la causa.
    """

    row: int = Field(ge=0)
    cause: str | None = Field(default=None, max_length=500)

    def to_record(self) -> AssignableCause:
        """Convierte a registro.

        Returns:
            La fila con su causa.
        """
        return AssignableCause(row=self.row, cause=self.cause)


class DepurationRequest(RequestModel):
    """Depuración: ``{dataset_id, assignable_cause}`` o ``{fit_id, limits_id}``.

    La exclusión humana referencia el dataset (sin ajuste) y solo se admite al principio; en las
    candidatas de una recalibración se pide con ``{dataset_id}`` solo (sale de las anotaciones).
    La ronda automática referencia el ajuste y sus límites. La forma la valida el caso de uso
    (``details.reason``).

    Attributes:
        dataset_id: Dataset (exclusión humana).
        fit_id: Ajuste ``succeeded`` (ronda automática).
        limits_id: Límites del mismo ajuste (ronda automática).
        assignable_cause: Filas del dataset con causa asignable (exclusión humana).
    """

    dataset_id: str | None = Field(default=None, min_length=1)
    fit_id: str | None = Field(default=None, min_length=1)
    limits_id: str | None = Field(default=None, min_length=1)
    assignable_cause: list[AssignableCauseIn] = Field(default_factory=list)


class ModelFromRefsRequest(RequestModel):
    """Modelo a partir de referencias: ``{depuration_id}`` o ``{fit_id, limits_id}``.

    Attributes:
        depuration_id: Depuración final.
        fit_id: Ajuste final (sin depuración automática posterior).
        limits_id: Límites de ese ajuste.
        lifecycle_policy: Política de revalidación.
    """

    depuration_id: str | None = Field(default=None, min_length=1)
    fit_id: str | None = Field(default=None, min_length=1)
    limits_id: str | None = Field(default=None, min_length=1)
    lifecycle_policy: LifecyclePolicyIn | None = None

    @model_validator(mode="after")
    def _one_form(self) -> Self:
        """Exige exactamente una de las dos formas.

        Returns:
            El modelo validado.

        Raises:
            ValueError: Si no es exactamente una forma.
        """
        by_depuration = self.depuration_id is not None
        by_refs = self.fit_id is not None and self.limits_id is not None
        partial = (self.fit_id is None) != (self.limits_id is None)
        if by_depuration == by_refs or partial:
            msg = "se pide con {depuration_id} o con {fit_id, limits_id}"
            raise ValueError(msg)
        return self


class Phase1PipelineRequest(RequestModel):
    """Fase I completa por pasos (orquestación).

    Attributes:
        dataset_id: Dataset raíz.
        params: Parámetros de la carta.
        assignable_cause: Filas del dataset raíz con causa asignable.
        lifecycle_policy: Política del modelo resultante.
    """

    dataset_id: str = Field(min_length=1)
    params: T2MRCDParamsIn
    assignable_cause: list[AssignableCauseIn] = Field(default_factory=list)
    lifecycle_policy: LifecyclePolicyIn | None = None


# --- respuestas -----------------------------------------------------------------------------------


class FitResponse(ResponseModel):
    """Estado de un ajuste y, si terminó bien, su resumen."""

    id: str
    status: JobState
    dataset_id: str
    params: dict[str, object]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: MRCDFitOut | None = None
    error: ErrorBody | None = None

    @classmethod
    def of(cls, record: FitRecord, include: Collection[str]) -> "FitResponse":
        """Convierte el registro.

        Args:
            record: Ajuste.
            include: Partes opcionales.

        Returns:
            La respuesta.
        """
        return cls(
            id=record.fit_id,
            status=record.status.value,
            dataset_id=record.dataset_id,
            params=dict(record.params),
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            result=None
            if record.result is None
            else MRCDFitOut.of(record.result, covariance="covariance" in include),
            error=error_body(record.error),
        )


class LimitsResponse(ResponseModel):
    """Estado de una calibración y, si terminó bien, sus límites."""

    id: str
    status: JobState
    fit_id: str
    params: dict[str, object]
    seed: int
    stage_kind: str
    round: int
    spawn_key: list[int]
    recalibration_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: LimitsOut | None = None
    clean_rows: list[bool] | None = None
    error: ErrorBody | None = None

    @classmethod
    def of(cls, record: LimitsRecord, include: Collection[str]) -> "LimitsResponse":
        """Convierte el registro.

        Args:
            record: Límites.
            include: Partes opcionales.

        Returns:
            La respuesta.
        """
        clean = record.clean_rows
        return cls(
            id=record.limits_id,
            status=record.status.value,
            fit_id=record.fit_id,
            params=dict(record.params),
            seed=record.seed,
            stage_kind=record.stage_kind,
            round=record.round,
            spawn_key=list(record.spawn_key),
            recalibration_id=record.recalibration_id,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            result=None if record.result is None else LimitsOut.of(record.result),
            clean_rows=None
            if clean is None or "clean_rows" not in include
            else [bool(v) for v in clean],
            error=error_body(record.error),
        )


class AssignableCauseOut(ResponseModel):
    """Fila excluida por una persona (con su anotación al recalibrar)."""

    row: int
    cause: str | None
    annotation_id: str | None


class DepurationResponse(ResponseModel):
    """Estado de una depuración y, si terminó bien, su resultado."""

    id: str
    status: JobState
    dataset_id: str
    fit_id: str | None
    limits_id: str | None
    round: int
    assignable_cause: list[AssignableCauseOut]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    converged: bool | None
    final: bool | None
    exhausted: bool | None
    output_dataset_id: str | None
    next_step: str | None
    n_kept: int | None
    n_excluded_assignable_cause: int | None
    n_excluded_automatic: int | None
    row_disposition: list[str] | None = None
    error: ErrorBody | None = None

    @classmethod
    def of(cls, record: DepurationRecord, include: Collection[str]) -> "DepurationResponse":
        """Convierte el registro.

        Args:
            record: Depuración.
            include: Partes opcionales.

        Returns:
            La respuesta.
        """
        result = record.result

        def count(kind: RowDisposition) -> int | None:
            return None if result is None else sum(1 for d in result if d is kind)

        return cls(
            id=record.depuration_id,
            status=record.status.value,
            dataset_id=record.dataset_id,
            fit_id=record.fit_id,
            limits_id=record.limits_id,
            round=record.round,
            assignable_cause=[
                AssignableCauseOut(row=a.row, cause=a.cause, annotation_id=a.annotation_id)
                for a in record.assignable_cause
            ],
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            converged=record.converged,
            final=record.final,
            exhausted=record.exhausted,
            output_dataset_id=record.output_dataset_id,
            next_step=None if record.next_step is None else record.next_step.value,
            n_kept=count(RowDisposition.KEPT),
            n_excluded_assignable_cause=count(RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE),
            n_excluded_automatic=count(RowDisposition.EXCLUDED_AUTOMATIC),
            row_disposition=None
            if result is None or "row_disposition" not in include
            else [d.value for d in result],
            error=error_body(record.error),
        )


class PipelineStepOut(ResponseModel):
    """Paso de una tubería."""

    kind: str
    id: str


class PipelineResponse(ResponseModel):
    """Estado de una tubería, sus pasos y, si terminó bien, el modelo."""

    id: str
    kind: str
    recalibration_id: str | None
    status: JobState
    dataset_id: str
    params: dict[str, object]
    steps: list[PipelineStepOut]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    model_id: str | None
    error: ErrorBody | None = None

    @classmethod
    def of(cls, record: PipelineRecord) -> "PipelineResponse":
        """Convierte el registro.

        Args:
            record: Tubería.

        Returns:
            La respuesta.
        """
        return cls(
            id=record.pipeline_id,
            kind=record.kind.value,
            recalibration_id=record.recalibration_id,
            status=record.status.value,
            dataset_id=record.dataset_id,
            params=dict(record.params),
            steps=[PipelineStepOut(kind=s.kind, id=s.resource_id) for s in record.steps],
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            model_id=record.model_id,
            error=error_body(record.error),
        )
