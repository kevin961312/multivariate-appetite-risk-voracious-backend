"""``scripts/check_auth_surface.py`` (paso E, E9): la puerta que impide abrir el 443 con una ruta
de negocio sin token.

Contra la app real (uvicorn en un hilo, por HTTP de verdad) da ``0`` y prueba exactamente las
operaciones no públicas de ``ROUTE_ROLES`` más un ``OPTIONS`` sin *preflight* por ruta. Contra un
servidor falso con una ruta abierta da ``1``; sin conexión o mal invocado, ``2``.
"""

import importlib.util
import json
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest
import uvicorn
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from support.auth import auth_settings
from support.routes import ROUTE_ROLES
from support.tools import run_tool
from voracious.api.app import create_app
from voracious.container import build_container

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_auth_surface.py"
PRIVATE = {route for route, roles in ROUTE_ROLES.items() if roles}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_auth_surface", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_auth_surface"] = module
    spec.loader.exec_module(module)
    return module


check = _load()


def _serve(app: ASGIApp) -> Iterator[str]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn no arrancó"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=30)


@pytest.fixture(scope="module")
def served() -> Iterator[str]:
    yield from _serve(create_app(build_container(auth_settings())))


@pytest.fixture(scope="module")
def served_without_docs() -> Iterator[tuple[str, FastAPI]]:
    app = create_app(build_container(auth_settings(api_docs=False)))
    for url in _serve(app):
        yield url, app


def _probed(out: str) -> list[tuple[str, str, str]]:
    """``(marca, método, plantilla)`` de cada línea de sonda de la salida."""
    lines = [line.split() for line in out.splitlines() if line.startswith(("OK", "FALLO "))]
    return [(parts[0], parts[2], parts[3]) for parts in lines if len(parts) == 4]


