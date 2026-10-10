"""Schemas HTTP de la carta T²MRCD: peticiones, respuestas y su conversión desde el dominio.

Los parámetros estadísticos que el cliente no envía **no** se rellenan aquí: se omiten y la
carta aplica sus defaults citados (``docs/metodos/t2mrcd.md``). Así la API no duplica ningún
default estadístico. Las estrategias (criterio de fila limpia, agregación, pruebas de cambio) no
se exponen: se usan las de producción de la carta.

Mejora M3: las matrices grandes (histórico ``n x p``, base de una versión, dispersión ``p x p``)
y los vectores por fila solo se devuelven si se piden con ``?include=``.
"""

from collections.abc import Collection
from dataclasses import replace
from datetime import datetime
from typing import Annotated, Literal

import numpy as np
from pydantic import Field, FiniteFloat

from voracious.api.schemas.common import (
    ErrorBody,
    JobState,
    RequestModel,
    ResponseModel,
    UtcDatetime,
    Vector,
)
from voracious.application.lifecycle import ChartStatusView
from voracious.application.records import (
    ErrorInfo,
    LifecyclePolicy,
    ModelRecord,
    ModelVersion,
    MonitoringRecord,
    ObservationRecord,
    RecalibrationRecord,
    SignalAnnotation,
    StructuralEvent,
)
from voracious.domain.charts.t2mrcd import (
    T2MRCD_MRCD_ALPHA,
    BootstrapLimits,
    ComparisonResult,
    LimitsSnapshot,
    T2MRCDBootstrap,
    T2MRCDModel,
    T2MRCDParams,
    T2MRCDRecalibrationParams,
    T2MRCDRecalibrationReport,
)
from voracious.domain.estimators.mrcd import MRCDFit, MRCDParams

__all__ = [
    "AnnotationOut",
    "AnnotationRequest",
    "ApproveRequest",
    "ChartStatusOut",
    "ComparisonOut",
    "LifecyclePolicyIn",
    "LimitsOut",
    "MRCDFitOut",
    "MRCDIn",
    "ModelInclude",
    "ModelResponse",
    "ObservationOut",
    "ProposalOut",
    "RecalibrationInclude",
    "RecalibrationRequest",
    "RecalibrationResponse",
    "RejectRequest",
    "ScoreRequest",
    "ScoreResponse",
    "StructuralEventOut",
    "StructuralEventRequest",
    "T2MRCDParamsIn",
    "VersionDetail",
    "VersionInclude",
    "VersionSummary",
    "error_body",
    "matrix",
]

ModelInclude = Literal["training_data", "observed_at", "covariance", "historical"]
"""Partes grandes opcionales de ``GET …/models/{id}``."""

VersionInclude = Literal["base_data", "base_refs", "covariance", "historical"]
"""Partes grandes opcionales de ``GET …/versions/{n}``."""

RecalibrationInclude = Literal["row_disposition"]
"""Partes grandes opcionales de ``GET …/recalibrations/{id}``."""


# --- peticiones ---------------------------------------------------------------


class BootstrapIn(RequestModel):
    """Bootstrap de los límites; lo omitido toma el default de la carta.

    Attributes:
        seed: Semilla raíz (obligatoria).
        n_replicates: Réplicas B.
        alpha_limit: Nivel del límite de Fase I.
        phase2_alpha_limit: Nivel del límite de Fase II.
    """

    seed: int = Field(ge=0)
    n_replicates: int | None = Field(default=None, ge=1)
    alpha_limit: float | None = Field(default=None, gt=0, lt=1)
    phase2_alpha_limit: float | None = Field(default=None, gt=0, lt=1)


class MRCDIn(RequestModel):
    """Parámetros de MRCD; lo omitido toma el default de la carta (``alpha`` 0.75).

    Attributes:
        alpha: Proporción del subconjunto.
        h: Tamaño del subconjunto.
        maxcsteps: Máximo de C-steps.
        rho: Regularización fija.
        target: Matriz objetivo.
        maxcond: Número de condición objetivo.
    """

    alpha: float | None = None
    h: int | None = None
    maxcsteps: int | None = None
    rho: float | None = None
    target: Literal["identity", "equicorrelation"] | None = None
    maxcond: float | None = None

    def to_domain(self) -> MRCDParams:
        """Parámetros de MRCD con solo los campos enviados.

        Lo omitido toma el ``alpha`` de la carta (``T2MRCD_MRCD_ALPHA``, 0.75, P2) y los
        defaults de ``rrcov`` de ``MRCDParams``; aquí no se fija ningún valor propio.

        Returns:
            Los parámetros de MRCD.
        """
        return MRCDParams(**{"alpha": T2MRCD_MRCD_ALPHA, **self.model_dump(exclude_none=True)})


