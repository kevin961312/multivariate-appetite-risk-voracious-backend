"""Recalibración de T²MRCD: exclusión humana, decisión EXTEND/REPLACE/INSUFFICIENT e informe.

Sin depuración automática iterativa (decisión del dueño, 2026-10-09): las filas nuevas solo pasan
por la exclusión humana y se recalibra en una sola pasada. Sin comparación de bases (decisión del
dueño, 2026-10-14): la carta T² ya es la prueba de hipótesis sobre la media, así que se amplía la
base por defecto (EXTEND) y solo se reemplaza (REPLACE) con ``force_replace`` (evento estructural o
petición explícita), aunque las filas nuevas estén desplazadas.
"""

import dataclasses

import numpy as np
import pytest

from support.mappers import ReversedTaskMapper
from support.solo_test import fast_params
from voracious.domain.charts.t2mrcd import (
    DEFAULT_MIN_OBSERVATIONS,
    SLOT_NEW_ROWS,
    SLOT_PHASE1,
    T2MRCD_DECISION_PENDING,
    T2MRCD_MRCD_ALPHA,
    LimitRegime,
    T2MRCDBootstrap,
    T2MRCDChart,
    T2MRCDModel,
    T2MRCDParams,
    T2MRCDRecalibrationParams,
    decide,
)
from voracious.domain.common import (
    InvalidInputError,
    MethodDecisionPendingError,
    RecalibrationDecision,
    RecalibrationOutcome,
    RowDisposition,
    SerialTaskMapper,
)
from voracious.domain.estimators.mrcd import MRCDEstimator, MRCDParams, fit_mrcd

CHART = T2MRCDChart()


def _normal(seed: int, n: int = 200, p: int = 3) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal((n, p))


@pytest.fixture(scope="module")
def active() -> tuple[T2MRCDModel, np.ndarray]:
    x = _normal(20)
    model = CHART.fit_phase1(x, fast_params(), mapper=SerialTaskMapper())
    return model, x[model.base_mask]


def _recalibrate(
    active: tuple[T2MRCDModel, np.ndarray],
    x_new: np.ndarray,
    params: T2MRCDRecalibrationParams | None = None,
    *,
    force_replace: bool = False,
    assignable_cause: np.ndarray | None = None,
    mapper: object = None,
) -> RecalibrationOutcome:
    model, base = active
    return CHART.recalibrate(
        model,
        base,
        x_new,
        assignable_cause=assignable_cause,
        force_replace=force_replace,
        params=params or T2MRCDRecalibrationParams(seed=11),
        mapper=mapper or SerialTaskMapper(),
    )


def _spy_fit(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []

    def spy(*args: object) -> None:
        calls.append(args)
        raise AssertionError("MRCD no debía ajustarse")

    monkeypatch.setattr(MRCDEstimator, "fit", spy)
    return calls


# --- parámetros --------------------------------------------------------------------------------


def test_production_defaults() -> None:
    params = T2MRCDRecalibrationParams(seed=1)
    assert params.min_observations == DEFAULT_MIN_OBSERVATIONS == 25  # documento del dueño
    assert [f.name for f in dataclasses.fields(params)] == ["seed", "min_observations"]


def test_seed_is_mandatory() -> None:
    with pytest.raises(TypeError):
        T2MRCDRecalibrationParams(**{})


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"seed": -1}, "recalibration.seed"),
        ({"seed": 1.0}, "recalibration.seed"),
        ({"seed": 1, "min_observations": 0}, "recalibration.min_observations"),
        ({"seed": 1, "min_observations": 2.0}, "recalibration.min_observations"),
    ],
)
def test_invalid_recalibration_params(kwargs: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidInputError) as info:
        T2MRCDRecalibrationParams(**kwargs)
    assert info.value.details["field"] == field


def test_there_is_no_automatic_depuration_parameter() -> None:
    """Decisión del dueño (2026-10-09): sin depuración automática iterativa ni su parámetro."""
    with pytest.raises(TypeError):
        T2MRCDRecalibrationParams(**{"seed": 1, "max_depuration_rounds": 1})


# --- decide (pura) -----------------------------------------------------------------------------


def test_decide_is_pure_and_ordered() -> None:
    # Pocas filas → INSUFFICIENT aunque se pida el reemplazo; reemplazo pedido → REPLACE; si no,
    # EXTEND (por defecto, sin comparar bases).
    assert decide(n_kept=24, min_observations=25, force_replace=True) is (
        RecalibrationDecision.INSUFFICIENT
    )
    assert decide(n_kept=24, min_observations=25, force_replace=False) is (
        RecalibrationDecision.INSUFFICIENT
    )
    assert decide(n_kept=25, min_observations=25, force_replace=True) is (
        RecalibrationDecision.REPLACE
    )
    assert decide(n_kept=25, min_observations=25, force_replace=False) is (
        RecalibrationDecision.EXTEND
    )


# --- escenarios con la carta -------------------------------------------------------------------


