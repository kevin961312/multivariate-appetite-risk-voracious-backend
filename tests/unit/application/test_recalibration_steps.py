"""Recalibración por pasos en la aplicación (T22, T23): sesión, comparación, propuesta y tubería."""

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from support.app import CHART, T0, TENANT, App, hours, lifecycle_app, score, trained_model
from support.memory import InMemoryRecalibrationRepository
from support.solo_test import fixed_tests_recalibration, small_data, solo_test_chart
from voracious.application.errors import (
    ComparisonNotFoundError,
    ComparisonNotReadyError,
    RecalibrationMismatchError,
    RecalibrationNotFoundError,
    RecalibrationNotInProgressError,
)
from voracious.application.ports import JobKind, JobRequest
from voracious.application.records import (
    DatasetSource,
    JobStatus,
    ProposalRequest,
    RecalibrationMode,
    RecalibrationRecord,
    VersionStatus,
)
from voracious.application.use_cases import RequestLimits
from voracious.domain.charts.t2mrcd import (
    ComparisonResult,
    T2MRCDChart,
    decode_comparison,
)
from voracious.domain.common import InvalidInputError, RecalibrationDecision
from voracious.infrastructure.charts import T2MRCDRecalibrationSteps

N = 30
END = T0 + timedelta(hours=N - 1)


def _scored_app(app: App | None = None) -> tuple[App, str]:
    app = app if app is not None else lifecycle_app()
    model_id = trained_model(app)
    x = small_data(N, 4, seed=50)
    x[[3, 7]] += 8.0
    score(app, model_id, x, hours(N))
    return app, model_id


def _open(app: App, model_id: str, **kwargs: object) -> RecalibrationRecord:
    args: dict[str, object] = {
        "range_from": T0,
        "range_to": END,
        "params": fixed_tests_recalibration(min_observations=10),
        "mode": RecalibrationMode.STEPWISE,
    }
    args.update(kwargs)
    rid = app.request_recalibration().execute(TENANT, CHART, model_id, **args)
    return app.get_recalibration().execute(TENANT, CHART, model_id, rid)


def _final_round(app: App, session: RecalibrationRecord) -> tuple[str, str, str]:
    """Ajusta, calibra y depura las candidatas hasta la ronda final: ``(fit, limits, dep)``."""
    assert session.candidates_dataset_id is not None
    dataset = session.candidates_dataset_id
    while True:
        fit_id = app.request_fit().execute(TENANT, CHART, dataset, None)
        app.run_all()
        limits_id = app.request_limits().execute(
            TENANT, CHART, fit_id, None, recalibration_id=session.recalibration_id
        )
        app.run_all()
        dep_id = app.request_depuration().execute(TENANT, CHART, fit_id=fit_id, limits_id=limits_id)
        app.run_all()
        dep = app.get_depuration().execute(TENANT, CHART, dep_id)
        if dep.final:
            return fit_id, limits_id, dep_id
        assert dep.output_dataset_id is not None
        dataset = dep.output_dataset_id


def test_stepwise_session_freezes_candidates_and_enqueues_nothing() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id)
    assert app.queue.jobs == []
    assert session.status is JobStatus.RUNNING
    assert session.mode is RecalibrationMode.STEPWISE
    assert session.pipeline_id is None
    assert len(session.candidate_ids) == N
    assert session.already_in_base_ids == ()
    bootstrap = session.inherited_params["bootstrap"]
    assert isinstance(bootstrap, dict)
    assert bootstrap["seed"] == 11
    assert session.candidates_dataset_id is not None
    dataset = app.datasets.get(TENANT, session.candidates_dataset_id)
    assert dataset is not None
    assert dataset.source is DatasetSource.RECALIBRATION_CANDIDATES
    assert dataset.origin_ref == session.recalibration_id
    observed = [app.observations.get(TENANT, CHART, model_id, oid) for oid in session.candidate_ids]
    values = np.array([o.values for o in observed if o is not None])
    assert dataset.data.tobytes() == values.tobytes()


