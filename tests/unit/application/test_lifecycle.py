"""Reglas puras del ciclo de vida, la huella de la base y el CAS del repositorio de versiones."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import numpy as np
import pytest

from support.memory import InMemoryModelVersionRepository
from voracious.application.lifecycle import (
    ChartStatus,
    add_months,
    base_content_hash,
    derive_chart_state,
    revalidation_due,
    revalidation_due_at,
    unresolved_structural_event,
    utc,
    version_for,
)
from voracious.application.ports import (
    JobKind,
    JobRequest,
    VersionDecision,
    VersionStatusChange,
)
from voracious.application.records import (
    LifecyclePolicy,
    ModelVersion,
    StructuralEvent,
    VersionStatus,
)
from voracious.domain.common import InvalidInputError, RecalibrationDecision

D = datetime(2026, 1, 31, 12, tzinfo=UTC)


def _version(
    number: int,
    status: VersionStatus,
    effective_from: datetime | None = None,
    approved_at: datetime | None = D,
    event_id: str | None = None,
) -> ModelVersion:
    data = np.zeros((2, 2))
    return ModelVersion(
        tenant_id="t",
        chart_id="c",
        model_id="m",
        number=number,
        status=status,
        model=object(),
        base_data=data,
        base_hash=base_content_hash(data),
        base_refs=(),
        exclusions=(),
        decision=RecalibrationDecision.INITIAL if number == 0 else RecalibrationDecision.EXTEND,
        justification="x",
        created_at=D,
        structural_event_id=event_id,
        effective_from=effective_from,
        approved_at=approved_at,
    )


def _event(event_id: str, occurred_at: datetime) -> StructuralEvent:
    return StructuralEvent("t", "c", "m", event_id, occurred_at, "cambio", None, occurred_at)


def test_add_months_clamps_to_month_end() -> None:
    assert add_months(D, 1) == datetime(2026, 2, 28, 12, tzinfo=UTC)
    assert add_months(D, 6) == datetime(2026, 7, 31, 12, tzinfo=UTC)
    assert add_months(D, 13) == datetime(2027, 2, 28, 12, tzinfo=UTC)
    assert add_months(datetime(2027, 12, 15, tzinfo=UTC), 2) == datetime(2028, 2, 15, tzinfo=UTC)


def test_utc_requires_timezone_and_normalizes() -> None:
    bogota = timezone(timedelta(hours=-5))
    assert utc(datetime(2026, 1, 1, 7, tzinfo=bogota), "f") == datetime(2026, 1, 1, 12, tzinfo=UTC)
    with pytest.raises(InvalidInputError) as info:
        utc(datetime(2026, 1, 1), "observed_at")
    assert info.value.details == {"field": "observed_at"}


def test_base_hash_is_stable_layout_independent_and_content_sensitive() -> None:
    x = np.arange(12, dtype=np.float64).reshape(4, 3)
    h = base_content_hash(x)
    assert h.startswith("sha256:")
    assert base_content_hash(x.copy()) == h
    assert base_content_hash(np.asfortranarray(x)) == h
    assert base_content_hash(x.astype(">f8")) == h
    y = x.copy()
    y[2, 1] = np.nextafter(y[2, 1], np.inf)
    assert base_content_hash(y) != h
    assert base_content_hash(x.reshape(3, 4)) != h
    assert base_content_hash(x[:3]) != h


def test_version_for_picks_the_approved_version_of_the_date() -> None:
    t1, t2 = D + timedelta(days=10), D + timedelta(days=20)
    versions = [
        _version(0, VersionStatus.SUPERSEDED),
        _version(1, VersionStatus.SUPERSEDED, t1),
        _version(2, VersionStatus.REJECTED, D + timedelta(days=12)),
        _version(3, VersionStatus.ACTIVE, t2),
        _version(4, VersionStatus.PROPOSED, D + timedelta(days=30)),
    ]
    assert version_for(D, versions) is versions[0]
    assert version_for(t1 - timedelta(seconds=1), versions) is versions[0]
    assert version_for(t1, versions) is versions[1]
    assert version_for(D + timedelta(days=15), versions) is versions[1]
    assert version_for(D + timedelta(days=40), versions) is versions[3]
    later = [_version(1, VersionStatus.ACTIVE, t1)]
    assert version_for(D, later) is None


def test_unresolved_structural_event_only_counts_the_latest() -> None:
    assert unresolved_structural_event([], []) is None
    e1, e2 = _event("e1", D), _event("e2", D + timedelta(days=1))
    assert unresolved_structural_event([e2, e1], []) is e2
    resolved = [_version(1, VersionStatus.ACTIVE, D, event_id="e2")]
    assert unresolved_structural_event([e1, e2], resolved) is None
    proposed = [_version(1, VersionStatus.PROPOSED, event_id="e2")]
    assert unresolved_structural_event([e1, e2], proposed) is e2


def test_revalidation_by_months_and_by_observations() -> None:
    active = _version(0, VersionStatus.ACTIVE)
    six = LifecyclePolicy()
    due_at = revalidation_due_at(six, active)
    assert due_at == datetime(2026, 7, 31, 12, tzinfo=UTC)
    assert not revalidation_due(six, active, due_at - timedelta(seconds=1), 10_000)
    assert revalidation_due(six, active, due_at, 0)
    by_count = LifecyclePolicy(revalidate_every_months=None, revalidate_every_observations=50)
    assert revalidation_due_at(by_count, active) is None
    assert not revalidation_due(by_count, active, D + timedelta(days=9999), 49)
    assert revalidation_due(by_count, active, D, 50)
    assert revalidation_due_at(six, _version(1, VersionStatus.ACTIVE, approved_at=None)) is None


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_lifecycle_policy_validation(value: object) -> None:
    with pytest.raises(InvalidInputError):
        LifecyclePolicy(revalidate_every_months=value)
    with pytest.raises(InvalidInputError):
        LifecyclePolicy(revalidate_every_observations=value)


def test_chart_state_precedence() -> None:
    v0, v1 = _version(0, VersionStatus.ACTIVE), _version(1, VersionStatus.ACTIVE, D)
    state = derive_chart_state
    assert (
        state(requires_new_base=True, proposal_pending=True, revalidation_is_due=True, active=v0)
        is ChartStatus.REQUIRES_NEW_BASE
    )
    assert (
        state(requires_new_base=False, proposal_pending=True, revalidation_is_due=True, active=v0)
        is ChartStatus.PROPOSAL_PENDING
    )
    assert (
        state(requires_new_base=False, proposal_pending=False, revalidation_is_due=True, active=v0)
        is ChartStatus.REVALIDATION_DUE
    )
    assert (
        state(requires_new_base=False, proposal_pending=False, revalidation_is_due=False, active=v0)
        is ChartStatus.STARTUP
    )
    assert (
        state(requires_new_base=False, proposal_pending=False, revalidation_is_due=False, active=v1)
        is ChartStatus.ACTIVE
    )


def test_version_repository_cas_is_atomic_and_append_only() -> None:
    repo = InMemoryModelVersionRepository()
    v0, v1 = _version(0, VersionStatus.ACTIVE), _version(1, VersionStatus.PROPOSED)
    repo.add(v0)
    repo.add(v1)
    with pytest.raises(Exception, match="1"):
        repo.add(replace(v1))
    approve = VersionStatusChange(
        "t",
        "c",
        "m",
        1,
        VersionStatus.PROPOSED,
        VersionStatus.ACTIVE,
        VersionDecision(D, "ana", "ok", D),
    )
    supersede = VersionStatusChange(
        "t", "c", "m", 0, VersionStatus.ACTIVE, VersionStatus.SUPERSEDED
    )
    stale = VersionStatusChange("t", "c", "m", 0, VersionStatus.PROPOSED, VersionStatus.REJECTED)
    assert not repo.apply_status_changes([approve, stale])
    assert repo.get("t", "c", "m", 1) is v1  # nada aplicado
    assert repo.apply_status_changes([approve, supersede])
    assert not repo.apply_status_changes([approve, supersede])  # segunda vez: CAS falla
    assert [v.status for v in repo.list("t", "c", "m")] == [
        VersionStatus.SUPERSEDED,
        VersionStatus.ACTIVE,
    ]
    assert repo.list("otro", "c", "m") == []
    missing = VersionStatusChange("t", "c", "m", 9, VersionStatus.ACTIVE, VersionStatus.SUPERSEDED)
    assert not repo.apply_status_changes([missing])


def test_job_request_version_proposal_coherence() -> None:
    job = JobRequest(JobKind.VERSION_PROPOSAL, "t", "c", "r", model_id="m")
    assert job.resource_id == "r"
    with pytest.raises(ValueError, match="model_id"):
        JobRequest(JobKind.VERSION_PROPOSAL, "t", "c", "r")
    with pytest.raises(ValueError, match="model_id"):
        JobRequest(JobKind.MRCD_FIT, "t", "c", "m", model_id="m")
    with pytest.raises(ValueError, match="resource_id"):
        JobRequest(JobKind.VERSION_PROPOSAL, "t", "c", "", model_id="m")


def test_frozen_base_is_read_only_copy() -> None:
    """La base de una versión es una copia de solo lectura con el mismo hash."""
    import numpy as np
    import pytest

    from voracious.application.lifecycle import base_content_hash, frozen_base

    data = np.arange(6.0).reshape(3, 2)
    frozen = frozen_base(data)
    assert base_content_hash(frozen) == base_content_hash(data)
    with pytest.raises(ValueError, match="read-only"):
        frozen[0, 0] = 1.0
    data[0, 0] = 99.0
    assert frozen[0, 0] == 0.0
