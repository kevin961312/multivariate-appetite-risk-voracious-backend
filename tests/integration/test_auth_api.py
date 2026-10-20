"""Autenticación y autorización de la API por caja negra (seguridad mínima: D1, D7-D9, M2 y M4).

Cada ruta de ``EXPECTED_ROUTES`` por cada rol: un rol no permitido da ``403 FORBIDDEN`` con
``details.required_roles`` y uno permitido da cualquier cosa menos ``401``/``403`` (los ``POST`` van
con ``{}`` e identificadores ficticios: nunca llegan a calcular nada). Sin token, ``401`` con
``WWW-Authenticate``; ``X-Tenant-ID`` se ignora siempre.
"""

import asyncio
import json
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
import structlog
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from support.api import DATASETS, upload
from support.auth import (
    JWKS_FILE,
    OTHER_KEY_PEM,
    TEST_AUDIENCE,
    TEST_ISSUER,
    auth_settings,
    bearer,
    claims,
    forge,
    token,
)
from support.routes import EXPECTED_ROUTES, ROUTE_ROLES
from support.solo_test import small_data
from voracious.api.access_log import ACCESS_EVENT, UNMATCHED_ROUTE, AccessLogMiddleware
from voracious.api.app import create_app
from voracious.api.auth import AuthenticationMiddleware
from voracious.application.auth import Role
from voracious.container import build_container
from voracious.infrastructure.auth import JwtTokenVerifier, load_jwks

PRIVATE = [route for route in EXPECTED_ROUTES if ROUTE_ROLES[route]]
PUBLIC = [route for route in EXPECTED_ROUTES if not ROUTE_ROLES[route]]
CHALLENGE = 'Bearer realm="voracious"'


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app(build_container(auth_settings()))) as test_client:
        yield test_client


def _url(path: str) -> str:
    """Ruta concreta con identificadores ficticios (``{number}`` debe ser entero)."""
    return re.sub(r"\{[a-z_]+\}", "nope", path.replace("{number}", "1"))


def _ids(route: tuple[str, str]) -> str:
    return f"{route[0]} {route[1]}"


def _call(
    client: TestClient, route: tuple[str, str], headers: dict[str, str] | None = None
) -> httpx2.Response:
    method, path = route
    body = {} if method == "POST" else None
    return client.request(method, _url(path), headers=headers or {}, json=body)


def test_the_matrix_covers_every_route_of_the_app() -> None:
    schema = create_app(build_container(auth_settings())).openapi()
    routes = {(m.upper(), p) for p, ops in schema["paths"].items() for m in ops}
    assert routes == set(ROUTE_ROLES)


@pytest.mark.parametrize("role", list(Role), ids=lambda r: r.value)
@pytest.mark.parametrize("route", PRIVATE, ids=_ids)
def test_role_matrix(client: TestClient, route: tuple[str, str], role: Role) -> None:
    response = _call(client, route, bearer(roles=(role,)))
    allowed = ROUTE_ROLES[route]
    if role in allowed:
        assert response.status_code not in {401, 403}, response.text
        return
    assert response.status_code == 403, response.text
    body = response.json()
    assert body["code"] == "FORBIDDEN"
    assert body["details"] == {"required_roles": sorted(r.value for r in allowed)}


@pytest.mark.parametrize("route", PRIVATE, ids=_ids)
def test_every_business_route_needs_a_token(client: TestClient, route: tuple[str, str]) -> None:
    response = _call(client, route, {"X-Tenant-ID": "tenant-a"})
    assert response.status_code == 401, response.text
    assert response.json() == {
        "code": "UNAUTHENTICATED",
        "message": "falta la cabecera Authorization: Bearer <token>",
        "details": {"reason": "missing_token"},
    }
    assert response.headers["www-authenticate"] == CHALLENGE


