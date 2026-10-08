import dataclasses
from pathlib import Path

import pytest
import structlog

from voracious.application.errors import FitNotFoundError
from voracious.application.ports import JobKind, JobRequest
from voracious.application.use_cases import RunFitJob, RunLimitsJob
from voracious.config import Settings
from voracious.container import ConfigurationError, Container, build_container, oversubscribed
from voracious.domain.common import SerialTaskMapper
from voracious.infrastructure.clock import SystemClock
from voracious.infrastructure.ids import UuidIdGenerator
from voracious.infrastructure.memory import InMemoryDatasetStorage
from voracious.infrastructure.parallel import ProcessPoolTaskMapper
from voracious.infrastructure.storage import LocalDatasetStorage


@pytest.fixture(autouse=True)
def _reset_structlog() -> None:
    structlog.reset_defaults()


def test_build_container_uses_given_settings() -> None:
    settings = Settings(log_level="WARNING")
    assert build_container(settings).settings is settings


def test_build_container_reads_env_when_no_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_LOG_LEVEL", "ERROR")
    assert build_container().settings.log_level == "ERROR"


def test_container_wires_use_cases_and_handlers() -> None:
    container = build_container(Settings())
    try:
        assert set(container.charts) == {"t2mrcd"}
        assert set(container.handlers) == {
            JobKind.MRCD_FIT,
            JobKind.LIMITS,
            JobKind.DEPURATION,
            JobKind.MODEL_ASSEMBLY,
            JobKind.PIPELINE,
            JobKind.SCORE,
            JobKind.COMPARISON,
            JobKind.VERSION_PROPOSAL,
        }
        assert isinstance(container.use_cases.request_fit.ids, UuidIdGenerator)
        assert isinstance(container.use_cases.status.clock, SystemClock)
    finally:
        container.shutdown()


def test_mapper_is_serial_or_processes() -> None:
    serial = build_container(Settings())
    procs = build_container(Settings(replicate_processes=2, mrcd_threads=1))
    try:
        assert isinstance(_mapper_of(serial), SerialTaskMapper)
        mapper = _mapper_of(procs)
        assert isinstance(mapper, ProcessPoolTaskMapper)
        assert (mapper.max_workers, mapper.mrcd_threads) == (2, 1)
    finally:
        serial.shutdown()
        procs.shutdown()


def _mapper_of(container: Container) -> object:
    handler = container.handlers[JobKind.LIMITS]
    run = getattr(handler, "__self__", None)
    assert isinstance(run, RunLimitsJob)
    return run.mapper


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("job_backend", "celery", "JOB_BACKEND"),
        ("repository", "postgres", "REPOSITORY"),
        ("storage", "s3", "STORAGE"),
    ],
)
def test_unknown_adapter_fails_at_startup(field: str, value: str, match: str) -> None:
    settings = Settings.model_construct(**{**Settings().model_dump(), field: value})
    with pytest.raises(ConfigurationError, match=match):
        build_container(settings)


def test_oversubscription_warns(capsys: pytest.CaptureFixture[str]) -> None:
    assert not oversubscribed(Settings(), 8)
    assert not oversubscribed(Settings(replicate_processes=2), None)
    assert oversubscribed(Settings(replicate_processes=2), 8)  # hilos = todos los núcleos
    assert not oversubscribed(Settings(replicate_processes=2, mrcd_threads=4), 8)
    assert oversubscribed(Settings(replicate_processes=4, mrcd_threads=4), 8)
    # build_container configura structlog (JSON a stdout), así que se lee la salida.
    build_container(Settings(replicate_processes=64, mrcd_threads=64)).shutdown()
    assert '"event": "replicate_oversubscription"' in capsys.readouterr().out


def test_handle_dispatches_and_rejects_unknown_kind() -> None:
    container = build_container(Settings())
    try:
        with pytest.raises(FitNotFoundError):
            container.handle(JobRequest(JobKind.MRCD_FIT, "t", "t2mrcd", "nope"))
        without = dataclasses.replace(container, handlers={})
        with pytest.raises(ValueError, match="manejador"):
            without.handle(JobRequest(JobKind.MRCD_FIT, "t", "t2mrcd", "x"))
    finally:
        container.shutdown()


def test_charts_receive_mrcd_threads_and_repositories_encode_models() -> None:
    from voracious.infrastructure.memory import ModelRecordCodec

    container = build_container(Settings(mrcd_threads=2))
    try:
        chart = container.charts["t2mrcd"]
        assert getattr(chart, "mrcd_threads", None) == 2
        handler = container.handlers[JobKind.MRCD_FIT]
        run = getattr(handler, "__self__", None)
        assert isinstance(run, RunFitJob)
        assert getattr(run.steps["t2mrcd"], "chart", None) is chart
        model_store = getattr(container.use_cases.get_model.models, "_store", None)
        assert isinstance(getattr(model_store, "codec", None), ModelRecordCodec)
    finally:
        container.shutdown()


def test_local_storage_needs_a_directory(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="STORAGE_DIR"):
        build_container(Settings(storage="local"))
    container = build_container(Settings(storage="local", storage_dir=tmp_path / "ds"))
    try:
        storage = container.use_cases.upload_dataset.datasets
        assert isinstance(storage, LocalDatasetStorage)
        assert storage.base_dir == tmp_path / "ds"
    finally:
        container.shutdown()


def test_memory_storage_by_default() -> None:
    container = build_container(Settings())
    try:
        assert isinstance(container.use_cases.upload_dataset.datasets, InMemoryDatasetStorage)
    finally:
        container.shutdown()
