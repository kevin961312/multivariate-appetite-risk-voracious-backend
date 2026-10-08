"""Pasos encadenables de Fase I y tubería (T19, T20): linaje, errores, idempotencia y avisos."""

from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest

from support.app import CHART, TENANT, App, lifecycle_app
from support.composition_cases import contaminated
from support.solo_test import fast_params, small_data
from voracious.application.errors import (
    DatasetNotFoundError,
    DepurationNotFinalError,
    DepurationNotFoundError,
    LimitsNotFoundError,
    LimitsParamsMismatchError,
    PipelineNotFoundError,
    UnknownChartError,
)
from voracious.application.phase1_steps import DepurationOutcome
from voracious.application.ports import JobKind, JobRequest
from voracious.application.records import (
    AssignableCause,
    DatasetRecord,
    DatasetSource,
    JobStatus,
    ModelRecord,
)
from voracious.application.use_cases.steps import parse_csv, stage_lineage
from voracious.domain.charts.t2mrcd import (
    T2MRCD_DECISION_PENDING,
    T2MRCDBootstrap,
    T2MRCDChart,
    T2MRCDParams,
)
from voracious.domain.common import (
    DomainError,
    EstimationError,
    InvalidInputError,
    StageKind,
    StageLineage,
)
from voracious.domain.estimators.mrcd import MRCDFit
from voracious.infrastructure.charts import T2MRCDPhase1Steps

T = datetime(2026, 1, 1, tzinfo=UTC)


def _record(source: DatasetSource, round_: int = 0) -> DatasetRecord:
    data = np.zeros((2, 2))
    return DatasetRecord("t", "d", data, "h", source, T, lineage_round=round_)


def _fitted(app: App, x: np.ndarray | None = None) -> tuple[str, str]:
    dataset = app.upload().execute(TENANT, small_data() if x is None else x)
    fit_id = app.request_fit().execute(TENANT, CHART, dataset.dataset_id, None)
    app.run_all()
    return dataset.dataset_id, fit_id


def test_parse_csv_header_blank_lines_and_errors() -> None:
    assert parse_csv("x,y\n1,2\n\n3,4.5\n") == [[1.0, 2.0], [3.0, 4.5]]
    assert parse_csv("1,2\n3,4\n") == [[1.0, 2.0], [3.0, 4.0]]
    with pytest.raises(InvalidInputError, match="no tiene filas"):
        parse_csv("x,y\n")
    with pytest.raises(InvalidInputError) as info:
        parse_csv("1,2\nx,3\n4,y\n")
    assert info.value.details["n_bad"] == 2


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        (DatasetSource.UPLOAD, StageKind.PHASE1),
        (DatasetSource.RECALIBRATION_CANDIDATES, StageKind.NEW_ROWS),
        (DatasetSource.RECALIBRATION_EXTENSION, StageKind.EXTENSION),
    ],
)
def test_stage_lineage_comes_from_the_root(source: DatasetSource, kind: StageKind) -> None:
    root = _record(source)
    assert stage_lineage([root]) == StageLineage(kind, 0)
    if kind is not StageKind.EXTENSION:
        assert stage_lineage([root, _record(DatasetSource.DEPURATION_OUTPUT, 2)]).round == 2


def test_stage_lineage_rejects_a_derived_root() -> None:
    with pytest.raises(InvalidInputError, match="raíz"):
        stage_lineage([_record(DatasetSource.DEPURATION_OUTPUT)])


def test_upload_and_get_dataset() -> None:
    app = lifecycle_app()
    record = app.upload().execute(TENANT, [[1.0, 2.0], [3.0, 4.0]])
    assert not record.data.flags.writeable
    assert record.content_hash.startswith("sha256:")
    view = app.get_dataset().execute(TENANT, record.dataset_id)
    assert view.chain == (view.dataset,)
    with pytest.raises(DatasetNotFoundError):
        app.get_dataset().execute("otro", record.dataset_id)
    for bad in ([[np.inf, 1.0]], np.zeros((0, 2))):
        with pytest.raises(InvalidInputError):
            app.upload().execute(TENANT, bad)
    csv = app.upload().execute_csv(TENANT, "a,b\n1,2\n3,4\n")
    assert csv.content_hash == record.content_hash


