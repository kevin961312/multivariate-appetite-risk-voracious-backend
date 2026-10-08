from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from support.app import App
from support.solo_test import fast_params, small_data
from voracious.application.errors import (
    FitNotFoundError,
    ModelNotFoundError,
    ModelNotReadyError,
    MonitoringNotFoundError,
    UnknownChartError,
)
from voracious.application.ports import JobKind, JobRequest
from voracious.application.records import JobStatus, ModelRecord, MonitoringSummary
from voracious.application.use_cases import INTERNAL_ERROR
from voracious.application.use_cases.training import initial_version
from voracious.domain.charts.t2mrcd import (
    T2MRCD_DECISION_PENDING,
    T2MRCDBootstrap,
    T2MRCDChart,
    T2MRCDModel,
    T2MRCDMonitoring,
    T2MRCDParams,
)
from voracious.domain.common import InvalidInputError, RowDisposition
from voracious.domain.estimators.mrcd import MRCDFit

TENANT = "tenant-a"
OTHER = "tenant-b"
T0 = datetime(2026, 3, 1, tzinfo=UTC)


def _dates(m: int, start: datetime = T0) -> list[datetime]:
    return [start + timedelta(hours=i) for i in range(m)]


def _t2mrcd_app() -> App:
    return App(charts={"t2mrcd": T2MRCDChart()})


def _trained(app: App) -> str:
    return app.train(TENANT, "t2mrcd", small_data().tolist(), fast_params())


def _queued_model(app: App) -> str:
    """Modelo pedido por referencias y aún ``queued`` (su trabajo no se ejecuta)."""
    dataset = app.upload().execute(TENANT, small_data())
    fit_id = app.request_fit().execute(TENANT, "t2mrcd", dataset.dataset_id, None)
    app.run_all()
    limits_id = app.request_limits().execute(TENANT, "t2mrcd", fit_id, fast_params())
    app.run_all()
    model_id = app.request_model().execute(TENANT, "t2mrcd", fit_id=fit_id, limits_id=limits_id)
    return model_id


def _failed_model(app: App, chart_id: str = "t2mrcd") -> str:
    record = ModelRecord(TENANT, chart_id, "failed-1", JobStatus.FAILED, {}, small_data(), T0)
    app.models.add(record)
    return record.model_id


class _BoomFitChart(T2MRCDChart):
    """T²MRCD cuyo ajuste suelto falla con una excepción inesperada."""

    def fit_estimator(self, *args: object, **kwargs: object) -> MRCDFit:
        raise RuntimeError("fallo inesperado con traza")


class _BoomChart:
    """Carta de prueba que falla con una excepción inesperada."""

    @property
    def chart_id(self) -> str:
        return "boom"

    def encode_params(self, params: object) -> dict[str, object]:
        return {}

    def decode_params(self, data: Mapping[str, object]) -> object:
        return data

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
    monitoring_id = app.monitor().execute(TENANT, "t2mrcd", model_id, x_new.tolist(), _dates(6))
    queued = app.get_monitoring().execute(TENANT, "t2mrcd", model_id, monitoring_id)
    assert queued.status is JobStatus.QUEUED
    app.run_all()
    done = app.get_monitoring().execute(TENANT, "t2mrcd", model_id, monitoring_id)
    assert done.status is JobStatus.SUCCEEDED
    assert isinstance(done.result, MonitoringSummary)
    assert done.result.version_numbers == (0,) * 6
    observations = [
        app.observations.get(TENANT, "t2mrcd", model_id, i) for i in done.result.observation_ids
    ]
    assert all(o is not None for o in observations)
    third = observations[2]
    assert third is not None
    assert third.signal
    assert done.result.n_signals >= 1
    assert third.limit == record.model.operative_limit == record.model.limits.phase1_limit
    assert third.limit_kind == "phase1_provisional"
    assert third.observed_at == T0 + timedelta(hours=2)
    direct = T2MRCDChart().score_phase2(record.model, x_new)
    assert isinstance(direct, T2MRCDMonitoring)
    assert [o.t2 for o in observations if o is not None] == direct.t2.tolist()
    assert [r.status for r in app.monitorings.history] == [
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.SUCCEEDED,
    ]


