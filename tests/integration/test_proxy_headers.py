"""Cabeceras del proxy de confianza (paso E, E4): IP y esquema reales solo si vienen de Caddy.

``ProxyHeadersMiddleware`` es la capa más exterior: el registro de acceso, el límite de peticiones y
la aplicación ven la IP del cliente real cuando (y solo cuando) la conexión llega de una IP de
``VORACIOUS_TRUSTED_PROXIES``. Desde cualquier otra, o sin la variable, ``X-Forwarded-*`` se ignora.
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from support.api import DATASETS
from support.auth import auth_settings, bearer
from voracious.api.access_log import ACCESS_EVENT
from voracious.api.app import create_app
from voracious.container import build_container

PROXY = "172.29.80.10"
ECHO = "/v1/echo"
CLIENT = "198.51.100.23"


def _app(trusted: str, **overrides: object) -> FastAPI:
    """Aplicación real con ``GET /v1/echo`` (con token), que devuelve la IP y el esquema vistos."""
    app = create_app(build_container(auth_settings(trusted_proxies=trusted, **overrides)))

    @app.get(ECHO)
    def echo(request: Request) -> dict[str, str | None]:
        return {
            "client": request.client.host if request.client else None,
            "scheme": request.url.scheme,
        }

    return app


def _echo(app: FastAPI, source: str, headers: dict[str, str]) -> tuple[dict[str, str], str]:
    """``(eco, client del registro de acceso)`` de una petición desde ``source``."""
    with (
        TestClient(app, client=(source, 40000)) as client,
        structlog.testing.capture_logs() as logs,
    ):
        response = client.get(ECHO, headers={**bearer(), **headers})
    assert response.status_code == 200, response.text
    access = [e for e in logs if e["event"] == ACCESS_EVENT]
    return response.json(), access[-1]["client"]


FORWARDED = {"X-Forwarded-For": CLIENT, "X-Forwarded-Proto": "https"}


def test_from_the_trusted_proxy_the_real_client_and_scheme_are_used() -> None:
    echoed, logged = _echo(_app(PROXY), PROXY, FORWARDED)
    assert echoed == {"client": CLIENT, "scheme": "https"}
    assert logged == CLIENT


def test_a_trusted_network_in_cidr_also_counts() -> None:
    echoed, _ = _echo(_app("172.29.80.0/24, 10.9.0.0/16"), "172.29.80.99", FORWARDED)
    assert echoed == {"client": CLIENT, "scheme": "https"}


def test_a_spoofed_chain_yields_the_last_untrusted_hop() -> None:
    """Caddy reescribe ``X-Forwarded-For``; aunque llegara una cadena, manda el último salto."""
    chain = {"X-Forwarded-For": f"203.0.113.7, {CLIENT}", "X-Forwarded-Proto": "https"}
    echoed, logged = _echo(_app(PROXY), PROXY, chain)
    assert (echoed["client"], logged) == (CLIENT, CLIENT)


def test_from_another_source_the_headers_are_ignored() -> None:
    echoed, logged = _echo(_app(PROXY), "10.1.2.3", FORWARDED)
    assert echoed == {"client": "10.1.2.3", "scheme": "http"}
    assert logged == "10.1.2.3"


def test_without_trusted_proxies_the_headers_are_ignored() -> None:
    echoed, logged = _echo(_app(""), PROXY, FORWARDED)
    assert echoed == {"client": PROXY, "scheme": "http"}
    assert logged == PROXY


def test_the_rate_limit_counts_the_real_client_behind_the_proxy() -> None:
    app = _app(PROXY, rate_limit_per_minute=1, rate_limit_burst=1)
    with TestClient(app, client=(PROXY, 40000)) as client:

        def status(ip: str) -> int:
            return client.get(f"{DATASETS}/nope", headers={"X-Forwarded-For": ip}).status_code

        assert [status(CLIENT), status(CLIENT)] == [401, 429]
        assert [status("203.0.113.7"), status("203.0.113.7")] == [401, 429]
