"""Recalibración de T²MRCD: exclusión humana, decisión EXTEND/REPLACE/INSUFFICIENT e informe.

Sin depuración automática iterativa (decisión del dueño, 2026-10-09): las filas nuevas solo pasan
por la exclusión humana y se recalibra en una sola pasada.

Los escenarios (a)-(c) usan las pruebas de permutación «SOLO TEST» de ``tests/support`` (las de
producción están pendientes), que son las que deciden. La Frobenius relativa con el umbral de
producción (0.10) es solo informativa: con n = 200 y p = 3 el ruido de estimación de MRCD entre
dos muestras de la misma normal ya la lleva por encima de 0.10 (se documenta en un test aparte).
"""

import dataclasses

import numpy as np
import pytest

from support.change_tests import FixedTest
from support.mappers import ReversedTaskMapper
from support.solo_test import fast_params, solo_test_recalibration
from voracious.domain.charts.t2mrcd import (
    DEFAULT_MIN_OBSERVATIONS,
    DEFAULT_RELATIVE_CHANGE_THRESHOLD,
    SLOT_NEW_ROWS,
    SLOT_PHASE1,
    T2MRCD_DECISION_PENDING,
    T2MRCD_MRCD_ALPHA,
    ComparisonResult,
    LimitRegime,
    T2MRCDChart,
    T2MRCDModel,
    T2MRCDRecalibrationParams,
    any_formal_test_change,
    decide,
    frobenius_relative_change,
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
        params=params or solo_test_recalibration(),
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


def test_production_defaults_and_pending() -> None:
    params = T2MRCDRecalibrationParams(seed=1)
    assert params.min_observations == DEFAULT_MIN_OBSERVATIONS == 25  # documento del dueño
    assert params.relative_change_threshold == DEFAULT_RELATIVE_CHANGE_THRESHOLD == 0.10  # Q4
    assert params.threshold_decides is False  # Q4: el umbral es informativo por defecto
    assert params.relative_change_metric is frobenius_relative_change  # Q4
    assert params.decision_rule is any_formal_test_change  # Q4: solo deciden las pruebas
    # (i) Las pruebas formales y sus remuestreos siguen pendientes (sin cita).
    assert CHART.pending_recalibration_decisions(params) == [
        "recalibration.covariance_test",
        "recalibration.mean_test",
        "recalibration.n_test_resamples",
    ]
    assert CHART.pending_recalibration_decisions(solo_test_recalibration()) == []


def test_seed_is_mandatory() -> None:
    with pytest.raises(TypeError):
        T2MRCDRecalibrationParams(**{})


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"seed": -1}, "recalibration.seed"),
        ({"seed": 1.0}, "recalibration.seed"),
        ({"seed": 1, "min_observations": 0}, "recalibration.min_observations"),
        ({"seed": 1, "relative_change_threshold": 0.0}, "recalibration.relative_change_threshold"),
        (
            {"seed": 1, "relative_change_threshold": float("inf")},
            "recalibration.relative_change_threshold",
        ),
        ({"seed": 1, "threshold_decides": 1}, "recalibration.threshold_decides"),
        ({"seed": 1, "n_test_resamples": 0}, "recalibration.n_test_resamples"),
        ({"seed": 1, "n_test_resamples": 2.0}, "recalibration.n_test_resamples"),
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


def _comparison(changed: bool) -> ComparisonResult:
    test = FixedTest(changed=False)(np.zeros((1, 1)), np.zeros((1, 1)))
    return ComparisonResult("m", 0.0, 0.1, False, False, test, test, "r", changed)


def test_decide_is_pure_and_ordered() -> None:
    insufficient = decide(_comparison(True), n_kept=24, min_observations=25, force_replace=True)
    assert insufficient is RecalibrationDecision.INSUFFICIENT
    assert decide(None, n_kept=25, min_observations=25, force_replace=True) is (
        RecalibrationDecision.REPLACE
    )
    assert decide(_comparison(True), n_kept=30, min_observations=25, force_replace=False) is (
        RecalibrationDecision.REPLACE
    )
    assert decide(_comparison(False), n_kept=30, min_observations=25, force_replace=False) is (
        RecalibrationDecision.EXTEND
    )
    with pytest.raises(ValueError, match="sin comparación"):
        decide(None, n_kept=30, min_observations=25, force_replace=False)