def test_decision_pending_fails_the_pipeline_before_fitting() -> None:
    app = App(charts={"t2mrcd": T2MRCDChart()})
    params = T2MRCDParams(bootstrap=T2MRCDBootstrap(seed=1, aggregation=None))
    record = app.pipeline(TENANT, "t2mrcd", small_data(), params)
    assert record.status is JobStatus.FAILED
    assert record.model_id is None
    assert record.steps == ()
    assert record.error is not None
    assert record.error.code == T2MRCD_DECISION_PENDING
    assert record.error.details["pending"] == ["bootstrap.aggregation"]
    assert record.finished_at is not None
    assert app.fits.get(TENANT, "t2mrcd", "id-1") is None


def test_tenant_isolation() -> None:
    app = _t2mrcd_app()
    model_id = _trained(app)
    with pytest.raises(ModelNotFoundError):
        app.get_model().execute(OTHER, "t2mrcd", model_id)
    with pytest.raises(ModelNotFoundError):
        app.monitor().execute(OTHER, "t2mrcd", model_id, small_data(2, 4).tolist(), _dates(2))
    monitoring_id = app.monitor().execute(TENANT, "t2mrcd", model_id, small_data(2, 4), _dates(2))
    with pytest.raises(MonitoringNotFoundError):
        app.get_monitoring().execute(OTHER, "t2mrcd", model_id, monitoring_id)
    with pytest.raises(MonitoringNotFoundError):
        app.get_monitoring().execute(TENANT, "t2mrcd", "otro-modelo", monitoring_id)


def test_unknown_chart_is_chart_not_found() -> None:
    app = _t2mrcd_app()
    dataset = app.upload().execute(TENANT, small_data())
    with pytest.raises(UnknownChartError) as info:
        app.request_pipeline().execute(TENANT, "ewma", dataset.dataset_id, fast_params())
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
    model_id = _queued_model(app)
    with pytest.raises(ModelNotReadyError) as info:
        app.monitor().execute(TENANT, "t2mrcd", model_id, small_data(2, 4), _dates(2))
    assert info.value.code == "MODEL_NOT_READY"
    assert info.value.details == {"model_id": model_id, "status": "queued"}


def test_failed_model_is_not_ready() -> None:
    app = App(charts={"t2mrcd": T2MRCDChart()})
    model_id = _failed_model(app)
    with pytest.raises(ModelNotReadyError):
        app.monitor().execute(TENANT, "t2mrcd", model_id, small_data(2, 4), _dates(2))


def test_phase2_input_is_validated_before_enqueue() -> None:
    app = _t2mrcd_app()
    model_id = _trained(app)
    with pytest.raises(InvalidInputError) as info:
        app.monitor().execute(TENANT, "t2mrcd", model_id, np.zeros((3, 5)), _dates(3))
    assert info.value.details["expected_features"] == 4
    with pytest.raises(InvalidInputError):
        app.monitor().execute(TENANT, "t2mrcd", model_id, [1.0, 2.0, 3.0, 4.0], _dates(1))
    assert app.queue.jobs == []
    assert app.monitorings.records == {}


def test_training_input_must_be_a_matrix() -> None:
    app = _t2mrcd_app()
    with pytest.raises(InvalidInputError):
        app.upload().execute(TENANT, [1.0, 2.0])
    assert app.models.records == {}


