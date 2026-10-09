"""Equivalencia en bits: la composición paso a paso de las piezas públicas = ``fit_phase1`` y
``recalibrate`` (vuelta 3.2 del Paso 3).

Cada caso se ejecuta dos veces: con el método completo de la carta y encadenando a mano
``validate_phase1_input``, ``fit_base``, ``calibrate`` (operación → ``stage_spawn_key``),
``compare`` y ``assemble_model``, como lo haría un orquestador. Sin depuración automática
iterativa (decisión del dueño, 2026-10-09): una exclusión humana, un ajuste y una calibración. Se
comparan todos los campos del modelo y del informe en su forma canónica (arreglos por ``tobytes``
y reales por ``float.hex``): sin tolerancia.
"""

import dataclasses
from typing import cast

import numpy as np
import numpy.typing as npt
import pytest

from support.bits import canonical
from support.composition_cases import (
    Phase1Case,
    RecalibrationCase,
    active_case,
    phase1_cases,
    recalibration_cases,
)
from support.solo_test import fast_params
from voracious.domain.charts.t2mrcd import (
    SLOT_NEW_ROWS,
    SLOT_PHASE1,
    LimitRegime,
    Phase1Stage,
    T2MRCDChart,
    T2MRCDModel,
    T2MRCDRecalibrationReport,
    decide,
)
from voracious.domain.charts.t2mrcd.revalidation import LimitsSnapshot
from voracious.domain.common import (
    InvalidInputError,
    MethodDecisionPendingError,
    RecalibrationDecision,
    RowDisposition,
    SerialTaskMapper,
    StageKind,
)

MAPPER = SerialTaskMapper()
BoolArray = npt.NDArray[np.bool_]


def _dispositions(human: BoolArray) -> tuple[RowDisposition, ...]:
    return tuple(
        RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE if h else RowDisposition.KEPT
        for h in human.tolist()
    )


def compose_phase1(chart: T2MRCDChart, case: Phase1Case) -> T2MRCDModel:
    """Fase I encadenando las piezas públicas."""
    chart.validate_phase1_input(case.x)
    arr = np.array(case.x, dtype=np.float64)
    n = arr.shape[0]
    human = case.excluded if case.excluded is not None else np.zeros(n, dtype=np.bool_)
    rows = np.flatnonzero(~human).astype(np.int64)
    x_rows = arr[rows]
    fit = chart.fit_base(x_rows, rows, case.params)
    stage = chart.calibrate(x_rows, fit, case.params, kind=StageKind.PHASE1, mapper=MAPPER)
    assert stage.limits.spawn_key == (SLOT_PHASE1, 0)
    return chart.assemble_model(
        arr,
        case.params,
        stage.fit,
        stage.clean,
        stage.limits,
        excluded=human,
        regime=LimitRegime.PHASE1_PROVISIONAL,
    )


def compose_recalibration(
    chart: T2MRCDChart, active: T2MRCDModel, base: np.ndarray, case: RecalibrationCase
) -> tuple[RecalibrationDecision, T2MRCDModel | None, T2MRCDRecalibrationReport]:
    """Recalibración encadenando las piezas públicas."""
    params = case.params
    new = np.array(case.x_new, dtype=np.float64)
    m = new.shape[0]
    human = (
        case.assignable_cause if case.assignable_cause is not None else np.zeros(m, dtype=np.bool_)
    )
    inherited = dataclasses.replace(
        active.params,
        bootstrap=dataclasses.replace(active.params.bootstrap, seed=params.seed),
    )
    rows = np.flatnonzero(~human).astype(np.int64)
    kept_new = new[rows]
    stage: Phase1Stage | None = None
    if rows.shape[0] >= params.min_observations:
        fit = chart.fit_base(kept_new, rows, inherited)
        stage = chart.calibrate(kept_new, fit, inherited, kind=StageKind.NEW_ROWS, mapper=MAPPER)
        assert stage.limits.spawn_key == (SLOT_NEW_ROWS, 0)
    comparison = None
    if stage is not None and not case.force_replace:
        comparison = chart.compare(active, base, kept_new, stage.fit, params, MAPPER)
    decision = decide(
        comparison,
        n_kept=int(rows.shape[0]),
        min_observations=params.min_observations,
        force_replace=case.force_replace,
    )
    model = None
    if stage is not None and decision is not RecalibrationDecision.INSUFFICIENT:
        if decision is RecalibrationDecision.EXTEND:
            x_final = np.vstack([base, kept_new])
            rows_final = np.arange(x_final.shape[0], dtype=np.int64)
            fit = chart.fit_base(x_final, rows_final, inherited)
            final = chart.calibrate(
                x_final, fit, inherited, kind=StageKind.EXTENSION, mapper=MAPPER
            )
            assert final.limits.spawn_key == (SLOT_PHASE1, 0)
        else:
            x_final, final = kept_new, stage
        model = chart.assemble_model(
            x_final,
            inherited,
            final.fit,
            final.clean,
            final.limits,
            excluded=np.zeros(x_final.shape[0], dtype=np.bool_),
            regime=LimitRegime.PHASE2,
        )
    report = T2MRCDRecalibrationReport(
        decision=decision,
        forced=case.force_replace,
        row_disposition=(RowDisposition.ALREADY_IN_BASE,) * base.shape[0] + _dispositions(human),
        n_base=int(base.shape[0]),
        n_new=m,
        n_excluded_assignable_cause=int(human.sum()),
        n_kept_new=int(rows.shape[0]),
        min_observations=params.min_observations,
        comparison=comparison,
        before=LimitsSnapshot.of(active),
        after=None if model is None else LimitsSnapshot.of(model),
        phase2_exceeds_phase1=None if model is None else model.limits.phase2_exceeds_phase1,
    )
    return decision, model, report


