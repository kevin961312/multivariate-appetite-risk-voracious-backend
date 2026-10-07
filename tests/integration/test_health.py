from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from voracious.api.app import create_app
from voracious.config import Settings
from voracious.container import build_container


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(build_container(Settings(log_level="INFO")))) as test_client:
        yield test_client


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_ready_with_empty_checks(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {}}
