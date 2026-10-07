import pytest
import structlog

from voracious.config import Settings
from voracious.container import build_container


@pytest.fixture(autouse=True)
def _reset_structlog() -> None:
    structlog.reset_defaults()


def test_build_container_uses_given_settings() -> None:
    settings = Settings(log_level="WARNING")
    assert build_container(settings).settings is settings


def test_build_container_reads_env_when_no_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_LOG_LEVEL", "ERROR")
    assert build_container().settings.log_level == "ERROR"