PHASE1 = phase1_cases()
RECALIBRATION = recalibration_cases()


@pytest.fixture(scope="module")
def active() -> tuple[T2MRCDModel, np.ndarray]:
    case = active_case()
    model = T2MRCDChart().fit_phase1(case.x, case.params, mapper=MAPPER)
    return model, case.x[model.base_mask]


@pytest.mark.parametrize("name", sorted(PHASE1))
def test_phase1_composition_matches_fit_phase1_in_bits(name: str) -> None:
    case = PHASE1[name]
    chart = T2MRCDChart()
    whole = chart.fit_phase1(case.x, case.params, mapper=MAPPER, excluded=case.excluded)
    assert canonical(compose_phase1(chart, case)) == canonical(whole)


def test_phase1_cases_cover_human_exclusion_and_p_gt_n() -> None:
    chart = T2MRCDChart()
    case = PHASE1["human_exclusion"]
    model = chart.fit_phase1(case.x, case.params, mapper=MAPPER, excluded=case.excluded)
    assert case.excluded is not None
    assert np.array_equal(model.base_mask, ~case.excluded)
    assert RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE in model.row_disposition
    assert PHASE1["p_gt_n"].x.shape[1] > PHASE1["p_gt_n"].x.shape[0]


def test_without_automatic_depuration_the_base_keeps_every_row_also_when_p_gt_n() -> None:
    """Decisión del dueño (2026-10-09): sin cascada; con p > n (30 x 40) la base son las 30 filas.

    Con la depuración automática iterativa la base se encogía en cada ronda (MRCD deja fuera un
    25 % de lo que recibe) y no convergía. En este caso 4 filas superan el límite de Fase I (la
    depuración las habría quitado y habría repetido); ahora siguen en la base, y las filas fuera
    de ``best`` solo no entran en la estimación ni en el bootstrap.
    """
    x = np.random.default_rng(30).normal(size=(30, 40))
    model = T2MRCDChart().fit_phase1(x, fast_params(), mapper=MAPPER)
    assert model.n_base == 30
    assert bool(model.base_mask.all())
    assert set(model.row_disposition) == {RowDisposition.KEPT}
    assert int(model.clean_mask.sum()) == model.mrcd.h < 30
    assert int(model.historical_outlier.sum()) == 4


@pytest.mark.parametrize("name", sorted(RECALIBRATION))
def test_recalibration_composition_matches_recalibrate_in_bits(
    name: str, active: tuple[T2MRCDModel, np.ndarray]
) -> None:
    case = RECALIBRATION[name]
    model, base = active
    chart = T2MRCDChart()
    whole = chart.recalibrate(
        model,
        base,
        case.x_new,
        assignable_cause=case.assignable_cause,
        force_replace=case.force_replace,
        params=case.params,
        mapper=MAPPER,
    )
    expected = {
        "extend": RecalibrationDecision.EXTEND,
        "replace": RecalibrationDecision.REPLACE,
        "insufficient": RecalibrationDecision.INSUFFICIENT,
        "insufficient_after_exclusion": RecalibrationDecision.INSUFFICIENT,
        "forced": RecalibrationDecision.REPLACE,
    }[name]
    assert whole.decision is expected
    composed = compose_recalibration(chart, model, base, case)
    assert canonical(composed) == canonical((whole.decision, whole.model, whole.report))