class T2MRCDParamsIn(RequestModel):
    """Parámetros de la carta.

    Attributes:
        bootstrap: Bootstrap de los límites.
        mrcd: Parámetros de MRCD.
    """

    bootstrap: BootstrapIn
    mrcd: MRCDIn | None = None

    def to_domain(self) -> T2MRCDParams:
        """Construye los parámetros de dominio con solo los campos enviados.

        Returns:
            Los parámetros de la carta.
        """
        params = T2MRCDParams(
            bootstrap=T2MRCDBootstrap(**self.bootstrap.model_dump(exclude_none=True))
        )
        if self.mrcd is not None:
            params = replace(params, mrcd=self.mrcd.to_domain())
        return params


class LifecyclePolicyIn(RequestModel):
    """Política de revalidación; un campo omitido toma el default, ``null`` lo desactiva.

    Attributes:
        revalidate_every_months: Meses.
        revalidate_every_observations: Observaciones.
    """

    revalidate_every_months: int | None = Field(default=None, ge=1)
    revalidate_every_observations: int | None = Field(default=None, ge=1)

    def to_domain(self) -> LifecyclePolicy:
        """Construye la política con solo los campos enviados.

        Returns:
            La política.
        """
        return LifecyclePolicy(**self.model_dump(exclude_unset=True))


class ObservationIn(RequestModel):
    """Una observación de Fase II.

    Attributes:
        observed_at: Fecha con zona horaria.
        values: Valores de las ``p`` variables.
    """

    observed_at: UtcDatetime
    values: Vector


class ScoreRequest(RequestModel):
    """Lote de observaciones a puntuar.

    Attributes:
        observations: Observaciones.
        batch_label: Etiqueta del lote.
        variables: Nombre de cada columna de ``values``, opcional; si el modelo tiene nombres
            (los de su dataset raíz) deben ser los mismos y en el mismo orden
            (``422 VARIABLES_MISMATCH``).
    """

    observations: list[ObservationIn] = Field(min_length=1)
    batch_label: str | None = Field(default=None, max_length=200)
    variables: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None, min_length=1
    )


class AnnotationRequest(RequestModel):
    """Anotación de una señal.

    Attributes:
        assignable_cause: Causa asignable confirmada.
        cause: Cuál.
        action: Acción tomada.
        actor: Quién anota.
    """

    assignable_cause: bool
    cause: str | None = None
    action: str | None = None
    actor: str | None = None


class StructuralEventRequest(RequestModel):
    """Evento estructural.

    Attributes:
        occurred_at: Cuándo ocurrió.
        description: Descripción.
        actor: Quién lo registra.
    """

    occurred_at: UtcDatetime
    description: str = Field(min_length=1)
    actor: str | None = None


class ApproveRequest(RequestModel):
    """Aprobación de una propuesta.

    Attributes:
        effective_from: Desde cuándo rige (por defecto, ahora).
        note: Nota.
        actor: Quién aprueba.
    """

    effective_from: UtcDatetime | None = None
    note: str | None = None
    actor: str | None = None


class RejectRequest(RequestModel):
    """Rechazo de una propuesta.

    Attributes:
        note: Motivo.
        actor: Quién rechaza.
    """

    note: str | None = None
    actor: str | None = None


class RecalibrationParamsIn(RequestModel):
    """Parámetros de la recalibración; lo omitido toma el default de la carta.

    Attributes:
        seed: Semilla raíz (obligatoria).
        min_observations: Mínimo de filas nuevas conservadas.
        relative_change_threshold: Umbral del cambio relativo.
        threshold_decides: Si el umbral decide.
    """

    seed: int = Field(ge=0)
    min_observations: int | None = Field(default=None, ge=1)
    relative_change_threshold: FiniteFloat | None = Field(default=None, gt=0)
    threshold_decides: bool | None = None

    def to_domain(self) -> T2MRCDRecalibrationParams:
        """Construye los parámetros de dominio con solo los campos enviados.

        Returns:
            Los parámetros de la recalibración.
        """
        return T2MRCDRecalibrationParams(**self.model_dump(exclude_none=True))


