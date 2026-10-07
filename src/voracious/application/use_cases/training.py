"""Fase I: ``TrainModel`` (encola), ``GetModel`` (consulta) y ``RunTrainingJob`` (ejecuta).

Al terminar bien, ``RunTrainingJob`` añade la **versión 0** del modelo, vigente desde el origen
(ADR 0008, D3): la carta del portafolio es el modelo y sus versiones cuelgan de él (D1).
"""

from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np
import numpy.typing as npt

from voracious.application.charts import ChartRegistry, as_versioned_model, resolve_chart
from voracious.application.lifecycle import base_content_hash, exclusion_reason, frozen_base
from voracious.application.ports import (
    Clock,
    IdGenerator,
    JobKind,
    JobQueue,
    JobRequest,
    ModelRepository,
    ModelVersionRepository,
)
from voracious.application.records import (
    BaseRowRef,
    BaseRowSource,
    ErrorInfo,
    Exclusion,
    JobStatus,
    LifecyclePolicy,
    ModelRecord,
    ModelVersion,
    VersionStatus,
)
from voracious.application.use_cases.common import INTERNAL_ERROR, get_model
from voracious.domain.common import DomainError, RecalibrationDecision, TaskMapper, as_matrix

__all__ = ["INTERNAL_ERROR", "GetModel", "RunTrainingJob", "TrainModel", "initial_version"]

INITIAL_JUSTIFICATION = "initial_fit"
"""Justificación de la versión 0: ajuste de Fase I sobre el histórico."""


