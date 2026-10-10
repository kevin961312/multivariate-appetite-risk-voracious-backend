"""Nombres de variables y fecha de cada fila en los datasets (Paso 4.2, pedido del dueño).

JSON (``variables``, ``observed_at``) y CSV (cabecera con nombres y columna de fecha); se guardan
con el dataset, pasan al modelo (y a la base de la versión 0 con su fecha) y ``/scores`` exige las
mismas variables (``422 VARIABLES_MISMATCH``). No cambian ningún cálculo.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from support.api import BASE, CHART_BASE, DATASETS, FAST_PARAMS, TENANT, observations, wait
from support.bits import canonical
from support.solo_test import small_data, solo_test_chart
from voracious.api.app import create_app
from voracious.config import Settings
from voracious.container import Container, build_container

NAMES = ["renta_fija", "renta_variable", "fx", "commodities"]
START = datetime(2025, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def container() -> Iterator[Container]:
    built = build_container(Settings(), charts={"t2mrcd": solo_test_chart()})
    yield built
    built.shutdown()


@pytest.fixture(scope="module")
def client(container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(container)) as test_client:
        yield test_client


def _dates(n: int) -> list[str]:
    return [(START + timedelta(days=i)).isoformat() for i in range(n)]


def _upload(client: TestClient, body: dict[str, Any], code: int = 201) -> dict[str, Any]:
    response = client.post(DATASETS, headers=TENANT, json=body)
    assert response.status_code == code, response.text
    result: dict[str, Any] = response.json()
    return result


def _named_model(client: TestClient, body: dict[str, Any] | None = None) -> tuple[str, str]:
    x = small_data(40, 4, seed=3)
    created = _upload(client, {"data": x.tolist(), "variables": NAMES, "observed_at": _dates(40)})
    payload = {"dataset_id": created["dataset_id"], "params": FAST_PARAMS, **(body or {})}
    response = client.post(f"{CHART_BASE}/pipelines/phase1", headers=TENANT, json=payload)
    assert response.status_code == 202, response.text
    pipeline = wait(client, f"{CHART_BASE}/pipelines/phase1/{response.json()['id']}")
    assert pipeline["status"] == "succeeded", pipeline
    return str(pipeline["model_id"]), str(created["dataset_id"])


def test_json_upload_keeps_names_and_dates(client: TestClient) -> None:
    offset = timezone(timedelta(hours=-5))
    dates = [datetime(2025, 1, 1, 19, tzinfo=offset), datetime(2025, 1, 2, 19, tzinfo=offset)]
    created = _upload(
        client,
        {
            "data": [[1.0, 2.0], [3.0, 4.0]],
            "variables": [" a ", "b"],
            "observed_at": [d.isoformat() for d in dates],
        },
    )
    assert created["variables"] == ["a", "b"]
    assert created["has_observed_at"] is True
    url = f"{DATASETS}/{created['dataset_id']}"
    plain = client.get(url, headers=TENANT).json()
    assert plain["observed_at"] is None
    assert plain["variables"] == ["a", "b"]
    full = client.get(url, headers=TENANT, params={"include": "observed_at"}).json()
    assert full["observed_at"] == ["2025-01-02T00:00:00Z", "2025-01-03T00:00:00Z"]  # en UTC


@pytest.mark.parametrize(
    ("extra", "field"),
    [
        ({"variables": ["a"]}, "variables"),
        ({"variables": ["a", "a"]}, "variables"),
        ({"observed_at": ["2025-01-01T00:00:00Z"]}, "observed_at"),
    ],
)
def test_json_labels_must_fit_the_matrix(
    client: TestClient, extra: dict[str, Any], field: str
) -> None:
    body = _upload(client, {"data": [[1.0, 2.0], [3.0, 4.0]], **extra}, code=422)
    assert body["code"] == "INVALID_INPUT"
    assert body["details"]["input"] == field


def test_json_dates_need_a_timezone(client: TestClient) -> None:
    body = {"data": [[1.0]], "observed_at": ["2025-01-01T00:00:00"]}
    assert _upload(client, body, code=422)["code"] == "INVALID_INPUT"


def _csv(client: TestClient, text: str, **params: str) -> httpx2.Response:
    return client.post(
        DATASETS,
        headers={**TENANT, "Content-Type": "text/csv"},
        content=text.encode("utf-8"),
        params=params,
    )


def test_csv_header_gives_names_and_date_column(client: TestClient) -> None:
    text = "observed_at,a,b\n2025-01-01T00:00:00+00:00,1,2\n2025-01-02T00:00:00+00:00,3,4\n"
    response = _csv(client, text)
    assert response.status_code == 201, response.text
    created = response.json()
    assert (created["n"], created["p"], created["variables"]) == (2, 2, ["a", "b"])
    detail = client.get(
        f"{DATASETS}/{created['dataset_id']}",
        headers=TENANT,
        params=[("include", "observed_at"), ("include", "data")],
    ).json()
    assert detail["data"] == [[1.0, 2.0], [3.0, 4.0]]
    assert detail["observed_at"] == ["2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"]
    custom = _csv(client, "a,fecha\n1,2025-03-01T00:00:00Z\n", date_column="fecha")
    assert custom.status_code == 201, custom.text
    assert custom.json()["variables"] == ["a"]
    assert custom.json()["has_observed_at"]
    unnamed = _csv(client, "1,2\n3,4\n")
    assert unnamed.json()["variables"] is None
    assert not unnamed.json()["has_observed_at"]
    no_dates = _csv(client, "a,b\n1,2\n")
    assert no_dates.json()["variables"] == ["a", "b"]
    assert not no_dates.json()["has_observed_at"]


@pytest.mark.parametrize(
    "text",
    [
        "observed_at,a\nayer,1\n",
        "observed_at,a\n2025-01-01T00:00:00,1\n",  # sin zona horaria
        "observed_at,a\n2025-01-01T00:00:00Z,1\n2025-01-02T00:00:00Z\n",  # fila sin valor
        "a,a\n1,2\n",  # nombres repetidos
    ],
)
def test_csv_bad_dates_or_names_are_422(client: TestClient, text: str) -> None:
    response = _csv(client, text)
    assert response.status_code == 422, response.text


def test_model_inherits_names_and_dates_and_version_rows_are_dated(client: TestClient) -> None:
    model_id, _ = _named_model(client)
    body = client.get(f"{BASE}/{model_id}", headers=TENANT, params={"include": "observed_at"})
    model = body.json()
    assert model["variables"] == NAMES
    assert model["has_observed_at"] is True
    assert model["observed_at"][0] == "2025-01-01T00:00:00Z"
    assert len(model["observed_at"]) == 40
    v0 = client.get(
        f"{BASE}/{model_id}/versions/0", headers=TENANT, params={"include": "base_refs"}
    )
    refs = v0.json()["base_refs"]
    assert all(r["observed_at"] == model["observed_at"][int(r["ref"])] for r in refs)


def test_exclusion_output_keeps_names_and_dates(client: TestClient, container: Container) -> None:
    model_id, _ = _named_model(client, {"assignable_cause": [{"row": 0}, {"row": 5}]})
    record = container.use_cases.get_model.execute("tenant-a", "t2mrcd", model_id)
    assert record.provenance is not None
    assert record.provenance.exclusion_id is not None
    exclusion = client.get(
        f"{CHART_BASE}/exclusions/{record.provenance.exclusion_id}", headers=TENANT
    ).json()
    out = client.get(
        f"{DATASETS}/{exclusion['output_dataset_id']}",
        headers=TENANT,
        params={"include": "observed_at"},
    ).json()
    assert out["variables"] == NAMES
    assert len(out["observed_at"]) == 38  # sin las filas 0 y 5
    assert out["observed_at"][:5] == [f"2025-01-0{d}T00:00:00Z" for d in (2, 3, 4, 5, 7)]
    v0 = container.use_cases.get_version.execute("tenant-a", "t2mrcd", model_id, 0)
    excluded = {e.ref.ref: e.ref.observed_at for e in v0.exclusions}
    assert excluded == {"0": START, "5": START + timedelta(days=5)}


def _score(client: TestClient, model_id: str, body: dict[str, Any]) -> httpx2.Response:
    return client.post(f"{BASE}/{model_id}/scores", headers=TENANT, json=body)


def test_scores_check_variables(client: TestClient) -> None:
    model_id, _ = _named_model(client)
    rows = observations(3, start=START + timedelta(days=60))
    ok = _score(client, model_id, {"observations": rows, "variables": NAMES})
    assert ok.status_code == 202, ok.text
    assert wait(client, f"{BASE}/{model_id}/scores/{ok.json()['id']}")["status"] == "succeeded"
    assert _score(client, model_id, {"observations": rows}).status_code == 202  # sin nombres
    wrong = _score(client, model_id, {"observations": rows, "variables": NAMES[::-1]})
    assert wrong.status_code == 422
    assert wrong.json()["code"] == "VARIABLES_MISMATCH"
    assert wrong.json()["details"]["expected"] == NAMES
    short = _score(client, model_id, {"observations": rows, "variables": NAMES[:3]})
    assert (short.status_code, short.json()["code"]) == (422, "VARIABLES_MISMATCH")
    narrow = [{**r, "values": r["values"][:3]} for r in rows]
    fewer = _score(client, model_id, {"observations": narrow})
    assert (fewer.status_code, fewer.json()["code"]) == (422, "VARIABLES_MISMATCH")


def test_names_and_dates_do_not_change_the_model(client: TestClient, container: Container) -> None:
    named, _ = _named_model(client)
    x = small_data(40, 4, seed=3)
    plain = _upload(client, {"data": x.tolist()})
    payload = {"dataset_id": plain["dataset_id"], "params": FAST_PARAMS}
    response = client.post(f"{CHART_BASE}/pipelines/phase1", headers=TENANT, json=payload)
    pipeline = wait(client, f"{CHART_BASE}/pipelines/phase1/{response.json()['id']}")
    get = container.use_cases.get_model.execute
    a = get("tenant-a", "t2mrcd", named)
    b = get("tenant-a", "t2mrcd", str(pipeline["model_id"]))
    assert canonical(a.model) == canonical(b.model)
    assert np.array_equal(a.training_data, b.training_data)
    assert b.variables is None
    assert b.observed_at is None
