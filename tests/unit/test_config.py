from pathlib import Path

import pytest
from pydantic import ValidationError

from voracious.config import Settings


def test_log_level_default_is_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VORACIOUS_LOG_LEVEL", raising=False)
    assert Settings().log_level == "INFO"


def test_log_level_is_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_LOG_LEVEL", "DEBUG")
    assert Settings().log_level == "DEBUG"


def test_invalid_log_level_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_are_frozen() -> None:
    assert Settings.model_config.get("frozen") is True


def test_mrcd_threads_default_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VORACIOUS_MRCD_THREADS", raising=False)
    assert Settings().mrcd_threads is None


def test_mrcd_threads_empty_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_MRCD_THREADS", "")
    assert Settings().mrcd_threads is None


def test_mrcd_threads_is_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_MRCD_THREADS", "4")
    assert Settings().mrcd_threads == 4


@pytest.mark.parametrize("value", ["0", "-1", "dos"])
def test_invalid_mrcd_threads_raises(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("VORACIOUS_MRCD_THREADS", value)
    with pytest.raises(ValidationError):
        Settings()


def test_paso3_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "JOB_BACKEND",
        "REPOSITORY",
        "STORAGE",
        "REPLICATE_PROCESSES",
        "QUEUE_WORKERS_LIGHT",
        "MAX_UPLOAD_MB",
    ):
        monkeypatch.delenv(f"VORACIOUS_{name}", raising=False)
    s = Settings()
    assert (s.job_backend, s.repository, s.storage) == ("inline", "memory", "memory")
    assert s.replicate_processes is None
    assert (
        s.queue_workers_estimation,
        s.queue_workers_calibration,
        s.queue_workers_light,
        s.queue_workers_orchestration,
    ) == (1, 1, 4, 2)
    assert s.max_upload_mb >= 1


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JOB_BACKEND", "celery"),
        ("REPOSITORY", "mongo"),
        ("DATABASE_POOL_SIZE", "0"),
        ("STORAGE", "s3"),
        ("REPLICATE_PROCESSES", "0"),
        ("QUEUE_WORKERS_LIGHT", "0"),
        ("MAX_UPLOAD_MB", "0"),
    ],
)
def test_invalid_paso3_values_fail(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(f"VORACIOUS_{name}", value)
    with pytest.raises(ValidationError):
        Settings()


def test_replicate_processes_is_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_REPLICATE_PROCESSES", "3")
    assert Settings().replicate_processes == 3


def test_storage_dir_is_read_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VORACIOUS_STORAGE", "local")
    monkeypatch.setenv("VORACIOUS_STORAGE_DIR", str(tmp_path))
    s = Settings()
    assert (s.storage, s.storage_dir) == ("local", tmp_path)
    assert Settings.model_construct().storage_dir is None


def test_database_url_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql://usuario:clave-muy-secreta@db:5432/voracious"
    monkeypatch.setenv("VORACIOUS_REPOSITORY", "postgres")
    monkeypatch.setenv("VORACIOUS_DATABASE_URL", url)
    monkeypatch.setenv("VORACIOUS_DATABASE_POOL_SIZE", "3")
    settings = Settings()
    assert settings.repository == "postgres"
    assert settings.database_pool_size == 3
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value() == url
    assert "clave-muy-secreta" not in repr(settings)
    assert "clave-muy-secreta" not in str(settings)