@pytest.mark.parametrize("route", PUBLIC, ids=_ids)
def test_public_routes_need_no_token(client: TestClient, route: tuple[str, str]) -> None:
    assert _call(client, route).status_code == 200


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"])
def test_the_api_documentation_is_public(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


def test_several_roles_add_up(client: TestClient) -> None:
    both = bearer(roles=(Role.ANALYST, Role.APPROVER))
    for route in PRIVATE:
        assert _call(client, route, both).status_code not in {401, 403}, route


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (lambda: forge(key=OTHER_KEY_PEM), "bad_signature"),
        (lambda: forge(claims(iat=1, exp=2)), "expired"),
        (lambda: forge(claims(aud="otra-api")), "wrong_audience"),
        (lambda: forge(claims(iss="otro-emisor")), "wrong_issuer"),
        (lambda: forge(headers={"kid": "otra"}), "unknown_key"),
        (lambda: forge(algorithm="none"), "algorithm_not_allowed"),
        (lambda: forge(claims(roles=["root"])), "invalid_claim"),
        (lambda: forge(claims(tenant=None)), "missing_claim"),
        (lambda: "no-es-un-jwt", "malformed"),
    ],
)
def test_invalid_tokens_are_401_with_their_reason(
    client: TestClient, raw: Callable[[], str], reason: str
) -> None:
    response = client.get(f"{DATASETS}/nope", headers={"Authorization": f"Bearer {raw()}"})
    assert response.status_code == 401, response.text
    assert response.json()["details"] == {"reason": reason}
    assert response.headers["www-authenticate"] == f'{CHALLENGE}, error="invalid_token"'


def test_tokens_living_longer_than_seven_days_are_rejected(client: TestClient) -> None:
    """Mejora M4."""
    now = int(datetime.now(UTC).timestamp())
    long_lived = forge(claims(iat=now, exp=now + 8 * 86400))
    response = client.get(f"{DATASETS}/nope", headers={"Authorization": f"Bearer {long_lived}"})
    assert response.status_code == 401
    assert response.json()["details"] == {"reason": "lifetime_too_long"}


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("Basic dXNlcjpwYXNz", "missing_token"),
        ("Bearer", "malformed"),
        ("Bearer    ", "malformed"),
        ("Bearer a b", "malformed"),
        (f"Bearer {'x' * 9000}", "malformed"),
    ],
)
def test_authorization_header_variants(client: TestClient, value: str, reason: str) -> None:
    response = client.get(f"{DATASETS}/nope", headers={"Authorization": value})
    assert response.status_code == 401
    assert response.json()["details"] == {"reason": reason}


def test_scheme_is_case_insensitive_and_one_header_only(client: TestClient) -> None:
    raw = token()
    lower = client.get(f"{DATASETS}/nope", headers={"Authorization": f"bearer {raw}"})
    assert lower.status_code == 404
    twice = client.get(f"{DATASETS}/nope", headers=[("Authorization", f"Bearer {raw}")] * 2)
    assert twice.status_code == 401
    assert twice.json()["details"] == {"reason": "malformed"}


def test_the_token_is_never_read_from_the_query(client: TestClient) -> None:
    response = client.get(f"{DATASETS}/nope", params={"access_token": token()})
    assert response.status_code == 401
    assert response.json()["details"] == {"reason": "missing_token"}


def test_post_without_token_and_malformed_json_is_401_not_422(client: TestClient) -> None:
    for path in (DATASETS, "/v1/charts/t2mrcd/fits", "/v1/charts/t2mrcd/pipelines/phase1"):
        response = client.post(
            path, content=b"{esto no es json", headers={"content-type": "application/json"}
        )
        assert response.status_code == 401, (path, response.text)


def test_unknown_route_is_401_without_token_and_404_with_it(client: TestClient) -> None:
    assert client.get("/v1/no-existe").status_code == 401
    response = client.get("/v1/no-existe", headers=bearer())
    assert response.status_code == 404
    assert response.json()["code"] == "ROUTE_NOT_FOUND"


def _asgi_upload(headers: list[tuple[bytes, bytes]]) -> tuple[int, int]:
    """``POST /v1/datasets`` de 50 MB por ASGI directo; devuelve (estado, veces que se leyó)."""
    app = create_app(build_container(auth_settings()))
    reads = 0
    sent: list[Message] = []
    size = 60 * 1024 * 1024  # más que VORACIOUS_MAX_UPLOAD_MB (50 por defecto)

    async def receive() -> Message:
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": b"1.0\n" * 1024, "more_body": reads < 4}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": DATASETS,
        "raw_path": DATASETS.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"text/csv"),
            (b"content-length", str(size).encode()),
            *headers,
        ],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
        "state": {},
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return int(start["status"]), reads