def test_stable_data_extends_the_base(active: tuple[T2MRCDModel, np.ndarray]) -> None:
    model, base = active
    x_new = _normal(101)
    out = _recalibrate(active, x_new)
    report = out.report
    assert out.decision is RecalibrationDecision.EXTEND
    # Nueva base = vstack(base, nuevas conservadas); Fase I completa en régimen PHASE2.
    new_model = out.model
    assert new_model is not None
    kept = np.array([d is RowDisposition.KEPT for d in report.row_disposition[base.shape[0] :]])
    assert report.n_kept_new == int(kept.sum())
    assert new_model.n_base == base.shape[0] + report.n_kept_new
    combined = np.vstack([base, x_new[kept]])
    fit = fit_mrcd(combined, MRCDParams(alpha=T2MRCD_MRCD_ALPHA))
    assert np.array_equal(new_model.mrcd.cov, fit.cov)
    assert new_model.limit_regime is LimitRegime.PHASE2
    assert new_model.operative_limit == new_model.limits.phase2_limit
    # Sin depuración automática: se conservan todas las filas nuevas (sin causa asignable).
    assert report.n_kept_new == 200
    # Q8: hereda B, niveles y MRCD; la semilla es la de la recalibración (hueco de Fase I).
    assert new_model.params.mrcd == model.params.mrcd
    assert new_model.params.bootstrap.n_replicates == model.params.bootstrap.n_replicates
    assert new_model.params.bootstrap.alpha_limit == model.params.bootstrap.alpha_limit
    assert new_model.limits.seed == new_model.seed == 11
    assert new_model.limits.spawn_key == (SLOT_PHASE1, 0)
    # Informe antes/después.
    assert report.row_disposition[: base.shape[0]] == (RowDisposition.ALREADY_IN_BASE,) * len(base)
    assert report.n_base == base.shape[0]
    assert report.n_new == 200
    assert report.before.operative_limit == model.operative_limit
    assert report.before.regime is LimitRegime.PHASE1_PROVISIONAL
    assert report.after is not None
    assert report.after.regime is LimitRegime.PHASE2
    assert report.after.n_base == new_model.n_base
    assert report.phase2_exceeds_phase1 == new_model.limits.phase2_exceeds_phase1


@pytest.mark.parametrize("shift", ["mean", "scale"])
def test_shifted_rows_still_extend_without_a_request(
    active: tuple[T2MRCDModel, np.ndarray], shift: str
) -> None:
    # Sin comparación de bases: ni una media desplazada ni una dispersión x2 reemplazan la base
    # por sí solas (eso lo dice la carta T² en Fase II y lo decide una persona).
    x_new = _normal(101) + 1.0 if shift == "mean" else _normal(101) * np.sqrt(2.0)
    out = _recalibrate(active, x_new)
    assert out.decision is RecalibrationDecision.EXTEND
    assert out.model is not None
    assert out.model.n_base == active[1].shape[0] + 200


def test_requested_replace_uses_only_the_new_rows(
    active: tuple[T2MRCDModel, np.ndarray],
) -> None:
    x_new = _normal(101) + 1.0
    out = _recalibrate(active, x_new, force_replace=True)
    assert out.decision is RecalibrationDecision.REPLACE
    new_model = out.model
    assert new_model is not None
    kept = np.array(
        [d is RowDisposition.KEPT for d in out.report.row_disposition[out.report.n_base :]]
    )
    assert new_model.n_base == int(kept.sum()) == out.report.n_kept_new
    fit = fit_mrcd(x_new[kept], MRCDParams(alpha=T2MRCD_MRCD_ALPHA))
    assert np.array_equal(new_model.mrcd.cov, fit.cov)
    assert new_model.limit_regime is LimitRegime.PHASE2
    assert new_model.params == dataclasses.replace(
        active[0].params,
        bootstrap=dataclasses.replace(active[0].params.bootstrap, seed=new_model.seed),
    )


