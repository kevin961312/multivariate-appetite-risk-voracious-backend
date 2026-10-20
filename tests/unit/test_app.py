import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from support.auth import JWKS_FILE, TEST_AUDIENCE, TEST_ISSUER, auth_settings
from support.routes import EXPECTED_ROUTES
from voracious.api.access_log import AccessLogMiddleware
from voracious.api.app import create_app
from voracious.api.auth import PROBE_PATHS, PUBLIC_PATHS, AuthenticationMiddleware
from voracious.api.errors import ErrorBoundaryMiddleware
from voracious.api.rate_limit import RateLimitMiddleware
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


# --- paso E: pila de middlewares, 429 en el OpenAPI y arranque de la imagen ---------------------

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


def _stack(**overrides: object) -> list[tuple[type, dict[str, object]]]:
    app = create_app(build_container(auth_settings(**overrides)))
    return [(m.cls, dict(m.kwargs)) for m in app.user_middleware]  # de fuera adentro


def test_the_middleware_stack_from_outside_in() -> None:
    stack = _stack(
        trusted_proxies="172.29.80.10,10.0.0.0/8",
        cors_allowed_origins="http://localhost:5173",
        rate_limit_per_minute=60,
        rate_limit_burst=7,
    )
    assert [cls for cls, _ in stack] == [
        ProxyHeadersMiddleware,
        AccessLogMiddleware,
        CORSMiddleware,
        ErrorBoundaryMiddleware,
        RateLimitMiddleware,
        AuthenticationMiddleware,
    ]
    kwargs = dict(stack)
    assert kwargs[ProxyHeadersMiddleware] == {"trusted_hosts": ["172.29.80.10/32", "10.0.0.0/8"]}
    assert kwargs[CORSMiddleware] == {
        "allow_origins": ("http://localhost:5173",),
        "allow_methods": ("GET", "POST"),
        "allow_headers": ("Authorization", "Content-Type"),
        "expose_headers": ("Retry-After", "WWW-Authenticate"),
        "allow_credentials": False,
        "max_age": 600,
    }
    assert kwargs[RateLimitMiddleware] == {"per_minute": 60, "burst": 7}
    assert kwargs[AuthenticationMiddleware]["public_paths"] == PUBLIC_PATHS
    assert kwargs[AccessLogMiddleware]["public_paths"] == PUBLIC_PATHS


def test_without_proxies_nor_origins_those_layers_are_absent() -> None:
    stack = _stack(api_docs=False)
    assert [cls for cls, _ in stack] == [
        AccessLogMiddleware,
        ErrorBoundaryMiddleware,
        RateLimitMiddleware,
        AuthenticationMiddleware,
    ]
    kwargs = dict(stack)
    assert kwargs[AuthenticationMiddleware]["public_paths"] == PROBE_PATHS
    assert kwargs[AccessLogMiddleware]["public_paths"] == PROBE_PATHS


def test_the_star_reaches_cors_as_any_origin() -> None:
    kwargs = dict(_stack(cors_allowed_origins="*"))
    assert kwargs[CORSMiddleware]["allow_origins"] == ("*",)
    assert kwargs[CORSMiddleware]["allow_credentials"] is False


def test_every_operation_declares_429() -> None:
    schema = create_app(build_container(auth_settings())).openapi()
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            declared = operation["responses"].get("429")
            assert declared is not None, (method, path)
            ref = declared["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/ErrorResponse"), (method, path)
            assert "Retry-After" in declared["headers"], (method, path)


def test_the_image_runs_uvicorn_behind_the_proxy_without_its_own_headers() -> None:
    cmd = next(
        json.loads(line.removeprefix("CMD "))
        for line in DOCKERFILE.read_text(encoding="utf-8").splitlines()
        if line.startswith('CMD ["uvicorn"')
    )
    assert cmd[:3] == ["uvicorn", "voracious.api.app:create_app", "--factory"]
    for flag in ("--no-proxy-headers", "--no-server-header", "--no-access-log"):
        assert flag in cmd
    assert cmd[cmd.index("--workers") + 1] == "1"
    assert cmd[cmd.index("--timeout-keep-alive") + 1] == "75"
