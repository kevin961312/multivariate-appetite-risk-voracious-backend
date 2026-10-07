from dataclasses import dataclass, field, replace

import numpy as np
import pytest

from support.memory import (
    InMemoryModelRepository,
    InMemoryMonitoringRepository,
    RecordingJobQueue,
    SequentialIds,
    TickingClock,
)
from support.solo_test import fast_params, small_data
from voracious.application.charts import AnyChart
from voracious.application.errors import (
    ModelNotFoundError,
    ModelNotReadyError,
    MonitoringNotFoundError,
    UnknownChartError,
)
from voracious.application.ports import JobKind, JobRequest
from voracious.application.records import JobStatus
from voracious.application.use_cases import (
    INTERNAL_ERROR,
    GetModel,
    GetMonitoring,
    MonitorObservations,
    RunMonitoringJob,
    RunTrainingJob,
    TrainModel,
)
from voracious.domain.charts.t2mrcd import (
    T2MRCD_DECISION_PENDING,
    T2MRCDBootstrap,
    T2MRCDChart,
    T2MRCDModel,
    T2MRCDMonitoring,
    T2MRCDParams,
)
from voracious.domain.common import InvalidInputError, SerialTaskMapper

TENANT = "tenant-a"
OTHER = "tenant-b"


@dataclass
class App:
    """Casos de uso cableados con dobles en memoria."""

    charts: dict[str, AnyChart]
    models: InMemoryModelRepository = field(default_factory=InMemoryModelRepository)
    monitorings: InMemoryMonitoringRepository = field(default_factory=InMemoryMonitoringRepository)
    queue: RecordingJobQueue = field(default_factory=RecordingJobQueue)
    ids: SequentialIds = field(default_factory=SequentialIds)
    clock: TickingClock = field(default_factory=TickingClock)

    def train(self) -> TrainModel:
        return TrainModel(self.charts, self.models, self.queue, self.ids, self.clock)

    def get_model(self) -> GetModel:
        return GetModel(self.charts, self.models)

    def run_training(self) -> RunTrainingJob:
        return RunTrainingJob(self.charts, self.models, SerialTaskMapper(), self.clock)

    def monitor(self) -> MonitorObservations:
        return MonitorObservations(
            self.charts, self.models, self.monitorings, self.queue, self.ids, self.clock
        )

    def get_monitoring(self) -> GetMonitoring:
        return GetMonitoring(self.charts, self.monitorings)

    def run_monitoring(self) -> RunMonitoringJob:
        return RunMonitoringJob(self.charts, self.models, self.monitorings, self.clock)

    def run_all(self) -> None:
        while self.queue.jobs:
            job = self.queue.jobs.pop(0)
            if job.kind is JobKind.TRAIN:
                self.run_training().execute(job)
            else:
                self.run_monitoring().execute(job)


def _t2mrcd_app() -> App:
    return App(charts={"t2mrcd": T2MRCDChart()})


def _trained(app: App) -> str:
    model_id = app.train().execute(TENANT, "t2mrcd", small_data().tolist(), fast_params())
    app.run_all()
    return model_id


class _BoomChart:
    """Carta de prueba que falla con una excepción inesperada."""

    @property
    def chart_id(self) -> str:
        return "boom"

    def fit_phase1(self, x: object, params: object, *, mapper: object) -> object:
        raise RuntimeError("fallo inesperado con traza")

    def validate_phase2_input(self, model: object, x_new: object) -> None:
        return None

    def score_phase2(self, model: object, x_new: object) -> object:
        raise RuntimeError("fallo inesperado en fase II")


def test_full_phase1_and_phase2_with_real_t2mrcd() -> None:
    app = _t2mrcd_app()
    model_id = _trained(app)
    record = app.get_model().execute(TENANT, "t2mrcd", model_id)
    assert record.status is JobStatus.SUCCEEDED
    assert isinstance(record.model, T2MRCDModel)
    assert record.error is None
    assert record.started_at is not None
    assert record.finished_at is not None
    assert record.created_at < record.started_at < record.finished_at
    assert [r.status for r in app.models.history] == [
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.SUCCEEDED,
    ]

    x_new = small_data(6, 4, seed=50)
    x_new[2] += 10.0
    monitoring_id = app.monitor().execute(TENANT, "t2mrcd", model_id, x_new.tolist())
    queued = app.get_monitoring().execute(TENANT, "t2mrcd", model_id, monitoring_id)
    assert queued.status is JobStatus.QUEUED
    app.run_all()
    done = app.get_monitoring().execute(TENANT, "t2mrcd", model_id, monitoring_id)
    assert done.status is JobStatus.SUCCEEDED
    assert isinstance(done.result, T2MRCDMonitoring)
    assert done.result.signal[2]
    assert done.result.limit == record.model.limits.limit
    assert [r.status for r in app.monitorings.history] == [
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.SUCCEEDED,
    ]