class RecalibrationRequest(RequestModel):
    """Recalibración: todo junto (``pipeline``, ``202``) o paso a paso (``stepwise``, ``201``).

    Attributes:
        range_from: Inicio del rango (inclusivo).
        range_to: Fin del rango (inclusivo).
        params: Parámetros.
        force_replace: Reemplazo forzado.
        actor: Quién la pide.
        mode: ``pipeline`` (por defecto) o ``stepwise``.
    """

    range_from: UtcDatetime
    range_to: UtcDatetime
    params: RecalibrationParamsIn
    force_replace: bool = False
    actor: str | None = None
    mode: Literal["pipeline", "stepwise"] = "pipeline"


# --- respuestas ---------------------------------------------------------------


def error_body(error: ErrorInfo | None) -> ErrorBody | None:
    """Error de un trabajo ``failed`` en el formato uniforme.

    Args:
        error: Error del registro.

    Returns:
        El cuerpo del error o ``None``.
    """
    if error is None:
        return None
    return ErrorBody(code=error.code, message=error.message, details=dict(error.details))


def matrix(data: object) -> list[list[float]]:
    """Matriz numpy a listas de ``float``.

    Args:
        data: Arreglo ``n x p``.

    Returns:
        Las filas.
    """
    return [[float(v) for v in row] for row in np.asarray(data, dtype=np.float64)]


class LimitsOut(ResponseModel):
    """Límites bootstrap de un modelo."""

    phase1_limit: float
    phase2_limit: float
    n_replicates: int
    seed: int
    n_clean: int
    alpha_limit: float
    phase2_alpha_limit: float
    oob_size_min: int
    oob_size_mean: float
    phase1_mc_error: float | None
    phase2_mc_error: float | None
    estimator_name: str
    sampler_name: str

    @classmethod
    def of(cls, limits: object) -> "LimitsOut":
        """Convierte unos límites de la carta.

        Args:
            limits: ``BootstrapLimits``.

        Returns:
            La respuesta.

        Raises:
            TypeError: Si no son ``BootstrapLimits``.
        """
        if not isinstance(limits, BootstrapLimits):
            msg = "los límites no son de T²MRCD"
            raise TypeError(msg)
        return cls(
            phase1_limit=limits.phase1_limit,
            phase2_limit=limits.phase2_limit,
            n_replicates=limits.n_replicates,
            seed=limits.seed,
            n_clean=limits.n_clean,
            alpha_limit=limits.alpha_limit,
            phase2_alpha_limit=limits.phase2_alpha_limit,
            oob_size_min=limits.oob_size_min,
            oob_size_mean=limits.oob_size_mean,
            phase1_mc_error=limits.phase1_mc_error,
            phase2_mc_error=limits.phase2_mc_error,
            estimator_name=limits.estimator_name,
            sampler_name=limits.sampler_name,
        )


class MRCDFitOut(ResponseModel):
    """Resumen del ajuste MRCD; ``center`` y ``cov`` solo con ``include=covariance``."""

    alpha: float
    h: int
    rho: float
    cnp2: float
    crit: float
    n_obs: int
    center: list[float] | None = None
    cov: list[list[float]] | None = None

    @classmethod
    def of(cls, fit: object, *, covariance: bool) -> "MRCDFitOut":
        """Convierte un ajuste MRCD.

        Args:
            fit: ``MRCDFit``.
            covariance: Incluir ``center`` y ``cov``.

        Returns:
            La respuesta.

        Raises:
            TypeError: Si no es un ``MRCDFit``.
        """
        if not isinstance(fit, MRCDFit):
            msg = "el ajuste no es de MRCD"
            raise TypeError(msg)
        return cls(
            alpha=fit.alpha,
            h=fit.h,
            rho=fit.rho,
            cnp2=fit.cnp2,
            crit=fit.crit,
            n_obs=fit.n_obs,
            center=[float(v) for v in fit.center] if covariance else None,
            cov=matrix(fit.cov) if covariance else None,
        )


