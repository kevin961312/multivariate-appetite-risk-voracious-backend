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
