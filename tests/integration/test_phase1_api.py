"""Rutas de datasets y de los pasos de Fase I de T²MRCD: 201/202, 404 de otro tenant, 409 y 422."""

import threading
from collections.abc import Iterator
from typing import Any

import httpx2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from support.api import BASE, CHART_BASE, DATASETS, FAST_PARAMS, OTHER, TENANT, upload, wait
from support.solo_test import small_data
from voracious.api.app import create_app
from voracious.config import Settings
from voracious.container import build_container
from voracious.domain.charts.t2mrcd import T2MRCDChart
from voracious.domain.estimators.mrcd import MRCDFit


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app(build_container(Settings()))) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def chain(client: TestClient) -> dict[str, str]:
    """Dataset, ajuste, límites y una exclusión humana ya terminados. Solo lectura."""
    dataset = upload(client, small_data(40, 4, seed=5))
    fit = _accepted(client.post(f"{CHART_BASE}/fits", headers=TENANT, json={"dataset_id": dataset}))
    assert wait(client, f"{CHART_BASE}/fits/{fit}")["status"] == "succeeded"
    limits = _accepted(
        client.post(
            f"{CHART_BASE}/limits", headers=TENANT, json={"fit_id": fit, "params": FAST_PARAMS}
        )
    )
    assert wait(client, f"{CHART_BASE}/limits/{limits}")["status"] == "succeeded"
    exclusion = _accepted(
        client.post(
            f"{CHART_BASE}/exclusions",
            headers=TENANT,
            json={"dataset_id": dataset, "assignable_cause": [{"row": 3, "cause": "x"}]},
        )
    )
    assert wait(client, f"{CHART_BASE}/exclusions/{exclusion}")["status"] == "succeeded"
    return {"dataset": dataset, "fit": fit, "limits": limits, "exclusion": exclusion}


def _accepted(response: httpx2.Response) -> str:
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    return str(response.json()["id"])