def test_unknown_chart_and_missing_resources() -> None:
    app = lifecycle_app()
    with pytest.raises(UnknownChartError):
        app.request_fit().execute(TENANT, "ewma", "d", None)
    with pytest.raises(DatasetNotFoundError):
        app.request_fit().execute(TENANT, CHART, "nada", None)
    with pytest.raises(LimitsNotFoundError):
        app.get_limits().execute(TENANT, CHART, "nada")
    with pytest.raises(DepurationNotFoundError):
        app.get_depuration().execute(TENANT, CHART, "nada")
    with pytest.raises(PipelineNotFoundError):
        app.get_pipeline().execute(TENANT, CHART, "nada")
    with pytest.raises(DatasetNotFoundError):
        app.request_pipeline().execute(TENANT, CHART, "nada", fast_params())
    assert app.queue.jobs == []


def test_fit_validation_is_synchronous() -> None:
    app = lifecycle_app()
    dataset = DatasetRecord(TENANT, "nan", np.array([[np.nan, 1.0]]), "h", DatasetSource.UPLOAD, T)
    app.datasets.add(dataset)
    with pytest.raises(InvalidInputError, match="no finitos"):
        app.request_fit().execute(TENANT, CHART, "nan", None)
    assert app.queue.jobs == []


@pytest.mark.parametrize(
    ("kind", "runner"),
    [
        (JobKind.MRCD_FIT, "run_limits"),
        (JobKind.LIMITS, "run_depuration"),
        (JobKind.DEPURATION, "run_assembly"),
        (JobKind.MODEL_ASSEMBLY, "run_fit"),
        (JobKind.MRCD_FIT, "run_pipeline"),
    ],
)
def test_runners_reject_other_kinds(kind: JobKind, runner: str) -> None:
    app = lifecycle_app()
    with pytest.raises(ValueError, match="solo ejecuta"):
        getattr(app, runner)().execute(JobRequest(kind, TENANT, CHART, "x"))


def test_jobs_are_idempotent_and_standalone_steps_do_not_notify() -> None:
    app = lifecycle_app()
    _, fit_id = _fitted(app)
    limits_id = app.request_limits().execute(TENANT, CHART, fit_id, fast_params())
    job = app.queue.jobs[0]
    app.run_all()
    done = app.get_limits().execute(TENANT, CHART, limits_id)
    app.run_limits().execute(job)
    assert app.get_limits().execute(TENANT, CHART, limits_id).finished_at == done.finished_at
    assert app.queue.jobs == []  # sin tubería, nadie a quien avisar


def test_limits_fail_if_the_fit_disappears() -> None:
    app = lifecycle_app()
    _, fit_id = _fitted(app)
    limits_id = app.request_limits().execute(TENANT, CHART, fit_id, fast_params())
    del app.fits._steps.store.rows[(TENANT, CHART, fit_id)]
    app.run_all()
    failed = app.get_limits().execute(TENANT, CHART, limits_id)
    assert failed.status is JobStatus.FAILED
    assert failed.error is not None
    assert failed.error.code == "FIT_NOT_FOUND"


def test_assembly_without_provenance_fails() -> None:
    app = lifecycle_app()
    record = ModelRecord(TENANT, CHART, "m", JobStatus.QUEUED, {}, small_data(), T)
    app.models.add(record)
    app.run_assembly().execute(JobRequest(JobKind.MODEL_ASSEMBLY, TENANT, CHART, "m"))
    failed = app.get_model().execute(TENANT, CHART, "m")
    assert failed.status is JobStatus.FAILED
    assert failed.error is not None
    assert failed.error.code == "INVALID_INPUT"


class _FailingFitChart(T2MRCDChart):
    """T²MRCD cuyo ajuste suelto falla con un error del dominio."""

    def fit_estimator(self, *args: object, **kwargs: object) -> MRCDFit:
        raise EstimationError("MRCD_FIT_FAILED", "falló", {"r_message": "x"})


def test_pipeline_fails_with_the_error_of_its_step() -> None:
    app = App(charts={CHART: _FailingFitChart()})
    record = app.pipeline(TENANT, CHART, small_data(), fast_params())
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == "MRCD_FIT_FAILED"
    assert record.error.details["step"] == "fit"
    assert record.error.details["step_id"] == record.steps[0].resource_id
    assert record.error.details["r_message"] == "x"
    fit = app.get_fit().execute(TENANT, CHART, record.steps[0].resource_id)
    assert fit.status is JobStatus.FAILED


