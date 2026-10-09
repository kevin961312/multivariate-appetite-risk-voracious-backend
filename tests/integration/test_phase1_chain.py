"""Equivalencia por API (T20): cadena manual por HTTP = tubería = ``fit_phase1``, en bits.

Caso contaminado con exclusión humana (``composition_cases.phase1_cases()["human_exclusion"]``).
Sin depuración automática iterativa (decisión del dueño, 2026-10-09). La cadena manual sube el
histórico, excluye las filas con causa asignable referenciando el dataset (``/exclusions``, sin
ajuste), ajusta, calibra y pide el modelo con ``{fit_id, limits_id}``. La tubería hace lo mismo
con una sola petición. Los tres modelos se comparan en su forma canónica (``support.bits``:
arreglos por ``tobytes`` y reales por ``float.hex``), sin tolerancia. Cada recurso intermedio se
consulta.
"""

from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from support.api import CHART_BASE, DATASETS, TENANT, upload, wait
from support.bits import canonical
from support.composition_cases import Phase1Case, phase1_cases
from voracious.api.app import create_app
from voracious.config import Settings
from voracious.container import Container, build_container
from voracious.domain.charts.t2mrcd import SLOT_PHASE1, T2MRCDChart, T2MRCDModel
from voracious.domain.common import SerialTaskMapper

CASE = phase1_cases()["human_exclusion"]
PARAMS: dict[str, Any] = {"bootstrap": {"seed": 8, "n_replicates": 5}}
"""Los de ``fast_params(seed=8)`` (B reducido por velocidad, SOLO TEST)."""


@pytest.fixture(scope="module")
def container() -> Iterator[Container]:
    built = build_container(Settings())
    yield built
    built.shutdown()


@pytest.fixture(scope="module")
def client(container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(container)) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def reference() -> T2MRCDModel:
    """``fit_phase1`` directo sobre el mismo caso."""
    return T2MRCDChart().fit_phase1(
        CASE.x, CASE.params, mapper=SerialTaskMapper(), excluded=CASE.excluded
    )


def _post(client: TestClient, path: str, body: dict[str, Any]) -> str:
    response = client.post(f"{CHART_BASE}/{path}", headers=TENANT, json=body)
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def _done(client: TestClient, path: str) -> dict[str, Any]:
    body = wait(client, f"{CHART_BASE}/{path}")
    assert body["status"] == "succeeded", body
    return body


def _model(container: Container, model_id: str) -> object:
    return container.use_cases.get_model.execute("tenant-a", "t2mrcd", model_id).model


def _human() -> list[dict[str, Any]]:
    assert CASE.excluded is not None
    return [{"row": int(i), "cause": "evento"} for i in np.flatnonzero(CASE.excluded)]


def _error(client: TestClient, path: str, body: dict[str, Any], code: str) -> dict[str, Any]:
    response = client.post(f"{CHART_BASE}/{path}", headers=TENANT, json=body)
    assert response.status_code == 422, response.text
    error: dict[str, Any] = response.json()
    assert error["code"] == code
    return error


def _manual_chain(client: TestClient, x: np.ndarray) -> tuple[str, str, str, str]:
    """Cadena manual por HTTP; devuelve modelo, exclusión, ajuste y límites."""
    root = upload(client, x)
    human = _post(client, "exclusions", {"dataset_id": root, "assignable_cause": _human()})
    body = _done(client, f"exclusions/{human}")
    assert body["dataset_id"] == root
    assert (body["insufficient"], body["n_excluded_assignable_cause"]) == (False, 4)
    dataset = body["output_dataset_id"]
    fit = _post(client, "fits", {"dataset_id": dataset})
    assert _done(client, f"fits/{fit}")["dataset_id"] == dataset
    limits = _post(client, "limits", {"fit_id": fit, "params": PARAMS})
    limits_body = _done(client, f"limits/{limits}")
    assert limits_body["stage_kind"] == "phase1"
    assert "round" not in limits_body
    assert limits_body["spawn_key"] == [SLOT_PHASE1, 0]
    model_id = _post(client, "models", {"fit_id": fit, "limits_id": limits})
    model = wait(client, f"{CHART_BASE}/models/{model_id}")
    assert model["status"] == "succeeded", model
    return model_id, human, fit, limits


def test_case_has_human_exclusion_and_rows_above_the_limit(reference: T2MRCDModel) -> None:
    assert CASE.excluded is not None
    assert CASE.excluded.sum() == 4
    # Sin depuración automática las filas por encima del límite siguen en la base.
    assert np.array_equal(reference.base_mask, ~CASE.excluded)
    assert bool(reference.historical_outlier[reference.base_mask].any())


def test_manual_chain_matches_fit_phase1_in_bits(
    client: TestClient, container: Container, reference: T2MRCDModel
) -> None:
    model_id, human, fit, limits = _manual_chain(client, CASE.x)
    model = wait(client, f"{CHART_BASE}/models/{model_id}")
    root = model["provenance"]["root_dataset_id"]
    assert model["provenance"] == {
        "root_dataset_id": root,
        "fit_id": fit,
        "limits_id": limits,
        "exclusion_id": human,
    }
    assert "depuration_rounds" not in model["result"]
    derived = _done(client, f"exclusions/{human}")["output_dataset_id"]
    lineage = client.get(f"{DATASETS}/{derived}", headers=TENANT).json()
    assert "lineage_round" not in lineage
    assert lineage["source"] == "exclusion_output"
    assert lineage["lineage"][0]["dataset_id"] == root
    assert [e["origin_ref"] for e in lineage["lineage"][1:]] == [human]
    assert canonical(_model(container, model_id)) == canonical(reference)


