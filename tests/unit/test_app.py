import pytest
from fastapi.testclient import TestClient

from voracious.api.app import create_app
from voracious.application.ports import JobKind, JobRequest
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


EXPECTED_ROUTES = [
    ("GET", "/health"),
    ("GET", "/ready"),
    ("POST", "/v1/datasets"),
    ("GET", "/v1/datasets/{dataset_id}"),
    ("POST", "/v1/charts/t2mrcd/fits"),
    ("GET", "/v1/charts/t2mrcd/fits/{fit_id}"),
    ("POST", "/v1/charts/t2mrcd/limits"),
    ("GET", "/v1/charts/t2mrcd/limits/{limits_id}"),
    ("POST", "/v1/charts/t2mrcd/depurations"),
    ("GET", "/v1/charts/t2mrcd/depurations/{depuration_id}"),
    ("POST", "/v1/charts/t2mrcd/pipelines/phase1"),
    ("GET", "/v1/charts/t2mrcd/pipelines/phase1/{pipeline_id}"),
    ("POST", "/v1/charts/t2mrcd/models"),
    ("GET", "/v1/charts/t2mrcd/models/{model_id}"),
    ("GET", "/v1/charts/t2mrcd/models/{model_id}/status"),
    ("POST", "/v1/charts/t2mrcd/models/{model_id}/scores"),
    ("GET", "/v1/charts/t2mrcd/models/{model_id}/scores/{score_id}"),
    ("GET", "/v1/charts/t2mrcd/models/{model_id}/observations"),
    ("POST", "/v1/charts/t2mrcd/models/{model_id}/observations/{observation_id}/annotations"),
    ("POST", "/v1/charts/t2mrcd/models/{model_id}/structural-events"),
    ("GET", "/v1/charts/t2mrcd/models/{model_id}/structural-events"),
    ("GET", "/v1/charts/t2mrcd/models/{model_id}/versions"),
    ("GET", "/v1/charts/t2mrcd/models/{model_id}/versions/{number}"),
    ("POST", "/v1/charts/t2mrcd/models/{model_id}/versions/{number}/approve"),
    ("POST", "/v1/charts/t2mrcd/models/{model_id}/versions/{number}/reject"),
    ("POST", "/v1/charts/t2mrcd/models/{model_id}/recalibrations"),
    ("GET", "/v1/charts/t2mrcd/models/{model_id}/recalibrations/{recalibration_id}"),
    ("POST", "/v1/charts/t2mrcd/models/{model_id}/comparisons"),
    ("GET", "/v1/charts/t2mrcd/models/{model_id}/comparisons/{comparison_id}"),
    ("POST", "/v1/charts/t2mrcd/models/{model_id}/versions"),
    ("POST", "/v1/charts/t2mrcd/models/{model_id}/recalibrations/{recalibration_id}/cancel"),
    ("GET", "/v1/charts/t2mrcd/pipelines/{pipeline_id}"),
]


def test_route_snapshot() -> None:
    schema = create_app(build_container(Settings())).openapi()
    routes = [(method.upper(), path) for path, ops in schema["paths"].items() for method in ops]
    assert sorted(routes) == sorted(EXPECTED_ROUTES)
    tags = {t["name"] for t in schema["tags"]}
    used = {tag for ops in schema["paths"].values() for op in ops.values() for tag in op["tags"]}
    assert used == tags


def test_lifespan_shuts_the_queue_down() -> None:
    container = build_container(Settings())
    with TestClient(create_app(container)):
        container.queue.enqueue(JobRequest(JobKind.MRCD_FIT, "t", "t2mrcd", "nope"))
    with pytest.raises(RuntimeError):
        container.queue.enqueue(JobRequest(JobKind.MRCD_FIT, "t", "t2mrcd", "nope"))
