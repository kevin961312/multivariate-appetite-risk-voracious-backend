"""Fase I: ``TrainModel`` (encola), ``GetModel`` (consulta) y ``RunTrainingJob`` (ejecuta)."""

from dataclasses import dataclass, replace

import numpy.typing as npt

from voracious.application.charts import ChartRegistry, resolve_chart
from voracious.application.errors import ModelNotFoundError
from voracious.application.ports import (
    Clock,
    IdGenerator,
    JobKind,
    JobQueue,
    JobRequest,
    ModelRepository,
)
from voracious.application.records import ErrorInfo, JobStatus, ModelRecord
from voracious.domain.common import DomainError, TaskMapper, as_matrix

__all__ = ["INTERNAL_ERROR", "GetModel", "RunTrainingJob", "TrainModel"]

INTERNAL_ERROR = "INTERNAL_ERROR"
"""Código de un fallo inesperado (no ``DomainError``); el detalle va al log, no al registro."""


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
        self, tenant_id: str, chart_id: str, training_data: npt.ArrayLike, params: object
    ) -> str:
        """Registra el modelo y encola la Fase I.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            training_data: Histórico ``n x p``.
            params: Parámetros de la carta (ya validados por su schema).

        Returns:
            El ``model_id``.

        Raises:
            UnknownChartError: Si la carta no existe.
            InvalidInputError: Si ``training_data`` no es una matriz numérica ``n x p``.
        """
        resolve_chart(self.charts, chart_id)
        record = ModelRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            model_id=self.ids.new_id(),
            status=JobStatus.QUEUED,
            params=params,
            training_data=as_matrix(training_data, name="training_data"),
            created_at=self.clock.now(),
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
        return _get_model(self.models, tenant_id, chart_id, model_id)


def _get_model(
    models: ModelRepository, tenant_id: str, chart_id: str, model_id: str
) -> ModelRecord:
    """Busca un modelo o lanza ``ModelNotFoundError``.

    Args:
        models: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo.

    Returns:
        El registro.

    Raises:
        ModelNotFoundError: Si no existe para esa clave.
    """
    record = models.get(tenant_id, chart_id, model_id)
    if record is None:
        raise ModelNotFoundError(
            f"el modelo '{model_id}' no existe", details={"model_id": model_id}
        )
    return record


@dataclass(frozen=True)
class RunTrainingJob:
    """Ejecuta la Fase I de un modelo encolado: ``running`` → ``succeeded | failed``.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        mapper: Reparto de tareas para la carta (réplicas bootstrap).
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    mapper: TaskMapper
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo. Es idempotente: si el modelo ya no está ``queued``, no hace nada.

        Un ``DomainError`` deja el modelo ``failed`` con su código y sus detalles. Cualquier otra
        excepción lo deja ``failed / INTERNAL_ERROR`` (sin traza en ``details``) y se relanza.

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
        record = _get_model(self.models, job.tenant_id, job.chart_id, job.model_id)
        if record.status is not JobStatus.QUEUED:
            return
        record = replace(record, status=JobStatus.RUNNING, started_at=self.clock.now())
        self.models.update(record)
        try:
            model = chart.fit_phase1(record.training_data, record.params, mapper=self.mapper)
        except DomainError as exc:
            error = ErrorInfo(code=exc.code, message=exc.message, details=exc.details)
            self.models.update(_finish(record, self.clock, error=error))
            return
        except Exception:
            error = ErrorInfo(code=INTERNAL_ERROR, message="error interno en la Fase I")
            self.models.update(_finish(record, self.clock, error=error))
            raise
        self.models.update(_finish(record, self.clock, model=model))


def _finish(
    record: ModelRecord, clock: Clock, *, model: object = None, error: ErrorInfo | None = None
) -> ModelRecord:
    """Cierra un modelo en ``succeeded`` (con ``model``) o ``failed`` (con ``error``).

    Args:
        record: Registro en ``running``.
        clock: Reloj.
        model: Modelo de la carta, si terminó bien.
        error: Error, si falló.

    Returns:
        El registro terminado.
    """
    status = JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED
    return replace(record, status=status, finished_at=clock.now(), model=model, error=error)
