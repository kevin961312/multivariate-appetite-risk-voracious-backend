import pytest
from fastapi.testclient import TestClient

from support.auth import JWKS_FILE, TEST_AUDIENCE, TEST_ISSUER, auth_settings
from support.routes import EXPECTED_ROUTES
from voracious.api.app import create_app
from voracious.application.ports import JobKind, JobRequest
from voracious.config import Settings
from voracious.container import ConfigurationError, build_container


def test_create_app_stores_given_container() -> None:
    container = build_container(auth_settings(log_level="INFO"))
    app = create_app(container)
    assert app.state.container is container


def test_create_app_without_args_builds_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("VORACIOUS_JWT_JWKS_FILE", str(JWKS_FILE))
    monkeypatch.setenv("VORACIOUS_JWT_ISSUER", TEST_ISSUER)
    monkeypatch.setenv("VORACIOUS_JWT_AUDIENCE", TEST_AUDIENCE)
    app = create_app()
    assert app.state.container.settings.log_level == "WARNING"
    assert app.state.container.token_verifier is not None


def test_the_api_does_not_start_without_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falla cerrado: sin JWKS no hay modo «sin autenticación» (D1)."""
    with pytest.raises(ConfigurationError, match="VORACIOUS_JWT_JWKS_FILE"):
        create_app(build_container(Settings()))
    monkeypatch.delenv("VORACIOUS_JWT_JWKS_FILE", raising=False)
    with pytest.raises(ConfigurationError, match="VORACIOUS_JWT_ISSUER"):
        create_app()


def test_route_snapshot() -> None:
    schema = create_app(build_container(auth_settings())).openapi()
    routes = [(method.upper(), path) for path, ops in schema["paths"].items() for method in ops]
    assert sorted(routes) == sorted(EXPECTED_ROUTES)
    tags = {t["name"] for t in schema["tags"]}
    used = {tag for ops in schema["paths"].values() for op in ops.values() for tag in op["tags"]}
    assert used == tags


def test_lifespan_shuts_the_queue_down() -> None:
    container = build_container(auth_settings())
    with TestClient(create_app(container)):
        container.queue.enqueue(JobRequest(JobKind.MRCD_FIT, "t", "t2mrcd", "nope"))
    with pytest.raises(RuntimeError):
        container.queue.enqueue(JobRequest(JobKind.MRCD_FIT, "t", "t2mrcd", "nope"))