def test_pipeline_job_is_idempotent_once_finished() -> None:
    app = lifecycle_app()
    record = app.pipeline(TENANT, CHART, small_data(), fast_params())
    assert record.status is JobStatus.SUCCEEDED
    app.run_pipeline().execute(JobRequest(JobKind.PIPELINE, TENANT, CHART, record.pipeline_id))
    again = app.get_pipeline().execute(TENANT, CHART, record.pipeline_id)
    assert again.steps == record.steps
    assert again.finished_at == record.finished_at


def test_a_stale_advance_does_not_duplicate_the_step() -> None:
    app = lifecycle_app()
    dataset = app.upload().execute(TENANT, small_data())
    pid = app.request_pipeline().execute(TENANT, CHART, dataset.dataset_id, fast_params())
    job = app.queue.jobs.pop(0)
    app.run_pipeline().execute(job)  # arranca y crea el ajuste
    assert len(app.get_pipeline().execute(TENANT, CHART, pid).steps) == 1
    app.run_pipeline().execute(job)  # aviso repetido: el ajuste sigue en cola
    assert len(app.get_pipeline().execute(TENANT, CHART, pid).steps) == 1
    app.run_all()
    assert app.get_pipeline().execute(TENANT, CHART, pid).status is JobStatus.SUCCEEDED


def test_exhausted_depuration_has_no_final_round(monkeypatch: pytest.MonkeyPatch) -> None:
    def exhausted(self: object, x: np.ndarray, *args: object, **kwargs: object) -> object:
        n = x.shape[0]
        return DepurationOutcome(
            kept=np.zeros(n, dtype=np.bool_),
            excluded_automatic=np.ones(n, dtype=np.bool_),
            converged=False,
            final=True,
            exhausted=True,
        )

    monkeypatch.setattr(T2MRCDPhase1Steps, "depurate", exhausted)
    app = lifecycle_app()
    record = app.pipeline(TENANT, CHART, small_data(), fast_params())
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == "DEPURATION_NOT_FINAL"
    assert record.error.details["reason"] == "exhausted"
    depuration_id = record.steps[-1].resource_id
    depuration = app.get_depuration().execute(TENANT, CHART, depuration_id)
    assert (depuration.final, depuration.exhausted, depuration.next_step) == (True, True, None)
    assert depuration.output_dataset_id is None
    with pytest.raises(DepurationNotFinalError):
        app.request_model().execute(TENANT, CHART, depuration_id=depuration_id)


def test_human_exclusion_keeps_order_and_lineage() -> None:
    app = lifecycle_app()
    x = small_data(20, 3, seed=9)
    dataset_id, fit_id = _fitted(app, x)
    depuration_id = app.request_depuration().execute(
        TENANT,
        CHART,
        dataset_id=dataset_id,
        assignable_cause=[AssignableCause(3, "a"), AssignableCause(0)],
    )
    app.run_all()
    done = app.get_depuration().execute(TENANT, CHART, depuration_id)
    assert done.output_dataset_id is not None
    derived = app.get_dataset().execute(TENANT, done.output_dataset_id)
    assert derived.dataset.parent_id == dataset_id
    assert derived.dataset.rows is not None
    assert derived.dataset.rows.tolist() == [i for i in range(20) if i not in {0, 3}]
    assert np.array_equal(derived.dataset.data, x[derived.dataset.rows])
    assert derived.dataset.data.flags.c_contiguous
    assert [d.dataset_id for d in derived.chain] == [dataset_id, derived.dataset.dataset_id]
    with pytest.raises(InvalidInputError):
        app.request_model().execute(TENANT, CHART, fit_id=fit_id)
    with pytest.raises(InvalidInputError):
        app.request_model().execute(TENANT, CHART, depuration_id=depuration_id, fit_id=fit_id)