class T2MRCDModelOut(ResponseModel):
    """Modelo de Fase I de T²MRCD."""

    n_features: int
    n_base: int
    limit_regime: str
    operative_limit: float
    limits: LimitsOut
    mrcd: MRCDFitOut
    pymrcd_version: str
    seed: int
    statistic_reference: str
    historical_t2: list[float] | None = None
    historical_outlier: list[bool] | None = None

    @classmethod
    def of(cls, model: object, include: Collection[str]) -> "T2MRCDModelOut":
        """Convierte el modelo de la carta.

        Args:
            model: Modelo (``T2MRCDModel``).
            include: Partes opcionales pedidas.

        Returns:
            La respuesta.

        Raises:
            TypeError: Si no es un ``T2MRCDModel``.
        """
        if not isinstance(model, T2MRCDModel):
            msg = "el modelo no es de T²MRCD"
            raise TypeError(msg)
        historical = "historical" in include
        return cls(
            n_features=model.n_features,
            n_base=model.n_base,
            limit_regime=str(model.limit_regime),
            operative_limit=model.operative_limit,
            limits=LimitsOut.of(model.limits),
            mrcd=MRCDFitOut.of(model.mrcd, covariance="covariance" in include),
            pymrcd_version=model.pymrcd_version,
            seed=model.seed,
            statistic_reference=model.statistic_reference,
            historical_t2=[float(v) for v in model.historical_t2] if historical else None,
            historical_outlier=[bool(v) for v in model.historical_outlier] if historical else None,
        )


class ProvenanceOut(ResponseModel):
    """De qué recursos se ensambló el modelo."""

    root_dataset_id: str
    fit_id: str
    limits_id: str
    exclusion_id: str | None


class LifecyclePolicyOut(ResponseModel):
    """Política de revalidación."""

    revalidate_every_months: int | None
    revalidate_every_observations: int | None


class ModelResponse(ResponseModel):
    """Estado de un modelo y, si terminó bien, el modelo."""

    id: str
    status: JobState
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    params: dict[str, object]
    lifecycle_policy: LifecyclePolicyOut
    n_rows: int
    n_features: int
    variables: list[str] | None = None
    has_observed_at: bool = False
    provenance: ProvenanceOut | None = None
    result: T2MRCDModelOut | None = None
    error: ErrorBody | None = None
    training_data: list[list[float]] | None = None
    observed_at: list[datetime] | None = None

    @classmethod
    def of(cls, record: ModelRecord, include: Collection[str]) -> "ModelResponse":
        """Convierte el registro.

        Args:
            record: Modelo.
            include: Partes opcionales pedidas.

        Returns:
            La respuesta.
        """
        n_rows, n_features = record.training_data.shape
        policy = record.lifecycle_policy
        return cls(
            id=record.model_id,
            status=record.status.value,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            params=dict(record.params),
            lifecycle_policy=LifecyclePolicyOut(
                revalidate_every_months=policy.revalidate_every_months,
                revalidate_every_observations=policy.revalidate_every_observations,
            ),
            n_rows=int(n_rows),
            n_features=int(n_features),
            variables=None if record.variables is None else list(record.variables),
            has_observed_at=record.observed_at is not None,
            provenance=None
            if record.provenance is None
            else ProvenanceOut(
                root_dataset_id=record.provenance.root_dataset_id,
                fit_id=record.provenance.fit_id,
                limits_id=record.provenance.limits_id,
                exclusion_id=record.provenance.exclusion_id,
            ),
            result=None if record.model is None else T2MRCDModelOut.of(record.model, include),
            error=error_body(record.error),
            training_data=matrix(record.training_data) if "training_data" in include else None,
            observed_at=None
            if "observed_at" not in include or record.observed_at is None
            else list(record.observed_at),
        )


class ScoreSummaryOut(ResponseModel):
    """Observaciones registradas por una puntuación."""

    observation_ids: list[str]
    version_numbers: list[int]
    n_signals: int


class ScoreResponse(ResponseModel):
    """Estado de una puntuación (Fase II)."""

    id: str
    model_id: str
    status: JobState
    batch_label: str | None
    n_observations: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: ScoreSummaryOut | None = None
    error: ErrorBody | None = None

    @classmethod
    def of(cls, record: MonitoringRecord) -> "ScoreResponse":
        """Convierte el registro.

        Args:
            record: Monitoreo.

        Returns:
            La respuesta.
        """
        result = record.result
        return cls(
            id=record.monitoring_id,
            model_id=record.model_id,
            status=record.status.value,
            batch_label=record.batch_label,
            n_observations=int(record.observations.shape[0]),
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            result=None
            if result is None
            else ScoreSummaryOut(
                observation_ids=list(result.observation_ids),
                version_numbers=list(result.version_numbers),
                n_signals=result.n_signals,
            ),
            error=error_body(record.error),
        )


