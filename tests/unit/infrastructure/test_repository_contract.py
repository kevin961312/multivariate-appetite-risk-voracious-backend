"""Suite de contrato común de los repositorios: la misma contra memoria y contra Postgres real.

``backend ∈ {memory, postgres}``. Ambos usan los codecs de producción (los registros son de la
carta de prueba ``c``, ``support.records``), así que los registros se comparan por su forma
canónica en bits. Incluye la concurrencia: N hilos ``claim`` → gana uno; D6 (una recalibración en
curso, una propuesta sin resolver) y aprobaciones concurrentes.
"""

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from psycopg_pool import ConnectionPool

from support import records as rec
from support.bits import canonical
from support.postgres import truncate_all
from voracious.application.ports import (
    DuplicateKeyError,
    RecordNotFoundError,
    VersionDecision,
    VersionStatusChange,
)
from voracious.application.records import (
    JobStatus,
    PipelineStep,
    ProposalRequest,
    RecalibrationMode,
    VersionStatus,
)
from voracious.infrastructure.memory import (
    ComparisonRecordCodec,
    ExclusionRecordCodec,
    FitRecordCodec,
    InMemoryComparisonRepository,
    InMemoryExclusionRepository,
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
    KeyedStore,
    LimitsRecordCodec,
    ModelRecordCodec,
    ModelVersionCodec,
    MonitoringRecordCodec,
    ObservationRecordCodec,
    PassthroughCodec,
    PipelineRecordCodec,
    RecalibrationRecordCodec,
    SignalAnnotationCodec,
    StructuralEventCodec,
)
from voracious.infrastructure.postgres import (
    PostgresComparisonRepository,
    PostgresDatasetStorage,
    PostgresExclusionRepository,
    PostgresFitRepository,
    PostgresLimitsRepository,
    PostgresModelRepository,
    PostgresModelVersionRepository,
    PostgresMonitoringRepository,
    PostgresObservationRepository,
    PostgresPipelineRepository,
    PostgresRecalibrationRepository,
    PostgresSignalAnnotationRepository,
    PostgresStructuralEventRepository,
)
from voracious.infrastructure.storage import DatasetIntegrityError, LocalMatrixStore

N_THREADS = 8
"""Hilos que compiten en las pruebas de concurrencia."""


class Backend:
    """Fábrica de repositorios de un backend (``memory`` o ``postgres``)."""

    def __init__(
        self, name: str, pool: ConnectionPool | None = None, url: str | None = None
    ) -> None:
        self.name = name
        self.pool = pool
        self.url = url

    def reset(self) -> None:
        """Deja el backend vacío (Postgres: ``TRUNCATE``; memoria: repos nuevos cada vez)."""
        if self.url is not None:
            truncate_all(self.url)

    def _make(
        self, memory: Callable[[object], object], postgres: Callable[..., object], codec: object
    ) -> object:
        if self.pool is None:
            return memory(codec)
        return postgres(self.pool, codec)

    def models(self) -> object:
        return self._make(
            InMemoryModelRepository, PostgresModelRepository, ModelRecordCodec(rec.CHARTS)
        )

    def monitorings(self) -> object:
        return self._make(
            InMemoryMonitoringRepository, PostgresMonitoringRepository, MonitoringRecordCodec()
        )

    def recalibrations(self) -> object:
        return self._make(
            InMemoryRecalibrationRepository,
            PostgresRecalibrationRepository,
            RecalibrationRecordCodec(rec.CHARTS),
        )

    def versions(self) -> object:
        return self._make(
            InMemoryModelVersionRepository,
            PostgresModelVersionRepository,
            ModelVersionCodec(rec.CHARTS),
        )

    def observations(self) -> object:
        return self._make(
            InMemoryObservationRepository, PostgresObservationRepository, ObservationRecordCodec()
        )

    def annotations(self) -> object:
        return self._make(
            InMemorySignalAnnotationRepository,
            PostgresSignalAnnotationRepository,
            SignalAnnotationCodec(),
        )

    def events(self) -> object:
        return self._make(
            InMemoryStructuralEventRepository,
            PostgresStructuralEventRepository,
            StructuralEventCodec(),
        )

    def fits(self) -> object:
        return self._make(InMemoryFitRepository, PostgresFitRepository, FitRecordCodec(rec.CHARTS))

    def limits(self) -> object:
        return self._make(
            InMemoryLimitsRepository, PostgresLimitsRepository, LimitsRecordCodec(rec.CHARTS)
        )

    def exclusions(self) -> object:
        return self._make(
            InMemoryExclusionRepository, PostgresExclusionRepository, ExclusionRecordCodec()
        )

    def pipelines(self) -> object:
        return self._make(
            InMemoryPipelineRepository, PostgresPipelineRepository, PipelineRecordCodec()
        )

    def comparisons(self) -> object:
        return self._make(
            InMemoryComparisonRepository,
            PostgresComparisonRepository,
            ComparisonRecordCodec(rec.CHARTS),
        )


