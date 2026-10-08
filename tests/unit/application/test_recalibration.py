"""Recalibración a petición, anotaciones, eventos estructurales y revalidación periódica."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from support.app import (
    CHART,
    OTHER_TENANT,
    T0,
    TENANT,
    App,
    hours,
    lifecycle_app,
    queued_model,
    score,
    trained_model,
)
from support.memory import FixedClock
from support.solo_test import fast_params, fixed_tests_recalibration, small_data, solo_test_chart
from voracious.application.errors import (
    ModelNotFoundError,
    ModelNotReadyError,
    NotASignalError,
    ObservationNotFoundError,
    PipelineNotFoundError,
    ProposalPendingError,
    RangeBeforeStructuralEventError,
    RecalibrationDecisionPendingError,
    RecalibrationInProgressError,
    RecalibrationInsufficientObservationsError,
    RecalibrationNotFoundError,
)
from voracious.application.lifecycle import ChartStatus
from voracious.application.ports import JobKind, JobRequest
from voracious.application.records import (
    BaseRowSource,
    ExclusionReason,
    JobStatus,
    LifecyclePolicy,
    VersionStatus,
)
from voracious.domain.charts.t2mrcd import T2MRCDRecalibrationParams, T2MRCDRecalibrationReport
from voracious.domain.common import InvalidInputError, RecalibrationDecision

N = 30
END = T0 + timedelta(hours=N - 1)


def _scored(app: App, model_id: str, start: datetime = T0, seed: int = 50) -> list[str]:
    """Puntúa ``N`` observaciones (filas 3 y 7 desplazadas: señales) y devuelve sus ids."""
    x = small_data(N, 4, seed=seed)
    x[[3, 7]] += 8.0
    done = score(app, model_id, x, hours(N, start))
    assert done.result is not None
    return list(done.result.observation_ids)


def _request(app: App, model_id: str, **kwargs: object) -> str:
    args: dict[str, object] = {
        "range_from": T0,
        "range_to": END,
        "params": fixed_tests_recalibration(min_observations=10),
    }
    args.update(kwargs)
    return app.request_recalibration().execute(TENANT, CHART, model_id, **args)


def test_signal_annotations_are_append_only_and_only_for_signals() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    ids = _scored(app, model_id)
    signals = app.list_observations().execute(TENANT, CHART, model_id, signals_only=True)
    signal_ids = [s.observation.observation_id for s in signals]
    assert ids[3] in signal_ids
    assert ids[7] in signal_ids
    quiet = next(i for i in ids if i not in signal_ids)
    with pytest.raises(NotASignalError) as info:
        app.annotate().execute(TENANT, CHART, model_id, quiet, assignable_cause=True)
    assert info.value.code == "NOT_A_SIGNAL"
    with pytest.raises(ObservationNotFoundError):
        app.annotate().execute(OTHER_TENANT, CHART, model_id, ids[3], assignable_cause=True)
    first = app.annotate().execute(TENANT, CHART, model_id, ids[3], assignable_cause=False)
    second = app.annotate().execute(
        TENANT, CHART, model_id, ids[3], assignable_cause=True, cause="error", action="corregir"
    )
    assert app.annotations.history(TENANT, CHART, model_id, ids[3]) == [first, second]
    listed = app.list_observations().execute(
        TENANT,
        CHART,
        model_id,
        observed_from=T0 + timedelta(hours=3),
        observed_to=T0 + timedelta(hours=3),
    )
    assert [(o.observation.observation_id, o.annotation) for o in listed] == [(ids[3], second)]
    with pytest.raises(ModelNotFoundError):
        app.list_observations().execute(OTHER_TENANT, CHART, model_id)


def test_human_exclusion_comes_from_confirmed_assignable_cause() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    ids = _scored(app, model_id)
    annotation = app.annotate().execute(TENANT, CHART, model_id, ids[3], assignable_cause=True)
    app.annotate().execute(TENANT, CHART, model_id, ids[7], assignable_cause=False)
    rid = _request(app, model_id, actor="ana")
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.SUCCEEDED
    assert record.outcome is RecalibrationDecision.EXTEND
    assert record.actor == "ana"
    assert isinstance(record.report, T2MRCDRecalibrationReport)
    assert record.report.n_excluded_assignable_cause == 1
    assert record.params["covariance_test"] == "never_changed_solo_test"  # M1: por nombre
    version = app.get_version().execute(TENANT, CHART, model_id, 1)
    assert version.recalibration_id == rid
    assert version.justification == "no_change_detected"
    human = [e for e in version.exclusions if e.reason is ExclusionReason.ASSIGNABLE_CAUSE]
    assert [(e.ref.ref, e.annotation_id) for e in human] == [(ids[3], annotation.annotation_id)]
    observation_refs = {r.ref for r in version.base_refs if r.source is BaseRowSource.OBSERVATION}
    assert ids[3] not in observation_refs
    v0 = app.get_version().execute(TENANT, CHART, model_id, 0)
    assert version.base_refs[: len(v0.base_refs)] == v0.base_refs
    assert version.base_data.shape[0] == len(version.base_refs)


def test_request_validations() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    _scored(app, model_id)
    with pytest.raises(RecalibrationDecisionPendingError) as pending:
        _request(app, model_id, params=T2MRCDRecalibrationParams(seed=1, min_observations=10))
    assert pending.value.code == "RECALIBRATION_DECISION_PENDING"
    assert pending.value.details["pending"] == [
        "recalibration.covariance_test",
        "recalibration.mean_test",
        "recalibration.n_test_resamples",
    ]
    with pytest.raises(RecalibrationInsufficientObservationsError) as few:
        _request(app, model_id, range_to=T0 + timedelta(hours=4))
    assert few.value.details == {"available": 5, "required": 10}
    with pytest.raises(InvalidInputError):
        _request(app, model_id, range_from=END, range_to=T0)
    with pytest.raises(InvalidInputError):
        _request(app, model_id, range_from=datetime(2026, 3, 1))
    with pytest.raises(ModelNotFoundError):
        app.request_recalibration().execute(
            OTHER_TENANT, CHART, model_id, range_from=T0, range_to=END, params=None
        )
    assert app.queue.jobs == []

    rid = _request(app, model_id)
    with pytest.raises(RecalibrationInProgressError) as busy:
        _request(app, model_id)
    assert busy.value.details == {"recalibration_id": rid}
    app.run_all()
    with pytest.raises(ProposalPendingError):
        _request(app, model_id)
    with pytest.raises(RecalibrationNotFoundError):
        app.get_recalibration().execute(OTHER_TENANT, CHART, model_id, rid)

    # Ya en la base vigente: tras aprobar, solo quedan como candidatas las que no entraron.
    v1 = app.approve().execute(TENANT, CHART, model_id, 1)
    left_out = [e for e in v1.exclusions if e.reason is not ExclusionReason.ALREADY_IN_BASE]
    with pytest.raises(RecalibrationInsufficientObservationsError) as again:
        _request(app, model_id)
    assert again.value.details["available"] == len(left_out) < 10


def test_forced_replace_skips_pending_decisions() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    ids = _scored(app, model_id)
    rid = _request(
        app,
        model_id,
        params=T2MRCDRecalibrationParams(seed=1, min_observations=10),
        force_replace=True,
    )
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.outcome is RecalibrationDecision.REPLACE
    version = app.get_version().execute(TENANT, CHART, model_id, 1)
    assert version.justification == "forced_replace"
    assert all(r.source is BaseRowSource.OBSERVATION for r in version.base_refs)
    assert {r.ref for r in version.base_refs} <= set(ids)


def test_insufficient_recalibration_succeeds_without_version() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    ids = _scored(app, model_id)
    app.annotate().execute(TENANT, CHART, model_id, ids[3], assignable_cause=True)
    rid = _request(app, model_id, params=fixed_tests_recalibration(min_observations=N))
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.SUCCEEDED
    assert record.outcome is RecalibrationDecision.INSUFFICIENT
    assert record.proposed_version is None
    assert [v.number for v in app.list_versions().execute(TENANT, CHART, model_id)] == [0]
    assert app.status().execute(TENANT, CHART, model_id).status is ChartStatus.STARTUP


def test_structural_event_requires_new_base_and_forces_replace_after_it() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    before = _scored(app, model_id)
    _request(app, model_id)
    app.run_all()
    assert app.status().execute(TENANT, CHART, model_id).status is ChartStatus.PROPOSAL_PENDING

    occurred = END + timedelta(hours=1)
    event = app.register_event().execute(
        TENANT, CHART, model_id, occurred_at=occurred, description="fusión", actor="ana"
    )
    proposal = app.get_version().execute(TENANT, CHART, model_id, 1)
    assert proposal.status is VersionStatus.REJECTED
    assert proposal.decision_note == "structural_event"
    status = app.status().execute(TENANT, CHART, model_id)
    assert status.status is ChartStatus.REQUIRES_NEW_BASE
    assert status.unresolved_event_id == event.event_id
    assert status.notices == ("requires_new_base",)

    # Se sigue vigilando con la versión vigente (Q7).
    after = _scored(app, model_id, start=occurred + timedelta(hours=1), seed=60)
    with pytest.raises(RangeBeforeStructuralEventError) as info:
        _request(app, model_id, range_to=occurred + timedelta(hours=N + 1))
    assert info.value.code == "RANGE_BEFORE_STRUCTURAL_EVENT"
    rid = _request(
        app,
        model_id,
        range_from=occurred + timedelta(minutes=1),
        range_to=occurred + timedelta(hours=N + 1),
        params=T2MRCDRecalibrationParams(seed=3, min_observations=10),
    )
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.force_replace
    assert record.structural_event_id == event.event_id
    assert record.outcome is RecalibrationDecision.REPLACE
    version = app.get_version().execute(TENANT, CHART, model_id, 2)
    assert version.justification == "structural_event"
    assert version.structural_event_id == event.event_id
    refs = {r.ref for r in version.base_refs}
    assert refs <= set(after)
    assert refs.isdisjoint(before)
    app.approve().execute(TENANT, CHART, model_id, 2, effective_from=occurred + timedelta(days=3))
    assert app.status().execute(TENANT, CHART, model_id).status is ChartStatus.ACTIVE


def test_event_during_recalibration_rejects_the_new_version() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    _scored(app, model_id)
    rid = _request(app, model_id)
    app.register_event().execute(TENANT, CHART, model_id, occurred_at=END, description="x")
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.SUCCEEDED
    version = app.get_version().execute(TENANT, CHART, model_id, 1)
    assert version.status is VersionStatus.REJECTED
    assert version.decision_note == "structural_event"


def test_recalibration_job_failures_and_idempotency() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    _scored(app, model_id)
    rid = _request(app, model_id)
    key = (TENANT, CHART, model_id, rid)
    app.recalibrations.records[key] = replace(app.recalibrations.records[key], params={"seed": -1})
    job = app.queue.jobs[0]
    assert job.kind is JobKind.PIPELINE
    app.run_all()
    failed = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert failed.status is JobStatus.FAILED
    assert failed.error is not None
    assert failed.error.code == "INVALID_INPUT"
    app.run_recalibration().execute(job)  # idempotente: la tubería ya no está queued
    assert app.get_recalibration().execute(TENANT, CHART, model_id, rid) is failed

    with pytest.raises(ValueError, match="pipeline"):
        app.run_recalibration().execute(JobRequest(JobKind.MRCD_FIT, TENANT, CHART, model_id))
    with pytest.raises(PipelineNotFoundError):
        app.run_recalibration().execute(JobRequest(JobKind.PIPELINE, TENANT, CHART, "nope"))


def test_recalibration_requires_ready_model() -> None:
    app = lifecycle_app()
    model_id = queued_model(app)
    with pytest.raises(ModelNotReadyError):
        _request(app, model_id)
    with pytest.raises(ModelNotReadyError):
        app.register_event().execute(TENANT, CHART, model_id, occurred_at=T0, description="x")


def test_revalidation_due_by_months_and_by_observations() -> None:
    clock = FixedClock(datetime(2026, 1, 15, tzinfo=UTC))
    app = App(charts={CHART: solo_test_chart()}, clock=clock)
    model_id = trained_model(app)
    assert app.status().execute(TENANT, CHART, model_id).status is ChartStatus.STARTUP
    clock.advance(timedelta(days=181))
    status = app.status().execute(TENANT, CHART, model_id)
    assert status.status is ChartStatus.REVALIDATION_DUE
    assert status.revalidation_due_at == datetime(2026, 7, 15, tzinfo=UTC)
    assert status.notices == ("revalidation_due",)

    counted = App(charts={CHART: solo_test_chart()})
    policy = LifecyclePolicy(revalidate_every_months=None, revalidate_every_observations=N)
    counted_id = counted.train(TENANT, CHART, small_data(), fast_params(), policy=policy)
    assert not counted.status().execute(TENANT, CHART, counted_id).revalidation_due
    _scored(counted, counted_id)
    status = counted.status().execute(TENANT, CHART, counted_id)
    assert status.revalidation_due
    assert status.observations_since_active == N
    assert status.revalidation_due_at is None
