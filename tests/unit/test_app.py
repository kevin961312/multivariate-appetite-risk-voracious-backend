import pytest

from voracious.api.app import create_app
from voracious.config import Settings
from voracious.container import build_container


def test_create_app_stores_given_container() -> None:
    container = build_container(Settings(log_level="INFO"))
    app = create_app(container)
    assert app.state.container is container


def test_create_app_without_args_builds_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_LOG_LEVEL", "WARNING")
    app = create_app()
    assert app.state.container.settings.log_level == "WARNING"
