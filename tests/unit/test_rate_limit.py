"""Límite de peticiones por IP (paso E, E2): cubo de fichas con reloj falso, ASGI directo."""

import asyncio
import json

import pytest
import structlog
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from support.api import DATASETS
from support.auth import auth_settings
from voracious.api.access_log import ACCESS_EVENT
from voracious.api.app import create_app
from voracious.api.rate_limit import RATE_LIMITED, RateLimitMiddleware, is_loopback
from voracious.config import Settings
from voracious.container import build_container


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Harness:
    """Middleware sobre una app que responde ``204``; cuenta lecturas y llamadas a la app."""

    def __init__(self, *, per_minute: int, burst: int, max_keys: int = 100) -> None:
        self.clock = _Clock()
        self.reached: list[str] = []
        self.reads = 0

        async def inner(scope: Scope, receive: Receive, send: Send) -> None:
            self.reached.append(scope["type"])
            if scope["type"] == "http":
                await send({"type": "http.response.start", "status": 204, "headers": []})
                await send({"type": "http.response.body", "body": b""})

        self.middleware = RateLimitMiddleware(
            inner, per_minute=per_minute, burst=burst, clock=self.clock, max_keys=max_keys
        )

    def call(self, client: str | None = "203.0.113.7") -> tuple[int, dict[str, str], bytes]:
        sent: list[Message] = []

        async def receive() -> Message:
            self.reads += 1
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/datasets",
            "headers": [],
            "client": (client, 4321) if client is not None else None,
        }
        asyncio.run(self.middleware(scope, receive, send))
        start = next(m for m in sent if m["type"] == "http.response.start")
        headers = {k.decode(): v.decode() for k, v in start.get("headers", [])}
        body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        return int(start["status"]), headers, body

    def statuses(self, n: int, client: str | None = "203.0.113.7") -> list[int]:
        return [self.call(client)[0] for _ in range(n)]


def test_the_burst_passes_and_then_429_with_retry_after() -> None:
    h = _Harness(per_minute=60, burst=3)
    assert h.statuses(3) == [204, 204, 204]
    status, headers, body = h.call()
    assert status == 429
    assert headers["retry-after"] == "1"
    assert headers["content-type"] == "application/json"
    assert json.loads(body) == {
        "code": RATE_LIMITED,
        "message": "demasiadas peticiones; espera antes de reintentar",
        "details": {"retry_after_seconds": 1},
    }
    assert h.reached == ["http"] * 3


def test_the_bucket_refills_at_per_minute_over_sixty_and_caps_at_the_burst() -> None:
    h = _Harness(per_minute=60, burst=3)
    assert h.statuses(4) == [204, 204, 204, 429]
    h.clock.now += 1.0
    assert h.statuses(2) == [204, 429]
    h.clock.now += 3600.0  # nunca más de ``burst`` fichas
    assert h.statuses(4) == [204, 204, 204, 429]


def test_retry_after_is_the_whole_seconds_until_the_next_token() -> None:
    h = _Harness(per_minute=6, burst=1)  # una ficha cada 10 s
    assert h.statuses(1) == [204]
    assert h.call()[1]["retry-after"] == "10"
    h.clock.now += 4.0
    assert h.call()[1]["retry-after"] == "6"
    h.clock.now += 5.5
    assert h.call()[1]["retry-after"] == "1"  # nunca 0
    h.clock.now += 0.5
    assert h.statuses(1) == [204]


def test_a_clock_going_backwards_never_adds_tokens() -> None:
    h = _Harness(per_minute=60, burst=1)
    assert h.statuses(1) == [204]
    h.clock.now -= 100.0
    assert h.statuses(1) == [429]


def test_each_ip_has_its_own_bucket() -> None:
    h = _Harness(per_minute=60, burst=2)
    assert h.statuses(3, "203.0.113.7") == [204, 204, 429]
    assert h.statuses(3, "198.51.100.9") == [204, 204, 429]
    assert h.statuses(3, "2001:db8::1") == [204, 204, 429]


@pytest.mark.parametrize("client", ["127.0.0.1", "127.8.9.10", "::1", "::ffff:127.0.0.1"])
def test_loopback_is_exempt(client: str) -> None:
    """El ``HEALTHCHECK`` y el comprobador de la puerta llaman desde dentro del contenedor."""
    h = _Harness(per_minute=1, burst=1)
    assert h.statuses(20, client) == [204] * 20


