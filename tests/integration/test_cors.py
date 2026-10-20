"""CORS para un front en navegador (paso E, E14) y la barrera de errores dentro de CORS.

Dos modos: lista de orígenes (cada uno validado) y ``*`` (cualquier origen; decisión del dueño del
2026-10-20). En los dos el *preflight* se resuelve antes del límite de peticiones y de la
autenticación, y toda respuesta de la aplicación (``401``, ``404``, ``429`` y ``500``) lleva las
cabeceras de CORS.
"""

import asyncio
from collections.abc import Iterator

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from support.api import DATASETS
from support.auth import auth_settings, bearer
from voracious.api.access_log import ACCESS_EVENT
from voracious.api.app import create_app
from voracious.api.errors import UNHANDLED_EXCEPTION_EVENT, ErrorBoundaryMiddleware
from voracious.container import build_container

ALLOWED = "http://localhost:5173"
OTHER_ALLOWED = "http://localhost:3000"
EVIL = "https://evil.example"
BOOM = "/v1/boom"


def _app(origins: str | None, **overrides: object) -> FastAPI:
    """Aplicación real con una ruta extra que falla (``GET /v1/boom``, con token)."""
    settings = auth_settings(cors_allowed_origins=origins or "", **overrides)
    app = create_app(build_container(settings))

    @app.get(BOOM)
    def boom() -> None:
        msg = "traza secreta"
        raise RuntimeError(msg)

    return app


@pytest.fixture(scope="module")
def listed() -> Iterator[TestClient]:
    with TestClient(_app(f"{ALLOWED},{OTHER_ALLOWED}")) as client:
        yield client


@pytest.fixture(scope="module")
def anyone() -> Iterator[TestClient]:
    with TestClient(_app("*")) as client:
        yield client


@pytest.fixture(scope="module")
def closed() -> Iterator[TestClient]:
    with TestClient(_app(None)) as client:
        yield client


def _preflight(
    client: TestClient,
    origin: str,
    *,
    path: str = DATASETS,
    method: str = "POST",
    headers: str = "authorization,content-type",
) -> dict[str, str]:
    response = client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )
    return {"status": str(response.status_code), **response.headers}


def _listed(value: str) -> set[str]:
    return {part.strip().lower() for part in value.split(",")}


# --- modo lista ----------------------------------------------------------------------------------


@pytest.mark.parametrize("origin", [ALLOWED, OTHER_ALLOWED])
def test_a_preflight_from_an_allowed_origin(listed: TestClient, origin: str) -> None:
    got = _preflight(listed, origin)
    assert got["status"] == "200"
    assert got["access-control-allow-origin"] == origin
    assert {"get", "post"} <= _listed(got["access-control-allow-methods"])
    assert {"authorization", "content-type"} <= _listed(got["access-control-allow-headers"])
    assert got["access-control-max-age"] == "600"
    assert "access-control-allow-credentials" not in got
    assert "origin" in _listed(got["vary"])


def test_a_preflight_from_another_origin_is_400_without_acao(listed: TestClient) -> None:
    got = _preflight(listed, EVIL)
    assert got["status"] == "400"
    assert "access-control-allow-origin" not in got


@pytest.mark.parametrize(
    ("method", "headers"),
    [("POST", "authorization,x-tenant-id"), ("POST", "cookie"), ("DELETE", "authorization")],
)
def test_a_preflight_with_a_header_or_method_not_allowed_is_400(
    listed: TestClient, method: str, headers: str
) -> None:
    assert _preflight(listed, ALLOWED, method=method, headers=headers)["status"] == "400"


def test_a_401_carries_cors_only_for_an_allowed_origin(listed: TestClient) -> None:
    allowed = listed.get(f"{DATASETS}/nope", headers={"Origin": ALLOWED})
    assert allowed.status_code == 401
    assert allowed.headers["access-control-allow-origin"] == ALLOWED
    exposed = _listed(allowed.headers["access-control-expose-headers"])
    assert {"www-authenticate", "retry-after"} <= exposed
    assert "origin" in _listed(allowed.headers["vary"])
    assert "access-control-allow-credentials" not in allowed.headers
    other = listed.get(f"{DATASETS}/nope", headers={"Origin": EVIL})
    assert other.status_code == 401
    assert "access-control-allow-origin" not in other.headers


def test_a_4xx_with_a_token_carries_cors(listed: TestClient) -> None:
    response = listed.get(f"{DATASETS}/nope", headers={"Origin": ALLOWED, **bearer()})
    assert response.status_code == 404
    assert response.json()["code"] == "DATASET_NOT_FOUND"
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_an_unexpected_error_is_a_uniform_500_with_cors(listed: TestClient) -> None:
    with structlog.testing.capture_logs() as logs:
        response = listed.get(BOOM, headers={"Origin": ALLOWED, **bearer()})
    assert response.status_code == 500
    assert response.json() == {"code": "INTERNAL_ERROR", "message": "error interno", "details": {}}
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "traza secreta" not in response.text
    assert [e["event"] for e in logs].count(UNHANDLED_EXCEPTION_EVENT) == 1
    assert [e["status"] for e in logs if e["event"] == ACCESS_EVENT] == [500]


