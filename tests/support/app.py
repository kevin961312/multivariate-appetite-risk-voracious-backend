"""Casos de uso del ciclo de vida cableados con dobles en memoria (solo para tests)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy.typing as npt

from support.memory import (
    InMemoryModelRepository,
    InMemoryModelVersionRepository,
    InMemoryMonitoringRepository,
    InMemoryObservationRepository,
    InMemoryRecalibrationRepository,
    InMemorySignalAnnotationRepository,
    InMemoryStructuralEventRepository,
    RecordingJobQueue,
    SequentialIds,
    TickingClock,
)
from support.solo_test import fast_params, small_data, solo_test_chart
from voracious.application.charts import AnyChart
from voracious.application.ports import Clock, JobKind
from voracious.application.records import MonitoringRecord
from voracious.application.use_cases import (
    AnnotateSignal,
    ApproveVersion,
    GetChartStatus,
    GetModel,
    GetMonitoring,
    GetRecalibration,
    GetVersion,
    ListObservations,
    ListVersions,
    MonitorObservations,
    RegisterStructuralEvent,
    RejectVersion,
    RequestRecalibration,
    RunMonitoringJob,
    RunRecalibrationJob,
    RunTrainingJob,
    TrainModel,
)
from voracious.domain.common import SerialTaskMapper


@dataclass
class App:
    """Todos los casos de uso con repositorios en memoria."""

    charts: dict[str, AnyChart]
    clock: Clock = field(default_factory=TickingClock)
    models: InMemoryModelRepository = field(default_factory=InMemoryModelRepository)
    versions: InMemoryModelVersionRepository = field(default_factory=InMemoryModelVersionRepository)
    monitorings: InMemoryMonitoringRepository = field(default_factory=InMemoryMonitoringRepository)
    observations: InMemoryObservationRepository = field(
        default_factory=InMemoryObservationRepository
    )
    annotations: InMemorySignalAnnotationRepository = field(
        default_factory=InMemorySignalAnnotationRepository
    )
    events: InMemoryStructuralEventRepository = field(
        default_factory=InMemoryStructuralEventRepository
    )
    recalibrations: InMemoryRecalibrationRepository = field(
        default_factory=InMemoryRecalibrationRepository
    )
    queue: RecordingJobQueue = field(default_factory=RecordingJobQueue)
    ids: SequentialIds = field(default_factory=SequentialIds)

    def train(self) -> TrainModel:
        return TrainModel(self.charts, self.models, self.queue, self.ids, self.clock)

    def get_model(self) -> GetModel:
        return GetModel(self.charts, self.models)

    def run_training(self) -> RunTrainingJob:
        return RunTrainingJob(
            self.charts, self.models, self.versions, SerialTaskMapper(), self.clock
        )

    def monitor(self) -> MonitorObservations:
        return MonitorObservations(
            self.charts,
            self.models,
            self.versions,
            self.monitorings,
            self.queue,
            self.ids,
            self.clock,
        )

    def get_monitoring(self) -> GetMonitoring:
        return GetMonitoring(self.charts, self.monitorings)

    def run_monitoring(self) -> RunMonitoringJob:
        return RunMonitoringJob(
            self.charts,
            self.models,
            self.versions,
            self.monitorings,
            self.observations,
            self.ids,
            self.clock,
        )

    def list_observations(self) -> ListObservations:
        return ListObservations(self.charts, self.models, self.observations, self.annotations)

    def annotate(self) -> AnnotateSignal:
        return AnnotateSignal(
            self.charts, self.observations, self.annotations, self.ids, self.clock
        )

    def register_event(self) -> RegisterStructuralEvent:
        return RegisterStructuralEvent(
            self.charts, self.models, self.versions, self.events, self.ids, self.clock
        )

    def request_recalibration(self) -> RequestRecalibration:
        return RequestRecalibration(
            self.charts,
            self.models,
            self.versions,
            self.observations,
            self.events,
            self.recalibrations,
            self.queue,
            self.ids,
            self.clock,
        )

    def run_recalibration(self) -> RunRecalibrationJob:
        return RunRecalibrationJob(
            self.charts,
            self.models,
            self.versions,
            self.observations,
            self.annotations,
            self.events,
            self.recalibrations,
            SerialTaskMapper(),
            self.clock,
        )

    def get_recalibration(self) -> GetRecalibration:
        return GetRecalibration(self.charts, self.recalibrations)

    def approve(self) -> ApproveVersion:
        return ApproveVersion(
            self.charts, self.models, self.versions, self.observations, self.clock
        )

    def reject(self) -> RejectVersion:
        return RejectVersion(self.charts, self.versions, self.clock)

    def list_versions(self) -> ListVersions:
        return ListVersions(self.charts, self.models, self.versions)

    def get_version(self) -> GetVersion:
        return GetVersion(self.charts, self.versions)

    def status(self) -> GetChartStatus:
        return GetChartStatus(
            self.charts, self.models, self.versions, self.observations, self.events, self.clock
        )

    def run_all(self) -> None:
        while self.queue.jobs:
            job = self.queue.jobs.pop(0)
            if job.kind is JobKind.TRAIN:
                self.run_training().execute(job)
            elif job.kind is JobKind.MONITOR:
                self.run_monitoring().execute(job)
            else:
                self.run_recalibration().execute(job)


TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"
CHART = "t2mrcd"
T0 = datetime(2026, 3, 1, tzinfo=UTC)
"""Primera fecha de observación de los escenarios (anterior al reloj de ``TickingClock``)."""


def hours(m: int, start: datetime = T0) -> list[datetime]:
    """``m`` fechas consecutivas, una por hora desde ``start``."""
    return [start + timedelta(hours=i) for i in range(m)]


def lifecycle_app() -> App:
    """App con la carta T²MRCD y el registro de estrategias SOLO TEST."""
    return App(charts={CHART: solo_test_chart()})


def trained_model(app: App, n: int = 40, seed: int = 3) -> str:
    """Entrena un modelo pequeño (B reducido) y devuelve su ``model_id``."""
    model_id = app.train().execute(TENANT, CHART, small_data(n, 4, seed=seed), fast_params())
    app.run_all()
    return model_id


def score(
    app: App,
    model_id: str,
    x: npt.ArrayLike,
    dates: list[datetime],
    batch_label: str | None = None,
) -> MonitoringRecord:
    """Monitorea un lote, ejecuta el trabajo y devuelve el monitoreo terminado."""
    monitoring_id = app.monitor().execute(TENANT, CHART, model_id, x, dates, batch_label)
    app.run_all()
    return app.get_monitoring().execute(TENANT, CHART, model_id, monitoring_id)