def test_requests_without_client_share_one_bucket() -> None:
    h = _Harness(per_minute=60, burst=2)
    assert h.statuses(3, None) == [204, 204, 429]


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.255.255.254", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),
        ("::ffff:10.0.0.1", False),
        ("10.0.0.1", False),
        ("172.29.80.10", False),
        ("localhost", False),  # un nombre no es loopback: falla cerrado
        ("testclient", False),
        ("", False),
    ],
)
def test_is_loopback(host: str, expected: bool) -> None:
    assert is_loopback(host) is expected


def test_the_least_recent_ip_is_forgotten_beyond_max_keys() -> None:
    h = _Harness(per_minute=60, burst=1, max_keys=2)
    assert h.statuses(2, "10.0.0.1") == [204, 429]
    assert h.statuses(1, "10.0.0.2") == [204]
    assert h.statuses(1, "10.0.0.1") == [429]  # la usa: pasa a ser la más reciente
    assert h.statuses(1, "10.0.0.3") == [204]  # se olvida 10.0.0.2, no 10.0.0.1
    assert h.statuses(1, "10.0.0.1") == [429]
    assert h.statuses(1, "10.0.0.2") == [204]  # olvidada: cubo nuevo (y se olvida 10.0.0.3)
    assert h.statuses(1, "10.0.0.4") == [204]  # se olvida 10.0.0.1
    assert h.statuses(1, "10.0.0.1") == [204]
    assert len(h.middleware._buckets) == 2


def test_the_body_is_never_read() -> None:
    h = _Harness(per_minute=60, burst=1)
    assert h.statuses(5) == [204, 429, 429, 429, 429]
    assert h.reads == 0


def test_lifespan_and_websocket_are_not_counted() -> None:
    h = _Harness(per_minute=60, burst=1)
    assert h.statuses(2) == [204, 429]

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        return None

    client = ("203.0.113.7", 1)
    for kind in ("lifespan", "websocket", "lifespan"):
        asyncio.run(h.middleware({"type": kind, "client": client}, receive, send))
    assert h.reached == ["http", "lifespan", "websocket", "lifespan"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"per_minute": 0, "burst": 1},
        {"per_minute": 1, "burst": 0},
        {"per_minute": 1, "burst": 1, "max_keys": 0},
    ],
)
def test_limits_below_one_are_rejected(kwargs: dict[str, int]) -> None:
    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        return None

    with pytest.raises(ValueError, match=">= 1"):
        RateLimitMiddleware(inner, **kwargs)


# --- en la aplicación, con los valores por defecto ---------------------------------------------


def _default_limits_app() -> TestClient:
    defaults = Settings.model_construct()
    settings = auth_settings(
        rate_limit_per_minute=defaults.rate_limit_per_minute,
        rate_limit_burst=defaults.rate_limit_burst,
    )
    return TestClient(create_app(build_container(settings)), client=("203.0.113.7", 50000))


def test_the_app_limits_requests_without_token_with_the_default_burst() -> None:
    """Va antes de la autenticación: también acota las ráfagas de ``401``.

    Con 600/min se rellenan 10 fichas por segundo mientras dura el bucle: el ``429`` llega en
    cuanto se agota la ráfaga de 120 más lo rellenado.
    """
    with _default_limits_app() as client, structlog.testing.capture_logs() as logs:
        statuses = [client.get(f"{DATASETS}/nope").status_code for _ in range(400)]
    assert statuses[:120] == [401] * 120
    assert 429 in statuses
    limited = statuses.index(429)
    assert set(statuses[:limited]) == {401}
    rejected = [e for e in logs if e["event"] == ACCESS_EVENT and e["status"] == 429]
    assert rejected[0]["route"] == f"{DATASETS}/{{dataset_id}}"
    assert rejected[0]["client"] == "203.0.113.7"
    assert "auth_failure" not in rejected[0]


def test_the_429_of_the_app_has_the_uniform_format_and_public_routes_count() -> None:
    settings = auth_settings(rate_limit_per_minute=1, rate_limit_burst=2)
    app = create_app(build_container(settings))
    with TestClient(app, client=("203.0.113.8", 50000)) as client:
        assert [client.get("/health").status_code for _ in range(2)] == [200, 200]
        limited = client.get(f"{DATASETS}/nope")
    assert limited.status_code == 429
    assert limited.json() == {
        "code": RATE_LIMITED,
        "message": "demasiadas peticiones; espera antes de reintentar",
        "details": {"retry_after_seconds": int(limited.headers["retry-after"])},
    }
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    assert "www-authenticate" not in limited.headers


def test_the_app_does_not_limit_loopback() -> None:
    defaults = Settings.model_construct()
    settings = auth_settings(rate_limit_per_minute=1, rate_limit_burst=defaults.rate_limit_burst)
    app = create_app(build_container(settings))
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert {client.get("/health").status_code for _ in range(130)} == {200}