def test_a_plain_options_is_not_opened_by_cors(listed: TestClient) -> None:
    """Sin ``Access-Control-Request-Method`` no es un *preflight*: exige token como todo."""
    bare = listed.options(DATASETS)
    assert bare.status_code == 401
    assert bare.json()["details"] == {"reason": "missing_token"}
    with_origin = listed.options(DATASETS, headers={"Origin": ALLOWED})
    assert with_origin.status_code == 401
    assert with_origin.headers["access-control-allow-origin"] == ALLOWED


def test_preflights_spend_no_quota_and_429_carries_cors() -> None:
    app = _app(ALLOWED, rate_limit_per_minute=1, rate_limit_burst=1)
    with TestClient(app, client=("203.0.113.7", 50000)) as client:
        assert {_preflight(client, ALLOWED)["status"] for _ in range(10)} == {"200"}
        first = client.get(f"{DATASETS}/nope", headers={"Origin": ALLOWED})
        limited = client.get(f"{DATASETS}/nope", headers={"Origin": ALLOWED})
    assert first.status_code == 401
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
    assert limited.headers["access-control-allow-origin"] == ALLOWED
    assert "retry-after" in _listed(limited.headers["access-control-expose-headers"])


def test_preflights_go_to_the_access_log_at_debug() -> None:
    client = TestClient(_app(ALLOWED, log_level="DEBUG"))
    with structlog.testing.capture_logs() as logs:
        _preflight(client, ALLOWED)
        client.get(f"{DATASETS}/nope", headers={"Origin": ALLOWED})
    access = [e for e in logs if e["event"] == ACCESS_EVENT]
    assert [(e["method"], e["status"], e["log_level"]) for e in access] == [
        ("OPTIONS", 200, "debug"),
        ("GET", 401, "info"),
    ]
    assert access[0]["route"] == DATASETS


# --- modo «cualquier origen» ---------------------------------------------------------------------


@pytest.mark.parametrize("origin", [EVIL, ALLOWED, "https://front.cualquiera.example:8443"])
def test_with_a_star_a_preflight_from_any_origin_is_allowed(
    anyone: TestClient, origin: str
) -> None:
    got = _preflight(anyone, origin)
    assert got["status"] == "200"
    assert got["access-control-allow-origin"] == "*"
    assert {"get", "post"} <= _listed(got["access-control-allow-methods"])
    assert {"authorization", "content-type"} <= _listed(got["access-control-allow-headers"])
    assert got["access-control-max-age"] == "600"
    assert "access-control-allow-credentials" not in got


def test_with_a_star_the_header_and_method_lists_still_apply(anyone: TestClient) -> None:
    assert _preflight(anyone, EVIL, headers="authorization,x-tenant-id")["status"] == "400"
    assert _preflight(anyone, EVIL, method="DELETE")["status"] == "400"


def test_with_a_star_401_and_500_carry_acao_star(anyone: TestClient) -> None:
    unauthenticated = anyone.get(f"{DATASETS}/nope", headers={"Origin": EVIL})
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["access-control-allow-origin"] == "*"
    exposed = _listed(unauthenticated.headers["access-control-expose-headers"])
    assert {"www-authenticate", "retry-after"} <= exposed
    broken = anyone.get(BOOM, headers={"Origin": EVIL, **bearer()})
    assert broken.status_code == 500
    assert broken.json()["code"] == "INTERNAL_ERROR"
    assert broken.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in broken.headers


# --- CORS cerrado (por defecto) ------------------------------------------------------------------


def test_without_origins_there_are_no_cors_headers(closed: TestClient) -> None:
    preflight = _preflight(closed, ALLOWED)
    assert preflight["status"] == "401"  # sin CORS no hay preflight: exige token
    assert "access-control-allow-origin" not in preflight
    response = closed.get(f"{DATASETS}/nope", headers={"Origin": ALLOWED, **bearer()})
    assert response.status_code == 404
    assert not any(name.startswith("access-control-") for name in response.headers)
    broken = closed.get(BOOM, headers=bearer())
    assert (broken.status_code, broken.json()["code"]) == (500, "INTERNAL_ERROR")


# --- la barrera de errores por ASGI directo ----------------------------------------------------


def _run(app: ErrorBoundaryMiddleware, kind: str = "http") -> list[Message]:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app({"type": kind, "path": "/x", "headers": []}, receive, send))
    return sent


def test_the_boundary_rethrows_once_the_response_has_started() -> None:
    async def half(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        msg = "a mitad"
        raise RuntimeError(msg)

    with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError, match="a mitad"):
        _run(ErrorBoundaryMiddleware(half))
    assert [e["event"] for e in logs] == [UNHANDLED_EXCEPTION_EVENT]


def test_the_boundary_answers_500_before_the_response_starts() -> None:
    async def broken(scope: Scope, receive: Receive, send: Send) -> None:
        msg = "antes"
        raise ValueError(msg)

    with structlog.testing.capture_logs() as logs:
        sent = _run(ErrorBoundaryMiddleware(broken))
    assert sent[0]["status"] == 500
    assert b"INTERNAL_ERROR" in sent[1]["body"]
    assert [e["event"] for e in logs] == [UNHANDLED_EXCEPTION_EVENT]
    assert logs[0]["path"] == "/x"


def test_the_boundary_lets_other_scopes_through() -> None:
    reached: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(scope["type"])
        msg = "lifespan"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="lifespan"):
        _run(ErrorBoundaryMiddleware(inner), "lifespan")
    assert reached == ["lifespan"]
