import json
from collections.abc import Iterator

import pytest
import structlog

from voracious.infrastructure.logging import configure_logging


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()


def test_emits_json_line_with_event_level_timestamp(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    structlog.get_logger().info("hello", tenant="t1")

    line = capsys.readouterr().out.strip()
    record = json.loads(line)
    assert record["event"] == "hello"
    assert record["level"] == "info"
    assert record["tenant"] == "t1"
    assert "timestamp" in record


def test_filters_below_configured_level(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING")
    structlog.get_logger().info("hidden")
    assert capsys.readouterr().out == ""


def test_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    configure_logging("INFO")
    structlog.get_logger().info("once")
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1


def test_unknown_level_raises() -> None:
    with pytest.raises(ValueError, match="desconocido"):
        configure_logging("VERBOSE")