def test_unexpected_error_is_internal_error_and_reraised() -> None:
    app = App(charts={"t2mrcd": _BoomFitChart()})
    dataset = app.upload().execute(TENANT, small_data())
    fit_id = app.request_fit().execute(TENANT, "t2mrcd", dataset.dataset_id, None)
    job = app.queue.jobs.pop()
    with pytest.raises(RuntimeError, match="fallo inesperado"):
        app.run_fit().execute(job)
    record = app.get_fit().execute(TENANT, "t2mrcd", fit_id)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == INTERNAL_ERROR
    assert record.error.details == {}
    assert "traza" not in record.error.message


def test_unexpected_phase2_error_is_internal_error_and_reraised() -> None:
    app = App(charts={"boom": _BoomChart()})
    record = ModelRecord(TENANT, "boom", "m-1", JobStatus.QUEUED, {}, small_data(), T0)
    app.models.add(record)
    model_id = record.model_id
    key = (TENANT, "boom", model_id)
    app.models.records[key] = _succeeded(app, key)
    monitoring_id = app.monitor().execute(TENANT, "boom", model_id, small_data(2, 4), _dates(2))
    job = app.queue.jobs.pop()
    with pytest.raises(RuntimeError):
        app.run_monitoring().execute(job)
    record_m = app.get_monitoring().execute(TENANT, "boom", model_id, monitoring_id)
    assert record_m.status is JobStatus.FAILED
    assert record_m.error is not None
    assert record_m.error.code == INTERNAL_ERROR


class _FakeModel:
    base_mask = np.ones(40, dtype=np.bool_)
    row_disposition = (RowDisposition.KEPT,) * 40


def _succeeded(app: App, key: tuple[str, str, str]) -> object:
    record = replace(app.models.records[key], status=JobStatus.SUCCEEDED, model=_FakeModel())
    app.versions.add(initial_version(record, record.model, app.clock.now()))
    return record


def test_jobs_are_idempotent() -> None:
    app = _t2mrcd_app()
    dataset = app.upload().execute(TENANT, small_data())
    app.request_fit().execute(TENANT, "t2mrcd", dataset.dataset_id, None)
    job = app.queue.jobs[0]
    app.run_all()
    fit_before = app.fits.get(TENANT, "t2mrcd", job.resource_id)
    app.run_fit().execute(job)
    assert app.fits.get(TENANT, "t2mrcd", job.resource_id) is not None
    assert fit_before is not None
    model_id = _trained(app)
    monitoring_id = app.monitor().execute(TENANT, "t2mrcd", model_id, small_data(2, 4), _dates(2))
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
    monitoring_id = app.monitor().execute(TENANT, "t2mrcd", model_id, small_data(2, 4), _dates(2))
    del app.models.records[(TENANT, "t2mrcd", model_id)]
    app.run_all()
    record = app.get_monitoring().execute(TENANT, "t2mrcd", model_id, monitoring_id)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == "MODEL_NOT_FOUND"


def test_job_kind_mismatch_and_missing_resources() -> None:
    app = _t2mrcd_app()
    fit_job = JobRequest(JobKind.MRCD_FIT, TENANT, "t2mrcd", "nope")
    score_job = JobRequest(JobKind.SCORE, TENANT, "t2mrcd", "m", model_id="nope")
    assert fit_job.resource_id == "nope"
    assert score_job.resource_id == "m"
    with pytest.raises(ValueError, match="mrcd_fit"):
        app.run_fit().execute(score_job)
    with pytest.raises(ValueError, match="score"):
        app.run_monitoring().execute(fit_job)
    with pytest.raises(FitNotFoundError):
        app.run_fit().execute(fit_job)
    with pytest.raises(MonitoringNotFoundError):
        app.run_monitoring().execute(score_job)


@pytest.mark.parametrize(("kind", "model_id"), [(JobKind.SCORE, None), (JobKind.MRCD_FIT, "m")])
def test_job_request_consistency(kind: JobKind, model_id: str | None) -> None:
    with pytest.raises(ValueError, match="model_id"):
        JobRequest(kind, TENANT, "t2mrcd", "id", model_id)
