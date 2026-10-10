"""Postgres real: ida y vuelta en bits, migraciones, recuperación y punto de entrada ``cli``."""

import threading
from dataclasses import replace
from typing import Any

import numpy as np
import psycopg
import pytest
from psycopg_pool import ConnectionPool

from support import records as rec
from support.bits import canonical
from support.postgres import admin_url, temporary_database
from voracious import cli
from voracious.application.records import (
    ErrorInfo,
    JobStatus,
    ProposalRequest,
    RecalibrationMode,
)
from voracious.application.use_cases import JOB_INTERRUPTED, RecoverInterruptedJobs
from voracious.infrastructure.clock import SystemClock
from voracious.infrastructure.memory import (
    ComparisonRecordCodec,
    ExclusionRecordCodec,
    FitRecordCodec,
    LimitsRecordCodec,
    ModelRecordCodec,
    ModelVersionCodec,
    MonitoringRecordCodec,
    ObservationRecordCodec,
    PipelineRecordCodec,
    RecalibrationRecordCodec,
)
from voracious.infrastructure.postgres import (
    Migration,
    MigrationChecksumError,
    PayloadFormatError,
    PostgresComparisonRepository,
    PostgresExclusionRepository,
    PostgresFitRepository,
    PostgresLimitsRepository,
    PostgresModelRepository,
    PostgresModelVersionRepository,
    PostgresMonitoringRepository,
    PostgresObservationRepository,
    PostgresPipelineRepository,
    PostgresRecalibrationRepository,
    bundled_migrations,
    database_ready,
    dump_payload,
    load_payload,
    migrate,
)

SPECIAL = [-0.0, float("nan"), float("inf"), float("-inf"), 5e-324, 2.2250738585072014e-308, 1e308]
"""Reales que JSONB no conserva (``-0``, ``NaN``, ``±Inf``) y extremos (subnormales, 1e308)."""


def _bits(values: list[float]) -> list[str]:
    return [v.hex() for v in values]


def test_payload_json_keeps_every_bit() -> None:
    stored = {"x": SPECIAL, "n": 3, "s": "ñ", "z": None}
    loaded = load_payload(dump_payload(stored), 1, "t")
    assert isinstance(loaded, dict)
    assert _bits(loaded["x"]) == _bits(SPECIAL)
    assert {k: loaded[k] for k in ("n", "s", "z")} == {"n": 3, "s": "ñ", "z": None}
    with pytest.raises(PayloadFormatError, match="format_version"):
        load_payload("{}", 2, "t")


def test_special_floats_round_trip_through_postgres(pg_pool: ConnectionPool) -> None:
    fits = PostgresFitRepository(pg_pool, FitRecordCodec(rec.CHARTS))
    fit = replace(
        rec.fit(),
        params={"x": list(SPECIAL), "nested": {"y": [-0.0]}},
        result=rec.StubModel(-0.0),
        error=ErrorInfo("E", "m", {"v": float("nan")}),
    )
    fits.add(fit)
    got = fits.get("t", "c", "f")
    assert _bits(got.params["x"]) == _bits(SPECIAL)
    assert _bits(got.params["nested"]["y"]) == _bits([-0.0])
    assert got.result.value.hex() == (-0.0).hex()
    assert np.isnan(got.error.details["v"])

    models = PostgresModelRepository(pg_pool, ModelRecordCodec(rec.CHARTS))
    matrix = np.array([SPECIAL, SPECIAL[::-1]], dtype=np.float64)
    models.add(replace(rec.model(), training_data=matrix))
    assert models.get("t", "c", "m").training_data.tobytes() == matrix.tobytes()

    observations = PostgresObservationRepository(pg_pool, ObservationRecordCodec())
    values = np.array(SPECIAL, dtype=np.float64)
    for i, t2 in enumerate(SPECIAL):
        observations.add_many(
            [replace(rec.observation(rid=f"o{i}", hours=i), values=values, t2=t2, limit=-t2)]
        )
    got_obs = observations.list("t", "c", "m")
    assert [o.t2.hex() for o in got_obs] == _bits(SPECIAL)
    assert [o.limit.hex() for o in got_obs] == _bits([-v for v in SPECIAL])
    assert all(o.values.tobytes() == values.tobytes() for o in got_obs)
    with pg_pool.connection() as conn:
        column = conn.execute(
            "SELECT observed_values, t2 FROM observations WHERE observation_id = 'o0'"
        ).fetchone()
    assert _bits(column[0]) == _bits(SPECIAL)  # float8[] también (-0, NaN e infinitos)
    assert str(column[1]) == "-0.0"