@pytest.fixture(params=["memory", "postgres"])
def backend(request: pytest.FixtureRequest) -> Iterator[Backend]:
    if request.param == "memory":
        yield Backend("memory")
        return
    pool = request.getfixturevalue("pg_pool")
    yield Backend("postgres", pool, request.getfixturevalue("pg_url"))


def same(a: object, b: object) -> bool:
    """Igualdad en bits (los registros decodificados son objetos nuevos)."""
    return canonical(a) == canonical(b)


def same_list(a: list[Any], b: list[Any]) -> bool:
    return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))


@dataclass(frozen=True)
class Case:
    """Cómo crear, añadir y leer un registro de un repositorio."""

    name: str
    repo: Callable[[Backend], Any]
    make: Callable[[str], Any]
    add: Callable[[Any, Any], None]
    read: Callable[[Any, str], list[Any]]


def _one(value: object) -> list[object]:
    return [value] if value is not None else []


CASES = [
    Case(
        "models",
        Backend.models,
        lambda t: rec.model(t),
        lambda r, x: r.add(x),
        lambda r, t: _one(r.get(t, "c", "m")),
    ),
    Case(
        "monitorings",
        Backend.monitorings,
        lambda t: rec.monitoring(t),
        lambda r, x: r.add(x),
        lambda r, t: _one(r.get(t, "c", "m", "x")),
    ),
    Case(
        "recalibrations",
        Backend.recalibrations,
        lambda t: rec.recalibration(t),
        lambda r, x: r.add(x),
        lambda r, t: r.list(t, "c", "m"),
    ),
    Case(
        "versions",
        Backend.versions,
        lambda t: rec.version(t),
        lambda r, x: r.add(x),
        lambda r, t: r.list(t, "c", "m"),
    ),
    Case(
        "observations",
        Backend.observations,
        lambda t: rec.observation(t),
        lambda r, x: r.add_many([x]),
        lambda r, t: r.list(t, "c", "m"),
    ),
    Case(
        "annotations",
        Backend.annotations,
        lambda t: rec.annotation(t),
        lambda r, x: r.add(x),
        lambda r, t: r.history(t, "c", "m", "o"),
    ),
    Case(
        "events",
        Backend.events,
        lambda t: rec.event(t),
        lambda r, x: r.add(x),
        lambda r, t: r.list(t, "c", "m"),
    ),
    Case(
        "fits",
        Backend.fits,
        lambda t: rec.fit(t),
        lambda r, x: r.add(x),
        lambda r, t: _one(r.get(t, "c", "f")),
    ),
    Case(
        "limits",
        Backend.limits,
        lambda t: rec.limits(t),
        lambda r, x: r.add(x),
        lambda r, t: _one(r.get(t, "c", "l")),
    ),
    Case(
        "exclusions",
        Backend.exclusions,
        lambda t: rec.exclusion(t),
        lambda r, x: r.add(x),
        lambda r, t: _one(r.get(t, "c", "e")),
    ),
    Case(
        "pipelines",
        Backend.pipelines,
        lambda t: rec.pipeline(t),
        lambda r, x: r.add(x),
        lambda r, t: _one(r.get(t, "c", "p")),
    ),
    Case(
        "comparisons",
        Backend.comparisons,
        lambda t: rec.comparison(t),
        lambda r, x: r.add(x),
        lambda r, t: _one(r.get(t, "c", "m", "x")),
    ),
]

JOB_NAMES = {
    "models",
    "monitorings",
    "recalibrations",
    "fits",
    "limits",
    "exclusions",
    "pipelines",
    "comparisons",
}
JOB_CASES = [c for c in CASES if c.name in JOB_NAMES]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_add_read_and_tenant_isolation(backend: Backend, case: Case) -> None:
    repo = case.repo(backend)
    record = case.make("t")
    case.add(repo, record)
    assert same_list(case.read(repo, "t"), [record])
    assert case.read(repo, "otro") == []


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_duplicate_key_is_rejected(backend: Backend, case: Case) -> None:
    repo = case.repo(backend)
    case.add(repo, case.make("t"))
    with pytest.raises(DuplicateKeyError):
        case.add(repo, case.make("t"))
    case.add(repo, case.make("otro"))  # misma clave en otro tenant: es otro registro