class AnnotationOut(ResponseModel):
    """Anotación de una señal."""

    id: str
    observation_id: str
    assignable_cause: bool
    cause: str | None
    action: str | None
    actor: str | None
    created_at: datetime

    @classmethod
    def of(cls, annotation: SignalAnnotation) -> "AnnotationOut":
        """Convierte la anotación.

        Args:
            annotation: Anotación.

        Returns:
            La respuesta.
        """
        return cls(
            id=annotation.annotation_id,
            observation_id=annotation.observation_id,
            assignable_cause=annotation.assignable_cause,
            cause=annotation.cause,
            action=annotation.action,
            actor=annotation.actor,
            created_at=annotation.created_at,
        )


class ObservationOut(ResponseModel):
    """Observación registrada con su anotación vigente."""

    id: str
    score_id: str
    batch_label: str | None
    observed_at: datetime
    values: list[float]
    t2: float
    limit: float
    limit_kind: str
    version_number: int
    signal: bool
    recorded_at: datetime
    annotation: AnnotationOut | None = None

    @classmethod
    def of(cls, record: ObservationRecord, annotation: SignalAnnotation | None) -> "ObservationOut":
        """Convierte la observación.

        Args:
            record: Observación.
            annotation: Anotación vigente.

        Returns:
            La respuesta.
        """
        return cls(
            id=record.observation_id,
            score_id=record.monitoring_id,
            batch_label=record.batch_label,
            observed_at=record.observed_at,
            values=[float(v) for v in record.values],
            t2=record.t2,
            limit=record.limit,
            limit_kind=record.limit_kind,
            version_number=record.version_number,
            signal=record.signal,
            recorded_at=record.recorded_at,
            annotation=None if annotation is None else AnnotationOut.of(annotation),
        )


class StructuralEventOut(ResponseModel):
    """Evento estructural."""

    id: str
    occurred_at: datetime
    description: str
    actor: str | None
    registered_at: datetime

    @classmethod
    def of(cls, event: StructuralEvent) -> "StructuralEventOut":
        """Convierte el evento.

        Args:
            event: Evento.

        Returns:
            La respuesta.
        """
        return cls(
            id=event.event_id,
            occurred_at=event.occurred_at,
            description=event.description,
            actor=event.actor,
            registered_at=event.registered_at,
        )


class LimitsSnapshotOut(ResponseModel):
    """Límites de una versión (antes o después de recalibrar)."""

    phase1_limit: float
    phase2_limit: float
    phase1_mc_error: float | None
    phase2_mc_error: float | None
    regime: str
    operative_limit: float
    n_base: int

    @classmethod
    def of(cls, snapshot: LimitsSnapshot) -> "LimitsSnapshotOut":
        """Convierte la instantánea.

        Args:
            snapshot: Límites.

        Returns:
            La respuesta.
        """
        return cls(
            phase1_limit=snapshot.phase1_limit,
            phase2_limit=snapshot.phase2_limit,
            phase1_mc_error=snapshot.phase1_mc_error,
            phase2_mc_error=snapshot.phase2_mc_error,
            regime=str(snapshot.regime),
            operative_limit=snapshot.operative_limit,
            n_base=snapshot.n_base,
        )


class ChangeTestOut(ResponseModel):
    """Resultado de una prueba formal de cambio."""

    name: str
    statistic: float
    p_value: float | None
    changed: bool


class ComparisonOut(ResponseModel):
    """Comparación de bases."""

    metric_name: str
    relative_change: float
    threshold: float
    exceeds_threshold: bool
    threshold_decides: bool
    covariance: ChangeTestOut
    mean: ChangeTestOut
    decision_rule_name: str
    changed: bool

    @classmethod
    def of(cls, result: ComparisonResult) -> "ComparisonOut":
        """Convierte la comparación.

        Args:
            result: Comparación.

        Returns:
            La respuesta.
        """
        cov, mean = result.covariance, result.mean
        return cls(
            metric_name=result.metric_name,
            relative_change=result.relative_change,
            threshold=result.threshold,
            exceeds_threshold=result.exceeds_threshold,
            threshold_decides=result.threshold_decides,
            covariance=ChangeTestOut(
                name=cov.name, statistic=cov.statistic, p_value=cov.p_value, changed=cov.changed
            ),
            mean=ChangeTestOut(
                name=mean.name,
                statistic=mean.statistic,
                p_value=mean.p_value,
                changed=mean.changed,
            ),
            decision_rule_name=result.decision_rule_name,
            changed=result.changed,
        )