def test_other_job_records_round_trip(pg_pool: ConnectionPool) -> None:
    pairs: list[tuple[Any, Any]] = [
        (PostgresLimitsRepository(pg_pool, LimitsRecordCodec(rec.CHARTS)), rec.limits()),
        (PostgresExclusionRepository(pg_pool, ExclusionRecordCodec()), rec.exclusion()),
        (PostgresPipelineRepository(pg_pool, PipelineRecordCodec()), rec.pipeline()),
        (PostgresMonitoringRepository(pg_pool, MonitoringRecordCodec()), rec.monitoring()),
        (
            PostgresComparisonRepository(pg_pool, ComparisonRecordCodec(rec.CHARTS)),
            replace(rec.comparison(), result=rec.StubModel(float("inf"))),
        ),
    ]
    for repo, record in pairs:
        repo.add(record)
        done = replace(record, status=JobStatus.FAILED, error=rec.FAILED)
        repo.update(done)
    assert canonical(pairs[0][0].get("t", "c", "l")) == canonical(
        replace(pairs[0][1], status=JobStatus.FAILED, error=rec.FAILED)
    )


# --- migraciones ----------------------------------------------------------------------------


def _tables(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {str(r[0]) for r in rows.fetchall()}


def test_migrations_apply_once_and_are_idempotent() -> None:
    with temporary_database(admin_url()) as url:
        assert migrate(url) == [m.version for m in bundled_migrations()]
        assert migrate(url) == []  # dos veces: no-op
        assert {"schema_migrations", "models", "observations", "dataset_rows"} <= _tables(url)


def test_concurrent_migrations_apply_once() -> None:
    with temporary_database(admin_url()) as url:
        results: list[list[str]] = []
        lock = threading.Lock()
        barrier = threading.Barrier(4)

        def run() -> None:
            barrier.wait()
            applied = migrate(url)
            with lock:
                results.append(applied)

        threads = [threading.Thread(target=run) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(len(r) for r in results) == [0, 0, 0, len(bundled_migrations())]
        with psycopg.connect(url) as conn:
            count = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()
        assert count == (len(bundled_migrations()),)


def test_changed_migration_is_an_error_and_failed_one_rolls_back() -> None:
    first = Migration("0001", "0001_a.sql", b"CREATE TABLE a (x INT);")
    with temporary_database(admin_url()) as url:
        assert migrate(url, [first]) == ["0001"]
        edited = Migration("0001", "0001_a.sql", b"CREATE TABLE a (x BIGINT);")
        with pytest.raises(MigrationChecksumError, match=r"0001_a\.sql"):
            migrate(url, [edited])
        broken = Migration("0002", "0002_b.sql", b"CREATE TABLE b (x INT); SELECT 1/0;")
        with pytest.raises(psycopg.errors.DivisionByZero):
            migrate(url, [first, broken])
        assert "b" not in _tables(url)  # su transacción se deshizo
        ok = Migration("0002", "0002_b.sql", b"CREATE TABLE b (x INT);")
        assert migrate(url, [first, ok]) == ["0002"]


def test_bundled_migrations_are_well_named() -> None:
    names = [m.name for m in bundled_migrations()]
    assert names[0] == "0001_initial.sql"
    assert names == sorted(names)
    assert all(len(m.checksum) == 64 for m in bundled_migrations())


# --- recuperación de trabajos interrumpidos -------------------------------------------------


def test_interrupted_jobs_fail_and_open_sessions_survive(pg_pool: ConnectionPool) -> None:
    fits = PostgresFitRepository(pg_pool, FitRecordCodec(rec.CHARTS))
    limits = PostgresLimitsRepository(pg_pool, LimitsRecordCodec(rec.CHARTS))
    exclusions = PostgresExclusionRepository(pg_pool, ExclusionRecordCodec())
    pipelines = PostgresPipelineRepository(pg_pool, PipelineRecordCodec())
    models = PostgresModelRepository(pg_pool, ModelRecordCodec(rec.CHARTS))
    monitorings = PostgresMonitoringRepository(pg_pool, MonitoringRecordCodec())
    recalibrations = PostgresRecalibrationRepository(pg_pool, RecalibrationRecordCodec(rec.CHARTS))
    comparisons = PostgresComparisonRepository(pg_pool, ComparisonRecordCodec(rec.CHARTS))
    fits.add(rec.fit())
    fits.claim("t", "c", "f", rec.T)  # running
    fits.add(rec.fit(rid="ok", status=JobStatus.SUCCEEDED))
    limits.add(rec.limits())
    exclusions.add(rec.exclusion())
    pipelines.add(rec.pipeline())
    models.add(rec.model())
    monitorings.add(rec.monitoring(tenant="otro"))
    comparisons.add(rec.comparison())
    stepwise = RecalibrationMode.STEPWISE
    recalibrations.add(rec.recalibration(rid="open", status=JobStatus.RUNNING, mode=stepwise))
    recalibrations.add(
        replace(
            rec.recalibration(tenant="t2", rid="asked", status=JobStatus.RUNNING, mode=stepwise),
            proposal=ProposalRequest("f", "l", None, JobStatus.QUEUED, rec.T),
        )
    )
    recalibrations.add(rec.recalibration(tenant="t3", rid="piped"))
    recovery = RecoverInterruptedJobs(
        fits,
        limits,
        exclusions,
        pipelines,
        models,
        monitorings,
        recalibrations,
        comparisons,
        PostgresModelVersionRepository(pg_pool, ModelVersionCodec(rec.CHARTS)),
        SystemClock(),
    )
    counts = recovery.execute()
    assert counts == {
        "fits": 1,
        "limits": 1,
        "exclusions": 1,
        "pipelines": 1,
        "models": 1,
        "scores": 1,
        "recalibrations": 2,
        "comparisons": 1,
        "versions": 0,
    }
    failed = fits.get("t", "c", "f")
    assert failed.status is JobStatus.FAILED
    assert failed.error.code == JOB_INTERRUPTED
    assert failed.error.details == {"previous_status": "running"}
    assert failed.finished_at is not None
    assert fits.get("t", "c", "ok").status is JobStatus.SUCCEEDED
    assert models.get("t", "c", "m").error.details == {"previous_status": "queued"}
    assert recalibrations.get("t", "c", "m", "open").status is JobStatus.RUNNING  # respetada
    asked = recalibrations.get("t2", "c", "m", "asked")
    assert asked.status is JobStatus.FAILED
    assert asked.proposal.status is JobStatus.FAILED
    assert recalibrations.get("t3", "c", "m", "piped").error.code == JOB_INTERRUPTED
    assert recovery.execute() == dict.fromkeys(counts, 0)  # nada más que cerrar


def test_database_ready(pg_pool: ConnectionPool) -> None:
    assert database_ready(pg_pool)


# --- cli --------------------------------------------------------------------------------------


def test_cli_migrate(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    with temporary_database(admin_url()) as url:
        monkeypatch.setenv("VORACIOUS_REPOSITORY", "postgres")
        monkeypatch.setenv("VORACIOUS_DATABASE_URL", url)
        assert cli.main(["migrate"]) == 0
        assert "0001" in capsys.readouterr().out
        assert cli.main(["migrate"]) == 0
        out = capsys.readouterr().out
        assert "al día" in out
        assert url not in out  # la URL (con credenciales) nunca se imprime


def test_cli_migrate_needs_postgres(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("VORACIOUS_REPOSITORY", "memory")
    assert cli.main(["migrate"]) == 2
    assert "VORACIOUS_REPOSITORY=postgres" in capsys.readouterr().err
    monkeypatch.setenv("VORACIOUS_REPOSITORY", "postgres")
    monkeypatch.delenv("VORACIOUS_DATABASE_URL", raising=False)
    assert cli.main(["migrate"]) == 2
    assert "VORACIOUS_DATABASE_URL" in capsys.readouterr().err
