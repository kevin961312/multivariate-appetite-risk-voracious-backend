"""Fase II: ``MonitorObservations`` (valida y encola), ``GetMonitoring`` y ``RunMonitoringJob``.

Cada fila lleva su fecha (``observed_at``) y se puntúa con la versión vigente en esa fecha
(ADR 0008, Q6): un lote que abarque dos versiones se puntúa por partes. Cada fila puntuada se
registra como ``ObservationRecord`` (D4).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np
import numpy.typing as npt

from voracious.application.charts import (
    AnyChart,
    ChartRegistry,
    as_phase2_scores,
    resolve_chart,
)
from voracious.application.errors import (
    ApplicationError,
    MonitoringNotFoundError,
    ObservationBeforeFirstVersionError,
)
from voracious.application.lifecycle import utc, version_for
from voracious.application.ports import (
    Clock,
    IdGenerator,
    JobKind,
    JobQueue,
    JobRequest,
    ModelRepository,
    ModelVersionRepository,
    MonitoringRepository,
    ObservationRepository,
)
from voracious.application.records import (
    ErrorInfo,
    JobStatus,
    ModelVersion,
    MonitoringRecord,
    MonitoringSummary,
    ObservationRecord,
)
from voracious.application.use_cases.common import (
    INTERNAL_ERROR,
    ready_model,
    require_active_version,
)
from voracious.domain.common import DomainError, InvalidInputError, as_matrix

__all__ = ["GetMonitoring", "MonitorObservations", "RunMonitoringJob"]


def _versions_by_row(
    observed_at: Sequence[datetime], versions: Sequence[ModelVersion]
) -> list[ModelVersion]:
    """Versión vigente en la fecha de cada fila.

    Args:
        observed_at: Fecha de cada fila (UTC).
        versions: Versiones del modelo.

    Returns:
        La versión de cada fila.

    Raises:
        ObservationBeforeFirstVersionError: Si alguna fecha es anterior a todas las versiones.
    """
    out: list[ModelVersion] = []
    for row, when in enumerate(observed_at):
        version = version_for(when, versions)
        if version is None:
            raise ObservationBeforeFirstVersionError(
                "la observación es anterior a la primera versión vigente",
                details={"row": row, "observed_at": when.isoformat()},
            )
        out.append(version)
    return out


@dataclass(frozen=True)
class MonitorObservations:
    """Valida las observaciones contra el modelo, crea el monitoreo ``queued`` y lo encola.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        versions: Repositorio de versiones.
        monitorings: Repositorio de monitoreos.
        queue: Cola de trabajos.
        ids: Generador de identificadores.
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    versions: ModelVersionRepository
    monitorings: MonitoringRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        observations: npt.ArrayLike,
        observed_at: Sequence[datetime],
        batch_label: str | None = None,
    ) -> str:
        """Encola la Fase II tras validar la entrada de forma síncrona.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo de Fase I.
            observations: Observaciones nuevas ``m x p``.
            observed_at: Fecha de cada fila, con zona horaria (longitud ``m``).
            batch_label: Etiqueta opcional del lote.

        Returns:
            El ``monitoring_id``.

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si el modelo no existe para ese tenant y esa carta.
            ModelNotReadyError: Si el modelo no está en ``succeeded``.
            InvalidInputError: Si las observaciones no son compatibles con el modelo o las fechas
                no son válidas.
            ObservationBeforeFirstVersionError: Si una fecha es anterior a la primera versión.
        """
        chart = resolve_chart(self.charts, chart_id)
        ready_model(self.models, tenant_id, chart_id, model_id)
        x_new = as_matrix(observations, name="x_new")
        dates = tuple(utc(when, "observed_at") for when in observed_at)
        if len(dates) != x_new.shape[0]:
            raise InvalidInputError(
                "'observed_at' debe tener una fecha por fila",
                details={"input": "observed_at", "rows": x_new.shape[0], "dates": len(dates)},
            )
        versions = self.versions.list(tenant_id, chart_id, model_id)
        active = require_active_version(versions, model_id)
        chart.validate_phase2_input(active.model, x_new)
        _versions_by_row(dates, versions)
        record = MonitoringRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            model_id=model_id,
            monitoring_id=self.ids.new_id(),
            status=JobStatus.QUEUED,
            observations=x_new,
            observed_at=dates,
            batch_label=batch_label,
            created_at=self.clock.now(),
        )
        self.monitorings.add(record)
        self.queue.enqueue(
            JobRequest(
                kind=JobKind.SCORE,
                tenant_id=tenant_id,
                scope=chart_id,
                resource_id=record.monitoring_id,
                model_id=model_id,
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
        versions: Repositorio de versiones.
        monitorings: Repositorio de monitoreos.
        observations: Registro de observaciones.
        ids: Generador de identificadores de observación.
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    versions: ModelVersionRepository
    monitorings: MonitoringRepository
    observations: ObservationRepository
    ids: IdGenerator
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo. Es idempotente: si el monitoreo ya no está ``queued``, no hace nada.

        La transición ``queued → running`` es atómica (``MonitoringRepository.claim``).

        Cada fila se puntúa con la versión vigente en su fecha (por partes si el lote abarca
        varias) y se registra. Un ``DomainError`` o un error de aplicación (modelo que ya no está
        disponible, fecha anterior a la primera versión) dejan el monitoreo ``failed`` con su
        código y sin observaciones registradas. Cualquier otra excepción lo deja
        ``failed / INTERNAL_ERROR`` y se relanza.

        Args:
            job: Petición ``score``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``score``.
            UnknownChartError: Si la carta no existe.
            MonitoringNotFoundError: Si el monitoreo no existe.
        """
        if job.kind is not JobKind.SCORE or job.model_id is None:
            msg = f"RunMonitoringJob solo ejecuta trabajos 'score', no '{job.kind}'"
            raise ValueError(msg)
        chart = resolve_chart(self.charts, job.scope)
        model_id = job.model_id
        _get_monitoring(self.monitorings, job.tenant_id, job.scope, model_id, job.resource_id)
        claimed = self.monitorings.claim(
            job.tenant_id, job.scope, model_id, job.resource_id, self.clock.now()
        )
        if claimed is None:
            return
        record = claimed
        try:
            ready_model(self.models, job.tenant_id, job.scope, model_id)
            versions = self.versions.list(job.tenant_id, job.scope, model_id)
            by_row = _versions_by_row(record.observed_at, versions)
            observations = self._score(chart, record, by_row)
            self.observations.add_many(observations)
        except (DomainError, ApplicationError) as exc:
            error = ErrorInfo(code=exc.code, message=exc.message, details=exc.details)
            self.monitorings.update(self._finish(record, error=error))
            return
        except Exception:
            error = ErrorInfo(code=INTERNAL_ERROR, message="error interno en la Fase II")
            self.monitorings.update(self._finish(record, error=error))
            raise
        summary = MonitoringSummary(
            observation_ids=tuple(o.observation_id for o in observations),
            version_numbers=tuple(o.version_number for o in observations),
            n_signals=sum(o.signal for o in observations),
        )
        self.monitorings.update(self._finish(record, result=summary))

    def _score(
        self,
        chart: AnyChart,
        record: MonitoringRecord,
        by_row: Sequence[ModelVersion],
    ) -> list[ObservationRecord]:
        """Puntúa cada grupo de filas con su versión y construye las observaciones.

        Args:
            chart: Carta (``ControlChart``).
            record: Monitoreo en ``running``.
            by_row: Versión de cada fila.

        Returns:
            Las observaciones, en el orden de las filas.

        Raises:
            TypeError: Si el resultado de la carta no cumple ``Phase2Scores`` o no tiene una
                entrada por fila.
        """
        numbers = np.array([v.number for v in by_row], dtype=np.int64)
        rows: dict[int, ObservationRecord] = {}
        recorded_at = self.clock.now()
        for version in {v.number: v for v in by_row}.values():
            idx = np.flatnonzero(numbers == version.number)
            scores = as_phase2_scores(chart.score_phase2(version.model, record.observations[idx]))
            t2 = np.asarray(scores.t2, dtype=np.float64)
            signal = np.asarray(scores.signal, dtype=np.bool_)
            if t2.shape != (idx.size,) or signal.shape != (idx.size,):
                msg = "el resultado de Fase II no tiene una entrada por fila"
                raise TypeError(msg)
            for k, row in enumerate(idx.tolist()):
                rows[row] = ObservationRecord(
                    tenant_id=record.tenant_id,
                    chart_id=record.chart_id,
                    model_id=record.model_id,
                    observation_id=self.ids.new_id(),
                    monitoring_id=record.monitoring_id,
                    batch_label=record.batch_label,
                    observed_at=record.observed_at[row],
                    values=record.observations[row].copy(),
                    t2=float(t2[k]),
                    limit=float(scores.limit),
                    limit_kind=str(scores.limit_kind),
                    version_number=version.number,
                    signal=bool(signal[k]),
                    recorded_at=recorded_at,
                )
        return [rows[i] for i in range(len(by_row))]

    def _finish(
        self,
        record: MonitoringRecord,
        *,
        result: MonitoringSummary | None = None,
        error: ErrorInfo | None = None,
    ) -> MonitoringRecord:
        """Cierra un monitoreo en ``succeeded`` (con ``result``) o ``failed`` (con ``error``).

        Args:
            record: Registro en ``running``.
            result: Observaciones registradas, si terminó bien.
            error: Error, si falló.

        Returns:
            El registro terminado.
        """
        status = JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED
        return replace(
            record, status=status, finished_at=self.clock.now(), result=result, error=error
        )
