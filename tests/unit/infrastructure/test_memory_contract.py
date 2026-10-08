"""Suite de contrato común de los repositorios en memoria (T3)."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import pytest

from support import records as rec
from voracious.application.ports import (
    DuplicateKeyError,
    RecordNotFoundError,
    VersionDecision,
    VersionStatusChange,
)
from voracious.application.records import JobStatus, VersionStatus
from voracious.infrastructure.memory import (
    InMemoryModelRepository,
    InMemoryModelVersionRepository,
    InMemoryMonitoringRepository,
    InMemoryObservationRepository,
    InMemoryRecalibrationRepository,
    InMemorySignalAnnotationRepository,
    InMemoryStructuralEventRepository,
    KeyedStore,
    PassthroughCodec,
)


@dataclass(frozen=True)
class Case:
    """Cómo crear, añadir y leer un registro de un repositorio."""

    name: str
    repo: Callable[[], Any]
    make: Callable[[str], Any]
    add: Callable[[Any, Any], None]
    read: Callable[[Any, str], list[Any]]


CASES = [
    Case(
        "models",
        InMemoryModelRepository,
        lambda t: rec.model(t),
        lambda r, x: r.add(x),
        lambda r, t: [v for v in [r.get(t, "c", "m")] if v is not None],
    ),
    Case(
        "monitorings",
        InMemoryMonitoringRepository,
        lambda t: rec.monitoring(t),
        lambda r, x: r.add(x),
        lambda r, t: [v for v in [r.get(t, "c", "m", "x")] if v is not None],
    ),
    Case(
        "recalibrations",
        InMemoryRecalibrationRepository,
        lambda t: rec.recalibration(t),
        lambda r, x: r.add(x),
        lambda r, t: r.list(t, "c", "m"),
    ),
    Case(
        "versions",
        InMemoryModelVersionRepository,
        lambda t: rec.version(t),
        lambda r, x: r.add(x),
        lambda r, t: r.list(t, "c", "m"),
    ),
    Case(
        "observations",
        InMemoryObservationRepository,
        lambda t: rec.observation(t),
        lambda r, x: r.add_many([x]),
        lambda r, t: r.list(t, "c", "m"),
    ),
    Case(
        "annotations",
        InMemorySignalAnnotationRepository,
        lambda t: rec.annotation(t),
        lambda r, x: r.add(x),
        lambda r, t: r.history(t, "c", "m", "o"),
    ),
    Case(
        "events",
        InMemoryStructuralEventRepository,
        lambda t: rec.event(t),
        lambda r, x: r.add(x),
        lambda r, t: r.list(t, "c", "m"),
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_add_read_and_tenant_isolation(case: Case) -> None:
    repo = case.repo()
    record = case.make("t")
    case.add(repo, record)
    assert case.read(repo, "t") == [record]
    assert case.read(repo, "otro") == []


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_duplicate_key_is_rejected(case: Case) -> None:
    repo = case.repo()
    case.add(repo, case.make("t"))
    with pytest.raises(DuplicateKeyError):
        case.add(repo, case.make("t"))
    case.add(repo, case.make("otro"))  # misma clave en otro tenant: es otro registro


JOB_CASES = [c for c in CASES if c.name in {"models", "monitorings", "recalibrations"}]


def _claim(repo: object, tenant: str = "t") -> object | None:
    when = rec.T
    if isinstance(repo, InMemoryModelRepository):
        return repo.claim(tenant, "c", "m", when)
    if isinstance(repo, InMemoryMonitoringRepository):
        return repo.claim(tenant, "c", "m", "x", when)
    assert isinstance(repo, InMemoryRecalibrationRepository)
    return repo.claim(tenant, "c", "m", "r", when)


def _race[R](fn: Callable[[], R]) -> list[R]:
    """Lanza ``fn`` en dos hilos a la vez (barrera) y devuelve ambos resultados."""
    barrier = threading.Barrier(2)
    out: list[R] = []

    def worker() -> None:
        barrier.wait()
        out.append(fn())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def _claim_race(case: Case) -> list[object | None]:
    repo = case.repo()
    case.add(repo, case.make("t"))
    return _race(lambda: _claim(repo))


def _recalibration_race() -> list[bool]:
    repo = InMemoryRecalibrationRepository()
    ids = iter(["r1", "r2"])
    lock = threading.Lock()

    def add() -> bool:
        with lock:
            rid = next(ids)
        return repo.add_if_none_in_progress(rec.recalibration(rid=rid))

    return _race(add)


def _proposal_race() -> list[bool]:
    repo = InMemoryModelVersionRepository()
    repo.add(rec.version())
    numbers = iter([1, 2])
    lock = threading.Lock()

    def add() -> bool:
        with lock:
            number = next(numbers)
        return repo.add_proposal_if_none(rec.version(number=number, status=VersionStatus.PROPOSED))

    return _race(add)


@pytest.mark.parametrize("case", JOB_CASES, ids=lambda c: c.name)
def test_update_of_missing_record_raises(case: Case) -> None:
    with pytest.raises(RecordNotFoundError):
        case.repo().update(case.make("t"))


@pytest.mark.parametrize("case", JOB_CASES, ids=lambda c: c.name)
def test_update_replaces(case: Case) -> None:
    repo = case.repo()
    record = case.make("t")
    case.add(repo, record)
    done = replace(record, status=JobStatus.SUCCEEDED)
    repo.update(done)
    assert case.read(repo, "t") == [done]


@pytest.mark.parametrize("case", JOB_CASES, ids=lambda c: c.name)
def test_claim_is_queued_to_running_once(case: Case) -> None:
    repo = case.repo()
    assert _claim(repo) is None  # no existe
    case.add(repo, case.make("t"))
    assert _claim(repo, "otro") is None  # otro tenant
    running = _claim(repo)
    assert running.status is JobStatus.RUNNING
    assert running.started_at == rec.T
    assert _claim(repo) is None  # ya no está queued


@pytest.mark.parametrize("case", JOB_CASES, ids=lambda c: c.name)
def test_concurrent_claims_only_one_wins(case: Case) -> None:
    for _ in range(20):
        assert sum(r is not None for r in _claim_race(case)) == 1


def test_recalibration_add_if_none_in_progress_is_atomic() -> None:
    for _ in range(20):
        assert sorted(_recalibration_race()) == [False, True]
    repo = InMemoryRecalibrationRepository()
    repo.add(rec.recalibration(rid="done", status=JobStatus.FAILED))
    assert repo.add_if_none_in_progress(rec.recalibration(rid="r"))
    assert not repo.add_if_none_in_progress(rec.recalibration(rid="r2"))
    assert repo.add_if_none_in_progress(rec.recalibration(tenant="otro", rid="r2"))
    finished = InMemoryRecalibrationRepository()
    finished.add(rec.recalibration(rid="done", status=JobStatus.FAILED))
    with pytest.raises(DuplicateKeyError):
        finished.add_if_none_in_progress(rec.recalibration(rid="done"))


def test_version_add_proposal_if_none_is_atomic() -> None:
    for _ in range(20):
        assert sorted(_proposal_race()) == [False, True]
    repo = InMemoryModelVersionRepository()
    with pytest.raises(ValueError, match="proposed"):
        repo.add_proposal_if_none(rec.version())
    repo.add(rec.version())
    with pytest.raises(DuplicateKeyError):
        repo.add_proposal_if_none(rec.version(status=VersionStatus.PROPOSED))


def test_version_status_changes_are_all_or_nothing() -> None:
    repo = InMemoryModelVersionRepository()
    repo.add(rec.version())
    repo.add(rec.version(number=1, status=VersionStatus.PROPOSED))
    decision = VersionDecision(rec.T, "ana", "ok", effective_from=rec.T)
    approve = VersionStatusChange(
        "t", "c", "m", 1, VersionStatus.PROPOSED, VersionStatus.ACTIVE, decision
    )
    supersede = VersionStatusChange(
        "t", "c", "m", 0, VersionStatus.ACTIVE, VersionStatus.SUPERSEDED
    )
    missing = VersionStatusChange("t", "c", "m", 7, VersionStatus.ACTIVE, VersionStatus.SUPERSEDED)
    assert not repo.apply_status_changes([approve, missing])
    assert repo.get("t", "c", "m", 1).status is VersionStatus.PROPOSED
    assert repo.apply_status_changes([approve, supersede])
    v1 = repo.get("t", "c", "m", 1)
    assert (v1.status, v1.approved_at, v1.decided_by) == (VersionStatus.ACTIVE, rec.T, "ana")
    reject = VersionStatusChange(
        "t",
        "c",
        "m",
        1,
        VersionStatus.ACTIVE,
        VersionStatus.REJECTED,
        VersionDecision(rec.T, None, "x"),
    )
    assert repo.apply_status_changes([reject])
    assert repo.get("t", "c", "m", 1).rejected_at == rec.T


def test_observation_queries() -> None:
    repo = InMemoryObservationRepository()
    rows = [rec.observation(rid=f"o{i}", hours=i) for i in range(3)]
    rows[1] = replace(rows[1], signal=True, version_number=1)
    repo.add_many(rows)
    with pytest.raises(DuplicateKeyError):
        repo.add_many([rec.observation(rid="n"), rec.observation(rid="n")])
    assert repo.get("t", "c", "m", "n") is None  # nada guardado del lote fallido
    assert [r.observation_id for r in repo.list("t", "c", "m", signals_only=True)] == ["o1"]
    window = repo.list(
        "t", "c", "m", observed_from=rows[1].observed_at, observed_to=rows[2].observed_at
    )
    assert [r.observation_id for r in window] == ["o1", "o2"]
    assert repo.max_observed_at("t", "c", "m") == rows[2].observed_at
    assert repo.max_observed_at("otro", "c", "m") is None
    assert repo.count_scored_with("t", "c", "m", 1) == 1


def test_annotations_latest_wins_and_events_sorted() -> None:
    repo = InMemorySignalAnnotationRepository()
    first, second = rec.annotation(rid="a1"), rec.annotation(rid="a2")
    repo.add(first)
    repo.add(second)
    repo.add(rec.annotation(rid="a3", obs="otra"))
    assert repo.latest_for("t", "c", "m", ["o", "sin"]) == {"o": second}
    assert repo.latest_for("otro", "c", "m", ["o"]) == {}
    events = InMemoryStructuralEventRepository()
    late = replace(rec.event(rid="late"), occurred_at=rec.T.replace(year=2027))
    events.add(late)
    events.add(rec.event(rid="early"))
    assert [e.event_id for e in events.list("t", "c", "m")] == ["early", "late"]


def test_passthrough_codec_checks_type_and_store_items() -> None:
    codec = PassthroughCodec(int)
    assert codec.decode(codec.encode(3)) == 3
    with pytest.raises(TypeError, match="int"):
        codec.decode("x")
    store: KeyedStore[str, int] = KeyedStore(codec)
    store.put("a", 1)
    assert list(store.items()) == [("a", 1)]
    assert store.get("b") is None