def _claim(repo: object, name: str, tenant: str = "t") -> object:
    when = rec.T
    if name in {"models"}:
        return repo.claim(tenant, "c", "m", when)
    if name in {"monitorings", "comparisons"}:
        return repo.claim(tenant, "c", "m", "x", when)
    if name == "recalibrations":
        return repo.claim(tenant, "c", "m", "r", when)
    rid = {"fits": "f", "limits": "l", "exclusions": "e", "pipelines": "p"}[name]
    return repo.claim(tenant, "c", rid, when)


def _race[R](fn: Callable[[], R], n: int = N_THREADS) -> list[R]:
    """Lanza ``fn`` en ``n`` hilos a la vez (barrera) y devuelve los resultados."""
    barrier = threading.Barrier(n)
    out: list[R] = []
    lock = threading.Lock()
    errors: list[BaseException] = []

    def worker() -> None:
        barrier.wait()
        try:
            value = fn()
        except BaseException as exc:  # el hilo no debe tragarse un fallo del test
            errors.append(exc)
            return
        with lock:
            out.append(value)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    return out


@pytest.mark.parametrize("case", JOB_CASES, ids=lambda c: c.name)
def test_update_of_missing_record_raises(backend: Backend, case: Case) -> None:
    with pytest.raises(RecordNotFoundError):
        case.repo(backend).update(case.make("t"))


@pytest.mark.parametrize("case", JOB_CASES, ids=lambda c: c.name)
def test_update_replaces(backend: Backend, case: Case) -> None:
    repo = case.repo(backend)
    record = case.make("t")
    case.add(repo, record)
    done = replace(record, status=JobStatus.FAILED, error=rec.FAILED)
    repo.update(done)
    assert same_list(case.read(repo, "t"), [done])


@pytest.mark.parametrize("case", JOB_CASES, ids=lambda c: c.name)
def test_claim_is_queued_to_running_once(backend: Backend, case: Case) -> None:
    repo = case.repo(backend)
    assert _claim(repo, case.name) is None  # no existe
    case.add(repo, case.make("t"))
    assert _claim(repo, case.name, "otro") is None  # otro tenant
    running = _claim(repo, case.name)
    assert running.status is JobStatus.RUNNING
    assert running.started_at == rec.T
    assert case.read(repo, "t")[0].status is JobStatus.RUNNING
    assert _claim(repo, case.name) is None  # ya no está queued


@pytest.mark.parametrize("case", JOB_CASES, ids=lambda c: c.name)
def test_concurrent_claims_only_one_wins(backend: Backend, case: Case) -> None:
    for _ in range(5):
        backend.reset()
        repo = case.repo(backend)
        case.add(repo, case.make("t"))
        claims = _race(lambda repo=repo: _claim(repo, case.name))
        assert sum(r is not None for r in claims) == 1


@pytest.mark.parametrize("case", JOB_CASES, ids=lambda c: c.name)
def test_list_unfinished_spans_tenants(backend: Backend, case: Case) -> None:
    repo = case.repo(backend)
    case.add(repo, case.make("t"))
    case.add(repo, case.make("otro"))
    assert {r.tenant_id for r in repo.list_unfinished()} == {"t", "otro"}
    _claim(repo, case.name)
    assert len(repo.list_unfinished()) == 2  # running también
    for record in case.read(repo, "t") + case.read(repo, "otro"):
        repo.update(replace(record, status=JobStatus.SUCCEEDED))
    assert repo.list_unfinished() == []


def _recalibration_race(backend: Backend) -> list[bool]:
    repo = backend.recalibrations()
    ids = iter(f"r{i}" for i in range(N_THREADS))
    lock = threading.Lock()

    def add() -> bool:
        with lock:
            rid = next(ids)
        return bool(repo.add_if_none_in_progress(rec.recalibration(rid=rid)))

    return _race(add)


def _proposal_race(backend: Backend) -> list[bool]:
    repo = backend.versions()
    repo.add(rec.version())
    numbers = iter(range(1, N_THREADS + 1))
    lock = threading.Lock()

    def add() -> bool:
        with lock:
            number = next(numbers)
        version = rec.version(number=number, status=VersionStatus.PROPOSED)
        return bool(repo.add_proposal_if_none(version))

    return _race(add)


