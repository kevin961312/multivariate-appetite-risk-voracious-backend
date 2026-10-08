"""Equivalencia por API (T20): cadena manual por HTTP = tubería = ``fit_phase1``, en bits.

Caso contaminado con exclusión humana y dos rondas de depuración automática
(``composition_cases.phase1_cases()["human_exclusion"]``). La cadena manual sube el histórico,
excluye las filas con causa asignable referenciando el dataset (sin ajuste), y repite ajuste →
límites → depuración hasta que la depuración es final; los parámetros solo se mandan en la primera
ronda (las siguientes los heredan). Después pide el modelo con ``{depuration_id}``. La tubería hace
lo mismo con una sola petición. Los tres modelos se comparan en su forma canónica
(``support.bits``: arreglos por ``tobytes`` y reales por ``float.hex``), sin tolerancia. Cada
recurso intermedio se consulta.
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


def _manual_chain(client: TestClient, x: np.ndarray) -> tuple[str, list[str], str, str, int]:
    """Cadena manual por HTTP; devuelve modelo, depuraciones, último ajuste, límites y rondas."""
    root = upload(client, x)
    human = _post(client, "depurations", {"dataset_id": root, "assignable_cause": _human()})
    body = _done(client, f"depurations/{human}")
    assert (body["dataset_id"], body["fit_id"], body["limits_id"]) == (root, None, None)
    assert (body["next_step"], body["n_excluded_assignable_cause"]) == ("fit", 4)
    dataset, depurations, rounds = body["output_dataset_id"], [human], 0
    first_params: dict[str, Any] | None = None
    while True:
        fit = _post(client, "fits", {"dataset_id": dataset})
        assert _done(client, f"fits/{fit}")["dataset_id"] == dataset
        if rounds == 0:
            limits = _post(client, "limits", {"fit_id": fit, "params": PARAMS})
        else:
            # Rondas siguientes: sin reenviar los parámetros (se heredan de la cadena).
            limits = _post(client, "limits", {"fit_id": fit})
        limits_body = _done(client, f"limits/{limits}")
        first_params = first_params or limits_body["params"]
        assert limits_body["params"] == first_params
        assert (limits_body["stage_kind"], limits_body["round"]) == ("phase1", rounds)
        assert limits_body["spawn_key"] == [SLOT_PHASE1, rounds]
        depuration = _post(client, "depurations", {"fit_id": fit, "limits_id": limits})
        body = _done(client, f"depurations/{depuration}")
        assert (body["dataset_id"], body["fit_id"]) == (dataset, fit)
        depurations.append(depuration)
        if body["next_step"] == "model":
            assert body["final"] is True
            assert body["output_dataset_id"] is None
            break
        assert body["n_excluded_automatic"] > 0
        dataset, rounds = body["output_dataset_id"], rounds + 1
    model_id = _post(client, "models", {"depuration_id": depurations[-1]})
    model = wait(client, f"{CHART_BASE}/models/{model_id}")
    assert model["status"] == "succeeded", model
    return model_id, depurations, fit, limits, rounds


def test_case_has_human_exclusion_and_two_rounds(reference: T2MRCDModel) -> None:
    assert CASE.excluded is not None
    assert CASE.excluded.sum() == 4
    assert reference.depuration_rounds == 2
    assert reference.depuration_converged is True


def test_manual_chain_matches_fit_phase1_in_bits(
    client: TestClient, container: Container, reference: T2MRCDModel
) -> None:
    model_id, depurations, fit, limits, rounds = _manual_chain(client, CASE.x)
    assert rounds == reference.depuration_rounds
    model = wait(client, f"{CHART_BASE}/models/{model_id}")
    root = model["provenance"]["root_dataset_id"]
    assert model["provenance"] == {
        "root_dataset_id": root,
        "fit_id": fit,
        "limits_id": limits,
        "depuration_ids": depurations,
    }
    final = _done(client, f"depurations/{depurations[-1]}")
    lineage = client.get(f"{DATASETS}/{final['dataset_id']}", headers=TENANT).json()
    assert lineage["lineage_round"] == rounds
    assert lineage["lineage"][0]["dataset_id"] == root
    assert [e["origin_ref"] for e in lineage["lineage"][1:]] == depurations[:-1]
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


def test_rounds_of_a_chain_share_the_parameters(client: TestClient) -> None:
    root = upload(client, CASE.x)
    human = _post(client, "depurations", {"dataset_id": root, "assignable_cause": _human()})
    derived = _done(client, f"depurations/{human}")["output_dataset_id"]
    fit = _post(client, "fits", {"dataset_id": derived})
    _done(client, f"fits/{fit}")
    # Tras solo la exclusión humana no hay ronda automática de la que heredar.
    missing = _error(client, "limits", {"fit_id": fit}, "INVALID_INPUT")
    assert missing["details"]["reason"] == "params_required"
    limits = _post(client, "limits", {"fit_id": fit, "params": PARAMS})
    _done(client, f"limits/{limits}")
    depuration = _post(client, "depurations", {"fit_id": fit, "limits_id": limits})
    body = _done(client, f"depurations/{depuration}")
    assert body["next_step"] == "fit"
    dataset = body["output_dataset_id"]
    late = {"dataset_id": dataset, "assignable_cause": [{"row": 0}]}
    reason = _error(client, "depurations", late, "INVALID_INPUT")["details"]["reason"]
    assert reason == "human_exclusion_only_at_start"
    fit1 = _post(client, "fits", {"dataset_id": dataset})
    _done(client, f"fits/{fit1}")
    other = {"bootstrap": {**PARAMS["bootstrap"], "seed": 9}, "max_depuration_rounds": 3}
    error = _error(client, "limits", {"fit_id": fit1, "params": other}, "LIMITS_PARAMS_MISMATCH")
    assert error["details"]["source_limits_id"] == limits
    assert error["details"]["fields"] == ["bootstrap.seed", "max_depuration_rounds"]
    same = _post(client, "limits", {"fit_id": fit1, "params": PARAMS})
    inherited = _post(client, "limits", {"fit_id": fit1})
    assert (
        _done(client, f"limits/{same}")["params"] == _done(client, f"limits/{inherited}")["params"]
    )


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
    assert kinds == [
        "depuration",
        *(["fit", "limits", "depuration"] * (reference.depuration_rounds + 1)),
        "model",
    ]
    for step in body["steps"]:
        path = {"fit": "fits", "limits": "limits", "depuration": "depurations"}.get(step["kind"])
        resource = f"{path}/{step['id']}" if path else f"models/{step['id']}"
        assert _done(client, resource)["id"] == step["id"]
    assert body["model_id"] == body["steps"][-1]["id"]
    assert canonical(_model(container, body["model_id"])) == canonical(reference)


def test_model_from_fit_and_limits_matches_fit_phase1_without_depuration(
    client: TestClient, container: Container
) -> None:
    case: Phase1Case = phase1_cases()["contaminated"]
    params = {**PARAMS, "bootstrap": {"seed": 7, "n_replicates": 5}, "max_depuration_rounds": 0}
    reference = T2MRCDChart().fit_phase1(
        case.x,
        T2MRCDChart().decode_params(params),
        mapper=SerialTaskMapper(),
    )
    root = upload(client, case.x)
    fit = _post(client, "fits", {"dataset_id": root})
    _done(client, f"fits/{fit}")
    limits = _post(client, "limits", {"fit_id": fit, "params": params})
    _done(client, f"limits/{limits}")
    model_id = _post(client, "models", {"fit_id": fit, "limits_id": limits})
    assert wait(client, f"{CHART_BASE}/models/{model_id}")["status"] == "succeeded"
    assert reference.depuration_converged is False
    assert canonical(_model(container, model_id)) == canonical(reference)