def test_decision_pending_leaves_model_failed_with_details() -> None:
    app = App(charts={"t2mrcd": T2MRCDChart()})
    params = T2MRCDParams(bootstrap=T2MRCDBootstrap(seed=1, aggregation=None))
    model_id = app.train().execute(TENANT, "t2mrcd", small_data(), params)
    app.run_all()
    record = app.get_model().execute(TENANT, "t2mrcd", model_id)
    assert record.status is JobStatus.FAILED
    assert record.model is None
    assert record.error is not None
    assert record.error.code == T2MRCD_DECISION_PENDING
    assert record.error.details["pending"] == ["bootstrap.aggregation"]
    assert record.finished_at is not None


def test_tenant_isolation() -> None:
    app = _t2mrcd_app()
    model_id = _trained(app)
    with pytest.raises(ModelNotFoundError):
        app.get_model().execute(OTHER, "t2mrcd", model_id)
    with pytest.raises(ModelNotFoundError):
        app.monitor().execute(OTHER, "t2mrcd", model_id, small_data(2, 4).tolist())
    monitoring_id = app.monitor().execute(TENANT, "t2mrcd", model_id, small_data(2, 4))
    with pytest.raises(MonitoringNotFoundError):
        app.get_monitoring().execute(OTHER, "t2mrcd", model_id, monitoring_id)
    with pytest.raises(MonitoringNotFoundError):
        app.get_monitoring().execute(TENANT, "t2mrcd", "otro-modelo", monitoring_id)


def test_unknown_chart_is_chart_not_found() -> None:
    app = _t2mrcd_app()
    with pytest.raises(UnknownChartError) as info:
        app.train().execute(TENANT, "ewma", small_data(), fast_params())
    assert info.value.code == "CHART_NOT_FOUND"
    assert info.value.details == {"chart_id": "ewma"}
    with pytest.raises(UnknownChartError):
        app.get_model().execute(TENANT, "ewma", "id-1")
    with pytest.raises(UnknownChartError):
        app.get_monitoring().execute(TENANT, "ewma", "id-1", "id-2")
    assert app.queue.jobs == []


def test_model_of_other_chart_is_not_found() -> None:
    app = App(charts={"t2mrcd": T2MRCDChart(), "boom": _BoomChart()})
    model_id = _trained(app)
    with pytest.raises(ModelNotFoundError):
        app.get_model().execute(TENANT, "boom", model_id)


def test_monitoring_requires_succeeded_model() -> None:
    app = _t2mrcd_app()
    model_id = app.train().execute(TENANT, "t2mrcd", small_data(), fast_params())
    with pytest.raises(ModelNotReadyError) as info:
        app.monitor().execute(TENANT, "t2mrcd", model_id, small_data(2, 4))
    assert info.value.code == "MODEL_NOT_READY"
    assert info.value.details == {"model_id": model_id, "status": "queued"}


def test_failed_model_is_not_ready() -> None:
    app = App(charts={"t2mrcd": T2MRCDChart()})
    params = T2MRCDParams(bootstrap=T2MRCDBootstrap(seed=1, aggregation=None))
    model_id = app.train().execute(TENANT, "t2mrcd", small_data(), params)
    app.run_all()
    with pytest.raises(ModelNotReadyError):
        app.monitor().execute(TENANT, "t2mrcd", model_id, small_data(2, 4))


def test_phase2_input_is_validated_before_enqueue() -> None:
    app = _t2mrcd_app()
    model_id = _trained(app)
    with pytest.raises(InvalidInputError) as info:
        app.monitor().execute(TENANT, "t2mrcd", model_id, np.zeros((3, 5)))
    assert info.value.details["expected_features"] == 4
    with pytest.raises(InvalidInputError):
        app.monitor().execute(TENANT, "t2mrcd", model_id, [1.0, 2.0, 3.0, 4.0])
    assert app.queue.jobs == []
    assert app.monitorings.records == {}


