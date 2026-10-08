"""Equivalencia de la recalibración (vuelta 3.4): paso a paso por HTTP = tubería = ``recalibrate``.

Tres caminos sobre el mismo modelo y las mismas observaciones:

- **paso a paso** por HTTP: ``/fits`` → (exclusión humana) → ``/limits`` con
  ``recalibration_id`` → ``/depurations`` … → ``…/comparisons`` → (``extend``: ajuste y límites
  del dataset de extensión) → ``…/versions``;
- **tubería** (``mode = pipeline``), que encadena los mismos casos de uso;
- ``T2MRCDChart.recalibrate`` directo, con la base y el modelo de la versión 0.

Se comparan en bits (``support.bits``) el modelo, el informe, ``base_hash``, ``base_refs`` y
``exclusions`` en tres casos: EXTEND (pruebas formales «SOLO TEST» de ``tests/support``,
registradas solo aquí, con exclusión humana por anotaciones), REPLACE forzado e INSUFFICIENT. Se
comprueban los huecos de semilla de cada calibración: ``(1, r)`` las rondas de las filas nuevas y
``(0, 0)`` la base ampliada.

Las pruebas formales no se pueden mandar por HTTP (en producción están pendientes, P3), así que
en EXTEND la recalibración se **abre** con el caso de uso y todo lo demás va por HTTP.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
from fastapi.testclient import TestClient

from support.api import BASE, CHART_BASE, T0, TENANT, score, train, wait
from support.bits import canonical
from support.solo_test import small_data, solo_test_chart, solo_test_recalibration
from voracious.api.app import create_app
from voracious.application.lifecycle import base_content_hash
from voracious.application.records import (
    BaseRowRef,
    BaseRowSource,
    Exclusion,
    ExclusionReason,
    ModelVersion,
    RecalibrationMode,
)
from voracious.config import Settings
from voracious.container import Container, build_container
from voracious.domain.charts.t2mrcd import (
    SLOT_NEW_ROWS_DEPURATION,
    SLOT_PHASE1,
    T2MRCDChart,
    T2MRCDRecalibrationParams,
)
from voracious.domain.common import (
    RecalibrationDecision,
    RecalibrationOutcome,
    RowDisposition,
    SerialTaskMapper,
)

TENANT_ID = "tenant-a"
CHART_ID = "t2mrcd"
N = 30
END = T0 + timedelta(hours=N - 1)
SHIFTED = (3, 7)


@pytest.fixture(scope="module")
def container() -> Iterator[Container]:
    built = build_container(Settings(), charts={CHART_ID: solo_test_chart()})
    yield built
    built.shutdown()


@pytest.fixture(scope="module")
def client(container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(container)) as test_client:
        yield test_client


@dataclass(frozen=True)
class Scenario:
    """Modelo entrenado con ``N`` observaciones puntuadas."""

    model_id: str
    x: npt.NDArray[np.float64]
    observation_ids: list[str]
    annotation_ids: dict[int, str]


def _scenario(client: TestClient, seed: int, annotate: tuple[int, ...] = ()) -> Scenario:
    model_id = train(client, seed=3)
    x = small_data(N, 4, seed=seed)
    x[list(SHIFTED)] += 8.0
    rows = [
        {"observed_at": (T0 + timedelta(hours=i)).isoformat(), "values": row}
        for i, row in enumerate(x.tolist())
    ]
    done = score(client, model_id, rows)
    ids = list(done["result"]["observation_ids"])
    annotations: dict[int, str] = {}
    for i in annotate:
        response = client.post(
            f"{BASE}/{model_id}/observations/{ids[i]}/annotations",
            headers=TENANT,
            json={"assignable_cause": True, "cause": "error de carga"},
        )
        assert response.status_code == 201, response.text
        annotations[i] = response.json()["id"]
    return Scenario(model_id, x, ids, annotations)


def _post(client: TestClient, path: str, body: dict[str, Any], code: int = 202) -> dict[str, Any]:
    response = client.post(path, headers=TENANT, json=body)
    assert response.status_code == code, response.text
    result: dict[str, Any] = response.json()
    return result


def _done(client: TestClient, path: str) -> dict[str, Any]:
    body = wait(client, path)
    assert body["status"] == "succeeded", body
    return body


def _fit(client: TestClient, dataset_id: str) -> str:
    fit_id = str(_post(client, f"{CHART_BASE}/fits", {"dataset_id": dataset_id})["id"])
    _done(client, f"{CHART_BASE}/fits/{fit_id}")
    return fit_id


def _limits(client: TestClient, fit_id: str, rid: str, kind: str, round_: int) -> str:
    body = {"fit_id": fit_id, "recalibration_id": rid}
    limits_id = str(_post(client, f"{CHART_BASE}/limits", body)["id"])
    limits = _done(client, f"{CHART_BASE}/limits/{limits_id}")
    slot = SLOT_NEW_ROWS_DEPURATION if kind == "new_rows" else SLOT_PHASE1
    assert (limits["stage_kind"], limits["round"]) == (kind, round_)
    assert limits["spawn_key"] == [slot, round_]
    assert limits["recalibration_id"] == rid
    return limits_id


def _depurate(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    depuration_id = _post(client, f"{CHART_BASE}/depurations", body)["id"]
    return _done(client, f"{CHART_BASE}/depurations/{depuration_id}")


def _stepwise(
    client: TestClient, model_id: str, rid: str, candidates: str, *, human: bool, forced: bool
) -> dict[str, Any]:
    """Recalibración completa por HTTP, paso a paso; devuelve la recalibración terminada."""
    url = f"{BASE}/{model_id}/recalibrations/{rid}"
    if human:
        # Exclusión humana sobre el dataset de candidatas, sin ajustarlo antes.
        body = _depurate(client, {"dataset_id": candidates})
        assert body["n_excluded_assignable_cause"] > 0
        assert all(a["annotation_id"] for a in body["assignable_cause"])
        if body["exhausted"]:
            return _done(client, url)
        candidates = body["output_dataset_id"]
    fit_id = _fit(client, candidates)
    rounds = 0
    while True:
        limits_id = _limits(client, fit_id, rid, "new_rows", rounds)
        body = _depurate(client, {"fit_id": fit_id, "limits_id": limits_id})
        if body["exhausted"]:
            return _done(client, url)
        if body["next_step"] == "model":
            final = body
            break
        rounds += 1
        fit_id = _fit(client, body["output_dataset_id"])
    version: dict[str, Any] = {"recalibration_id": rid, "fit_id": fit_id, "limits_id": limits_id}
    if not forced:
        comparison_id = _post(
            client,
            f"{BASE}/{model_id}/comparisons",
            {"recalibration_id": rid, "depuration_id": final["id"]},
        )["id"]
        comparison = _done(client, f"{BASE}/{model_id}/comparisons/{comparison_id}")
        version["comparison_id"] = comparison_id
        if comparison["decision"] == "extend":
            ext_fit = _fit(client, comparison["extension_dataset_id"])
            ext_limits = _limits(client, ext_fit, rid, "extension", 0)
            version.update(fit_id=ext_fit, limits_id=ext_limits)
    accepted = _post(client, f"{BASE}/{model_id}/versions", version)
    assert accepted["id"] == rid
    return _done(client, url)


def _version(container: Container, model_id: str, number: int) -> ModelVersion:
    return container.use_cases.get_version.execute(TENANT_ID, CHART_ID, model_id, number)


def _reference(
    container: Container,
    scenario: Scenario,
    params: T2MRCDRecalibrationParams,
    *,
    annotate: tuple[int, ...],
    forced: bool,
) -> RecalibrationOutcome[Any, Any]:
    v0 = _version(container, scenario.model_id, 0)
    mask = np.zeros(N, dtype=np.bool_)
    mask[list(annotate)] = True
    return solo_test_chart().recalibrate(
        v0.model,
        v0.base_data,
        scenario.x,
        assignable_cause=mask,
        force_replace=forced,
        params=params,
        mapper=SerialTaskMapper(),
    )


def _expected_base(
    container: Container, scenario: Scenario, outcome: RecalibrationOutcome[Any, Any]
) -> tuple[str, tuple[BaseRowRef, ...], tuple[Exclusion, ...]]:
    """``base_hash``, ``base_refs`` y exclusiones que debe tener la versión propuesta."""
    v0 = _version(container, scenario.model_id, 0)
    n_base = v0.base_data.shape[0]
    new = outcome.report.row_disposition[n_base:]
    kept = [i for i, d in enumerate(new) if d is RowDisposition.KEPT]
    kept_refs = tuple(
        BaseRowRef(BaseRowSource.OBSERVATION, scenario.observation_ids[i]) for i in kept
    )
    if outcome.decision is RecalibrationDecision.EXTEND:
        data = np.vstack([v0.base_data, scenario.x[kept]])
        refs = v0.base_refs + kept_refs
    else:
        data, refs = scenario.x[kept], kept_refs
    reasons = {
        RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE: ExclusionReason.ASSIGNABLE_CAUSE,
        RowDisposition.EXCLUDED_AUTOMATIC: ExclusionReason.AUTOMATIC,
    }
    exclusions = tuple(
        Exclusion(
            ref=BaseRowRef(BaseRowSource.OBSERVATION, scenario.observation_ids[i]),
            reason=reasons[d],
            annotation_id=scenario.annotation_ids.get(i)
            if d is RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE
            else None,
        )
        for i, d in enumerate(new)
        if d is not RowDisposition.KEPT
    )
    return base_content_hash(np.ascontiguousarray(data)), refs, exclusions


def _same_version(a: ModelVersion, b: ModelVersion) -> None:
    for name in ("model", "report", "base_hash", "base_refs", "exclusions", "decision"):
        assert canonical(getattr(a, name)) == canonical(getattr(b, name)), name


def _check(
    container: Container,
    scenario: Scenario,
    recal: dict[str, Any],
    outcome: RecalibrationOutcome[Any, Any],
) -> ModelVersion:
    """La versión propuesta coincide en bits con ``recalibrate``."""
    record = container.use_cases.get_recalibration.execute(
        TENANT_ID, CHART_ID, scenario.model_id, recal["id"]
    )
    assert canonical(record.report) == canonical(outcome.report)
    version = _version(container, scenario.model_id, recal["proposed_version"])
    assert canonical(version.model) == canonical(outcome.model)
    assert canonical(version.report) == canonical(outcome.report)
    base_hash, refs, exclusions = _expected_base(container, scenario, outcome)
    assert version.base_hash == base_hash
    assert version.base_refs == refs
    assert version.exclusions == exclusions
    return version


def _pipeline_slots(client: TestClient, pipeline_id: str) -> list[tuple[str, int, list[int]]]:
    """Linaje y hueco de semilla de cada calibración que creó la tubería, en orden."""
    body = _done(client, f"{CHART_BASE}/pipelines/{pipeline_id}")
    assert body["kind"] == "recalibration"
    out = []
    for step in body["steps"]:
        if step["kind"] == "limits":
            limits = _done(client, f"{CHART_BASE}/limits/{step['id']}")
            out.append((limits["stage_kind"], limits["round"], limits["spawn_key"]))
    return out


def _reject(client: TestClient, model_id: str, number: int) -> None:
    response = client.post(f"{BASE}/{model_id}/versions/{number}/reject", headers=TENANT)
    assert response.status_code == 200, response.text


def test_extend_with_human_exclusion_matches_recalibrate_in_bits(
    client: TestClient, container: Container
) -> None:
    annotate = (3,)
    scenario = _scenario(client, seed=50, annotate=annotate)
    params = solo_test_recalibration(seed=11, min_observations=10)
    outcome = _reference(container, scenario, params, annotate=annotate, forced=False)
    assert outcome.decision is RecalibrationDecision.EXTEND
    assert outcome.report.n_excluded_assignable_cause == 1
    assert outcome.report.n_excluded_automatic > 0
    assert outcome.report.depuration_rounds >= 1

    open_ = container.use_cases.request_recalibration
    rid = open_.execute(
        TENANT_ID,
        CHART_ID,
        scenario.model_id,
        range_from=T0,
        range_to=END,
        params=params,
        mode=RecalibrationMode.STEPWISE,
    )
    session = container.use_cases.get_recalibration.execute(
        TENANT_ID, CHART_ID, scenario.model_id, rid
    )
    assert session.status.value == "running"
    assert session.candidates_dataset_id is not None
    recal = _stepwise(
        client, scenario.model_id, rid, session.candidates_dataset_id, human=True, forced=False
    )
    assert recal["outcome"] == "extend"
    stepwise = _check(container, scenario, recal, outcome)
    human = [e for e in stepwise.exclusions if e.reason is ExclusionReason.ASSIGNABLE_CAUSE]
    assert [e.ref.ref for e in human] == [scenario.observation_ids[3]]
    assert all(e.annotation_id for e in human)
    assert stepwise.justification == "no_change_detected"
    _reject(client, scenario.model_id, stepwise.number)

    pid = open_.execute(
        TENANT_ID, CHART_ID, scenario.model_id, range_from=T0, range_to=END, params=params
    )
    piped = _done(client, f"{BASE}/{scenario.model_id}/recalibrations/{pid}")
    assert piped["mode"] == "pipeline"
    pipeline = _check(container, scenario, piped, outcome)
    _same_version(stepwise, pipeline)
    rounds = outcome.report.depuration_rounds
    assert _pipeline_slots(client, piped["pipeline_id"]) == [
        *(("new_rows", r, [SLOT_NEW_ROWS_DEPURATION, r]) for r in range(rounds + 1)),
        ("extension", 0, [SLOT_PHASE1, 0]),
    ]


def test_forced_replace_matches_recalibrate_in_bits(
    client: TestClient, container: Container
) -> None:
    scenario = _scenario(client, seed=51)
    body = {
        "range_from": T0.isoformat(),
        "range_to": END.isoformat(),
        "params": {"seed": 5, "min_observations": 10},
        "force_replace": True,
    }
    params = T2MRCDChart().decode_recalibration_params({"seed": 5, "min_observations": 10})
    outcome = _reference(container, scenario, params, annotate=(), forced=True)
    assert outcome.decision is RecalibrationDecision.REPLACE

    opened = _post(
        client, f"{BASE}/{scenario.model_id}/recalibrations", {**body, "mode": "stepwise"}, 201
    )
    assert opened["status"] == "running"
    rid = opened["recalibration_id"]
    recal = _stepwise(
        client,
        scenario.model_id,
        rid,
        opened["candidates_dataset_id"],
        human=False,
        forced=True,
    )
    assert recal["outcome"] == "replace"
    assert recal["proposal"]["comparison_id"] is None
    stepwise = _check(container, scenario, recal, outcome)
    assert stepwise.justification == "forced_replace"
    _reject(client, scenario.model_id, stepwise.number)

    accepted = _post(client, f"{BASE}/{scenario.model_id}/recalibrations", body)
    piped = _done(client, f"{BASE}/{scenario.model_id}/recalibrations/{accepted['id']}")
    pipeline = _check(container, scenario, piped, outcome)
    _same_version(stepwise, pipeline)
    steps = client.get(f"{CHART_BASE}/pipelines/{piped['pipeline_id']}", headers=TENANT)
    kinds = [s["kind"] for s in steps.json()["steps"]]
    assert kinds[-1] == "version"
    assert "comparison" not in kinds
    rounds = outcome.report.depuration_rounds
    assert _pipeline_slots(client, piped["pipeline_id"]) == [
        ("new_rows", r, [SLOT_NEW_ROWS_DEPURATION, r]) for r in range(rounds + 1)
    ]


@pytest.mark.parametrize(
    ("annotate", "min_observations", "rounds"),
    [((), N - 1, 1), ((3,), N, 0)],
    ids=["automatic", "human"],
)
def test_insufficient_matches_recalibrate_in_bits(
    client: TestClient,
    container: Container,
    annotate: tuple[int, ...],
    min_observations: int,
    rounds: int,
) -> None:
    scenario = _scenario(client, seed=52, annotate=annotate)
    raw = {"seed": 9, "min_observations": min_observations}
    body = {
        "range_from": T0.isoformat(),
        "range_to": END.isoformat(),
        "params": raw,
        "force_replace": True,
    }
    params = T2MRCDChart().decode_recalibration_params(raw)
    outcome = _reference(container, scenario, params, annotate=annotate, forced=True)
    assert outcome.decision is RecalibrationDecision.INSUFFICIENT
    assert outcome.report.depuration_rounds == rounds

    results = []
    opened = _post(
        client, f"{BASE}/{scenario.model_id}/recalibrations", {**body, "mode": "stepwise"}, 201
    )
    results.append(
        _stepwise(
            client,
            scenario.model_id,
            opened["recalibration_id"],
            opened["candidates_dataset_id"],
            human=bool(annotate),
            forced=True,
        )
    )
    accepted = _post(client, f"{BASE}/{scenario.model_id}/recalibrations", body)
    results.append(_done(client, f"{BASE}/{scenario.model_id}/recalibrations/{accepted['id']}"))
    for recal in results:
        assert (recal["outcome"], recal["proposed_version"]) == ("insufficient", None)
        record = container.use_cases.get_recalibration.execute(
            TENANT_ID, CHART_ID, scenario.model_id, recal["id"]
        )
        assert canonical(record.report) == canonical(outcome.report)
    versions = client.get(f"{BASE}/{scenario.model_id}/versions", headers=TENANT).json()
    assert [v["number"] for v in versions] == [0]