class RecalibrationReportOut(ResponseModel):
    """Informe antes/después de una recalibración."""

    decision: str
    forced: bool
    n_base: int
    n_new: int
    n_excluded_assignable_cause: int
    n_kept_new: int
    min_observations: int
    comparison: ComparisonOut | None
    before: LimitsSnapshotOut
    after: LimitsSnapshotOut | None
    phase2_exceeds_phase1: bool | None
    row_disposition: list[str] | None = None

    @classmethod
    def of(cls, report: object, include: Collection[str]) -> "RecalibrationReportOut":
        """Convierte el informe de la carta.

        Args:
            report: Informe (``T2MRCDRecalibrationReport``).
            include: Partes opcionales pedidas.

        Returns:
            La respuesta.

        Raises:
            TypeError: Si no es un informe de T²MRCD.
        """
        if not isinstance(report, T2MRCDRecalibrationReport):
            msg = "el informe no es de T²MRCD"
            raise TypeError(msg)
        return cls(
            decision=str(report.decision),
            forced=report.forced,
            n_base=report.n_base,
            n_new=report.n_new,
            n_excluded_assignable_cause=report.n_excluded_assignable_cause,
            n_kept_new=report.n_kept_new,
            min_observations=report.min_observations,
            comparison=None if report.comparison is None else ComparisonOut.of(report.comparison),
            before=LimitsSnapshotOut.of(report.before),
            after=None if report.after is None else LimitsSnapshotOut.of(report.after),
            phase2_exceeds_phase1=report.phase2_exceeds_phase1,
            row_disposition=[str(d) for d in report.row_disposition]
            if "row_disposition" in include
            else None,
        )


class BaseRowOut(ResponseModel):
    """Origen de una fila de la base y su fecha, si se conoce (trazabilidad)."""

    source: str
    ref: str
    observed_at: datetime | None = None


class ExclusionOut(ResponseModel):
    """Fila candidata que no entró en la base."""

    source: str
    ref: str
    reason: str
    annotation_id: str | None
    observed_at: datetime | None = None


class VersionSummary(ResponseModel):
    """Versión de un modelo, sin el modelo ni la base."""

    number: int
    status: Literal["proposed", "active", "superseded", "rejected"]
    decision: str
    justification: str
    created_at: datetime
    effective_from: datetime | None
    approved_at: datetime | None
    rejected_at: datetime | None
    decided_by: str | None
    decision_note: str | None
    recalibration_id: str | None
    structural_event_id: str | None
    previous_number: int | None
    base_hash: str
    n_base: int
    n_exclusions: int

    @classmethod
    def fields_of(cls, version: ModelVersion) -> dict[str, object]:
        """Campos comunes del resumen.

        Args:
            version: Versión.

        Returns:
            Los campos.
        """
        return {
            "number": version.number,
            "status": version.status.value,
            "decision": str(version.decision),
            "justification": version.justification,
            "created_at": version.created_at,
            "effective_from": version.effective_from,
            "approved_at": version.approved_at,
            "rejected_at": version.rejected_at,
            "decided_by": version.decided_by,
            "decision_note": version.decision_note,
            "recalibration_id": version.recalibration_id,
            "structural_event_id": version.structural_event_id,
            "previous_number": version.previous_number,
            "base_hash": version.base_hash,
            "n_base": int(version.base_data.shape[0]),
            "n_exclusions": len(version.exclusions),
        }

    @classmethod
    def of(cls, version: ModelVersion) -> "VersionSummary":
        """Convierte la versión.

        Args:
            version: Versión.

        Returns:
            El resumen.
        """
        return cls.model_validate(cls.fields_of(version))