@dataclass(frozen=True)
class TrainModel:
    """Crea un modelo ``queued`` y encola su entrenamiento.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        queue: Cola de trabajos.
        ids: Generador de identificadores.
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        training_data: npt.ArrayLike,
        params: object,
        lifecycle_policy: LifecyclePolicy | None = None,
    ) -> str:
        """Registra el modelo con los parámetros codificados como datos y encola la Fase I.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            training_data: Histórico ``n x p``.
            params: Parámetros de la carta (ya validados por su schema).
            lifecycle_policy: Política de revalidación; ``None`` usa la de por defecto.

        Returns:
            El ``model_id``.

        Raises:
            UnknownChartError: Si la carta no existe.
            InvalidInputError: Si ``training_data`` no es una matriz numérica ``n x p`` o los
                parámetros no se pueden codificar (estrategia sin nombre registrado).
        """
        chart = resolve_chart(self.charts, chart_id)
        data = as_matrix(training_data, name="training_data")
        encoded = chart.encode_params(params)
        record = ModelRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            model_id=self.ids.new_id(),
            status=JobStatus.QUEUED,
            params=encoded,
            training_data=data,
            created_at=self.clock.now(),
            lifecycle_policy=lifecycle_policy
            if lifecycle_policy is not None
            else LifecyclePolicy(),
        )
        self.models.add(record)
        self.queue.enqueue(
            JobRequest(
                kind=JobKind.TRAIN,
                tenant_id=tenant_id,
                chart_id=chart_id,
                model_id=record.model_id,
            )
        )
        return record.model_id


@dataclass(frozen=True)
class GetModel:
    """Consulta un modelo del tenant.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
    """

    charts: ChartRegistry
    models: ModelRepository

    def execute(self, tenant_id: str, chart_id: str, model_id: str) -> ModelRecord:
        """Devuelve el modelo.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            El registro del modelo.

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si no existe para ese tenant y esa carta.
        """
        resolve_chart(self.charts, chart_id)
        return get_model(self.models, tenant_id, chart_id, model_id)


def initial_version(record: ModelRecord, model: object, now: datetime) -> ModelVersion:
    """Versión 0 de un modelo recién ajustado: vigente desde el origen.

    La base son las filas del histórico marcadas en ``base_mask``; las excluidas por la
    depuración de la carta quedan en ``exclusions``.

    Args:
        record: Modelo (con su histórico).
        model: Modelo de la carta devuelto por ``fit_phase1``.
        now: Instante de creación y aprobación (UTC).

    Returns:
        La versión 0, ``active``.

    Raises:
        TypeError: Si el modelo no cumple ``VersionedModel`` o su máscara no tiene la longitud
            del histórico.
    """
    view = as_versioned_model(model)
    mask = np.asarray(view.base_mask, dtype=np.bool_)
    n_rows = record.training_data.shape[0]
    if mask.shape != (n_rows,) or len(view.row_disposition) != n_rows:
        msg = "la máscara de la base no tiene la longitud del histórico"
        raise TypeError(msg)
    base = np.ascontiguousarray(record.training_data[mask])
    refs = tuple(BaseRowRef(BaseRowSource.TRAINING, str(i)) for i in np.flatnonzero(mask))
    exclusions = tuple(
        Exclusion(ref=BaseRowRef(BaseRowSource.TRAINING, str(i)), reason=reason)
        for i, disposition in enumerate(view.row_disposition)
        if (reason := exclusion_reason(disposition)) is not None
    )
    return ModelVersion(
        tenant_id=record.tenant_id,
        chart_id=record.chart_id,
        model_id=record.model_id,
        number=0,
        status=VersionStatus.ACTIVE,
        model=model,
        base_data=frozen_base(base),
        base_hash=base_content_hash(base),
        base_refs=refs,
        exclusions=exclusions,
        decision=RecalibrationDecision.INITIAL,
        justification=INITIAL_JUSTIFICATION,
        created_at=now,
        effective_from=None,
        approved_at=now,
    )


@dataclass(frozen=True)
class RunTrainingJob:
    """Ejecuta la Fase I de un modelo encolado: ``running`` → ``succeeded | failed``.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        versions: Repositorio de versiones (recibe la versión 0).
        mapper: Reparto de tareas para la carta (réplicas bootstrap).
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    versions: ModelVersionRepository
    mapper: TaskMapper
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo. Es idempotente: si el modelo ya no está ``queued``, no hace nada.

        Un ``DomainError`` (incluidos parámetros codificados inválidos) deja el modelo ``failed``
        con su código y sus detalles. Cualquier otra excepción lo deja
        ``failed / INTERNAL_ERROR`` (sin traza en ``details``) y se relanza. Si termina bien,
        añade la versión 0 antes de marcar el modelo ``succeeded``.

        Args:
            job: Petición ``train``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``train``.
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si el modelo no existe.
        """
        if job.kind is not JobKind.TRAIN:
            msg = f"RunTrainingJob solo ejecuta trabajos 'train', no '{job.kind}'"
            raise ValueError(msg)
        chart = resolve_chart(self.charts, job.chart_id)
        record = get_model(self.models, job.tenant_id, job.chart_id, job.model_id)
        if record.status is not JobStatus.QUEUED:
            return
        record = replace(record, status=JobStatus.RUNNING, started_at=self.clock.now())
        self.models.update(record)
        try:
            params = chart.decode_params(record.params)
            model = chart.fit_phase1(record.training_data, params, mapper=self.mapper)
            finished_at = self.clock.now()
            self.versions.add(initial_version(record, model, finished_at))
        except DomainError as exc:
            error = ErrorInfo(code=exc.code, message=exc.message, details=exc.details)
            self.models.update(_finish(record, self.clock.now(), error=error))
            return
        except Exception:
            error = ErrorInfo(code=INTERNAL_ERROR, message="error interno en la Fase I")
            self.models.update(_finish(record, self.clock.now(), error=error))
            raise
        self.models.update(_finish(record, finished_at, model=model))


def _finish(
    record: ModelRecord,
    finished_at: datetime,
    *,
    model: object = None,
    error: ErrorInfo | None = None,
) -> ModelRecord:
    """Cierra un modelo en ``succeeded`` (con ``model``) o ``failed`` (con ``error``).

    Args:
        record: Registro en ``running``.
        finished_at: Instante de cierre (UTC).
        model: Modelo de la carta, si terminó bien.
        error: Error, si falló.

    Returns:
        El registro terminado.
    """
    status = JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED
    return replace(record, status=status, finished_at=finished_at, model=model, error=error)