def test_job_runners_reject_other_kinds_and_unknown_resources() -> None:
    app, model_id = _scored_app()
    with pytest.raises(ValueError, match="comparison"):
        app.run_comparison().execute(JobRequest(JobKind.MRCD_FIT, TENANT, CHART, "x"))
    with pytest.raises(ComparisonNotFoundError):
        app.run_comparison().execute(JobRequest(JobKind.COMPARISON, TENANT, CHART, "x", model_id))
    with pytest.raises(ValueError, match="version_proposal"):
        app.run_version_proposal().execute(JobRequest(JobKind.MRCD_FIT, TENANT, CHART, "x"))
    job = JobRequest(JobKind.VERSION_PROPOSAL, TENANT, CHART, "x", model_id)
    with pytest.raises(RecalibrationNotFoundError):
        app.run_version_proposal().execute(job)
    session = _open(app, model_id)
    idle = JobRequest(JobKind.VERSION_PROPOSAL, TENANT, CHART, session.recalibration_id, model_id)
    app.run_version_proposal().execute(idle)  # sin propuesta pedida: no hace nada
    assert (
        app.get_recalibration().execute(TENANT, CHART, model_id, session.recalibration_id).status
        is JobStatus.RUNNING
    )
    with pytest.raises(ComparisonNotFoundError):
        app.get_comparison().execute(TENANT, CHART, model_id, "nada")


def test_comparison_not_ready_and_failed_comparison() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id)
    rid = session.recalibration_id
    fit_id, limits_id, dep_id = _final_round(app, session)
    comparison_id = app.request_comparison().execute(TENANT, CHART, model_id, rid, dep_id)
    with pytest.raises(ComparisonNotReadyError):
        app.request_version_proposal().execute(
            TENANT,
            CHART,
            model_id,
            rid,
            fit_id=fit_id,
            limits_id=limits_id,
            comparison_id=comparison_id,
        )
    key = (TENANT, CHART, model_id, rid)
    stored = app.recalibrations.records[key]
    app.recalibrations.records[key] = replace(stored, params={"seed": -1})
    app.run_all()
    failed = app.get_comparison().execute(TENANT, CHART, model_id, comparison_id)
    assert failed.status is JobStatus.FAILED
    assert failed.error is not None
    assert failed.error.code == "INVALID_INPUT"
    app.recalibrations.records[key] = stored
    job = JobRequest(JobKind.COMPARISON, TENANT, CHART, comparison_id, model_id)
    app.run_comparison().execute(job)  # idempotente
    assert app.get_comparison().execute(TENANT, CHART, model_id, comparison_id) is not None


def app_fit(app: App, session: RecalibrationRecord) -> str:
    """Ajuste del dataset de candidatas (ya ejecutado)."""
    assert session.candidates_dataset_id is not None
    fit_id = app.request_fit().execute(TENANT, CHART, session.candidates_dataset_id, None)
    app.run_all()
    return fit_id


def test_replace_by_detected_change_reuses_the_last_new_rows_round() -> None:
    app, model_id = _scored_app()
    params = fixed_tests_recalibration(min_observations=10, changed=True)
    session = _open(app, model_id, params=params)
    fit_id, limits_id, dep_id = _final_round(app, session)
    rid = session.recalibration_id
    comparison_id = app.request_comparison().execute(TENANT, CHART, model_id, rid, dep_id)
    app.run_all()
    comparison = app.get_comparison().execute(TENANT, CHART, model_id, comparison_id)
    assert comparison.decision is RecalibrationDecision.REPLACE
    assert comparison.extension_dataset_id is None
    assert isinstance(comparison.result, ComparisonResult)
    app.request_version_proposal().execute(
        TENANT,
        CHART,
        model_id,
        rid,
        fit_id=fit_id,
        limits_id=limits_id,
        comparison_id=comparison_id,
    )
    with pytest.raises(RecalibrationNotInProgressError):
        app.request_version_proposal().execute(
            TENANT, CHART, model_id, rid, fit_id=fit_id, limits_id=limits_id
        )
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.SUCCEEDED
    assert record.outcome is RecalibrationDecision.REPLACE
    version = app.get_version().execute(TENANT, CHART, model_id, 1)
    assert version.justification == "change_detected"
    assert version.status is VersionStatus.PROPOSED