def test_a_big_upload_without_token_is_401_without_reading_the_body() -> None:
    status, reads = _asgi_upload([])
    assert (status, reads) == (401, 0)
    # Con token sí se lee (y aquí el cuerpo declarado supera el máximo: 413 sin leerlo entero).
    authorized = [(b"authorization", f"Bearer {token()}".encode())]
    assert _asgi_upload(authorized)[0] == 413


# --- WebSocket y demás scopes: sin token solo pasan lifespan y HTTP a PUBLIC_PATHS -------------


@pytest.mark.parametrize(
    ("path", "headers", "reason"),
    [
        (DATASETS, {}, "missing_token"),
        ("/health", {}, "missing_token"),  # las rutas públicas lo son solo por HTTP
        (DATASETS, {"Authorization": "Bearer no-es-un-jwt"}, "malformed"),
        (DATASETS, {"Authorization": f"Bearer {forge(key=OTHER_KEY_PEM)}"}, "bad_signature"),
    ],
)
def test_a_websocket_without_a_valid_token_is_closed_with_1008(
    client: TestClient, path: str, headers: dict[str, str], reason: str
) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect(path, headers=headers),
    ):
        pytest.fail("el WebSocket no debía aceptarse")
    assert (closed.value.code, closed.value.reason) == (1008, reason)


def test_a_websocket_with_a_valid_token_reaches_the_router(client: TestClient) -> None:
    # No hay rutas WebSocket: el enrutador lo cierra con 1000 (no 1008), ya autenticado.
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("/ws", headers=bearer()),
    ):
        pytest.fail("el WebSocket no debía aceptarse")
    assert closed.value.code == 1000


def test_only_lifespan_reaches_the_app_without_a_token() -> None:
    """ASGI directo: ``lifespan`` pasa, un scope desconocido no y un WebSocket exige el token."""
    reached: list[Scope] = []
    sent: list[Message] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(scope)

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        sent.append(message)

    keys = load_jwks(JWKS_FILE.read_text(encoding="utf-8"), allowed_algorithms=("EdDSA",))
    verifier = JwtTokenVerifier(
        keys,
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        algorithms=("EdDSA",),
        leeway=timedelta(seconds=30),
    )
    middleware = AuthenticationMiddleware(inner, verifier)
    asyncio.run(middleware({"type": "lifespan"}, receive, send))
    asyncio.run(middleware({"type": "otro", "path": "/health", "headers": []}, receive, send))
    anonymous: Scope = {"type": "websocket", "path": "/health", "headers": [], "state": {}}
    asyncio.run(middleware(anonymous, receive, send))
    assert [scope["type"] for scope in reached] == ["lifespan"]
    assert sent == [{"type": "websocket.close", "code": 1008, "reason": "missing_token"}]
    assert anonymous["state"] == {"auth_failure": "missing_token"}
    authorization = (b"authorization", f"Bearer {token(subject='ws')}".encode())
    signed: Scope = {"type": "websocket", "path": "/ws", "headers": [authorization]}
    asyncio.run(middleware(signed, receive, send))
    assert [scope["type"] for scope in reached] == ["lifespan", "websocket"]
    assert reached[-1]["state"]["principal"].subject == "ws"
    assert len(sent) == 1


def test_tenant_comes_from_the_token_and_the_header_is_ignored(client: TestClient) -> None:
    dataset_id = upload(client, small_data(5, 2, seed=1), headers=bearer("tenant-a"))
    spoof = {**bearer("tenant-b"), "X-Tenant-ID": "tenant-a"}
    response = client.get(f"{DATASETS}/{dataset_id}", headers=spoof)
    assert response.status_code == 404
    assert response.json()["code"] == "DATASET_NOT_FOUND"
    own = {**bearer("tenant-a"), "X-Tenant-ID": "tenant-b"}
    assert client.get(f"{DATASETS}/{dataset_id}", headers=own).status_code == 200
    admin_b = bearer("tenant-b", roles=(Role.ADMIN,))  # admin solo de su tenant
    assert client.get(f"{DATASETS}/{dataset_id}", headers=admin_b).status_code == 404