def test_training_input_must_be_a_matrix() -> None:
    app = _t2mrcd_app()
    with pytest.raises(InvalidInputError):
        app.train().execute(TENANT, "t2mrcd", [1.0, 2.0], fast_params())
    assert app.models.records == {}


def test_unexpected_error_is_internal_error_and_reraised() -> None:
    app = App(charts={"boom": _BoomChart()})
    model_id = app.train().execute(TENANT, "boom", small_data(), object())
    job = app.queue.jobs.pop()
    with pytest.raises(RuntimeError, match="fallo inesperado"):
        app.run_training().execute(job)
    record = app.get_model().execute(TENANT, "boom", model_id)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == INTERNAL_ERROR
    assert record.error.details == {}
    assert "traza" not in record.error.message


def test_unexpected_phase2_error_is_internal_error_and_reraised() -> None:
    app = App(charts={"boom": _BoomChart()})
    model_id = app.train().execute(TENANT, "boom", small_data(), object())
    key = (TENANT, "boom", model_id)
    app.models.records[key] = _succeeded(app, key)
    monitoring_id = app.monitor().execute(TENANT, "boom", model_id, small_data(2, 4))
    job = app.queue.jobs.pop()
    with pytest.raises(RuntimeError):
        app.run_monitoring().execute(job)
    record = app.get_monitoring().execute(TENANT, "boom", model_id, monitoring_id)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == INTERNAL_ERROR


def _succeeded(app: App, key: tuple[str, str, str]) -> object:
    return replace(app.models.records[key], status=JobStatus.SUCCEEDED, model=object())


def test_jobs_are_idempotent() -> None:
    app = _t2mrcd_app()
    model_id = app.train().execute(TENANT, "t2mrcd", small_data(), fast_params())
    job = app.queue.jobs[0]
    app.run_all()
    before = len(app.models.history)
    app.run_training().execute(job)
    assert len(app.models.history) == before
    monitoring_id = app.monitor().execute(TENANT, "t2mrcd", model_id, small_data(2, 4))
    mjob = app.queue.jobs[0]
    app.run_all()
    before = len(app.monitorings.history)
    app.run_monitoring().execute(mjob)
    assert len(app.monitorings.history) == before
    assert app.get_monitoring().execute(TENANT, "t2mrcd", model_id, monitoring_id).status is (
        JobStatus.SUCCEEDED
    )


def test_monitoring_fails_if_model_disappears() -> None:
    app = _t2mrcd_app()
    model_id = _trained(app)
    monitoring_id = app.monitor().execute(TENANT, "t2mrcd", model_id, small_data(2, 4))
    del app.models.records[(TENANT, "t2mrcd", model_id)]
    app.run_all()
    record = app.get_monitoring().execute(TENANT, "t2mrcd", model_id, monitoring_id)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == "MODEL_NOT_FOUND"


def test_job_kind_mismatch_and_missing_resources() -> None:
    app = _t2mrcd_app()
    train_job = JobRequest(JobKind.TRAIN, TENANT, "t2mrcd", "nope")
    monitor_job = JobRequest(JobKind.MONITOR, TENANT, "t2mrcd", "nope", "m")
    assert train_job.resource_id == "nope"
    assert monitor_job.resource_id == "m"
    with pytest.raises(ValueError, match="train"):
        app.run_training().execute(monitor_job)
    with pytest.raises(ValueError, match="monitor"):
        app.run_monitoring().execute(train_job)
    with pytest.raises(ModelNotFoundError):
        app.run_training().execute(train_job)
    with pytest.raises(MonitoringNotFoundError):
        app.run_monitoring().execute(monitor_job)


@pytest.mark.parametrize(("kind", "monitoring_id"), [(JobKind.MONITOR, None), (JobKind.TRAIN, "m")])
def test_job_request_consistency(kind: JobKind, monitoring_id: str | None) -> None:
    with pytest.raises(ValueError, match="monitoring_id"):
        JobRequest(kind, TENANT, "t2mrcd", "id", monitoring_id)
