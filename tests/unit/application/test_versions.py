"""Versiones: aprobación con CAS, inmutabilidad, no retroactividad y régimen por fecha."""

from datetime import timedelta

import numpy as np
import pytest

from support.app import (
    CHART,
    OTHER_TENANT,
    T0,
    TENANT,
    App,
    hours,
    lifecycle_app,
    score,
    trained_model,
)
from support.solo_test import fixed_tests_recalibration, small_data
from voracious.application.errors import (
    EffectiveFromNotAfterScoredError,
    ModelNotFoundError,
    ObservationBeforeFirstVersionError,
    VersionNotFoundError,
    VersionNotProposedError,
)
from voracious.application.lifecycle import ChartStatus, base_content_hash
from voracious.application.ports import VersionStatusChange
from voracious.application.records import (
    BaseRowSource,
    ExclusionReason,
    JobStatus,
    ModelVersion,
    VersionStatus,
)
from voracious.domain.charts.t2mrcd import LimitRegime, T2MRCDModel
from voracious.domain.common import RecalibrationDecision


def _proposal(app: App, model_id: str, n: int = 30, start: object = T0) -> int:
    """Puntúa ``n`` observaciones desde ``start`` y propone una versión EXTEND."""
    assert isinstance(start, type(T0))
    x = small_data(n, 4, seed=50)
    x[[3, 7]] += 8.0
    score(app, model_id, x, hours(n, start))
    rid = app.request_recalibration().execute(
        TENANT,
        CHART,
        model_id,
        range_from=start,
        range_to=start + timedelta(hours=n - 1),
        params=fixed_tests_recalibration(min_observations=10),
    )
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.SUCCEEDED, record.error
    assert record.proposed_version is not None
    return record.proposed_version


def _snapshot(version: ModelVersion) -> tuple[object, ...]:
    return (
        version.model,
        version.base_data.tobytes(),
        version.base_data.shape,
        version.base_hash,
        version.base_refs,
        version.exclusions,
        version.decision,
        version.report,
        version.effective_from,
        version.approved_at,
    )


def test_training_creates_active_version_zero_with_base_hash() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    [v0] = app.list_versions().execute(TENANT, CHART, model_id)
    record = app.get_model().execute(TENANT, CHART, model_id)
    assert isinstance(record.model, T2MRCDModel)
    assert v0.model is record.model
    assert v0.status is VersionStatus.ACTIVE
    assert v0.decision is RecalibrationDecision.INITIAL
    assert v0.effective_from is None
    assert v0.approved_at == record.finished_at
    np.testing.assert_array_equal(v0.base_data, record.training_data[record.model.base_mask])
    assert v0.base_hash == base_content_hash(v0.base_data)
    assert all(r.source is BaseRowSource.TRAINING for r in v0.base_refs)
    assert len(v0.base_refs) + len(v0.exclusions) == record.training_data.shape[0]
    assert all(e.reason is ExclusionReason.AUTOMATIC for e in v0.exclusions)
    assert isinstance(record.params, dict)  # M1: parámetros persistidos como datos
    status = app.status().execute(TENANT, CHART, model_id)
    assert status.status is ChartStatus.STARTUP
    assert status.notices == ()


def test_approve_supersedes_previous_and_keeps_versions_intact() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    v1_number = _proposal(app, model_id)
    v0_before = _snapshot(app.get_version().execute(TENANT, CHART, model_id, 0))
    v1 = app.get_version().execute(TENANT, CHART, model_id, v1_number)
    assert v1.status is VersionStatus.PROPOSED
    assert v1.decision is RecalibrationDecision.EXTEND
    assert v1.previous_number == 0
    assert v1.base_hash == base_content_hash(v1.base_data)
    assert v1.base_hash != app.get_version().execute(TENANT, CHART, model_id, 0).base_hash
    assert isinstance(v1.model, T2MRCDModel)
    assert v1.model.limit_regime is LimitRegime.PHASE2
    v1_before = _snapshot(v1)

    approved = app.approve().execute(TENANT, CHART, model_id, v1_number, note="ok", actor="ana")
    assert approved.status is VersionStatus.ACTIVE
    assert approved.decided_by == "ana"
    assert approved.decision_note == "ok"
    assert approved.effective_from is not None
    v0 = app.get_version().execute(TENANT, CHART, model_id, 0)
    assert v0.status is VersionStatus.SUPERSEDED
    assert _snapshot(v0) == v0_before
    after = _snapshot(approved)
    assert after[:8] == v1_before[:8]  # el contenido no cambia; solo estado y decisión

    # v2 sobre v1: las anteriores siguen intactas bit a bit.
    start = approved.effective_from + timedelta(hours=1)
    v2_number = _proposal(app, model_id, start=start)
    app.approve().execute(
        TENANT, CHART, model_id, v2_number, effective_from=start + timedelta(days=2)
    )
    statuses = [v.status for v in app.list_versions().execute(TENANT, CHART, model_id)]
    assert statuses == [VersionStatus.SUPERSEDED, VersionStatus.SUPERSEDED, VersionStatus.ACTIVE]
    assert _snapshot(app.get_version().execute(TENANT, CHART, model_id, 0)) == v0_before
    assert _snapshot(app.get_version().execute(TENANT, CHART, model_id, 1))[:8] == v1_before[:8]
    assert app.status().execute(TENANT, CHART, model_id).status is ChartStatus.ACTIVE