def test_model_from_refs_records_the_previous_depurations() -> None:
    app = lifecycle_app()
    dataset_id = app.upload().execute(TENANT, small_data()).dataset_id
    human = app.request_depuration().execute(
        TENANT, CHART, dataset_id=dataset_id, assignable_cause=[AssignableCause(1)]
    )
    app.run_all()
    derived = app.get_depuration().execute(TENANT, CHART, human).output_dataset_id
    assert derived is not None
    fit2 = app.request_fit().execute(TENANT, CHART, derived, None)
    app.run_all()
    limits = app.request_limits().execute(TENANT, CHART, fit2, fast_params())
    app.run_all()
    model_id = app.request_model().execute(TENANT, CHART, fit_id=fit2, limits_id=limits)
    app.run_all()
    record = app.get_model().execute(TENANT, CHART, model_id)
    assert record.status is JobStatus.SUCCEEDED, record.error
    assert record.provenance is not None
    assert record.provenance.depuration_ids == (human,)
    model = record.model
    assert model is not None
    assert not bool(model.base_mask[1])
    assert replace(record, model=None).training_data.shape == (40, 4)


def test_limits_check_pending_decisions_before_queueing() -> None:
    app = App(charts={CHART: T2MRCDChart()})
    _, fit_id = _fitted(app)
    pending = T2MRCDParams(bootstrap=T2MRCDBootstrap(seed=1, aggregation=None))
    with pytest.raises(DomainError) as info:
        app.request_limits().execute(TENANT, CHART, fit_id, pending)
    assert info.value.code == T2MRCD_DECISION_PENDING
    assert info.value.details["pending"] == ["bootstrap.aggregation"]
    assert app.queue.jobs == []
    assert app.limits._steps.store.rows == {}


def _first_automatic_round(app: App) -> tuple[str, str, str]:
    """Raíz contaminada, ajuste, límites y una ronda que quita filas.

    Returns ``(raíz, límites, derivado)``.
    """
    root = app.upload().execute(TENANT, contaminated()).dataset_id
    fit_id = app.request_fit().execute(TENANT, CHART, root, None)
    app.run_all()
    limits_id = app.request_limits().execute(TENANT, CHART, fit_id, fast_params())
    app.run_all()
    depuration_id = app.request_depuration().execute(
        TENANT, CHART, fit_id=fit_id, limits_id=limits_id
    )
    app.run_all()
    derived = app.get_depuration().execute(TENANT, CHART, depuration_id).output_dataset_id
    assert derived is not None
    return root, limits_id, derived


def test_human_exclusion_only_at_start() -> None:
    app = lifecycle_app()
    root, _, derived = _first_automatic_round(app)
    with pytest.raises(InvalidInputError) as info:
        app.request_depuration().execute(
            TENANT, CHART, dataset_id=derived, assignable_cause=[AssignableCause(0)]
        )
    assert info.value.details["reason"] == "human_exclusion_only_at_start"
    # Sobre la raíz (o tras otra exclusión humana) sí se admite.
    human = app.request_depuration().execute(
        TENANT, CHART, dataset_id=root, assignable_cause=[AssignableCause(0)]
    )
    app.run_all()
    record = app.get_depuration().execute(TENANT, CHART, human)
    assert (record.dataset_id, record.fit_id, record.limits_id) == (root, None, None)
    assert record.output_dataset_id is not None
    again = app.request_depuration().execute(
        TENANT, CHART, dataset_id=record.output_dataset_id, assignable_cause=[AssignableCause(1)]
    )
    assert app.get_depuration().execute(TENANT, CHART, again).round == 0
    with pytest.raises(InvalidInputError) as info:
        app.request_depuration().execute(TENANT, CHART, dataset_id=root)
    assert info.value.details["reason"] == "assignable_cause_required"


def test_rounds_of_a_chain_inherit_the_parameters_of_its_limits() -> None:
    app = lifecycle_app()
    _, limits_id, derived = _first_automatic_round(app)
    fit_id = app.request_fit().execute(TENANT, CHART, derived, None)
    app.run_all()
    inherited = app.request_limits().execute(TENANT, CHART, fit_id, None)
    same = app.request_limits().execute(TENANT, CHART, fit_id, fast_params())
    source = app.get_limits().execute(TENANT, CHART, limits_id)
    for rid in (inherited, same):
        record = app.get_limits().execute(TENANT, CHART, rid)
        assert record.params == source.params
        assert (record.seed, record.round) == (source.seed, 1)
    with pytest.raises(LimitsParamsMismatchError) as info:
        app.request_limits().execute(TENANT, CHART, fit_id, fast_params(n_replicates=6))
    assert info.value.details["source_limits_id"] == limits_id
    assert info.value.details["fields"] == ["bootstrap.n_replicates"]
