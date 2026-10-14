"""Endpoints de la recalibración paso a paso (T24): códigos 201/202, 404 de otro tenant, 409 y 422.

``POST …/recalibrations`` (``mode = stepwise``), ``/exclusions`` sobre candidatas,
``…/recalibrations/{id}/extension``, ``/fits``, ``/limits`` con ``recalibration_id`` y
``…/versions``. Sin depuración automática iterativa (decisión del dueño, 2026-10-09) ni
comparación de bases (2026-10-14).
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from support.api import BASE, CHART_BASE, FAST_PARAMS, OTHER, T0, TENANT, observations, score, wait
from support.api import train as train_model
from voracious.api.app import create_app
from voracious.config import Settings
from voracious.container import Container, build_container
from voracious.domain.charts.t2mrcd import T2MRCDChart

N = 30
END = T0 + timedelta(hours=N - 1)
RANGE = {"range_from": T0.isoformat(), "range_to": END.isoformat()}


@pytest.fixture(scope="module")
def container() -> Iterator[Container]:
    built = build_container(Settings(), charts={"t2mrcd": T2MRCDChart()})
    yield built
    built.shutdown()


@pytest.fixture(scope="module")
def client(container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(container)) as test_client:
        yield test_client


def _error(response: httpx2.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body


def _post(
    client: TestClient, path: str, body: dict[str, Any], headers: dict[str, str] = TENANT
) -> httpx2.Response:
    return client.post(path, headers=headers, json=body)


def _ok(client: TestClient, path: str, body: dict[str, Any], code: int = 202) -> dict[str, Any]:
    response = _post(client, path, body)
    assert response.status_code == code, response.text
    result: dict[str, Any] = response.json()
    return result


def _done(client: TestClient, path: str) -> dict[str, Any]:
    body = wait(client, path)
    assert body["status"] == "succeeded", body
    return body


def _fit(client: TestClient, dataset_id: str) -> str:
    fit_id = str(_ok(client, f"{CHART_BASE}/fits", {"dataset_id": dataset_id})["id"])
    _done(client, f"{CHART_BASE}/fits/{fit_id}")
    return fit_id


def _limits(client: TestClient, fit_id: str, rid: str) -> str:
    body = {"fit_id": fit_id, "recalibration_id": rid}
    limits_id = str(_ok(client, f"{CHART_BASE}/limits", body)["id"])
    _done(client, f"{CHART_BASE}/limits/{limits_id}")
    return limits_id


def _exclude(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    exclusion_id = _ok(client, f"{CHART_BASE}/exclusions", body)["id"]
    return _done(client, f"{CHART_BASE}/exclusions/{exclusion_id}")


def _scored(client: TestClient, annotate: bool = True) -> tuple[str, list[str]]:
    model_id = train_model(client)
    done = score(client, model_id, observations(N))
    ids = list(done["result"]["observation_ids"])
    if annotate:
        response = _post(
            client,
            f"{BASE}/{model_id}/observations/{ids[3]}/annotations",
            {"assignable_cause": True, "cause": "carga"},
        )
        assert response.status_code == 201, response.text
    return model_id, ids


def test_stepwise_forced_replace_endpoints(client: TestClient) -> None:
    model_id, _ = _scored(client)
    url = f"{BASE}/{model_id}/recalibrations"
    body = {**RANGE, "params": {"seed": 4, "min_observations": 10}, "force_replace": True}
    stepwise = {**body, "mode": "stepwise"}
    _error(_post(client, url, stepwise, headers=OTHER), 404, "MODEL_NOT_FOUND")
    _error(_post(client, url, {**stepwise, "mode": "x"}), 422, "INVALID_INPUT")
    opened = _ok(client, url, stepwise, 201)
    rid, candidates = opened["recalibration_id"], opened["candidates_dataset_id"]
    _error(_post(client, url, stepwise), 409, "RECALIBRATION_IN_PROGRESS")
    _error(client.get(f"{url}/{rid}", headers=OTHER), 404, "RECALIBRATION_NOT_FOUND")
    session = client.get(f"{url}/{rid}", headers=TENANT).json()
    assert (session["mode"], session["status"], session["n_candidates"]) == (
        "stepwise",
        "running",
        N,
    )
    assert session["inherited_params"]["bootstrap"]["seed"] == 4
    lineage = client.get(f"/v1/datasets/{candidates}", headers=TENANT).json()
    assert lineage["source"] == "recalibration_candidates"
    assert lineage["origin_ref"] == rid

    root_fit = _fit(client, candidates)
    limits_url = f"{CHART_BASE}/limits"
    _error(
        _post(client, limits_url, {"fit_id": root_fit, "params": FAST_PARAMS}),
        422,
        "RECALIBRATION_MISMATCH",
    )
    both = {"fit_id": root_fit, "params": FAST_PARAMS, "recalibration_id": rid}
    _error(_post(client, limits_url, both), 422, "INVALID_INPUT")
    pending_human = _error(
        _post(client, limits_url, {"fit_id": root_fit, "recalibration_id": rid}),
        422,
        "INVALID_INPUT",
    )
    assert pending_human["details"]["reason"] == "human_exclusion_required"
    exclusions = f"{CHART_BASE}/exclusions"
    client_causes = {"dataset_id": candidates, "assignable_cause": [{"row": 1}]}
    reason = _error(_post(client, exclusions, client_causes), 422, "INVALID_INPUT")
    assert reason["details"]["reason"] == "assignable_cause_from_annotations"
    human = _exclude(client, {"dataset_id": candidates})
    assert (human["dataset_id"], human["insufficient"]) == (candidates, False)
    assert human["n_excluded_assignable_cause"] == 1
    assert human["assignable_cause"][0]["annotation_id"]
    fit0 = _fit(client, human["output_dataset_id"])
    again = _error(
        _post(client, exclusions, {"dataset_id": human["output_dataset_id"]}),
        422,
        "INVALID_INPUT",
    )
    assert again["details"]["reason"] == "human_exclusion_only_on_candidates"
    limits0 = _limits(client, fit0, rid)
    fit1 = _fit(client, human["output_dataset_id"])
    limits1 = _limits(client, fit1, rid)
    _error(
        _post(client, f"{CHART_BASE}/models", {"fit_id": fit0, "limits_id": limits0}),
        422,
        "RECALIBRATION_MISMATCH",
    )

    extension = f"{url}/{rid}/extension"
    forced = _error(
        _post(client, extension, {"dataset_id": human["output_dataset_id"]}),
        422,
        "INVALID_INPUT",
    )
    assert forced["details"]["reason"] == "forced_replace_has_no_extension"
    versions = f"{BASE}/{model_id}/versions"
    last = {"recalibration_id": rid, "fit_id": fit0, "limits_id": limits0}
    _error(_post(client, versions, {**last, "comparison_id": "x"}), 422, "INVALID_INPUT")
    mixed = {**last, "limits_id": limits1}
    mismatch = _error(_post(client, versions, mixed), 422, "VERSION_INPUTS_MISMATCH")
    assert mismatch["details"]["reason"] == "limits_of_another_fit"
    _error(_post(client, versions, last, headers=OTHER), 404, "RECALIBRATION_NOT_FOUND")
    _error(_post(client, versions, {**last, "fit_id": "nada"}), 404, "FIT_NOT_FOUND")
    accepted = _ok(client, versions, last)
    assert accepted == {"id": rid, "status": "queued"}
    done = _done(client, f"{url}/{rid}")
    assert done["outcome"] == "replace"
    assert done["proposal"]["status"] == "succeeded"
    _error(_post(client, versions, last), 409, "RECALIBRATION_NOT_IN_PROGRESS")
    _error(
        _post(client, f"{CHART_BASE}/fits", {"dataset_id": candidates}, headers=OTHER),
        404,
        "DATASET_NOT_FOUND",
    )
    _error(
        _post(client, limits_url, {"fit_id": fit0, "recalibration_id": rid}),
        409,
        "RECALIBRATION_NOT_IN_PROGRESS",
    )
    _error(_post(client, url, stepwise), 409, "PROPOSAL_PENDING")


def test_stepwise_extension_endpoints(client: TestClient) -> None:
    model_id, _ = _scored(client)
    url = f"{BASE}/{model_id}/recalibrations"
    body = {**RANGE, "params": {"seed": 11, "min_observations": 10}, "mode": "stepwise"}
    opened = _ok(client, url, body, 201)
    rid, candidates = opened["recalibration_id"], opened["candidates_dataset_id"]
    extension = f"{url}/{rid}/extension"
    human_first = _error(_post(client, extension, {"dataset_id": candidates}), 422, "INVALID_INPUT")
    assert human_first["details"]["reason"] == "human_exclusion_required"
    new_rows = _error(
        _post(client, f"{CHART_BASE}/fits", {"dataset_id": candidates}), 422, "INVALID_INPUT"
    )
    assert new_rows["details"]["reason"] == "new_rows_require_replace"
    human = _exclude(client, {"dataset_id": candidates})
    kept = human["output_dataset_id"]
    _error(
        _post(client, extension, {"dataset_id": kept}, headers=OTHER),
        404,
        "RECALIBRATION_NOT_FOUND",
    )
    _error(
        _post(client, f"{url}/nada/extension", {"dataset_id": kept}),
        404,
        "RECALIBRATION_NOT_FOUND",
    )
    _error(_post(client, extension, {"dataset_id": "nada"}), 404, "DATASET_NOT_FOUND")
    _error(_post(client, extension, {"dataset_id": kept, "x": 1}), 422, "INVALID_INPUT")
    _error(_post(client, extension, {}), 422, "INVALID_INPUT")
    built = _ok(client, extension, {"dataset_id": kept}, 201)
    assert built["n_kept_new"] == N - 1
    assert _ok(client, extension, {"dataset_id": kept}, 201) == built  # idempotente
    lineage = client.get(f"/v1/datasets/{built['dataset_id']}", headers=TENANT).json()
    assert lineage["source"] == "recalibration_extension"
    assert lineage["n"] == built["n_base"] + built["n_kept_new"]
    session = client.get(f"{url}/{rid}", headers=TENANT).json()
    assert (session["kept_dataset_id"], session["extension_dataset_id"]) == (
        kept,
        built["dataset_id"],
    )
    on_extension = _error(
        _post(client, f"{CHART_BASE}/exclusions", {"dataset_id": built["dataset_id"]}),
        422,
        "INVALID_INPUT",
    )
    assert on_extension["details"]["reason"] == "human_exclusion_only_on_candidates"
    ext_fit = _fit(client, built["dataset_id"])
    ext_limits = _limits(client, ext_fit, rid)
    versions = f"{BASE}/{model_id}/versions"
    proposal = {"recalibration_id": rid, "fit_id": ext_fit, "limits_id": ext_limits}
    _error(_post(client, versions, {**proposal, "comparison_id": "x"}), 422, "INVALID_INPUT")
    _ok(client, versions, proposal)
    done = _done(client, f"{url}/{rid}")
    assert done["outcome"] == "extend"
    assert "comparison_id" not in done["proposal"]
    assert "forced" not in done["report"]
    version = client.get(f"{versions}/{done['proposed_version']}", headers=TENANT).json()
    assert (version["status"], version["justification"]) == ("proposed", "default_extend")
    _error(_post(client, extension, {"dataset_id": kept}), 409, "RECALIBRATION_NOT_IN_PROGRESS")


def test_cancel_stepwise_session_frees_d6(client: TestClient) -> None:
    model_id, _ = _scored(client, annotate=False)
    url = f"{BASE}/{model_id}/recalibrations"
    body = {**RANGE, "params": {"seed": 6, "min_observations": 10}, "force_replace": True}
    opened = _ok(client, url, {**body, "mode": "stepwise"}, 201)
    rid = opened["recalibration_id"]
    cancel = f"{url}/{rid}/cancel"
    _error(client.post(cancel, headers=OTHER), 404, "RECALIBRATION_NOT_FOUND")
    _error(client.post(f"{url}/nada/cancel", headers=TENANT), 404, "RECALIBRATION_NOT_FOUND")
    response = client.post(cancel, headers=TENANT)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert response.json()["finished_at"] is not None
    again = _error(client.post(cancel, headers=TENANT), 409, "RECALIBRATION_NOT_IN_PROGRESS")
    assert again["details"]["status"] == "cancelled"
    # Los pasos sobre los datasets de una sesión cerrada ya no se aceptan (ni el ajuste).
    _error(
        _post(client, f"{CHART_BASE}/fits", {"dataset_id": opened["candidates_dataset_id"]}),
        409,
        "RECALIBRATION_NOT_IN_PROGRESS",
    )

    reopened = _ok(client, url, {**body, "mode": "stepwise"}, 201)
    rid2 = reopened["recalibration_id"]
    fit2 = _fit(client, reopened["candidates_dataset_id"])
    last = {"recalibration_id": rid2, "fit_id": fit2, "limits_id": _limits(client, fit2, rid2)}
    _ok(client, f"{BASE}/{model_id}/versions", last)
    _done(client, f"{url}/{rid2}")
    requested = _error(
        client.post(f"{url}/{rid2}/cancel", headers=TENANT), 409, "RECALIBRATION_NOT_IN_PROGRESS"
    )
    assert requested["details"]["proposal_requested"] is True
    number = client.get(f"{url}/{rid2}", headers=TENANT).json()["proposed_version"]
    reject = client.post(f"{BASE}/{model_id}/versions/{number}/reject", headers=TENANT)
    assert reject.status_code == 200, reject.text

    piped = _ok(client, url, body)
    pipeline_mode = _error(
        client.post(f"{url}/{piped['id']}/cancel", headers=TENANT),
        409,
        "RECALIBRATION_NOT_IN_PROGRESS",
    )
    assert pipeline_mode["details"]["mode"] == "pipeline"
    done = _done(client, f"{url}/{piped['id']}")
    generic = client.get(f"{CHART_BASE}/pipelines/{done['pipeline_id']}", headers=TENANT)
    alias = client.get(f"{CHART_BASE}/pipelines/phase1/{done['pipeline_id']}", headers=TENANT)
    assert generic.status_code == alias.status_code == 200
    assert generic.json() == alias.json()
    assert generic.json()["kind"] == "recalibration"
    assert generic.json()["recalibration_id"] == piped["id"]
    _error(
        client.get(f"{CHART_BASE}/pipelines/{done['pipeline_id']}", headers=OTHER),
        404,
        "PIPELINE_NOT_FOUND",
    )