def test_second_approval_fails_and_concurrent_cas_loses() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    number = _proposal(app, model_id)
    app.approve().execute(TENANT, CHART, model_id, number)
    with pytest.raises(VersionNotProposedError) as info:
        app.approve().execute(TENANT, CHART, model_id, number)
    assert info.value.code == "VERSION_NOT_PROPOSED"
    with pytest.raises(VersionNotProposedError):
        app.reject().execute(TENANT, CHART, model_id, number)


class _RacingVersions:
    """Repositorio que deja leer ``proposed`` pero otro proceso gana el CAS."""

    def __init__(self, app: App) -> None:
        self.inner = app.versions

    def __getattr__(self, name: str) -> object:
        return getattr(self.inner, name)

    def apply_status_changes(self, changes: list[VersionStatusChange]) -> bool:
        winner = [
            VersionStatusChange(
                c.tenant_id, c.chart_id, c.model_id, c.number, c.expected, VersionStatus.REJECTED
            )
            for c in changes[:1]
        ]
        assert self.inner.apply_status_changes(winner)
        return self.inner.apply_status_changes(changes)


def test_concurrent_decision_loses_the_cas() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    number = _proposal(app, model_id)
    racing = App(charts=app.charts, clock=app.clock, observations=app.observations)
    racing.models = app.models
    racing.versions = _RacingVersions(app)
    with pytest.raises(VersionNotProposedError) as info:
        racing.approve().execute(TENANT, CHART, model_id, number)
    assert info.value.details["reason"] == "concurrent_change"
    assert app.get_version().execute(TENANT, CHART, model_id, 0).status is VersionStatus.ACTIVE


def test_effective_from_is_not_retroactive() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    number = _proposal(app, model_id)
    last = T0 + timedelta(hours=29)
    with pytest.raises(EffectiveFromNotAfterScoredError) as info:
        app.approve().execute(TENANT, CHART, model_id, number, effective_from=last)
    assert info.value.code == "EFFECTIVE_FROM_NOT_AFTER_SCORED"
    assert info.value.details["last_scored"] == last.isoformat()
    ok = app.approve().execute(
        TENANT, CHART, model_id, number, effective_from=last + timedelta(seconds=1)
    )
    assert ok.effective_from == last + timedelta(seconds=1)


def test_late_observation_and_split_batch_use_the_version_of_their_date() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    number = _proposal(app, model_id)
    cut = T0 + timedelta(days=5)
    app.approve().execute(TENANT, CHART, model_id, number, effective_from=cut)
    v0 = app.get_version().execute(TENANT, CHART, model_id, 0)
    v1 = app.get_version().execute(TENANT, CHART, model_id, number)
    assert isinstance(v0.model, T2MRCDModel)
    assert isinstance(v1.model, T2MRCDModel)

    x = small_data(4, 4, seed=77)
    dates = [cut - timedelta(hours=2), cut + timedelta(hours=1), cut - timedelta(hours=1), cut]
    done = score(app, model_id, x, dates, batch_label="lote-mixto")
    assert done.status is JobStatus.SUCCEEDED
    assert done.result is not None
    assert done.result.version_numbers == (0, number, 0, number)
    rows = [app.observations.get(TENANT, CHART, model_id, i) for i in done.result.observation_ids]
    for row, values in zip(rows, x, strict=True):
        assert row is not None
        assert row.batch_label == "lote-mixto"
        version = v0 if row.version_number == 0 else v1
        assert isinstance(version.model, T2MRCDModel)
        assert row.limit == version.model.operative_limit
        expected = "phase1_provisional" if row.version_number == 0 else "phase2"
        assert row.limit_kind == expected
        np.testing.assert_array_equal(row.values, values)

    late = score(app, model_id, small_data(1, 4, seed=78), [T0 - timedelta(days=30)])
    assert late.result is not None
    assert late.result.version_numbers == (0,)


def test_reject_and_lookup_errors() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    number = _proposal(app, model_id)
    rejected = app.reject().execute(TENANT, CHART, model_id, number, note="no", actor="luis")
    assert rejected.status is VersionStatus.REJECTED
    assert rejected.rejected_at is not None
    assert rejected.decided_by == "luis"
    with pytest.raises(VersionNotFoundError):
        app.get_version().execute(TENANT, CHART, model_id, 99)
    with pytest.raises(VersionNotFoundError):
        app.get_version().execute(OTHER_TENANT, CHART, model_id, 0)
    with pytest.raises(VersionNotFoundError):
        app.approve().execute(TENANT, CHART, model_id, 99)
    with pytest.raises(ModelNotFoundError):
        app.list_versions().execute(OTHER_TENANT, CHART, model_id)
    with pytest.raises(ModelNotFoundError):
        app.status().execute(OTHER_TENANT, CHART, model_id)
    assert app.status().execute(TENANT, CHART, model_id).status is ChartStatus.STARTUP


def test_observation_before_first_version_is_rejected() -> None:
    app = lifecycle_app()
    model_id = trained_model(app)
    # Simula una carta cuya primera versión rige desde una fecha (no ocurre con la v0, D3).
    key = (TENANT, CHART, model_id, 0)
    v0 = app.versions.records[key]
    app.versions.records[key] = type(v0)(**{**v0.__dict__, "effective_from": T0})
    with pytest.raises(ObservationBeforeFirstVersionError) as info:
        app.monitor().execute(
            TENANT, CHART, model_id, small_data(1, 4), [T0 - timedelta(seconds=1)]
        )
    assert info.value.code == "OBSERVATION_BEFORE_FIRST_VERSION"
    assert app.queue.jobs == []