def test_few_observations_are_insufficient_without_fitting(
    active: tuple[T2MRCDModel, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    # (d) Menos de min_observations filas: INSUFFICIENT, sin modelo, sin excepción, sin ajustar.
    calls = _spy_fit(monkeypatch)
    out = _recalibrate(active, _normal(5, n=24))
    assert out.decision is RecalibrationDecision.INSUFFICIENT
    assert out.model is None
    assert calls == []
    report = out.report
    assert report.after is None
    assert report.phase2_exceeds_phase1 is None
    assert report.n_kept_new == 24
    assert report.min_observations == 25


def test_human_exclusion_can_make_it_insufficient(
    active: tuple[T2MRCDModel, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy_fit(monkeypatch)
    cause = np.zeros(30, dtype=np.bool_)
    cause[:6] = True
    out = _recalibrate(active, _normal(5, n=30), assignable_cause=cause)
    assert out.decision is RecalibrationDecision.INSUFFICIENT
    assert calls == []
    report = out.report
    assert report.n_excluded_assignable_cause == 6
    new_rows = report.row_disposition[report.n_base :]
    assert new_rows[:6] == (RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE,) * 6
    assert new_rows[6:] == (RowDisposition.KEPT,) * 24


def test_outliers_without_assignable_cause_stay_in_the_new_rows(
    active: tuple[T2MRCDModel, np.ndarray],
) -> None:
    # Sin depuración automática: una atípica sin causa asignable no se quita (antes la quitaba la
    # depuración); solo sale la fila con causa asignable confirmada.
    x_new = _normal(101)
    x_new[0] += 40.0  # causa asignable confirmada
    x_new[1] += 12.0  # atípica sin causa: se conserva
    cause = np.zeros(200, dtype=np.bool_)
    cause[0] = True
    out = _recalibrate(active, x_new, assignable_cause=cause)
    report = out.report
    new_rows = report.row_disposition[report.n_base :]
    assert new_rows[0] is RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE
    assert new_rows[1:] == (RowDisposition.KEPT,) * 199
    assert set(report.row_disposition) <= {
        RowDisposition.ALREADY_IN_BASE,
        RowDisposition.KEPT,
        RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE,
    }
    assert report.n_excluded_assignable_cause == 1
    assert report.n_kept_new == 199


def test_force_replace_is_insufficient_with_few_rows(
    active: tuple[T2MRCDModel, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy_fit(monkeypatch)
    out = _recalibrate(active, _normal(5, n=24), force_replace=True)
    assert out.decision is RecalibrationDecision.INSUFFICIENT
    assert out.model is None
    assert calls == []


def test_pending_phase1_decisions_block_before_fitting(
    active: tuple[T2MRCDModel, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    # T2MRCD_DECISION_PENDING sigue solo para la Fase I: si los parámetros heredados del modelo
    # vigente tienen una agregación pendiente, la recalibración no ajusta nada.
    model, base = active
    pending = dataclasses.replace(
        model,
        params=T2MRCDParams(bootstrap=T2MRCDBootstrap(seed=7, n_replicates=5, aggregation=None)),
    )
    calls = _spy_fit(monkeypatch)
    for force_replace in (False, True):
        with pytest.raises(MethodDecisionPendingError) as info:
            _recalibrate((pending, base), _normal(101), force_replace=force_replace)
        assert info.value.code == T2MRCD_DECISION_PENDING
        assert info.value.details == {"pending": ["bootstrap.aggregation"]}
    assert calls == []


def test_recalibration_is_reproducible_in_any_order(
    active: tuple[T2MRCDModel, np.ndarray],
) -> None:
    # (h) Mismo resultado en serie y en orden inverso.
    x_new = _normal(101) + 1.0
    serial = _recalibrate(active, x_new)
    backwards = _recalibrate(active, x_new, mapper=ReversedTaskMapper())
    assert serial.decision is backwards.decision
    assert serial.report.row_disposition == backwards.report.row_disposition
    assert serial.model is not None
    assert backwards.model is not None
    assert serial.model.limits == backwards.model.limits


def _record_spawn_keys(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, ...]]:
    from voracious.domain.charts.t2mrcd import phase1 as phase1_module

    keys: list[tuple[int, ...]] = []
    original = phase1_module.calibrate_limits

    def recording(*args: object, **kwargs: object) -> object:
        keys.append(tuple(kwargs["spawn_key"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(phase1_module, "calibrate_limits", recording)
    return keys


def test_replace_calibrates_in_the_new_rows_slot(
    active: tuple[T2MRCDModel, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    # REPLACE: la nueva base son las filas nuevas conservadas, con una única calibración en su
    # hueco (1, 0).
    keys = _record_spawn_keys(monkeypatch)
    out = _recalibrate(active, _normal(101) + 1.0, force_replace=True)
    assert out.decision is RecalibrationDecision.REPLACE
    assert keys == [(SLOT_NEW_ROWS, 0)]
    assert out.model is not None
    assert out.model.limits.spawn_key == (SLOT_NEW_ROWS, 0)


def test_extend_calibrates_in_the_phase1_slot(
    active: tuple[T2MRCDModel, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    # EXTEND: una única calibración, la de la base ampliada, en el hueco (0, 0).
    keys = _record_spawn_keys(monkeypatch)
    out = _recalibrate(active, _normal(101))
    assert out.decision is RecalibrationDecision.EXTEND
    assert keys == [(SLOT_PHASE1, 0)]


def test_base_must_be_the_active_base(active: tuple[T2MRCDModel, np.ndarray]) -> None:
    model, base = active
    params = T2MRCDRecalibrationParams(seed=11)
    tampered = base.copy()
    tampered[3, 0] += 1.0
    for bad in (tampered, base[:-1]):
        with pytest.raises(InvalidInputError) as info:
            CHART.recalibrate(
                model,
                bad,
                _normal(101),
                assignable_cause=None,
                force_replace=False,
                params=params,
                mapper=SerialTaskMapper(),
            )
        assert info.value.details["reason"] == "base_mismatch"
    with pytest.raises(InvalidInputError):
        CHART.recalibrate(
            model,
            base,
            _normal(101, p=4),
            assignable_cause=None,
            force_replace=False,
            params=params,
            mapper=SerialTaskMapper(),
        )
    with pytest.raises(InvalidInputError):
        CHART.recalibrate(
            model,
            base,
            _normal(101),
            assignable_cause=np.zeros(3, dtype=np.bool_),
            force_replace=False,
            params=params,
            mapper=SerialTaskMapper(),
        )