def _error(response: httpx2.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    assert set(body) == {"code", "message", "details"}
    return body


# --- datasets ----------


def test_upload_json_csv_and_multipart_give_the_same_hash(client: TestClient) -> None:
    x = small_data(5, 3, seed=1)
    json_resp = client.post(DATASETS, headers=TENANT, json={"data": x.tolist()})
    assert json_resp.status_code == 201
    body = json_resp.json()
    assert (body["n"], body["p"]) == (5, 3)
    assert body["content_hash"].startswith("sha256:")
    csv_text = "a,b,c\n" + "\n".join(",".join(repr(v) for v in row) for row in x.tolist())
    csv_resp = client.post(
        DATASETS, headers={**TENANT, "content-type": "text/csv"}, content=csv_text
    )
    assert csv_resp.status_code == 201, csv_resp.text
    multipart = client.post(
        DATASETS, headers=TENANT, files={"file": ("x.csv", csv_text.encode(), "text/csv")}
    )
    assert multipart.status_code == 201, multipart.text
    hashes = {r.json()["content_hash"] for r in (json_resp, csv_resp, multipart)}
    assert hashes == {body["content_hash"]}
    assert len({r.json()["dataset_id"] for r in (json_resp, csv_resp, multipart)}) == 3


def test_get_dataset_with_lineage_and_includes(client: TestClient) -> None:
    dataset = upload(client, small_data(4, 2, seed=2))
    url = f"{DATASETS}/{dataset}"
    body = client.get(url, headers=TENANT).json()
    assert body["source"] == "upload"
    assert body["parent_id"] is None
    assert body["data"] is None
    assert [e["dataset_id"] for e in body["lineage"]] == [dataset]
    full = client.get(url, headers=TENANT, params=[("include", "data"), ("include", "rows")])
    assert np.array_equal(np.array(full.json()["data"]), small_data(4, 2, seed=2))
    assert full.json()["rows"] is None
    _error(client.get(url, headers=OTHER), 404, "DATASET_NOT_FOUND")
    _error(client.get(url, headers=TENANT, params={"include": "todo"}), 422, "INVALID_INPUT")


def test_upload_rejects_invalid_data(client: TestClient) -> None:
    headers = {**TENANT, "content-type": "application/json"}
    _error(
        client.post(DATASETS, headers=headers, content='{"data": [[NaN, 1.0]]}'),
        422,
        "INVALID_INPUT",
    )
    _error(
        client.post(DATASETS, headers=TENANT, json={"data": [[1.0]], "x": 1}), 422, "INVALID_INPUT"
    )
    ragged = client.post(DATASETS, headers=TENANT, json={"data": [[1.0, 2.0], [3.0]]})
    assert "errors" not in _error(ragged, 422, "INVALID_INPUT")["details"]
    csv = {**TENANT, "content-type": "text/csv"}
    bad = _error(client.post(DATASETS, headers=csv, content="1,2\n3,x\n"), 422, "INVALID_INPUT")
    assert bad["details"]["cells"] == [{"row": 1, "column": 1}]
    _error(client.post(DATASETS, headers=csv, content="1,nan\n"), 422, "INVALID_INPUT")
    _error(client.post(DATASETS, headers=csv, content="a,b\n"), 422, "INVALID_INPUT")
    _error(client.post(DATASETS, headers=csv, content=b"\xff\xfe"), 422, "INVALID_INPUT")
    missing = client.post(DATASETS, headers=TENANT, files={"other": ("x.csv", b"1,2\n")})
    _error(missing, 422, "INVALID_INPUT")
    plain = {**TENANT, "content-type": "text/plain"}
    _error(client.post(DATASETS, headers=plain, content="1"), 415, "UNSUPPORTED_MEDIA_TYPE")
    _error(client.post(DATASETS, json={"data": [[1.0]]}), 400, "TENANT_REQUIRED")


def test_upload_is_limited_by_max_upload_mb() -> None:
    with TestClient(create_app(build_container(Settings(max_upload_mb=1)))) as small:
        big = "1.0\n" * (300 * 1024)
        csv = {**TENANT, "content-type": "text/csv"}
        body = _error(small.post(DATASETS, headers=csv, content=big), 413, "PAYLOAD_TOO_LARGE")
        assert body["details"]["max_bytes"] == 1024 * 1024
        assert small.post(DATASETS, headers=csv, content="1.0\n2.0\n").status_code == 201


# --- ajustes y límites ----------


def test_fit_get_includes_and_isolation(client: TestClient, chain: dict[str, str]) -> None:
    url = f"{CHART_BASE}/fits/{chain['fit']}"
    body = client.get(url, headers=TENANT).json()
    assert body["dataset_id"] == chain["dataset"]
    assert body["params"]["alpha"] == 0.75
    assert body["result"]["cov"] is None
    full = client.get(url, headers=TENANT, params={"include": "covariance"}).json()
    assert len(full["result"]["cov"]) == 4
    _error(client.get(url, headers=OTHER), 404, "FIT_NOT_FOUND")


def test_fit_request_errors(client: TestClient) -> None:
    path = f"{CHART_BASE}/fits"
    _error(client.post(path, headers=TENANT, json={"dataset_id": "nada"}), 404, "DATASET_NOT_FOUND")
    other = upload(client, small_data(10, 2), headers=OTHER)
    _error(client.post(path, headers=TENANT, json={"dataset_id": other}), 404, "DATASET_NOT_FOUND")
    _error(
        client.post(path, headers=TENANT, json={"dataset_id": other, "extra": 1}),
        422,
        "INVALID_INPUT",
    )


def test_fit_with_explicit_alpha(client: TestClient) -> None:
    dataset = upload(client, small_data(40, 4, seed=6))
    fit = _accepted(
        client.post(
            f"{CHART_BASE}/fits",
            headers=TENANT,
            json={"dataset_id": dataset, "mrcd": {"alpha": 0.6}},
        )
    )
    body = wait(client, f"{CHART_BASE}/fits/{fit}")
    assert body["params"]["alpha"] == 0.6
    mismatch = client.post(
        f"{CHART_BASE}/limits", headers=TENANT, json={"fit_id": fit, "params": FAST_PARAMS}
    )
    details = _error(mismatch, 422, "T2MRCD_FIT_PARAMS_MISMATCH")["details"]
    assert details["fit_mrcd"]["alpha"] == 0.6
    assert details["chart_mrcd"]["alpha"] == 0.75
    matching = {**FAST_PARAMS, "mrcd": {"alpha": 0.6}}
    _accepted(
        client.post(
            f"{CHART_BASE}/limits", headers=TENANT, json={"fit_id": fit, "params": matching}
        )
    )


def test_limits_get_and_errors(client: TestClient, chain: dict[str, str]) -> None:
    url = f"{CHART_BASE}/limits/{chain['limits']}"
    body = client.get(url, headers=TENANT).json()
    assert (body["fit_id"], body["stage_kind"]) == (chain["fit"], "phase1")
    assert "round" not in body
    assert body["spawn_key"] == [0, 0]
    assert body["seed"] == 7
    assert body["clean_rows"] is None
    full = client.get(url, headers=TENANT, params={"include": "clean_rows"}).json()
    assert len(full["clean_rows"]) == 40
    assert sum(full["clean_rows"]) == full["result"]["n_clean"]
    _error(client.get(url, headers=OTHER), 404, "LIMITS_NOT_FOUND")
    path = f"{CHART_BASE}/limits"
    _error(
        client.post(path, headers=TENANT, json={"fit_id": "nada", "params": FAST_PARAMS}),
        404,
        "FIT_NOT_FOUND",
    )
    _error(
        client.post(path, headers=OTHER, json={"fit_id": chain["fit"], "params": FAST_PARAMS}),
        404,
        "FIT_NOT_FOUND",
    )
    missing_params = client.post(path, headers=TENANT, json={"fit_id": chain["fit"]})
    assert _error(missing_params, 422, "INVALID_INPUT")["details"]["reason"] == "params_required"
    both = {"fit_id": chain["fit"], "params": FAST_PARAMS, "recalibration_id": "r"}
    _error(client.post(path, headers=TENANT, json=both), 422, "INVALID_INPUT")


class _SlowFitChart(T2MRCDChart):
    """T²MRCD cuyo ajuste suelto espera a ``_RELEASE`` (ajuste en curso)."""

    def fit_estimator(self, *args: object, **kwargs: object) -> MRCDFit:
        assert _RELEASE.wait(timeout=60)
        return super().fit_estimator(*args, **kwargs)


_RELEASE = threading.Event()


def test_steps_on_unfinished_resources_are_409() -> None:
    container = build_container(Settings(), charts={"t2mrcd": _SlowFitChart()})
    with TestClient(create_app(container)) as slow:
        dataset = upload(slow, small_data(40, 4))
        fit = _accepted(
            slow.post(f"{CHART_BASE}/fits", headers=TENANT, json={"dataset_id": dataset})
        )
        _error(
            slow.post(
                f"{CHART_BASE}/limits", headers=TENANT, json={"fit_id": fit, "params": FAST_PARAMS}
            ),
            409,
            "FIT_NOT_READY",
        )
        _error(
            slow.post(BASE, headers=TENANT, json={"fit_id": fit, "limits_id": "nada"}),
            409,
            "FIT_NOT_READY",
        )
        # La exclusión humana referencia el dataset: no espera a ningún ajuste.
        _accepted(
            slow.post(
                f"{CHART_BASE}/exclusions",
                headers=TENANT,
                json={"dataset_id": dataset, "assignable_cause": [{"row": 0}]},
            )
        )
        _RELEASE.set()
        assert wait(slow, f"{CHART_BASE}/fits/{fit}")["status"] == "succeeded"


# --- exclusiones humanas ----------


def test_exclusion_get_and_includes(client: TestClient, chain: dict[str, str]) -> None:
    url = f"{CHART_BASE}/exclusions/{chain['exclusion']}"
    body = client.get(url, headers=TENANT).json()
    assert body["dataset_id"] == chain["dataset"]
    assert (body["insufficient"], body["n_kept"], body["n_excluded_assignable_cause"]) == (
        False,
        39,
        1,
    )
    assert body["assignable_cause"] == [{"row": 3, "cause": "x", "annotation_id": None}]
    assert body["row_disposition"] is None
    assert not {"fit_id", "limits_id", "round", "converged", "next_step"} & set(body)
    full = client.get(url, headers=TENANT, params={"include": "row_disposition"}).json()
    assert len(full["row_disposition"]) == 40
    assert full["row_disposition"][3] == "excluded_assignable_cause"
    _error(client.get(url, headers=OTHER), 404, "EXCLUSION_NOT_FOUND")
    derived = client.get(
        f"{DATASETS}/{body['output_dataset_id']}", headers=TENANT, params={"include": "rows"}
    ).json()
    assert derived["source"] == "exclusion_output"
    assert derived["origin_ref"] == chain["exclusion"]
    assert 3 not in derived["rows"]


def test_exclusion_request_errors(client: TestClient, chain: dict[str, str]) -> None:
    path = f"{CHART_BASE}/exclusions"
    dataset, fit, limits = chain["dataset"], chain["fit"], chain["limits"]
    # El modo automático ``{fit_id, limits_id}`` ya no existe (dueño, 2026-10-09).
    for body in (
        {"fit_id": fit, "limits_id": limits},
        {"dataset_id": dataset, "fit_id": fit, "limits_id": limits},
        {"assignable_cause": [{"row": 1}]},
    ):
        _error(client.post(path, headers=TENANT, json=body), 422, "INVALID_INPUT")
    no_rows = client.post(path, headers=TENANT, json={"dataset_id": dataset})
    assert _error(no_rows, 422, "INVALID_INPUT")["details"]["reason"] == (
        "assignable_cause_required"
    )
    out = {"dataset_id": dataset, "assignable_cause": [{"row": 40}]}
    _error(client.post(path, headers=TENANT, json=out), 422, "INVALID_INPUT")
    repeated = {"dataset_id": dataset, "assignable_cause": [{"row": 1}, {"row": 1}]}
    _error(client.post(path, headers=TENANT, json=repeated), 422, "INVALID_INPUT")
    every = {"dataset_id": dataset, "assignable_cause": [{"row": i} for i in range(40)]}
    _error(client.post(path, headers=TENANT, json=every), 422, "INVALID_INPUT")
    negative = {"dataset_id": dataset, "assignable_cause": [{"row": -1}]}
    _error(client.post(path, headers=TENANT, json=negative), 422, "INVALID_INPUT")
    other = {"dataset_id": dataset, "assignable_cause": [{"row": 1}]}
    _error(client.post(path, headers=OTHER, json=other), 404, "DATASET_NOT_FOUND")
    old = client.post(f"{CHART_BASE}/depurations", headers=TENANT, json=other)
    assert old.status_code == 404


def test_limits_of_another_fit_are_a_mismatch(client: TestClient, chain: dict[str, str]) -> None:
    dataset = upload(client, small_data(40, 4, seed=8))
    other_fit = _accepted(
        client.post(f"{CHART_BASE}/fits", headers=TENANT, json={"dataset_id": dataset})
    )
    assert wait(client, f"{CHART_BASE}/fits/{other_fit}")["status"] == "succeeded"
    body = {"fit_id": other_fit, "limits_id": chain["limits"]}
    _error(client.post(BASE, headers=TENANT, json=body), 422, "LIMITS_FIT_MISMATCH")


# --- modelos y tuberías ----------


def test_model_request_errors(client: TestClient, chain: dict[str, str]) -> None:
    _error(client.post(BASE, headers=TENANT, json={}), 422, "INVALID_INPUT")
    _error(client.post(BASE, headers=TENANT, json={"fit_id": chain["fit"]}), 422, "INVALID_INPUT")
    legacy = {"depuration_id": chain["exclusion"]}
    _error(client.post(BASE, headers=TENANT, json=legacy), 422, "INVALID_INPUT")
    refs = {"fit_id": chain["fit"], "limits_id": chain["limits"]}
    _error(client.post(BASE, headers=OTHER, json=refs), 404, "FIT_NOT_FOUND")
    missing = {"fit_id": chain["fit"], "limits_id": "nada"}
    _error(client.post(BASE, headers=TENANT, json=missing), 404, "LIMITS_NOT_FOUND")


def test_pipeline_get_errors_and_isolation(client: TestClient) -> None:
    path = f"{CHART_BASE}/pipelines/phase1"
    _error(
        client.post(path, headers=TENANT, json={"dataset_id": "nada", "params": FAST_PARAMS}),
        404,
        "DATASET_NOT_FOUND",
    )
    dataset = upload(client, small_data(40, 4, seed=4))
    out = {"dataset_id": dataset, "params": FAST_PARAMS, "assignable_cause": [{"row": 99}]}
    _error(client.post(path, headers=TENANT, json=out), 422, "INVALID_INPUT")
    pipeline = _accepted(
        client.post(path, headers=TENANT, json={"dataset_id": dataset, "params": FAST_PARAMS})
    )
    body = wait(client, f"{path}/{pipeline}")
    assert body["status"] == "succeeded"
    assert body["kind"] == "phase1"
    assert [s["kind"] for s in body["steps"]] == ["fit", "limits", "model"]
    _error(client.get(f"{path}/{pipeline}", headers=OTHER), 404, "PIPELINE_NOT_FOUND")
    _error(client.get(f"{path}/nada", headers=TENANT), 404, "PIPELINE_NOT_FOUND")
