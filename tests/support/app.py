"""Casos de uso del ciclo de vida cableados con dobles en memoria (solo para tests)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy.typing as npt

from support.memory import (
    InMemoryComparisonRepository,
    InMemoryDatasetStorage,
    InMemoryDepurationRepository,
    InMemoryFitRepository,
    InMemoryLimitsRepository,
    InMemoryModelRepository,
    InMemoryModelVersionRepository,
    InMemoryMonitoringRepository,
    InMemoryObservationRepository,
    InMemoryPipelineRepository,
    InMemoryRecalibrationRepository,
    InMemorySignalAnnotationRepository,
    InMemoryStructuralEventRepository,
    RecordingJobQueue,
    SequentialIds,
    TickingClock,
)
from support.solo_test import fast_params, small_data, solo_test_chart
from voracious.application.charts import AnyChart
from voracious.application.phase1_steps import Phase1Steps
from voracious.application.ports import Clock, JobKind, JobRequest
from voracious.application.recalibration_steps import RecalibrationSteps
from voracious.application.records import (
    AssignableCause,
    JobStatus,
    LifecyclePolicy,
    MonitoringRecord,
    PipelineRecord,
)
from voracious.application.use_cases import (
    AnnotateSignal,
    ApproveVersion,
    GetChartStatus,
    GetComparison,
    GetDataset,
    GetDepuration,
    GetFit,
    GetLimits,
    GetModel,
    GetMonitoring,
    GetPipeline,
    GetRecalibration,
    GetVersion,
    ListObservations,
    ListVersions,
    MonitorObservations,
    RecalibrationChain,
    RegisterStructuralEvent,
    RejectVersion,
    RequestComparison,
    RequestDepuration,
    RequestFit,
    RequestLimits,
    RequestModel,
    RequestPhase1Pipeline,
    RequestRecalibration,
    RequestVersionProposal,
    RunComparisonJob,
    RunDepurationJob,
    RunFitJob,
    RunLimitsJob,
    RunModelAssemblyJob,
    RunMonitoringJob,
    RunPhase1Pipeline,
    RunPipelineJob,
    RunRecalibrationJob,
    RunVersionProposalJob,
    UploadDataset,
)
from voracious.domain.charts.t2mrcd import T2MRCDChart
from voracious.domain.common import SerialTaskMapper
from voracious.infrastructure.charts import T2MRCDPhase1Steps, T2MRCDRecalibrationSteps


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
    datasets: InMemoryDatasetStorage = field(default_factory=InMemoryDatasetStorage)
    fits: InMemoryFitRepository = field(default_factory=InMemoryFitRepository)
    limits: InMemoryLimitsRepository = field(default_factory=InMemoryLimitsRepository)
    depurations: InMemoryDepurationRepository = field(default_factory=InMemoryDepurationRepository)
    pipelines: InMemoryPipelineRepository = field(default_factory=InMemoryPipelineRepository)
    comparisons: InMemoryComparisonRepository = field(default_factory=InMemoryComparisonRepository)

    @property
    def steps(self) -> dict[str, Phase1Steps]:
        """Pasos de Fase I de las cartas T²MRCD del registro (como ``build_container``)."""
        return {
            cid: T2MRCDPhase1Steps(chart)
            for cid, chart in self.charts.items()
            if isinstance(chart, T2MRCDChart)
        }

    @property
    def rsteps(self) -> dict[str, RecalibrationSteps]:
        """Pasos de la recalibración de las cartas T²MRCD del registro."""
        return {
            cid: T2MRCDRecalibrationSteps(chart)
            for cid, chart in self.charts.items()
            if isinstance(chart, T2MRCDChart)
        }

    @property
    def chain(self) -> RecalibrationChain:
        """Enlaces de los pasos con la recalibración (como ``build_container``)."""
        return RecalibrationChain(
            self.rsteps,
            self.recalibrations,
            self.versions,
            self.annotations,
            self.depurations,
            self.clock,
        )

    # --- pasos de Fase I ---------------------------------------------------------

    def upload(self) -> UploadDataset:
        return UploadDataset(self.datasets, self.ids, self.clock)

    def get_dataset(self) -> GetDataset:
        return GetDataset(self.datasets)

    def request_fit(self) -> RequestFit:
        return RequestFit(self.steps, self.datasets, self.fits, self.queue, self.ids, self.clock)

    def get_fit(self) -> GetFit:
        return GetFit(self.steps, self.fits)

    def run_fit(self) -> RunFitJob:
        return RunFitJob(self.steps, self.datasets, self.fits, self.queue, self.clock)

    def request_limits(self) -> RequestLimits:
        return RequestLimits(
            self.steps,
            self.datasets,
            self.fits,
            self.limits,
            self.depurations,
            self.queue,
            self.ids,
            self.clock,
            self.chain,
        )

    def get_limits(self) -> GetLimits:
        return GetLimits(self.steps, self.limits)

    def run_limits(self) -> RunLimitsJob:
        return RunLimitsJob(
            self.steps,
            self.datasets,
            self.fits,
            self.limits,
            SerialTaskMapper(),
            self.queue,
            self.clock,
        )

    def request_depuration(self) -> RequestDepuration:
        return RequestDepuration(
            self.steps,
            self.datasets,
            self.fits,
            self.limits,
            self.depurations,
            self.queue,
            self.ids,
            self.clock,
            self.chain,
        )

    def get_depuration(self) -> GetDepuration:
        return GetDepuration(self.steps, self.depurations)

    def run_depuration(self) -> RunDepurationJob:
        return RunDepurationJob(
            self.steps,
            self.datasets,
            self.fits,
            self.limits,
            self.depurations,
            self.queue,
            self.ids,
            self.clock,
            self.chain,
        )

    def request_model(self) -> RequestModel:
        return RequestModel(
            self.steps,
            self.datasets,
            self.fits,
            self.limits,
            self.depurations,
            self.models,
            self.queue,
            self.ids,
            self.clock,
        )

    def run_assembly(self) -> RunModelAssemblyJob:
        return RunModelAssemblyJob(
            self.steps,
            self.datasets,
            self.fits,
            self.limits,
            self.depurations,
            self.models,
            self.versions,
            self.queue,
            self.clock,
        )

    def request_pipeline(self) -> RequestPhase1Pipeline:
        return RequestPhase1Pipeline(
            self.steps, self.datasets, self.pipelines, self.queue, self.ids, self.clock
        )

    def get_pipeline(self) -> GetPipeline:
        return GetPipeline(self.steps, self.pipelines)

    def run_pipeline(self) -> RunPipelineJob:
        return RunPipelineJob(self.pipelines, self.run_phase1(), self.run_recalibration())

    def run_phase1(self) -> RunPhase1Pipeline:
        return RunPhase1Pipeline(
            self.steps,
            self.pipelines,
            self.fits,
            self.limits,
            self.depurations,
            self.models,
            self.request_fit(),
            self.request_limits(),
            self.request_depuration(),
            self.request_model(),
            self.ids,
            self.clock,
        )

    def pipeline(
        self,
        tenant: str,
        chart: str,
        data: npt.ArrayLike,
        params: object,
        assignable_cause: tuple[AssignableCause, ...] = (),
        policy: LifecyclePolicy | None = None,
    ) -> PipelineRecord:
        """Sube ``data``, ejecuta la tubería de Fase I hasta el final y la devuelve."""
        dataset = self.upload().execute(tenant, data)
        pipeline_id = self.request_pipeline().execute(
            tenant, chart, dataset.dataset_id, params, assignable_cause, policy
        )
        self.run_all()
        return self.get_pipeline().execute(tenant, chart, pipeline_id)

    def train(
        self,
        tenant: str,
        chart: str,
        data: npt.ArrayLike,
        params: object,
        policy: LifecyclePolicy | None = None,
    ) -> str:
        """Fase I completa por la tubería; devuelve el ``model_id`` (exige que termine bien)."""
        record = self.pipeline(tenant, chart, data, params, policy=policy)
        assert record.status is JobStatus.SUCCEEDED, record.error
        assert record.model_id is not None
        return record.model_id

    def get_model(self) -> GetModel:
        return GetModel(self.charts, self.models)

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
            self.rsteps,
            self.models,
            self.versions,
            self.observations,
            self.events,
            self.recalibrations,
            self.datasets,
            self.pipelines,
            self.queue,
            self.ids,
            self.clock,
        )

    def run_recalibration(self) -> RunRecalibrationJob:
        return RunRecalibrationJob(
            self.charts,
            self.steps,
            self.pipelines,
            self.recalibrations,
            self.fits,
            self.limits,
            self.depurations,
            self.comparisons,
            self.datasets,
            self.chain,
            self.request_fit(),
            self.request_limits(),
            self.request_depuration(),
            self.request_comparison(),
            self.request_version_proposal(),
            self.ids,
            self.clock,
        )

    def request_comparison(self) -> RequestComparison:
        return RequestComparison(
            self.charts,
            self.rsteps,
            self.recalibrations,
            self.datasets,
            self.fits,
            self.depurations,
            self.comparisons,
            self.queue,
            self.ids,
            self.clock,
        )

    def get_comparison(self) -> GetComparison:
        return GetComparison(self.charts, self.comparisons)

    def run_comparison(self) -> RunComparisonJob:
        return RunComparisonJob(
            self.rsteps,
            self.recalibrations,
            self.versions,
            self.datasets,
            self.fits,
            self.comparisons,
            SerialTaskMapper(),
            self.queue,
            self.ids,
            self.clock,
        )

    def request_version_proposal(self) -> RequestVersionProposal:
        return RequestVersionProposal(
            self.steps,
            self.rsteps,
            self.recalibrations,
            self.versions,
            self.datasets,
            self.fits,
            self.limits,
            self.comparisons,
            self.queue,
            self.clock,
        )

    def run_version_proposal(self) -> RunVersionProposalJob:
        return RunVersionProposalJob(
            self.steps,
            self.rsteps,
            self.models,
            self.versions,
            self.events,
            self.recalibrations,
            self.datasets,
            self.fits,
            self.limits,
            self.depurations,
            self.comparisons,
            self.queue,
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

    def run(self, job: JobRequest) -> None:
        """Ejecuta un trabajo con su caso de uso."""
        runners = {
            JobKind.MRCD_FIT: self.run_fit,
            JobKind.LIMITS: self.run_limits,
            JobKind.DEPURATION: self.run_depuration,
            JobKind.MODEL_ASSEMBLY: self.run_assembly,
            JobKind.PIPELINE: self.run_pipeline,
            JobKind.SCORE: self.run_monitoring,
            JobKind.COMPARISON: self.run_comparison,
            JobKind.VERSION_PROPOSAL: self.run_version_proposal,
        }
        runners[job.kind]().execute(job)

    def run_all(self) -> None:
        while self.queue.jobs:
            self.run(self.queue.jobs.pop(0))


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
    return app.train(TENANT, CHART, small_data(n, 4, seed=seed), fast_params())


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


def queued_model(app: App, n: int = 40, seed: int = 3) -> str:
    """Modelo pedido por referencias (ajuste y límites listos) cuyo ensamblado no se ejecuta."""
    dataset = app.upload().execute(TENANT, small_data(n, 4, seed=seed))
    fit_id = app.request_fit().execute(TENANT, CHART, dataset.dataset_id, None)
    app.run_all()
    limits_id = app.request_limits().execute(TENANT, CHART, fit_id, fast_params())
    app.run_all()
    return app.request_model().execute(TENANT, CHART, fit_id=fit_id, limits_id=limits_id)