# --- escenarios con la carta -------------------------------------------------------------------


def test_stable_data_extends_the_base(active: tuple[T2MRCDModel, np.ndarray]) -> None:
    # (a) Misma normal: ninguna de las pruebas formales detecta cambio → EXTEND.
    model, base = active
    x_new = _normal(101)
    out = _recalibrate(active, x_new)
    report = out.report
    assert out.decision is RecalibrationDecision.EXTEND
    assert report.comparison is not None
    assert not report.comparison.changed
    assert not report.comparison.covariance.changed
    assert not report.comparison.mean.changed
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


def test_production_threshold_is_informative_only(
    active: tuple[T2MRCDModel, np.ndarray],
) -> None:
    # Motivo de la decisión del dueño: con datos estables la Frobenius relativa ya supera el
    # umbral de producción (0.10) por puro ruido de estimación; por eso no decide y se EXTIENDE.
    out = _recalibrate(active, _normal(101))
    comparison = out.report.comparison
    assert comparison is not None
    assert comparison.threshold == DEFAULT_RELATIVE_CHANGE_THRESHOLD == 0.10
    assert comparison.relative_change > 0.10
    assert comparison.exceeds_threshold
    assert not comparison.threshold_decides
    assert not comparison.changed
    assert out.decision is RecalibrationDecision.EXTEND


def test_threshold_decides_replaces_on_estimation_noise(
    active: tuple[T2MRCDModel, np.ndarray],
) -> None:
    # Modo decisivo: el mismo escenario estable supera 0.10 y con threshold_decides=True se
    # reemplaza aunque las pruebas formales no detecten cambio («cualquiera»).
    out = _recalibrate(active, _normal(101), solo_test_recalibration(threshold_decides=True))
    comparison = out.report.comparison
    assert comparison is not None
    assert comparison.threshold_decides
    assert comparison.exceeds_threshold
    assert not comparison.covariance.changed
    assert not comparison.mean.changed
    assert comparison.changed
    assert out.decision is RecalibrationDecision.REPLACE
    # Con un umbral configurado por encima del cambio observado, vuelve a EXTEND.
    relaxed = solo_test_recalibration(
        threshold_decides=True, relative_change_threshold=comparison.relative_change * 2
    )
    again = _recalibrate(active, _normal(101), relaxed)
    assert again.report.comparison is not None
    assert not again.report.comparison.exceeds_threshold
    assert again.decision is RecalibrationDecision.EXTEND


