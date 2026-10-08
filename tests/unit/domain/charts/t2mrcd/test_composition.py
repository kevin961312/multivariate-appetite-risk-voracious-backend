"""Equivalencia en bits: la composición paso a paso de las piezas públicas = ``fit_phase1`` y
``recalibrate`` (vuelta 3.2 del Paso 3).

Cada caso se ejecuta dos veces: con el método completo de la carta y encadenando a mano
``validate_phase1_input``, ``fit_base``, ``calibrate`` (linaje → ``stage_spawn_key``),
``depurate_step``, ``compare`` y ``assemble_model``, como lo haría un orquestador. Se comparan
todos los campos del modelo y del informe en su forma canónica (arreglos por ``tobytes`` y reales
por ``float.hex``): sin tolerancia.
"""

import dataclasses

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
from voracious.domain.charts.t2mrcd import (
    SLOT_NEW_ROWS_DEPURATION,
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
    StageLineage,
)

MAPPER = SerialTaskMapper()
BoolArray = npt.NDArray[np.bool_]


def _dispositions(human: BoolArray, automatic: BoolArray) -> tuple[RowDisposition, ...]:
    return tuple(
        RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE
        if h
        else RowDisposition.EXCLUDED_AUTOMATIC
        if a
        else RowDisposition.KEPT
        for h, a in zip(human.tolist(), automatic.tolist(), strict=True)
    )