def test_against_the_real_app_it_probes_exactly_the_private_routes(
    served: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check.main(["--base-url", served]) == 0
    out = capsys.readouterr().out
    probed = _probed(out)
    assert {mark for mark, _, _ in probed} == {"OK"}
    assert ("OK", "GET", "/health") in probed
    business = {(m, t) for _, m, t in probed if m != "OPTIONS" and (m, t) != ("GET", "/health")}
    assert business == PRIVATE
    options = sorted(t for _, m, t in probed if m == "OPTIONS")
    assert options == sorted({template for _, template in PRIVATE})
    assert "superficie de autenticación cerrada" in out


def test_it_runs_from_stdin_with_only_the_standard_library(served: str) -> None:
    """Como lo usa ``deploy.sh``: ``python - --base-url … < scripts/check_auth_surface.py``."""
    result = run_tool(
        [sys.executable, "-I", "-", "--base-url", served],
        stdin=SCRIPT.read_text(encoding="utf-8"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "superficie de autenticación cerrada" in result.stdout


def test_without_docs_it_needs_the_openapi_file(
    served_without_docs: tuple[str, FastAPI],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url, app = served_without_docs
    assert check.main(["--base-url", url]) == 2
    assert "--openapi" in capsys.readouterr().err
    spec = tmp_path / "openapi.json"
    spec.write_text(json.dumps(app.openapi()), encoding="utf-8")
    assert check.main(["--base-url", url, "--openapi", str(spec)]) == 0


# --- servidor falso ----------------------------------------------------------------------------

Responder = Callable[[str, str], tuple[int, dict[str, str]]]
"""(método, ruta) → (estado, cabeceras) del servidor falso."""

FAKE_SPEC = {
    "paths": {
        "/health": {"get": {}},
        "/ready": {"get": {}},
        "/v1/things/{thing_id}": {"get": {}, "post": {}},
        "/v1/leak": {"get": {}},
    }
}

GUARDED = (401, {"WWW-Authenticate": 'Bearer realm="voracious"'})


def _well_behaved(method: str, path: str) -> tuple[int, dict[str, str]]:
    if path == "/health":
        return 200, {}
    return GUARDED


def _fake(responder: Responder, spec: object = FAKE_SPEC) -> Iterator[str]:
    """Servidor ASGI falso (uvicorn): sirve ``spec`` y responde el resto con ``responder``."""
    seen: list[tuple[str, str, dict[str, str]]] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        more = True
        while more:
            more = (await receive()).get("more_body", False)
        method, path = scope["method"], scope["path"]
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        seen.append((method, path, headers))
        if path == "/openapi.json":
            status, extra, body = 200, {}, json.dumps(spec).encode()
        else:
            status, extra = responder(method, path)
            body = b"{}"
        raw = [(k.lower().encode(), v.encode()) for k, v in extra.items()]
        await send({"type": "http.response.start", "status": status, "headers": raw})
        await send({"type": "http.response.body", "body": body})

    yield from _serve(app)
    for method, path, headers in seen:
        assert "authorization" not in headers, (method, path)
        assert "origin" not in headers, (method, path)
        assert "access-control-request-method" not in headers, (method, path)
        if path != "/openapi.json":
            assert headers.get("x-tenant-id") == "demo"


def _run(responder: Responder, spec: object = FAKE_SPEC) -> int:
    code = -1
    for url in _fake(responder, spec):
        code = check.main(["--base-url", url, "--timeout", "5"])
    return code


def test_the_fake_well_behaved_server_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(_well_behaved) == 0
    probed = _probed(capsys.readouterr().out)
    assert {(m, t) for _, m, t in probed} == {
        ("GET", "/health"),
        ("GET", "/v1/leak"),
        ("GET", "/v1/things/{thing_id}"),
        ("POST", "/v1/things/{thing_id}"),
        ("OPTIONS", "/v1/leak"),
        ("OPTIONS", "/v1/things/{thing_id}"),
    }


def test_a_route_answering_without_token_fails_with_1(capsys: pytest.CaptureFixture[str]) -> None:
    def leaky(method: str, path: str) -> tuple[int, dict[str, str]]:
        return (200, {}) if path == "/v1/leak" else _well_behaved(method, path)

    assert _run(leaky) == 1
    out = capsys.readouterr().out
    assert "FALLO 200 GET /v1/leak" in out
    assert "OK    401 GET /v1/things/{thing_id}" in out


@pytest.mark.parametrize(
    ("broken", "expected_line"),
    [
        (lambda m, p: (200, {}) if m == "OPTIONS" else _well_behaved(m, p), "FALLO 200 OPTIONS"),
        (lambda m, p: (401, {}) if p == "/v1/leak" else _well_behaved(m, p), "FALLO 401 GET"),
        (lambda m, p: (404, {}) if m == "POST" else _well_behaved(m, p), "FALLO 404 POST"),
        (lambda m, p: (503, {}) if p == "/health" else _well_behaved(m, p), "FALLO 503 GET"),
    ],
    ids=["options-open", "401-without-challenge", "404-without-token", "health-down"],
)
def test_other_unguarded_answers_fail_with_1(
    capsys: pytest.CaptureFixture[str], broken: Responder, expected_line: str
) -> None:
    assert _run(broken) == 1
    assert expected_line in capsys.readouterr().out


def test_the_placeholder_fills_every_path_parameter() -> None:
    assert check.concrete("/m/{model_id}/r/{recalibration_id}/x") == "/m/auth-check/r/auth-check/x"


@pytest.mark.parametrize(
    "spec",
    [{"paths": {"/health": {"get": {}}}}, {"openapi": "3.1.0"}, ["no", "es", "un", "objeto"]],
    ids=["only-public", "no-paths", "not-an-object"],
)
def test_an_openapi_without_business_operations_is_2(spec: object) -> None:
    assert _run(_well_behaved, spec) == 2


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--base-url"],
        ["--base-url", "ftp://127.0.0.1"],
        ["--base-url", "http://"],
        ["--base-url", "http://127.0.0.1:8000/?x=1"],
        ["--base-url", "http://127.0.0.1:8000", "--openapi", "/no/existe/openapi.json"],
    ],
)
def test_usage_errors_are_2(argv: list[str]) -> None:
    assert check.main(argv) == 2


def test_no_connection_is_2(capsys: pytest.CaptureFixture[str]) -> None:
    url = f"http://127.0.0.1:{_closed_port()}"
    assert check.main(["--base-url", url, "--timeout", "2"]) == 2
    assert "sin respuesta de la API" in capsys.readouterr().err