def test_recalibration_add_if_none_in_progress_is_atomic(backend: Backend) -> None:
    for _ in range(5):
        backend.reset()
        assert sorted(_recalibration_race(backend)) == [False] * (N_THREADS - 1) + [True]
    backend.reset()
    repo = backend.recalibrations()
    repo.add(rec.recalibration(rid="done", status=JobStatus.FAILED))
    assert repo.add_if_none_in_progress(rec.recalibration(rid="r"))
    assert not repo.add_if_none_in_progress(rec.recalibration(rid="r2"))
    assert not repo.add_if_none_in_progress(rec.recalibration(rid="r3", status=JobStatus.FAILED))
    assert repo.add_if_none_in_progress(rec.recalibration(tenant="otro", rid="r2"))
    finished = backend.recalibrations()
    backend.reset()
    finished.add(rec.recalibration(rid="done", status=JobStatus.FAILED))
    with pytest.raises(DuplicateKeyError):
        finished.add_if_none_in_progress(rec.recalibration(rid="done"))
    assert finished.add_if_none_in_progress(rec.recalibration(rid="old", status=JobStatus.FAILED))


def test_version_add_proposal_if_none_is_atomic(backend: Backend) -> None:
    for _ in range(5):
        backend.reset()
        assert sorted(_proposal_race(backend)) == [False] * (N_THREADS - 1) + [True]
    backend.reset()
    repo = backend.versions()
    with pytest.raises(ValueError, match="proposed"):
        repo.add_proposal_if_none(rec.version())
    repo.add(rec.version())
    with pytest.raises(DuplicateKeyError):
        repo.add_proposal_if_none(rec.version(status=VersionStatus.PROPOSED))


def _approve(number: int, decided_by: str) -> list[VersionStatusChange]:
    decision = VersionDecision(rec.T, decided_by, "ok", effective_from=rec.T)
    return [
        VersionStatusChange(
            "t", "c", "m", number, VersionStatus.PROPOSED, VersionStatus.ACTIVE, decision
        ),
        VersionStatusChange("t", "c", "m", 0, VersionStatus.ACTIVE, VersionStatus.SUPERSEDED),
    ]


def test_version_status_changes_are_all_or_nothing(backend: Backend) -> None:
    repo = backend.versions()
    repo.add(rec.version())
    repo.add(rec.version(number=1, status=VersionStatus.PROPOSED))
    approve, supersede = _approve(1, "ana")
    missing = VersionStatusChange("t", "c", "m", 7, VersionStatus.ACTIVE, VersionStatus.SUPERSEDED)
    assert not repo.apply_status_changes([approve, missing])
    assert repo.get("t", "c", "m", 1).status is VersionStatus.PROPOSED
    assert repo.apply_status_changes([])
    assert repo.apply_status_changes([approve, supersede])
    v1 = repo.get("t", "c", "m", 1)
    assert (v1.status, v1.approved_at, v1.decided_by) == (VersionStatus.ACTIVE, rec.T, "ana")
    assert v1.effective_from == rec.T
    assert repo.get("t", "c", "m", 0).status is VersionStatus.SUPERSEDED
    assert same(repo.get("t", "c", "m", 1).model, rec.version().model)  # contenido intacto
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
    assert repo.get("otro", "c", "m", 1) is None


def _approval_race(repo: object) -> list[bool]:
    names = iter(f"p{i}" for i in range(N_THREADS))
    lock = threading.Lock()

    def approve() -> bool:
        with lock:
            who = next(names)
        return bool(repo.apply_status_changes(_approve(1, who)))

    return _race(approve)


def test_concurrent_approvals_only_one_wins(backend: Backend) -> None:
    for _ in range(5):
        backend.reset()
        repo: Any = backend.versions()
        repo.add(rec.version())
        repo.add(rec.version(number=1, status=VersionStatus.PROPOSED))
        assert sum(_approval_race(repo)) == 1
        statuses = [v.status for v in repo.list("t", "c", "m")]
        assert statuses == [VersionStatus.SUPERSEDED, VersionStatus.ACTIVE]


