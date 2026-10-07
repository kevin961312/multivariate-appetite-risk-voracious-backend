"""Fase II: ``MonitorObservations`` (valida y encola), ``GetMonitoring`` y ``RunMonitoringJob``."""

from dataclasses import dataclass, replace

import numpy.typing as npt

from voracious.application.charts import ChartRegistry, resolve_chart
from voracious.application.errors import (
    ModelNotFoundError,
    ModelNotReadyError,
    MonitoringNotFoundError,
)
from voracious.application.ports import (
    Clock,
    IdGenerator,
    JobKind,
    JobQueue,
    JobRequest,
    ModelRepository,
    MonitoringRepository,
)
from voracious.application.records import ErrorInfo, JobStatus, ModelRecord, MonitoringRecord
from voracious.application.use_cases.training import INTERNAL_ERROR
from voracious.domain.common import DomainError, as_matrix

__all__ = ["GetMonitoring", "MonitorObservations", "RunMonitoringJob"]


def _ready_model(
    models: ModelRepository, tenant_id: str, chart_id: str, model_id: str
) -> ModelRecord:
    """Devuelve un modelo ``succeeded`` del tenant y la carta.

    Args:
        models: Repositorio de modelos.
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo.

    Returns:
        El registro del modelo.

    Raises:
        ModelNotFoundError: Si no existe para ese tenant y esa carta.
        ModelNotReadyError: Si existe pero no está en ``succeeded``.
    """
    record = models.get(tenant_id, chart_id, model_id)
    if record is None:
        raise ModelNotFoundError(
            f"el modelo '{model_id}' no existe", details={"model_id": model_id}
        )
    if record.status is not JobStatus.SUCCEEDED:
        raise ModelNotReadyError(
            f"el modelo '{model_id}' no está listo",
            details={"model_id": model_id, "status": str(record.status)},
        )
    return record


@dataclass(frozen=True)
class MonitorObservations:
    """Valida las observaciones contra el modelo, crea el monitoreo ``queued`` y lo encola.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        monitorings: Repositorio de monitoreos.
        queue: Cola de trabajos.
        ids: Generador de identificadores.
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    monitorings: MonitoringRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock

    def execute(
        self, tenant_id: str, chart_id: str, model_id: str, observations: npt.ArrayLike
    ) -> str:
        """Encola la Fase II tras validar la entrada de forma síncrona.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo de Fase I.
            observations: Observaciones nuevas ``m x p``.

        Returns:
            El ``monitoring_id``.

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si el modelo no existe para ese tenant y esa carta.
            ModelNotReadyError: Si el modelo no está en ``succeeded``.
            InvalidInputError: Si las observaciones no son compatibles con el modelo.
        """
        chart = resolve_chart(self.charts, chart_id)
        model = _ready_model(self.models, tenant_id, chart_id, model_id)
        x_new = as_matrix(observations, name="x_new")
        chart.validate_phase2_input(model.model, x_new)
        record = MonitoringRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            model_id=model_id,
            monitoring_id=self.ids.new_id(),
            status=JobStatus.QUEUED,
            observations=x_new,
            created_at=self.clock.now(),
        )
        self.monitorings.add(record)
        self.queue.enqueue(
            JobRequest(
                kind=JobKind.MONITOR,
                tenant_id=tenant_id,
                chart_id=chart_id,
                model_id=model_id,
                monitoring_id=record.monitoring_id,
            )
        )
        return record.monitoring_id


@dataclass(frozen=True)
class GetMonitoring:
    """Consulta un monitoreo del tenant.

    Attributes:
        charts: Cartas registradas.
        monitorings: Repositorio de monitoreos.
    """

    charts: ChartRegistry
    monitorings: MonitoringRepository

    def execute(
        self, tenant_id: str, chart_id: str, model_id: str, monitoring_id: str
    ) -> MonitoringRecord:
        """Devuelve el monitoreo.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            monitoring_id: Monitoreo.

        Returns:
            El registro del monitoreo.

        Raises:
            UnknownChartError: Si la carta no existe.
            MonitoringNotFoundError: Si no existe para esa clave.
        """
        resolve_chart(self.charts, chart_id)
        return _get_monitoring(self.monitorings, tenant_id, chart_id, model_id, monitoring_id)


def _get_monitoring(
    monitorings: MonitoringRepository,
    tenant_id: str,
    chart_id: str,
    model_id: str,
    monitoring_id: str,
) -> MonitoringRecord:
    """Busca un monitoreo o lanza ``MonitoringNotFoundError``.

    Args:
        monitorings: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo.
        monitoring_id: Monitoreo.

    Returns:
        El registro.

    Raises:
        MonitoringNotFoundError: Si no existe para esa clave.
    """
    record = monitorings.get(tenant_id, chart_id, model_id, monitoring_id)
    if record is None:
        raise MonitoringNotFoundError(
            f"el monitoreo '{monitoring_id}' no existe",
            details={"model_id": model_id, "monitoring_id": monitoring_id},
        )
    return record


@dataclass(frozen=True)
class RunMonitoringJob:
    """Ejecuta la Fase II de un monitoreo encolado: ``running`` → ``succeeded | failed``.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        monitorings: Repositorio de monitoreos.
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    monitorings: MonitoringRepository
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo. Es idempotente: si el monitoreo ya no está ``queued``, no hace nada.

        Un ``DomainError`` o un modelo que ya no está disponible dejan el monitoreo ``failed``
        con su código. Cualquier otra excepción lo deja ``failed / INTERNAL_ERROR`` y se relanza.

        Args:
            job: Petición ``monitor``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``monitor``.
            UnknownChartError: Si la carta no existe.
            MonitoringNotFoundError: Si el monitoreo no existe.
        """
        if job.kind is not JobKind.MONITOR or job.monitoring_id is None:
            msg = f"RunMonitoringJob solo ejecuta trabajos 'monitor', no '{job.kind}'"
            raise ValueError(msg)
        chart = resolve_chart(self.charts, job.chart_id)
        record = _get_monitoring(
            self.monitorings, job.tenant_id, job.chart_id, job.model_id, job.monitoring_id
        )
        if record.status is not JobStatus.QUEUED:
            return
        record = replace(record, status=JobStatus.RUNNING, started_at=self.clock.now())
        self.monitorings.update(record)
        try:
            model = _ready_model(self.models, job.tenant_id, job.chart_id, job.model_id)
            result = chart.score_phase2(model.model, record.observations)
        except (DomainError, ModelNotFoundError, ModelNotReadyError) as exc:
            error = ErrorInfo(code=exc.code, message=exc.message, details=exc.details)
            self.monitorings.update(self._finish(record, error=error))
            return
        except Exception:
            error = ErrorInfo(code=INTERNAL_ERROR, message="error interno en la Fase II")
            self.monitorings.update(self._finish(record, error=error))
            raise
        self.monitorings.update(self._finish(record, result=result))

    def _finish(
        self,
        record: MonitoringRecord,
        *,
        result: object = None,
        error: ErrorInfo | None = None,
    ) -> MonitoringRecord:
        """Cierra un monitoreo en ``succeeded`` (con ``result``) o ``failed`` (con ``error``).

        Args:
            record: Registro en ``running``.
            result: Resultado de la carta, si terminó bien.
            error: Error, si falló.

        Returns:
            El registro terminado.
        """
        status = JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED
        return replace(
            record, status=status, finished_at=self.clock.now(), result=result, error=error
        )