def test_openapi_declares_bearer_auth_on_business_operations_only(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    scheme = schema["components"]["securitySchemes"]["bearerAuth"]
    assert (scheme["type"], scheme["scheme"], scheme["bearerFormat"]) == ("http", "bearer", "JWT")
    for (method, path), roles in ROUTE_ROLES.items():
        operation = schema["paths"][path][method.lower()]
        if roles:
            assert operation["security"] == [{"bearerAuth": []}], (method, path)
            assert {"401", "403"} <= set(operation["responses"]), (method, path)
        else:
            assert "security" not in operation, (method, path)


def test_access_log_has_identity_and_route_templates_but_never_the_token() -> None:
    """Mejora M2: una línea por petición con quién, qué plantilla, estado y duración."""
    raw = token(subject="auditor", roles=(Role.ANALYST,))
    forged = forge(key=OTHER_KEY_PEM)
    authorization = {"Authorization": f"Bearer {raw}"}
    debug = TestClient(
        create_app(build_container(auth_settings(log_level="DEBUG"))),
        client=("198.51.100.4", 43210),
    )
    with structlog.testing.capture_logs() as logs:
        debug.get(f"{DATASETS}/id-secreto-1", headers=authorization)
        debug.get(f"{DATASETS}/id-secreto-2")
        debug.get("/v1/no-existe/id-secreto-3", headers=authorization)
        debug.get(f"{DATASETS}/id-secreto-4", headers={"Authorization": f"Bearer {forged}"})
        debug.get("/health")
        debug.post("/v1/charts/t2mrcd/pipelines/phase1", headers=authorization, json={})
        debug.get("/v1/charts/t2mrcd/pipelines/phase1", headers=authorization)
    access = [entry for entry in logs if entry["event"] == ACCESS_EVENT]
    assert len(access) == 7
    ok, anonymous, unmatched, bad, health, literal, by_id = access
    assert ok["log_level"] == "info"
    assert (ok["method"], ok["route"], ok["status"]) == ("GET", f"{DATASETS}/{{dataset_id}}", 404)
    assert (ok["sub"], ok["tenant"]) == ("auditor", "tenant-a")
    assert ok["jti"]
    assert isinstance(ok["duration_ms"], float)
    assert "auth_failure" not in ok
    # Paso E (E3): la IP del cliente, sin puerto, en todas las líneas (también en los 401).
    assert {entry["client"] for entry in access} == {"198.51.100.4"}
    assert (anonymous["status"], anonymous["auth_failure"]) == (401, "missing_token")
    assert anonymous["route"] == f"{DATASETS}/{{dataset_id}}"
    assert "sub" not in anonymous
    assert (unmatched["route"], unmatched["status"]) == (UNMATCHED_ROUTE, 404)
    assert (bad["status"], bad["auth_failure"]) == (401, "bad_signature")
    assert (health["route"], health["log_level"]) == ("/health", "debug")
    assert literal["route"] == "/v1/charts/t2mrcd/pipelines/phase1"
    assert by_id["route"] == "/v1/charts/t2mrcd/pipelines/{pipeline_id}"
    text = json.dumps(logs, default=str)
    assert "id-secreto" not in text  # plantilla, nunca la ruta cruda
    assert "43210" not in text  # ni el puerto del cliente
    for secret in (raw, forged):
        for part in secret.split(".")[1:]:
            assert part not in text


def test_access_log_records_a_500_when_the_app_raises() -> None:
    async def broken(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("roto")

    middleware = AccessLogMiddleware(broken, dict)
    scope: Scope = {"type": "http", "method": "GET", "path": "/x", "headers": [], "state": {}}

    async def receive() -> Message:
        return {"type": "http.request"}

    async def send(message: Message) -> None:
        return None

    with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError):
        asyncio.run(middleware(scope, receive, send))
    assert [(e["status"], e["route"], e["client"]) for e in logs] == [(500, UNMATCHED_ROUTE, None)]
    lifespan: Scope = {"type": "lifespan"}
    with pytest.raises(RuntimeError):
        asyncio.run(middleware(lifespan, receive, send))