def test_observation_queries(backend: Backend) -> None:
    repo = backend.observations()
    rows = [rec.observation(rid=f"o{i}", hours=i) for i in range(3)]
    rows[1] = replace(rows[1], signal=True, version_number=1)
    repo.add_many(list(reversed(rows)))
    with pytest.raises(DuplicateKeyError):
        repo.add_many([rec.observation(rid="n"), rec.observation(rid="n")])
    with pytest.raises(DuplicateKeyError):
        repo.add_many([rec.observation(rid="nuevo"), rec.observation(rid="o0")])
    assert repo.get("t", "c", "m", "n") is None  # nada guardado de los lotes fallidos
    assert repo.get("t", "c", "m", "nuevo") is None
    assert [r.observation_id for r in repo.list("t", "c", "m")] == ["o0", "o1", "o2"]
    assert [r.observation_id for r in repo.list("t", "c", "m", signals_only=True)] == ["o1"]
    window = repo.list(
        "t", "c", "m", observed_from=rows[1].observed_at, observed_to=rows[2].observed_at
    )
    assert [r.observation_id for r in window] == ["o1", "o2"]
    assert [r.observation_id for r in repo.list("t", "c", "m", observed_to=rows[0].observed_at)]
    assert repo.max_observed_at("t", "c", "m") == rows[2].observed_at
    assert repo.max_observed_at("otro", "c", "m") is None
    assert repo.count_scored_with("t", "c", "m", 1) == 1
    assert repo.count_scored_with("otro", "c", "m", 1) == 0


def test_observations_with_same_date_keep_insertion_order(backend: Backend) -> None:
    repo = backend.observations()
    repo.add_many([rec.observation(rid=r) for r in ("z", "a", "m")])
    assert [r.observation_id for r in repo.list("t", "c", "m")] == ["z", "a", "m"]


def test_annotations_latest_wins_and_events_sorted(backend: Backend) -> None:
    repo = backend.annotations()
    first, second = rec.annotation(rid="a1"), rec.annotation(rid="a2")
    repo.add(first)
    repo.add(second)
    repo.add(rec.annotation(rid="a3", obs="otra"))
    latest = repo.latest_for("t", "c", "m", ["o", "sin"])
    assert list(latest) == ["o"]
    assert same(latest["o"], second)
    assert repo.latest_for("otro", "c", "m", ["o"]) == {}
    assert repo.latest_for("t", "c", "m", []) == {}
    assert [a.annotation_id for a in repo.history("t", "c", "m", "o")] == ["a1", "a2"]
    events = backend.events()
    late = replace(rec.event(rid="late"), occurred_at=rec.T.replace(year=2027))
    events.add(late)
    events.add(rec.event(rid="early"))
    events.add(rec.event(rid="early2"))
    assert [e.event_id for e in events.list("t", "c", "m")] == ["early", "early2", "late"]


def test_pipeline_append_step_is_compare_and_set(backend: Backend) -> None:
    repo = backend.pipelines()
    repo.add(rec.pipeline())
    step = PipelineStep("fit", "f1")
    assert repo.append_step("t", "c", "p", 0, step) is None  # aún queued
    repo.claim("t", "c", "p", rec.T)
    assert repo.append_step("t", "c", "p", 1, step) is None  # cuenta errónea
    done = repo.append_step("t", "c", "p", 0, step)
    assert done.steps == (step,)
    assert repo.get("t", "c", "p").steps == (step,)
    assert repo.append_step("otro", "c", "p", 1, step) is None
    wins = _race(lambda: repo.append_step("t", "c", "p", 1, PipelineStep("limits", "l1")))
    assert sum(r is not None for r in wins) == 1
    assert len(repo.get("t", "c", "p").steps) == 2


def test_recalibration_session_transitions(backend: Backend) -> None:
    repo = backend.recalibrations()
    session = rec.recalibration(status=JobStatus.RUNNING, mode=RecalibrationMode.STEPWISE)
    repo.add(session)
    assert same(repo.find("t", "c", "r"), session)
    assert repo.find("otro", "c", "r") is None
    proposal = ProposalRequest("f", "l", None, JobStatus.QUEUED, rec.T)
    assert repo.claim_proposal("t", "c", "m", "r") is None  # sin propuesta
    asked = repo.request_proposal("t", "c", "m", "r", proposal)
    assert asked.proposal == proposal
    assert repo.request_proposal("t", "c", "m", "r", proposal) is None  # ya tiene una
    assert repo.cancel("t", "c", "m", "r", rec.T) is None  # con propuesta pedida
    claimed = _race(lambda: repo.claim_proposal("t", "c", "m", "r"))
    assert sum(r is not None for r in claimed) == 1
    assert repo.get("t", "c", "m", "r").proposal.status is JobStatus.RUNNING
    other = rec.recalibration(
        tenant="t2", status=JobStatus.RUNNING, mode=RecalibrationMode.STEPWISE
    )
    repo.add(other)
    cancelled = repo.cancel("t2", "c", "m", "r", rec.T)
    assert (cancelled.status, cancelled.finished_at) == (JobStatus.CANCELLED, rec.T)
    assert repo.cancel("t2", "c", "m", "r", rec.T) is None
    piped = rec.recalibration(tenant="t3", status=JobStatus.RUNNING)
    repo.add(piped)
    assert repo.cancel("t3", "c", "m", "r", rec.T) is None  # solo sesiones paso a paso