def compose_phase1(chart: T2MRCDChart, case: Phase1Case) -> T2MRCDModel:
    """Fase I encadenando las piezas públicas."""
    chart.validate_phase1_input(case.x)
    arr = np.array(case.x, dtype=np.float64)
    n = arr.shape[0]
    human = case.excluded if case.excluded is not None else np.zeros(n, dtype=np.bool_)
    kept, automatic, r = ~human, np.zeros(n, dtype=np.bool_), 0
    while True:
        rows = np.flatnonzero(kept).astype(np.int64)
        x_rows = arr[rows]
        fit = chart.fit_base(x_rows, rows, case.params)
        stage = chart.calibrate(
            x_rows, fit, case.params, lineage=StageLineage(StageKind.PHASE1, r), mapper=MAPPER
        )
        assert stage.limits.spawn_key == (SLOT_PHASE1, r)
        step = chart.depurate_step(
            stage, x_rows, rows, kept, r, max_rounds=case.params.max_depuration_rounds
        )
        kept = step.kept
        automatic |= step.excluded_automatic_now
        if step.final:
            assert not step.exhausted
            break
        r += 1
    return chart.assemble_model(
        arr,
        case.params,
        stage.fit,
        stage.clean,
        stage.limits,
        kept=kept,
        excluded=human,
        automatic=automatic,
        rounds=r,
        converged=step.converged,
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
    kept, automatic, r = ~human, np.zeros(m, dtype=np.bool_), 0
    stage: Phase1Stage | None = None
    converged: bool | None = None
    if int(kept.sum()) >= params.min_observations:
        while True:
            rows = np.flatnonzero(kept).astype(np.int64)
            x_rows = new[rows]
            fit = chart.fit_base(x_rows, rows, inherited)
            stage = chart.calibrate(
                x_rows, fit, inherited, lineage=StageLineage(StageKind.NEW_ROWS, r), mapper=MAPPER
            )
            assert stage.limits.spawn_key == (SLOT_NEW_ROWS_DEPURATION, r)
            step = chart.depurate_step(
                stage,
                x_rows,
                rows,
                kept,
                r,
                max_rounds=params.max_depuration_rounds,
                min_rows=params.min_observations,
            )
            kept = step.kept
            automatic |= step.excluded_automatic_now
            if step.exhausted:
                stage, r = None, r + 1
                break
            if step.final:
                converged = step.converged
                break
            r += 1
    comparison = None
    if stage is not None and not case.force_replace:
        comparison = chart.compare(active, base, new[kept], stage.fit, params, MAPPER)
    decision = (
        RecalibrationDecision.INSUFFICIENT
        if stage is None
        else decide(
            comparison,
            n_kept=int(kept.sum()),
            min_observations=params.min_observations,
            force_replace=case.force_replace,
        )
    )
    model = None
    if stage is not None and decision is not RecalibrationDecision.INSUFFICIENT:
        if decision is RecalibrationDecision.EXTEND:
            x_final = np.vstack([base, new[kept]])
            rows_final = np.arange(x_final.shape[0], dtype=np.int64)
            fit = chart.fit_base(x_final, rows_final, inherited)
            final = chart.calibrate(
                x_final, fit, inherited, lineage=StageLineage(StageKind.EXTENSION), mapper=MAPPER
            )
            assert final.limits.spawn_key == (SLOT_PHASE1, 0)
        else:
            x_final, final = new[kept], stage
        n_final = x_final.shape[0]
        model = chart.assemble_model(
            x_final,
            inherited,
            final.fit,
            final.clean,
            final.limits,
            kept=np.ones(n_final, dtype=np.bool_),
            excluded=np.zeros(n_final, dtype=np.bool_),
            automatic=np.zeros(n_final, dtype=np.bool_),
            rounds=0,
            converged=None,
            regime=LimitRegime.PHASE2,
        )
    report = T2MRCDRecalibrationReport(
        decision=decision,
        forced=case.force_replace,
        row_disposition=(RowDisposition.ALREADY_IN_BASE,) * base.shape[0]
        + _dispositions(human, automatic),
        n_base=int(base.shape[0]),
        n_new=m,
        n_excluded_assignable_cause=int(human.sum()),
        n_excluded_automatic=int(automatic.sum()),
        n_kept_new=int(kept.sum()),
        min_observations=params.min_observations,
        depuration_rounds=r,
        depuration_converged=None if stage is None else converged,
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


def test_phase1_cases_cover_the_depuration_paths() -> None:
    chart = T2MRCDChart()
    models = {
        name: chart.fit_phase1(c.x, c.params, mapper=MAPPER, excluded=c.excluded)
        for name, c in PHASE1.items()
        if name in {"contaminated", "human_exclusion", "max_rounds"}
    }
    assert models["contaminated"].depuration_rounds >= 2
    assert models["contaminated"].depuration_converged is True
    assert RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE in models["human_exclusion"].row_disposition
    max_rounds = models["max_rounds"]
    assert max_rounds.depuration_rounds == max_rounds.params.max_depuration_rounds
    assert max_rounds.depuration_converged is False
    assert PHASE1["p_gt_n"].x.shape[1] > PHASE1["p_gt_n"].x.shape[0]


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
        "insufficient_in_loop": RecalibrationDecision.INSUFFICIENT,
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


def test_stage_spawn_key_maps_lineage_to_seed_slots() -> None:
    chart = T2MRCDChart()
    assert chart.stage_spawn_key(StageLineage(StageKind.PHASE1, 3)) == (SLOT_PHASE1, 3)
    assert chart.stage_spawn_key(StageLineage(StageKind.NEW_ROWS, 2)) == (
        SLOT_NEW_ROWS_DEPURATION,
        2,
    )
    assert chart.stage_spawn_key(StageLineage(StageKind.EXTENSION)) == (SLOT_PHASE1, 0)


@pytest.mark.parametrize(
    ("kind", "round_"),
    [(StageKind.PHASE1, -1), (StageKind.NEW_ROWS, 1.0), (StageKind.PHASE1, True)],
)
def test_invalid_lineage_round(kind: StageKind, round_: object) -> None:
    with pytest.raises(InvalidInputError, match="round"):
        StageLineage(kind, round_)


def test_insufficient_in_loop_case_depurates_below_the_minimum(
    active: tuple[T2MRCDModel, np.ndarray],
) -> None:
    case = RECALIBRATION["insufficient_in_loop"]
    model, base = active
    assert case.x_new.shape[0] >= case.params.min_observations
    report = (
        T2MRCDChart()
        .recalibrate(
            model,
            base,
            case.x_new,
            assignable_cause=None,
            force_replace=False,
            params=case.params,
            mapper=MAPPER,
        )
        .report
    )
    assert report.decision is RecalibrationDecision.INSUFFICIENT
    assert report.n_excluded_automatic > 0
    assert report.n_kept_new < case.params.min_observations
    assert report.depuration_rounds >= 1
    assert report.depuration_converged is None


@pytest.mark.parametrize("kind", ["phase1", "new_rows", "extension"])
def test_lineage_kind_given_as_text_is_normalised(kind: str) -> None:
    lineage = StageLineage(kind, 0)
    assert lineage.kind is StageKind(kind)
    assert T2MRCDChart().stage_spawn_key(lineage) == T2MRCDChart().stage_spawn_key(
        StageLineage(StageKind(kind))
    )


def test_unknown_lineage_kind_is_invalid_input() -> None:
    with pytest.raises(InvalidInputError, match="kind") as info:
        StageLineage("bogus", 0)
    assert info.value.details["field"] == "lineage.kind"


def test_extension_given_as_text_keeps_a_single_round() -> None:
    with pytest.raises(InvalidInputError, match="una sola ronda"):
        StageLineage("extension", 5)


def test_extension_lineage_has_a_single_round() -> None:
    with pytest.raises(InvalidInputError, match="una sola ronda"):
        StageLineage(StageKind.EXTENSION, 1)


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