@pytest.mark.parametrize("threads", [1, 4])
@pytest.mark.parametrize("name", ["contaminated", "p_gt_n"])
def test_mrcd_threads_do_not_change_any_bit(name: str, threads: int) -> None:
    case = PHASE1[name]
    reference = T2MRCDChart().fit_phase1(case.x, case.params, mapper=MAPPER)
    threaded = T2MRCDChart(mrcd_threads=threads).fit_phase1(case.x, case.params, mapper=MAPPER)
    assert canonical(threaded) == canonical(reference)


def test_mrcd_threads_reach_every_fit_and_are_not_compared(
    monkeypatch: pytest.MonkeyPatch, active: tuple[T2MRCDModel, np.ndarray]
) -> None:
    from voracious.domain.estimators.mrcd import estimator as mrcd_estimator

    seen: list[int | None] = []
    original = mrcd_estimator.fit_mrcd

    def spy(x: object, params: object, n_threads: int | None = None) -> object:
        seen.append(n_threads)
        return original(x, params, n_threads=n_threads)

    monkeypatch.setattr(mrcd_estimator, "fit_mrcd", spy)
    chart = T2MRCDChart(mrcd_threads=2)
    model, base = active
    case = RECALIBRATION["extend"]
    chart.recalibrate(
        model,
        base,
        case.x_new,
        assignable_cause=case.assignable_cause,
        force_replace=False,
        params=case.params,
        mapper=MAPPER,
    )
    assert seen
    assert set(seen) == {2}
    assert chart == T2MRCDChart()


@pytest.mark.parametrize("threads", [0, -1, 1.5, True])
def test_invalid_mrcd_threads(threads: object) -> None:
    with pytest.raises(InvalidInputError) as info:
        T2MRCDChart(mrcd_threads=threads)
    assert info.value.details["field"] == "mrcd_threads"


def test_stage_spawn_key_maps_each_operation_to_its_seed_slot() -> None:
    chart = T2MRCDChart()
    assert chart.stage_spawn_key(StageKind.PHASE1) == (SLOT_PHASE1, 0)
    assert chart.stage_spawn_key(StageKind.NEW_ROWS) == (SLOT_NEW_ROWS, 0)
    assert chart.stage_spawn_key(StageKind.EXTENSION) == (SLOT_PHASE1, 0)


@pytest.mark.parametrize("kind", ["phase1", "new_rows", "extension"])
def test_operation_given_as_text_is_normalised(kind: str) -> None:
    chart = T2MRCDChart()
    assert chart.stage_spawn_key(cast(StageKind, kind)) == chart.stage_spawn_key(StageKind(kind))


def test_unknown_operation_is_invalid_input() -> None:
    with pytest.raises(InvalidInputError, match="kind") as info:
        T2MRCDChart().stage_spawn_key(cast(StageKind, "bogus"))
    assert info.value.details["field"] == "stage_kind"


def test_insufficient_after_exclusion_fits_nothing(
    active: tuple[T2MRCDModel, np.ndarray],
) -> None:
    case = RECALIBRATION["insufficient_after_exclusion"]
    model, base = active
    assert case.x_new.shape[0] >= case.params.min_observations
    outcome = T2MRCDChart().recalibrate(
        model,
        base,
        case.x_new,
        assignable_cause=case.assignable_cause,
        force_replace=False,
        params=case.params,
        mapper=MAPPER,
    )
    report = outcome.report
    assert outcome.model is None
    assert report.decision is RecalibrationDecision.INSUFFICIENT
    assert report.n_excluded_assignable_cause == 7
    assert report.n_kept_new < case.params.min_observations


def test_validate_phase1_input_rejects_what_fit_phase1_rejects() -> None:
    chart = T2MRCDChart()
    chart.validate_phase1_input(np.zeros((3, 2)))
    for bad in (np.zeros((0, 2)), np.array([[1.0, np.nan]]), [1.0, 2.0]):
        with pytest.raises(InvalidInputError):
            chart.validate_phase1_input(bad)


def test_compare_requires_the_formal_tests(active: tuple[T2MRCDModel, np.ndarray]) -> None:
    model, base = active
    production = RECALIBRATION["forced"].params
    with pytest.raises(MethodDecisionPendingError) as info:
        T2MRCDChart().compare(model, base, base, model.mrcd, production, MAPPER)
    assert "recalibration.covariance_test" in info.value.details["pending"]


def test_compare_rejects_a_base_that_is_not_the_active_one(
    active: tuple[T2MRCDModel, np.ndarray],
) -> None:
    model, base = active
    with pytest.raises(InvalidInputError) as info:
        T2MRCDChart().compare(
            model, base[:-1], base, model.mrcd, RECALIBRATION["extend"].params, MAPPER
        )
    assert info.value.details["reason"] == "base_mismatch"
