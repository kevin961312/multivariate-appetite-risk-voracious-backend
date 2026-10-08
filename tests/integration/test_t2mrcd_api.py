"""Rutas del ciclo de vida de T²MRCD: éxito, 404 de otro tenant, 409 y 422 por endpoint (T10)."""

import threading
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from support.api import (
    BASE,
    CHART_BASE,
    FAST_PARAMS,
    OTHER,
    T0,
    TENANT,
    observations,
    score,
    train,
    upload,
    wait,
)
from support.solo_test import small_data
from voracious.api.app import create_app
from voracious.config import Settings
from voracious.container import build_container
from voracious.domain.charts.t2mrcd import T2MRCDChart, T2MRCDModel

END = (T0 + timedelta(hours=29)).isoformat()


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app(build_container(Settings()))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def scored(client: TestClient) -> dict[str, Any]:
    """Modelo entrenado con 30 observaciones puntuadas (filas 3 y 7 con señal). Solo lectura."""
    model_id = train(client)
    result = score(client, model_id, observations(30))
    return {"model_id": model_id, "observation_ids": result["result"]["observation_ids"]}


def _error(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    assert set(body) == {"code", "message", "details"}
    return body


# --- tenant ---------------------------------------------------------------------


@pytest.mark.parametrize("headers", [{}, {"X-Tenant-ID": "a b"}, {"X-Tenant-ID": "x" * 65}])
def test_tenant_is_required_and_validated(client: TestClient, headers: dict[str, str]) -> None:
    _error(client.get(f"{BASE}/nada", headers=headers), 400, "TENANT_REQUIRED")


# --- modelos --------------------------------------------------------------------


def test_model_get_and_includes(client: TestClient, scored: dict[str, Any]) -> None:
    url = f"{BASE}/{scored['model_id']}"
    body = client.get(url, headers=TENANT).json()
    assert body["status"] == "succeeded"
    assert (body["n_rows"], body["n_features"]) == (40, 4)
    assert body["training_data"] is None
    assert body["result"]["mrcd"]["cov"] is None
    assert body["result"]["historical_t2"] is None
    assert body["result"]["limit_regime"] == "phase1_provisional"
    assert body["lifecycle_policy"]["revalidate_every_months"] == 6
    full = client.get(
        url,
        headers=TENANT,
        params=[("include", "training_data"), ("include", "covariance"), ("include", "historical")],
    ).json()
    assert len(full["training_data"]) == 40
    assert len(full["result"]["mrcd"]["cov"]) == 4
    assert len(full["result"]["historical_t2"]) == 40
    _error(client.get(url, headers=TENANT, params={"include": "todo"}), 422, "INVALID_INPUT")
    _error(client.get(url, headers=OTHER), 404, "MODEL_NOT_FOUND")


def test_model_post_only_accepts_references(client: TestClient) -> None:
    retired = {"training_data": [[1.0, 2.0], [3.0, 4.0]], "params": FAST_PARAMS}
    body = _error(client.post(BASE, headers=TENANT, json=retired), 422, "INVALID_INPUT")
    assert "errors" in body["details"]


def test_model_params_and_policy_are_passed(client: TestClient) -> None:
    body = {
        "params": {**FAST_PARAMS, "mrcd": {"maxcsteps": 100}, "max_depuration_rounds": 1},
        "lifecycle_policy": {"revalidate_every_months": None, "revalidate_every_observations": 5},
    }
    model_id = train(client, seed=9, body=body)
    model = client.get(f"{BASE}/{model_id}", headers=TENANT).json()
    assert model["status"] == "succeeded"
    assert model["lifecycle_policy"] == {
        "revalidate_every_months": None,
        "revalidate_every_observations": 5,
    }
    assert model["params"]["mrcd"]["maxcsteps"] == 100
    assert model["params"]["max_depuration_rounds"] == 1
    assert model["result"]["mrcd"]["alpha"] == pytest.approx(0.75, abs=0.05)
    assert model["provenance"]["root_dataset_id"]


_RELEASE = threading.Event()


class _BlockingChart(T2MRCDChart):
    """T²MRCD cuyo ensamblado espera a ``_RELEASE`` (para ver el modelo antes de que termine)."""

    def assemble_model(self, *args: object, **kwargs: object) -> T2MRCDModel:
        assert _RELEASE.wait(timeout=60)
        return super().assemble_model(*args, **kwargs)


def test_post_returns_202_before_the_job_finishes() -> None:
    chart = _BlockingChart()
    container = build_container(Settings(), charts={"t2mrcd": chart})
    with TestClient(create_app(container)) as client:
        dataset_id = upload(client, small_data(40, 4))
        fit = client.post(f"{CHART_BASE}/fits", headers=TENANT, json={"dataset_id": dataset_id})
        fit_id = fit.json()["id"]
        assert wait(client, f"{CHART_BASE}/fits/{fit_id}")["status"] == "succeeded"
        limits = client.post(
            f"{CHART_BASE}/limits", headers=TENANT, json={"fit_id": fit_id, "params": FAST_PARAMS}
        )
        limits_id = limits.json()["id"]
        assert wait(client, f"{CHART_BASE}/limits/{limits_id}")["status"] == "succeeded"
        response = client.post(
            BASE, headers=TENANT, json={"fit_id": fit_id, "limits_id": limits_id}
        )
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        model_id = response.json()["id"]
        url = f"{BASE}/{model_id}"
        assert client.get(url, headers=TENANT).json()["status"] in {"queued", "running"}
        _error(
            client.post(f"{url}/scores", headers=TENANT, json={"observations": observations(2)}),
            409,
            "MODEL_NOT_READY",
        )
        _error(client.get(f"{url}/status", headers=TENANT), 409, "MODEL_NOT_READY")
        _RELEASE.set()
        assert wait(client, url)["status"] == "succeeded"


# --- puntuaciones y observaciones --------------------------------------------------


def test_scores(client: TestClient, scored: dict[str, Any]) -> None:
    model_url = f"{BASE}/{scored['model_id']}"
    later = T0 + timedelta(days=30)
    done = score(client, scored["model_id"], observations(3, seed=1, shifted=(), start=later))
    assert done["n_observations"] == 3
    assert done["batch_label"] == "b1"
    assert done["result"]["version_numbers"] == [0, 0, 0]
    _error(
        client.get(f"{model_url}/scores/{done['id']}", headers=OTHER), 404, "MONITORING_NOT_FOUND"
    )
    wrong_p = {"observations": [{"observed_at": T0.isoformat(), "values": [1.0, 2.0]}]}
    _error(client.post(f"{model_url}/scores", headers=TENANT, json=wrong_p), 422, "INVALID_INPUT")
    naive = {"observations": [{"observed_at": "2026-03-01T00:00:00", "values": [1.0] * 4}]}
    _error(client.post(f"{model_url}/scores", headers=TENANT, json=naive), 422, "INVALID_INPUT")
    _error(
        client.post(f"{BASE}/nada/scores", headers=TENANT, json={"observations": observations(1)}),
        404,
        "MODEL_NOT_FOUND",
    )


def test_observations_list_and_filters(client: TestClient, scored: dict[str, Any]) -> None:
    url = f"{BASE}/{scored['model_id']}/observations"
    rows = client.get(url, headers=TENANT, params={"from": T0.isoformat(), "to": END}).json()
    assert [r["id"] for r in rows] == scored["observation_ids"]
    assert rows[0]["score_id"]
    signals = client.get(url, headers=TENANT, params={"signals_only": True}).json()
    ids = {r["id"] for r in signals}
    assert {scored["observation_ids"][3], scored["observation_ids"][7]} <= ids
    _error(
        client.get(url, headers=TENANT, params={"from": "2026-03-01T00:00:00"}),
        422,
        "INVALID_INPUT",
    )
    _error(client.get(url, headers=OTHER), 404, "MODEL_NOT_FOUND")


def test_annotations(client: TestClient, scored: dict[str, Any]) -> None:
    model_url = f"{BASE}/{scored['model_id']}"
    signal = scored["observation_ids"][3]
    url = f"{model_url}/observations/{signal}/annotations"
    response = client.post(url, headers=TENANT, json={"assignable_cause": False, "actor": "ana"})
    assert response.status_code == 201
    assert response.json()["observation_id"] == signal
    rows = client.get(f"{model_url}/observations", headers=TENANT, params={"signals_only": True})
    annotated = {r["id"]: r["annotation"] for r in rows.json()}
    assert annotated[signal]["actor"] == "ana"
    quiet = next(
        r["id"]
        for r in client.get(f"{model_url}/observations", headers=TENANT).json()
        if not r["signal"]
    )
    _error(
        client.post(
            f"{model_url}/observations/{quiet}/annotations",
            headers=TENANT,
            json={"assignable_cause": True},
        ),
        409,
        "NOT_A_SIGNAL",
    )
    _error(
        client.post(url, headers=OTHER, json={"assignable_cause": True}),
        404,
        "OBSERVATION_NOT_FOUND",
    )
    _error(
        client.post(url, headers=TENANT, json={"assignable_cause": True, "x": 1}),
        422,
        "INVALID_INPUT",
    )


# --- versiones y estado ---------------------------------------------------------------


def test_versions_and_status(client: TestClient, scored: dict[str, Any]) -> None:
    model_url = f"{BASE}/{scored['model_id']}"
    versions = client.get(f"{model_url}/versions", headers=TENANT).json()
    assert [(v["number"], v["status"]) for v in versions] == [(0, "active")]
    assert versions[0]["justification"] == "initial_fit"
    detail = client.get(f"{model_url}/versions/0", headers=TENANT).json()
    assert detail["base_data"] is None
    assert detail["report"] is None
    assert detail["model"]["n_base"] == detail["n_base"]
    full = client.get(
        f"{model_url}/versions/0",
        headers=TENANT,
        params=[("include", "base_data"), ("include", "base_refs")],
    ).json()
    assert len(full["base_data"]) == detail["n_base"]
    assert len(full["base_refs"]) == detail["n_base"]
    assert len(full["exclusions"]) == detail["n_exclusions"]
    _error(client.get(f"{model_url}/versions/9", headers=TENANT), 404, "VERSION_NOT_FOUND")
    _error(client.get(f"{model_url}/versions/0", headers=OTHER), 404, "VERSION_NOT_FOUND")
    _error(client.get(f"{model_url}/versions", headers=OTHER), 404, "MODEL_NOT_FOUND")
    _error(
        client.post(f"{model_url}/versions/0/approve", headers=TENANT), 409, "VERSION_NOT_PROPOSED"
    )
    _error(
        client.post(f"{model_url}/versions/0/reject", headers=TENANT, json={}),
        409,
        "VERSION_NOT_PROPOSED",
    )
    _error(
        client.post(f"{model_url}/versions/0/reject", headers=TENANT, json={"x": 1}),
        422,
        "INVALID_INPUT",
    )
    state = client.get(f"{model_url}/status", headers=TENANT).json()
    assert state["status"] == "startup"
    assert state["active_version"] == 0
    assert state["observations_since_active"] >= 30
    _error(client.get(f"{model_url}/status", headers=OTHER), 404, "MODEL_NOT_FOUND")


# --- recalibraciones y eventos --------------------------------------------------------


def _recalibrate(client: TestClient, model_id: str, **extra: object) -> httpx.Response:
    body: dict[str, Any] = {
        "range_from": T0.isoformat(),
        "range_to": END,
        "params": {"seed": 11, "min_observations": 20},
        **extra,
    }
    return client.post(f"{BASE}/{model_id}/recalibrations", headers=TENANT, json=body)


def test_recalibration_validation(client: TestClient, scored: dict[str, Any]) -> None:
    model_id = scored["model_id"]
    body = _error(_recalibrate(client, model_id), 422, "RECALIBRATION_DECISION_PENDING")
    assert body["details"]["pending"]
    _error(
        _recalibrate(client, model_id, range_to=(T0 + timedelta(hours=2)).isoformat()),
        422,
        "RECALIBRATION_INSUFFICIENT_OBSERVATIONS",
    )
    _error(
        _recalibrate(client, model_id, range_from=END, range_to=T0.isoformat()),
        422,
        "INVALID_INPUT",
    )
    _error(_recalibrate(client, model_id, params={"seed": 1, "x": 2}), 422, "INVALID_INPUT")
    _error(_recalibrate(client, "nada", force_replace=True), 404, "MODEL_NOT_FOUND")
    _error(
        client.get(f"{BASE}/{model_id}/recalibrations/nada", headers=TENANT),
        404,
        "RECALIBRATION_NOT_FOUND",
    )


def test_forced_recalibration_proposal_and_reject(client: TestClient) -> None:
    model_id = train(client, seed=21)
    score(client, model_id, observations(30))
    response = _recalibrate(client, model_id, force_replace=True, actor="ana")
    assert response.status_code == 202
    rid = response.json()["id"]
    url = f"{BASE}/{model_id}/recalibrations/{rid}"
    done = wait(client, url)
    assert done["status"] == "succeeded", done
    assert done["outcome"] == "replace"
    assert done["proposed_version"] == 1
    assert done["report"]["forced"] is True
    assert done["report"]["row_disposition"] is None
    full = client.get(url, headers=TENANT, params={"include": "row_disposition"}).json()
    assert len(full["report"]["row_disposition"]) == full["report"]["n_base"] + 30
    _error(client.get(url, headers=OTHER), 404, "RECALIBRATION_NOT_FOUND")
    _error(_recalibrate(client, model_id, force_replace=True), 409, "PROPOSAL_PENDING")
    state = client.get(f"{BASE}/{model_id}/status", headers=TENANT).json()
    assert (state["status"], state["proposed_version"]) == ("proposal_pending", 1)
    retro = {"effective_from": T0.isoformat()}
    _error(
        client.post(f"{BASE}/{model_id}/versions/1/approve", headers=TENANT, json=retro),
        409,
        "EFFECTIVE_FROM_NOT_AFTER_SCORED",
    )
    _error(
        client.post(f"{BASE}/{model_id}/versions/1/reject", headers=OTHER), 404, "VERSION_NOT_FOUND"
    )
    rejected = client.post(
        f"{BASE}/{model_id}/versions/1/reject", headers=TENANT, json={"note": "no", "actor": "luis"}
    )
    assert rejected.status_code == 200
    assert (rejected.json()["status"], rejected.json()["decided_by"]) == ("rejected", "luis")
    detail = client.get(f"{BASE}/{model_id}/versions/1", headers=TENANT).json()
    assert detail["report"]["after"]["regime"] == "phase2"


def test_structural_events(client: TestClient) -> None:
    model_id = train(client, seed=22)
    score(client, model_id, observations(30))
    url = f"{BASE}/{model_id}/structural-events"
    when = (T0 + timedelta(hours=10)).isoformat()
    response = client.post(url, headers=TENANT, json={"occurred_at": when, "description": "fusión"})
    assert response.status_code == 201
    event_id = response.json()["id"]
    assert [e["id"] for e in client.get(url, headers=TENANT).json()] == [event_id]
    _error(client.get(url, headers=OTHER), 404, "MODEL_NOT_FOUND")
    _error(
        client.post(url, headers=OTHER, json={"occurred_at": when, "description": "x"}),
        404,
        "MODEL_NOT_FOUND",
    )
    _error(
        client.post(url, headers=TENANT, json={"occurred_at": when, "description": ""}),
        422,
        "INVALID_INPUT",
    )
    state = client.get(f"{BASE}/{model_id}/status", headers=TENANT).json()
    assert (state["status"], state["unresolved_event_id"]) == ("requires_new_base", event_id)
    _error(_recalibrate(client, model_id), 422, "RANGE_BEFORE_STRUCTURAL_EVENT")


# --- de extremo a extremo ---------------------------------------------------------------


def test_end_to_end_train_score_annotate_recalibrate_approve(client: TestClient) -> None:
    model_id = train(client, seed=31)
    scored = score(client, model_id, observations(30, shifted=(5,)))
    signal = scored["result"]["observation_ids"][5]
    annotation = client.post(
        f"{BASE}/{model_id}/observations/{signal}/annotations",
        headers=TENANT,
        json={"assignable_cause": True, "cause": "error de carga", "action": "corregido"},
    )
    assert annotation.status_code == 201
    response = _recalibrate(client, model_id, force_replace=True)
    assert response.status_code == 202
    recalibration = wait(client, f"{BASE}/{model_id}/recalibrations/{response.json()['id']}")
    assert recalibration["status"] == "succeeded", recalibration
    assert recalibration["report"]["n_excluded_assignable_cause"] == 1
    number = recalibration["proposed_version"]
    detail = client.get(
        f"{BASE}/{model_id}/versions/{number}", headers=TENANT, params={"include": "base_refs"}
    )
    excluded = {(e["ref"], e["reason"]) for e in detail.json()["exclusions"]}
    assert (signal, "assignable_cause") in excluded
    approved = client.post(
        f"{BASE}/{model_id}/versions/{number}/approve", headers=TENANT, json={"actor": "ana"}
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"
    state = client.get(f"{BASE}/{model_id}/status", headers=TENANT).json()
    assert (state["status"], state["active_version"]) == ("active", number)
    versions = client.get(f"{BASE}/{model_id}/versions", headers=TENANT).json()
    assert [v["status"] for v in versions] == ["superseded", "active"]


def test_concurrent_recalibration_posts_one_202_one_409(client: TestClient) -> None:
    model_id = train(client, seed=41)
    score(client, model_id, observations(30))
    barrier = threading.Barrier(2)
    responses: list[httpx.Response] = []

    def post() -> None:
        barrier.wait()
        responses.append(_recalibrate(client, model_id, force_replace=True))

    threads = [threading.Thread(target=post) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.status_code for r in responses) == [202, 409]
    conflict = next(r for r in responses if r.status_code == 409).json()["code"]
    # Si la primera ya terminó cuando llega la segunda, el conflicto es la propuesta pendiente.
    assert conflict in {"RECALIBRATION_IN_PROGRESS", "PROPOSAL_PENDING"}
    accepted = next(r for r in responses if r.status_code == 202).json()["id"]
    assert wait(client, f"{BASE}/{model_id}/recalibrations/{accepted}")["status"] == "succeeded"