def test_datasets_keep_variables_dates_and_check_hash(backend: Backend, tmp_path: Path) -> None:
    if backend.pool is None:
        from voracious.infrastructure.storage import LocalDatasetStorage

        storage: Any = LocalDatasetStorage(tmp_path)
    else:
        storage = PostgresDatasetStorage(backend.pool, LocalMatrixStore(tmp_path))
    dated, plain = rec.dataset(rid="d1"), rec.dataset(rid="d2", dated=False)
    storage.add(dated)
    storage.add(plain)
    with pytest.raises(DuplicateKeyError):
        storage.add(dated)
    got = storage.get("t", "d1")
    assert same(got, dated)
    assert got.variables == ("a", "b")
    assert got.observed_at == dated.observed_at
    assert same(storage.get("t", "d2"), plain)
    assert storage.get("otro", "d1") is None
    assert storage.get("t", "nada") is None
    assert storage.get("t", "../x") is None
    with pytest.raises(ValueError, match="huella"):
        storage.add(replace(rec.dataset(rid="d3"), content_hash="sha256:mal"))
    assert storage.get("t", "d3") is None  # la transacción no dejó metadatos
    npy = tmp_path / "t" / "d1.npy"
    np.save(npy, np.zeros((3, 2)))
    with pytest.raises(DatasetIntegrityError, match="huella"):
        storage.get("t", "d1")
    npy.unlink()
    if backend.pool is not None:
        with pytest.raises(DatasetIntegrityError, match="falta la matriz"):
            storage.get("t", "d1")


def test_postgres_dataset_rows_hold_the_dates(pg_pool: ConnectionPool, tmp_path: Path) -> None:
    storage = PostgresDatasetStorage(pg_pool, LocalMatrixStore(tmp_path))
    record = rec.dataset(rid="d1")
    storage.add(record)
    with pg_pool.connection() as conn:
        rows = conn.execute(
            "SELECT row_index, observed_at FROM dataset_rows WHERE tenant_id = %s"
            " AND dataset_id = %s ORDER BY row_index",
            ("t", "d1"),
        ).fetchall()
        meta = conn.execute(
            "SELECT variables, n_rows, n_cols FROM datasets WHERE dataset_id = %s", ("d1",)
        ).fetchone()
    assert [r[1] for r in rows] == list(record.observed_at or ())
    assert meta == (["a", "b"], 3, 2)


def test_postgres_version_base_rows_hold_refs(pg_pool: ConnectionPool) -> None:
    repo = backend_versions = PostgresModelVersionRepository(pg_pool, ModelVersionCodec(rec.CHARTS))
    repo.add(rec.version())
    assert backend_versions.add_proposal_if_none(
        rec.version(number=1, status=VersionStatus.PROPOSED)
    )
    with pg_pool.connection() as conn:
        rows = conn.execute(
            "SELECT number, row_index, source, ref, observed_at FROM version_base_rows"
            " ORDER BY number, row_index"
        ).fetchall()
    assert [r[:4] for r in rows] == [
        (0, 0, "training", "0"),
        (0, 1, "observation", "o"),
        (1, 0, "training", "0"),
        (1, 1, "observation", "o"),
    ]
    assert rows[0][4] == rec.T
    assert rows[1][4] is None


def test_passthrough_codec_checks_type_and_store_items() -> None:
    codec = PassthroughCodec(int)
    assert codec.decode(codec.encode(3)) == 3
    with pytest.raises(TypeError, match="int"):
        codec.decode("x")
    store: KeyedStore[str, int] = KeyedStore(codec)
    store.put("a", 1)
    assert list(store.items()) == [("a", 1)]
    assert store.get("b") is None
    assert store.where(lambda v: v == 1) == [1]