def test_threshold_decides_keeps_formal_tests_pending(
    active: tuple[T2MRCDModel, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Que el umbral decida no salta las pruebas formales pendientes.
    calls = _spy_fit(monkeypatch)
    params = T2MRCDRecalibrationParams(seed=3, threshold_decides=True)
    assert CHART.pending_recalibration_decisions(params) == [
        "recalibration.covariance_test",
        "recalibration.mean_test",
        "recalibration.n_test_resamples",
    ]
    with pytest.raises(MethodDecisionPendingError) as info:
        _recalibrate(active, _normal(101), params)
    assert info.value.code == T2MRCD_DECISION_PENDING
    assert calls == []


def test_shifted_mean_replaces_the_base(active: tuple[T2MRCDModel, np.ndarray]) -> None:
    # (b) Media desplazada: la prueba de ubicación lo detecta → REPLACE (regla «cualquiera de las
    # dos pruebas formales»).
    x_new = _normal(101) + 1.0
    out = _recalibrate(active, x_new)
    comparison = out.report.comparison
    assert comparison is not None
    assert comparison.mean.changed
    assert comparison.changed
    assert out.decision is RecalibrationDecision.REPLACE
    new_model = out.model
    assert new_model is not None
    kept = np.array(
        [d is RowDisposition.KEPT for d in out.report.row_disposition[out.report.n_base :]]
    )
    assert new_model.n_base == int(kept.sum())
    fit = fit_mrcd(x_new[kept], MRCDParams(alpha=T2MRCD_MRCD_ALPHA))
    assert np.array_equal(new_model.mrcd.cov, fit.cov)
    assert new_model.params == dataclasses.replace(
        active[0].params,
        bootstrap=dataclasses.replace(active[0].params.bootstrap, seed=new_model.seed),
    )


@pytest.mark.parametrize("factor", [1.5, 2.0])
def test_scaled_covariance_is_detected(
    active: tuple[T2MRCDModel, np.ndarray], factor: float
) -> None:
    # (c) S x 1.5 y S x 2: cambio de dispersión detectado por la prueba formal (el umbral
    # informativo también se supera, pero no decide).
    out = _recalibrate(active, _normal(101) * np.sqrt(factor))
    comparison = out.report.comparison
    assert comparison is not None
    assert comparison.covariance.changed
    assert comparison.exceeds_threshold
    assert out.decision is RecalibrationDecision.REPLACE


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
    assert report.comparison is None
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


def test_force_replace_skips_comparison_and_pending(
    active: tuple[T2MRCDModel, np.ndarray],
) -> None:
    # (e) Reemplazo forzado con los defaults de producción (pruebas pendientes): REPLACE sin
    # comparar y sin T2MRCD_DECISION_PENDING.
    out = _recalibrate(active, _normal(101), T2MRCDRecalibrationParams(seed=3), force_replace=True)
    assert out.decision is RecalibrationDecision.REPLACE
    assert out.report.forced
    assert out.report.comparison is None
    assert out.model is not None
    assert out.model.n_base == out.report.n_kept_new
    assert out.model.limit_regime is LimitRegime.PHASE2


def test_production_defaults_block_before_fitting(
    active: tuple[T2MRCDModel, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    # (i) Sin pruebas decididas: T2MRCD_DECISION_PENDING antes de ajustar nada.
    calls = _spy_fit(monkeypatch)
    with pytest.raises(MethodDecisionPendingError) as info:
        _recalibrate(active, _normal(101), T2MRCDRecalibrationParams(seed=3))
    assert info.value.code == T2MRCD_DECISION_PENDING
    assert info.value.details == {
        "pending": [
            "recalibration.covariance_test",
            "recalibration.mean_test",
            "recalibration.n_test_resamples",
        ]
    }
    assert calls == []


def test_recalibration_is_reproducible_in_any_order(
    active: tuple[T2MRCDModel, np.ndarray],
) -> None:
    # (h) Mismo resultado en serie y en orden inverso.
    x_new = _normal(101) + 1.0
    serial = _recalibrate(active, x_new)
    backwards = _recalibrate(active, x_new, mapper=ReversedTaskMapper())
    assert serial.decision is backwards.decision
    assert serial.report.comparison == backwards.report.comparison
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


def test_replace_reuses_the_new_rows_calibration(
    active: tuple[T2MRCDModel, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    # REPLACE: la nueva base son las filas nuevas conservadas, así que se reutiliza su única
    # calibración (sin repetir las B réplicas en el hueco de Fase I).
    keys = _record_spawn_keys(monkeypatch)
    out = _recalibrate(active, _normal(101) + 1.0)
    assert out.decision is RecalibrationDecision.REPLACE
    assert keys == [(SLOT_NEW_ROWS, 0)]
    assert out.model is not None
    assert out.model.limits.spawn_key == (SLOT_NEW_ROWS, 0)


def test_extend_calibrates_in_the_phase1_slot(
    active: tuple[T2MRCDModel, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = _record_spawn_keys(monkeypatch)
    out = _recalibrate(active, _normal(101))
    assert out.decision is RecalibrationDecision.EXTEND
    assert keys == [(SLOT_NEW_ROWS, 0), (SLOT_PHASE1, 0)]


def test_base_must_be_the_active_base(active: tuple[T2MRCDModel, np.ndarray]) -> None:
    model, base = active
    params = solo_test_recalibration()
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