class VersionDetail(VersionSummary):
    """Versión con su modelo, su informe y (con ``include``) su base."""

    model: T2MRCDModelOut
    report: RecalibrationReportOut | None
    exclusions: list[ExclusionOut] | None = None
    base_refs: list[BaseRowOut] | None = None
    base_data: list[list[float]] | None = None

    @classmethod
    def detail(cls, version: ModelVersion, include: Collection[str]) -> "VersionDetail":
        """Convierte la versión con detalle.

        Args:
            version: Versión.
            include: Partes opcionales pedidas.

        Returns:
            El detalle.
        """
        with_refs = "base_refs" in include
        return cls.model_validate(
            {
                **cls.fields_of(version),
                "model": T2MRCDModelOut.of(version.model, include),
                "report": None
                if version.report is None
                else RecalibrationReportOut.of(version.report, include),
                "exclusions": [
                    ExclusionOut(
                        source=str(e.ref.source),
                        ref=e.ref.ref,
                        reason=str(e.reason),
                        annotation_id=e.annotation_id,
                        observed_at=e.ref.observed_at,
                    )
                    for e in version.exclusions
                ]
                if with_refs
                else None,
                "base_refs": [
                    BaseRowOut(source=str(r.source), ref=r.ref, observed_at=r.observed_at)
                    for r in version.base_refs
                ]
                if with_refs
                else None,
                "base_data": matrix(version.base_data) if "base_data" in include else None,
            }
        )


class ChartStatusOut(ResponseModel):
    """Estado de la carta y sus avisos."""

    status: str
    active_version: int
    proposed_version: int | None
    unresolved_event_id: str | None
    revalidation_due: bool
    revalidation_due_at: datetime | None
    observations_since_active: int
    notices: list[str]

    @classmethod
    def of(cls, view: ChartStatusView) -> "ChartStatusOut":
        """Convierte el estado.

        Args:
            view: Estado.

        Returns:
            La respuesta.
        """
        return cls(
            status=str(view.status),
            active_version=view.active_version,
            proposed_version=view.proposed_version,
            unresolved_event_id=view.unresolved_event_id,
            revalidation_due=view.revalidation_due,
            revalidation_due_at=view.revalidation_due_at,
            observations_since_active=view.observations_since_active,
            notices=list(view.notices),
        )


class ProposalOut(ResponseModel):
    """Pasos con los que se pidió la versión propuesta."""

    fit_id: str
    limits_id: str
    comparison_id: str | None
    status: JobState
    requested_at: datetime


class RecalibrationResponse(ResponseModel):
    """Estado de una recalibración y, si terminó bien, su informe y la versión propuesta."""

    id: str
    model_id: str
    mode: Literal["pipeline", "stepwise"]
    status: JobState
    range_from: datetime
    range_to: datetime
    params: dict[str, object]
    force_replace: bool
    base_version_number: int
    structural_event_id: str | None
    actor: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    outcome: str | None
    proposed_version: int | None
    candidates_dataset_id: str | None
    n_candidates: int
    n_already_in_base: int
    inherited_params: dict[str, object]
    pipeline_id: str | None
    proposal: ProposalOut | None
    report: RecalibrationReportOut | None = None
    error: ErrorBody | None = None

    @classmethod
    def of(cls, record: RecalibrationRecord, include: Collection[str]) -> "RecalibrationResponse":
        """Convierte el registro.

        Args:
            record: Recalibración.
            include: Partes opcionales pedidas.

        Returns:
            La respuesta.
        """
        proposal = record.proposal
        return cls(
            id=record.recalibration_id,
            model_id=record.model_id,
            mode=record.mode.value,
            status=record.status.value,
            range_from=record.range_from,
            range_to=record.range_to,
            params=dict(record.params),
            force_replace=record.force_replace,
            base_version_number=record.base_version_number,
            structural_event_id=record.structural_event_id,
            actor=record.actor,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            outcome=None if record.outcome is None else str(record.outcome),
            proposed_version=record.proposed_version,
            candidates_dataset_id=record.candidates_dataset_id,
            n_candidates=len(record.candidate_ids),
            n_already_in_base=len(record.already_in_base_ids),
            inherited_params=dict(record.inherited_params),
            pipeline_id=record.pipeline_id,
            proposal=None
            if proposal is None
            else ProposalOut(
                fit_id=proposal.fit_id,
                limits_id=proposal.limits_id,
                comparison_id=proposal.comparison_id,
                status=proposal.status.value,
                requested_at=proposal.requested_at,
            ),
            report=None
            if record.report is None
            else RecalibrationReportOut.of(record.report, include),
            error=error_body(record.error),
        )
