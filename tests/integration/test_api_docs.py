"""Documentación interactiva apagable (paso E, M2): ``VORACIOUS_API_DOCS=false``.

Sin documentación, ``/docs``, ``/redoc``, ``/docs/oauth2-redirect`` y ``/openapi.json`` dejan de ser
públicas y de existir: sin token ``401`` (como cualquier ruta) y con token ``404``. ``/health`` y
``/ready`` siguen públicas y ``app.openapi()`` sigue sirviendo al registro de acceso.
"""

from collections.abc import Iterator

import pytest
import structlog
from fastapi.testclient import TestClient

from support.api import DATASETS
from support.auth import auth_settings, bearer
from support.routes import EXPECTED_ROUTES
from voracious.api.access_log import ACCESS_EVENT
from voracious.api.app import create_app
from voracious.api.auth import DOCS_PATHS, PROBE_PATHS, PUBLIC_PATHS
from voracious.container import build_container


@pytest.fixture(scope="module")
def no_docs() -> Iterator[TestClient]:
    with TestClient(create_app(build_container(auth_settings(api_docs=False)))) as client:
        yield client


@pytest.mark.parametrize("path", sorted(DOCS_PATHS))
def test_without_docs_they_are_401_without_token_and_404_with_it(
    no_docs: TestClient, path: str
) -> None:
    anonymous = no_docs.get(path)
    assert anonymous.status_code == 401
    assert anonymous.json()["details"] == {"reason": "missing_token"}
    assert anonymous.headers["www-authenticate"].startswith("Bearer")
    authorized = no_docs.get(path, headers=bearer())
    assert authorized.status_code == 404
    assert authorized.json()["code"] == "ROUTE_NOT_FOUND"


@pytest.mark.parametrize("path", sorted(PROBE_PATHS))
def test_without_docs_health_and_ready_stay_public(no_docs: TestClient, path: str) -> None:
    assert no_docs.get(path).status_code == 200


def test_without_docs_the_schema_still_feeds_the_access_log() -> None:
    app = create_app(build_container(auth_settings(api_docs=False)))
    schema = app.openapi()
    routes = [(method.upper(), path) for path, ops in schema["paths"].items() for method in ops]
    assert sorted(routes) == sorted(EXPECTED_ROUTES)
    with TestClient(app) as client, structlog.testing.capture_logs() as logs:
        client.get(f"{DATASETS}/id-1", headers=bearer())
        client.get("/openapi.json")
    access = [e for e in logs if e["event"] == ACCESS_EVENT]
    assert [(e["route"], e["status"], e["log_level"]) for e in access] == [
        (f"{DATASETS}/{{dataset_id}}", 404, "info"),
        ("<unmatched>", 401, "info"),  # ya no es pública: se registra como cualquier otra
    ]


def test_docs_paths_are_fastapi_defaults_and_public_by_default() -> None:
    app = create_app(build_container(auth_settings()))
    served = {app.docs_url, app.redoc_url, app.openapi_url, app.swagger_ui_oauth2_redirect_url}
    assert served == DOCS_PATHS
    assert PUBLIC_PATHS == PROBE_PATHS | DOCS_PATHS
    with TestClient(app) as client:
        assert {client.get(path).status_code for path in DOCS_PATHS} == {200}