def test_proposal_job_fails_if_a_proposal_appeared_and_concurrent_request_loses() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id, force_replace=True)
    fit_id, limits_id, _ = _final_round(app, session)
    rid = session.recalibration_id
    app.request_version_proposal().execute(
        TENANT, CHART, model_id, rid, fit_id=fit_id, limits_id=limits_id
    )
    v0 = app.versions.list(TENANT, CHART, model_id)[0]
    app.versions.add(replace(v0, number=7, status=VersionStatus.PROPOSED))
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert (record.error.code, record.error.details) == ("PROPOSAL_PENDING", {"version": 7})
    assert record.proposal is not None
    assert record.proposal.status is JobStatus.FAILED

    class _Busy(InMemoryRecalibrationRepository):
        def request_proposal(
            self,
            tenant_id: str,
            chart_id: str,
            model_id: str,
            recalibration_id: str,
            proposal: ProposalRequest,
        ) -> RecalibrationRecord | None:
            return None

    busy = App(charts={CHART: solo_test_chart()}, recalibrations=_Busy())
    busy, other = _scored_app(busy)
    opened = _open(busy, other, force_replace=True)
    fit_id, limits_id, _ = _final_round(busy, opened)
    with pytest.raises(RecalibrationNotInProgressError) as info:
        busy.request_version_proposal().execute(
            TENANT, CHART, other, opened.recalibration_id, fit_id=fit_id, limits_id=limits_id
        )
    assert info.value.details["reason"] == "concurrent_request"


def test_pipeline_step_failure_fails_the_recalibration() -> None:
    app, model_id = _scored_app()
    rid = app.request_recalibration().execute(
        TENANT,
        CHART,
        model_id,
        range_from=T0,
        range_to=END,
        params=fixed_tests_recalibration(min_observations=10),
    )
    key = (TENANT, CHART, model_id, rid)
    stored = app.recalibrations.records[key]
    inherited = dict(stored.inherited_params)
    bootstrap = inherited["bootstrap"]
    assert isinstance(bootstrap, dict)
    inherited["bootstrap"] = {**bootstrap, "aggregation": None}
    app.recalibrations.records[key] = replace(stored, inherited_params=inherited)
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == "T2MRCD_DECISION_PENDING"
    assert record.error.details["step"] == "limits"
    assert record.pipeline_id is not None
    pipeline = app.get_pipeline().execute(TENANT, CHART, record.pipeline_id)
    assert pipeline.status is JobStatus.FAILED
    with pytest.raises(ValueError, match="no es de Fase I"):
        app.run_phase1().execute(JobRequest(JobKind.PIPELINE, TENANT, CHART, record.pipeline_id))


def test_recalibration_datasets_need_the_links() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id, force_replace=True)
    fit_id = app_fit(app, session)
    unwired = RequestLimits(
        app.steps,
        app.datasets,
        app.fits,
        app.limits,
        app.depurations,
        app.queue,
        app.ids,
        app.clock,
    )
    with pytest.raises(RecalibrationMismatchError) as info:
        unwired.execute(TENANT, CHART, fit_id, None, recalibration_id=session.recalibration_id)
    assert info.value.details == {"reason": "not_wired"}
    with pytest.raises(RecalibrationMismatchError):
        app.request_limits().execute(TENANT, CHART, fit_id, None)


def test_adapter_rejects_foreign_values() -> None:
    steps = T2MRCDRecalibrationSteps(T2MRCDChart())
    for call in (
        lambda: steps.encode_comparison(object()),
        lambda: steps.inherited_params(object(), {"seed": 1}),
        lambda: steps.decide(
            object(), n_kept=1, recalibration_params={"seed": 1}, force_replace=False
        ),
        lambda: steps.compare(
            object(), np.zeros((2, 2)), np.zeros((2, 2)), object(), {"seed": 1}, mapper=None
        ),
    ):
        with pytest.raises(TypeError):
            call()
    with pytest.raises(InvalidInputError):
        decode_comparison(None)
