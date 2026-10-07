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