def test_overflowing_row_excluded_by_assignable_cause_matches_fit_phase1(
    client: TestClient, container: Container
) -> None:
    # Una fila finita cuya suma desborda: ``fit_phase1`` la quita antes de ajustar y termina
    # bien. La cadena tampoco la ajusta nunca (la exclusión humana no necesita ajuste).
    assert CASE.excluded is not None
    x = CASE.x.copy()
    x[int(np.flatnonzero(CASE.excluded)[0])] = 1.5e308
    reference = T2MRCDChart().fit_phase1(
        x, CASE.params, mapper=SerialTaskMapper(), excluded=CASE.excluded
    )
    model_id, *_ = _manual_chain(client, x)
    assert canonical(_model(container, model_id)) == canonical(reference)
    root = upload(client, x)
    pipeline = _post(
        client,
        "pipelines/phase1",
        {"dataset_id": root, "params": PARAMS, "assignable_cause": _human()},
    )
    body = _done(client, f"pipelines/phase1/{pipeline}")
    assert canonical(_model(container, body["model_id"])) == canonical(reference)


def test_exclusions_and_limits_contract(client: TestClient) -> None:
    root = upload(client, CASE.x)
    human = _post(client, "exclusions", {"dataset_id": root, "assignable_cause": _human()})
    derived = _done(client, f"exclusions/{human}")["output_dataset_id"]
    fit = _post(client, "fits", {"dataset_id": derived})
    _done(client, f"fits/{fit}")
    # En la Fase I los parámetros siempre se mandan (no hay rondas de las que heredarlos).
    missing = _error(client, "limits", {"fit_id": fit}, "INVALID_INPUT")
    assert missing["details"]["reason"] == "params_required"
    # La exclusión humana solo al principio, sobre el dataset subido.
    late = {"dataset_id": derived, "assignable_cause": [{"row": 0}]}
    reason = _error(client, "exclusions", late, "INVALID_INPUT")["details"]["reason"]
    assert reason == "human_exclusion_only_at_start"
    # El modo automático ``{fit_id, limits_id}`` y el parámetro de rondas ya no existen.
    limits = _post(client, "limits", {"fit_id": fit, "params": PARAMS})
    _done(client, f"limits/{limits}")
    _error(client, "exclusions", {"fit_id": fit, "limits_id": limits}, "INVALID_INPUT")
    legacy = {**PARAMS, "max_depuration_rounds": 3}
    _error(client, "limits", {"fit_id": fit, "params": legacy}, "INVALID_INPUT")
    gone = client.post(f"{CHART_BASE}/depurations", headers=TENANT, json={"dataset_id": root})
    assert gone.status_code == 404


def test_pipeline_matches_fit_phase1_in_bits(
    client: TestClient, container: Container, reference: T2MRCDModel
) -> None:
    root = upload(client, CASE.x)
    pipeline = _post(
        client,
        "pipelines/phase1",
        {"dataset_id": root, "params": PARAMS, "assignable_cause": _human()},
    )
    body = _done(client, f"pipelines/phase1/{pipeline}")
    kinds = [s["kind"] for s in body["steps"]]
    assert kinds == ["exclusion", "fit", "limits", "model"]
    for step in body["steps"]:
        path = {"fit": "fits", "limits": "limits", "exclusion": "exclusions"}.get(step["kind"])
        resource = f"{path}/{step['id']}" if path else f"models/{step['id']}"
        assert _done(client, resource)["id"] == step["id"]
    assert body["model_id"] == body["steps"][-1]["id"]
    assert canonical(_model(container, body["model_id"])) == canonical(reference)


def test_p_gt_n_pipeline_keeps_every_row(client: TestClient, container: Container) -> None:
    """Con p > n (30 x 40) y los defaults no hay cascada: la base son las 30 filas."""
    x = np.random.default_rng(30).normal(size=(30, 40))
    params = {"bootstrap": {"seed": 7, "n_replicates": 5}}
    reference = T2MRCDChart().fit_phase1(
        x, T2MRCDChart().decode_params(params), mapper=SerialTaskMapper()
    )
    root = upload(client, x)
    pipeline = _post(client, "pipelines/phase1", {"dataset_id": root, "params": params})
    body = _done(client, f"pipelines/phase1/{pipeline}")
    assert [s["kind"] for s in body["steps"]] == ["fit", "limits", "model"]
    model = _model(container, body["model_id"])
    assert isinstance(model, T2MRCDModel)
    assert model.n_base == 30
    assert bool(model.historical_outlier.any())
    assert canonical(model) == canonical(reference)


def test_model_from_fit_and_limits_matches_fit_phase1(
    client: TestClient, container: Container
) -> None:
    case: Phase1Case = phase1_cases()["contaminated"]
    params = {"bootstrap": {"seed": 7, "n_replicates": 5}}
    reference = T2MRCDChart().fit_phase1(
        case.x, T2MRCDChart().decode_params(params), mapper=SerialTaskMapper()
    )
    root = upload(client, case.x)
    fit = _post(client, "fits", {"dataset_id": root})
    _done(client, f"fits/{fit}")
    limits = _post(client, "limits", {"fit_id": fit, "params": params})
    _done(client, f"limits/{limits}")
    model_id = _post(client, "models", {"fit_id": fit, "limits_id": limits})
    model = wait(client, f"{CHART_BASE}/models/{model_id}")
    assert model["status"] == "succeeded"
    assert model["provenance"]["exclusion_id"] is None
    assert canonical(_model(container, model_id)) == canonical(reference)
