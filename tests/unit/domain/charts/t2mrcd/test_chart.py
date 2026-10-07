import dataclasses

import numpy as np
import pytest

from support.solo_test import fast_bootstrap, fast_params, small_data
from voracious.domain.charts.t2mrcd import (
    CHART_ID,
    SLOT_PHASE1,
    STATISTIC_REFERENCE,
    T2MRCD_CLEAN_CRITERION_INVALID,
    T2MRCD_DECISION_PENDING,
    T2MRCD_MRCD_ALPHA,
    T2MRCD_NO_CLEAN_OBSERVATIONS,
    LimitRegime,
    T2MRCDBootstrap,
    T2MRCDChart,
    T2MRCDModel,
    T2MRCDParams,
    best_subset_criterion,
    t2,
)
from voracious.domain.charts.t2mrcd import chart as chart_module
from voracious.domain.common import (
    InvalidInputError,
    MethodDecisionPendingError,
    RowDisposition,
    SerialTaskMapper,
)
from voracious.domain.estimators.mrcd import PYMRCD_VERSION, MRCDEstimator, MRCDParams, fit_mrcd


@pytest.fixture(scope="module")
def model() -> T2MRCDModel:
    # Sin depuración automática: el ajuste final es el del histórico completo.
    return T2MRCDChart().fit_phase1(
        small_data(), fast_params(max_depuration_rounds=0), mapper=SerialTaskMapper()
    )


def _spy_fit_mrcd(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> None:
        calls.append(args)
        raise AssertionError("MRCD no debía ajustarse")

    monkeypatch.setattr(MRCDEstimator, "fit", spy)
    return calls


def test_chart_id() -> None:
    assert T2MRCDChart().chart_id == CHART_ID == "t2mrcd"


def test_production_defaults_have_no_pending_decisions() -> None:
    params = T2MRCDParams(bootstrap=T2MRCDBootstrap(seed=1))
    assert T2MRCDChart().pending_decisions(params) == []


def test_explicit_none_aggregation_blocks_before_fitting(monkeypatch: pytest.MonkeyPatch) -> None:
    # El mecanismo de decisiones pendientes se conserva aunque hoy no quede ninguna.
    calls = _spy_fit_mrcd(monkeypatch)
    params = T2MRCDParams(bootstrap=T2MRCDBootstrap(seed=1, aggregation=None))
    with pytest.raises(MethodDecisionPendingError) as info:
        T2MRCDChart().fit_phase1(small_data(), params, mapper=SerialTaskMapper())
    assert info.value.code == T2MRCD_DECISION_PENDING
    assert info.value.details == {"pending": ["bootstrap.aggregation"]}
    assert calls == []


def test_explicit_none_phase2_aggregation_blocks_before_fitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _spy_fit_mrcd(monkeypatch)
    boot = T2MRCDBootstrap(seed=1, aggregation=None, phase2_aggregation=None)
    with pytest.raises(MethodDecisionPendingError) as info:
        T2MRCDChart().fit_phase1(
            small_data(), T2MRCDParams(bootstrap=boot), mapper=SerialTaskMapper()
        )
    assert info.value.details == {
        "pending": ["bootstrap.aggregation", "bootstrap.phase2_aggregation"]
    }
    assert calls == []


def test_statistic_reference_default() -> None:
    # P6: artículo en proceso de publicación (decisión del dueño 2026-10-07); no bloquea.
    assert T2MRCDChart().statistic_reference == STATISTIC_REFERENCE
    assert STATISTIC_REFERENCE


def test_clean_rows_are_ceiling_of_mrcd_alpha_times_n() -> None:
    # n = 41 no es múltiplo de 4: h = ceil(0.75 * 41) = 31 (no 30 ni 0.75 filas).
    x = small_data(41, 4)
    params = fast_params(n_replicates=2, max_depuration_rounds=0)
    model = T2MRCDChart().fit_phase1(x, params, mapper=SerialTaskMapper())
    assert model.mrcd.h == 31
    assert int(model.clean_mask.sum()) == model.limits.n_clean == 31


def test_input_is_validated_before_pending_check(monkeypatch: pytest.MonkeyPatch) -> None:
    _spy_fit_mrcd(monkeypatch)
    x = small_data()
    x[3, 1] = np.nan
    with pytest.raises(InvalidInputError):
        T2MRCDChart().fit_phase1(
            x,
            T2MRCDParams(bootstrap=T2MRCDBootstrap(seed=1, aggregation=None)),
            mapper=SerialTaskMapper(),
        )


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_history_is_invalid_input(monkeypatch: pytest.MonkeyPatch, bad: float) -> None:
    calls = _spy_fit_mrcd(monkeypatch)
    x = small_data()
    x[7, 2] = bad
    with pytest.raises(InvalidInputError) as info:
        T2MRCDChart().fit_phase1(x, fast_params(), mapper=SerialTaskMapper())
    assert info.value.code == "INVALID_INPUT"
    assert info.value.details["rows"] == [7]
    assert calls == []


def test_empty_history_is_invalid_input() -> None:
    with pytest.raises(InvalidInputError, match="vacía"):
        T2MRCDChart().fit_phase1(np.zeros((0, 3)), fast_params(), mapper=SerialTaskMapper())


def test_row_sum_overflow_is_invalid_input() -> None:
    # Fila finita cuya suma desborda: rrcov la descarta (CovMrcd.R:19-20); T²MRCD la rechaza.
    x = small_data()
    x[4, :] = 1e308
    with pytest.raises(InvalidInputError, match="desborda") as info:
        T2MRCDChart().fit_phase1(x, fast_params(), mapper=SerialTaskMapper())
    assert info.value.details["rows"] == [4]


def test_phase1_model(model: T2MRCDModel) -> None:
    x = small_data()
    fit = fit_mrcd(x, MRCDParams(alpha=T2MRCD_MRCD_ALPHA))
    assert model.params.mrcd.alpha == 0.75
    assert np.array_equal(model.mrcd.cov, fit.cov)
    assert model.n_features == 4
    # P2: limpias = subconjunto best del ajuste MRCD con alpha = 0.75.
    assert np.array_equal(np.flatnonzero(model.clean_mask), fit.best)
    assert model.limits.n_clean == fit.h == int(model.clean_mask.sum())
    assert fit.h < 40
    assert model.limits.n_replicates == 5
    assert model.limits.seed == model.seed == 7
    assert np.array_equal(model.historical_t2, fit.mah)
    assert np.array_equal(model.historical_outlier, model.historical_t2 > model.limits.phase1_limit)
    assert model.limits.alpha_limit == 0.005
    assert model.limits.phase2_alpha_limit == 0.005
    # Q2: la versión inicial vigila con el límite de Fase I, de forma provisional.
    assert model.limit_regime is LimitRegime.PHASE1_PROVISIONAL
    assert model.operative_limit == model.limits.phase1_limit
    assert model.limits.spawn_key == (SLOT_PHASE1, 0)
    assert model.base_mask.all()
    assert model.n_base == 40
    assert model.row_disposition == (RowDisposition.KEPT,) * 40
    assert model.depuration_rounds == 0
    assert model.pymrcd_version == PYMRCD_VERSION
    assert model.statistic_reference == STATISTIC_REFERENCE


def test_t2_of_fit_data_equals_mah() -> None:
    x = small_data()
    fit = fit_mrcd(x, MRCDParams())
    assert np.array_equal(t2(fit, x[fit.ok]), fit.mah)


def test_phase2_signal_is_strictly_greater(model: T2MRCDModel) -> None:
    x_new = small_data(10, 4, seed=99)
    x_new[0] += 8.0
    res = T2MRCDChart().score_phase2(model, x_new)
    # Versión inicial: Fase II vigila con el límite de Fase I (provisional).
    assert res.limit == model.operative_limit == model.limits.phase1_limit
    assert res.limit_kind is LimitRegime.PHASE1_PROVISIONAL
    assert np.array_equal(res.t2, t2(model.mrcd, x_new))
    assert np.array_equal(res.signal, res.t2 > res.limit)
    assert res.signal[0]
    # Un T² exactamente igual al límite no es señal (P5: estricto). El límite se toma del T² de la
    # misma entrada que se puntúa: el de una fila sola y el de esa fila dentro de un lote pueden
    # diferir en el último bit (bloqueo de BLAS).
    single = x_new[1:2]
    at_limit = dataclasses.replace(
        model,
        limits=dataclasses.replace(model.limits, phase1_limit=float(t2(model.mrcd, single)[0])),
    )
    assert not T2MRCDChart().score_phase2(at_limit, single).signal[0]


def test_phase2_rejects_wrong_p_and_non_finite(model: T2MRCDModel) -> None:
    chart = T2MRCDChart()
    with pytest.raises(InvalidInputError) as info:
        chart.validate_phase2_input(model, np.zeros((2, 5)))
    assert info.value.details["expected_features"] == 4
    with pytest.raises(InvalidInputError):
        chart.score_phase2(model, np.zeros((2, 3)))
    bad = np.zeros((2, 4))
    bad[1, 0] = np.nan
    with pytest.raises(InvalidInputError):
        chart.validate_phase2_input(model, bad)
    with pytest.raises(InvalidInputError):
        chart.validate_phase2_input(model, np.zeros((0, 4)))
    chart.validate_phase2_input(model, np.zeros((2, 4)))


def test_clean_mask_is_used_for_bootstrap() -> None:
    def first_half(fit: object, x: np.ndarray) -> np.ndarray:
        mask = np.zeros(x.shape[0], dtype=np.bool_)
        mask[: x.shape[0] // 2] = True
        return mask

    boot = dataclasses.replace(fast_bootstrap(), clean_criterion=first_half)
    model = T2MRCDChart().fit_phase1(
        small_data(),
        T2MRCDParams(bootstrap=boot, max_depuration_rounds=0),
        mapper=SerialTaskMapper(),
    )
    assert model.limits.n_clean == 20
    assert model.clean_mask.sum() == 20


@pytest.mark.parametrize(
    ("criterion", "code"),
    [
        (lambda fit, x: np.ones(x.shape[0] - 1, dtype=np.bool_), T2MRCD_CLEAN_CRITERION_INVALID),
        (lambda fit, x: np.ones(x.shape[0]), T2MRCD_CLEAN_CRITERION_INVALID),
        (lambda fit, x: np.zeros(x.shape[0], dtype=np.bool_), T2MRCD_NO_CLEAN_OBSERVATIONS),
    ],
)
def test_invalid_clean_criterion(criterion: object, code: str) -> None:
    boot = dataclasses.replace(fast_bootstrap(), clean_criterion=criterion)
    with pytest.raises(chart_module.EstimationError) as info:
        T2MRCDChart().fit_phase1(
            small_data(), T2MRCDParams(bootstrap=boot), mapper=SerialTaskMapper()
        )
    assert info.value.code == code


def test_best_subset_criterion_marks_exactly_best() -> None:
    x = small_data()
    fit = fit_mrcd(x, MRCDParams(alpha=T2MRCD_MRCD_ALPHA))
    mask = best_subset_criterion(fit, x)
    assert mask.dtype == np.bool_
    assert mask.shape == (40,)
    assert np.array_equal(np.flatnonzero(mask), fit.best)
    assert int(mask.sum()) == fit.h


def test_best_subset_criterion_maps_through_ok() -> None:
    # Si MRCD descartó filas (ok = False), best indexa x[ok]; la máscara se expresa sobre x.
    x = small_data()
    x[4, :] = 1e308
    fit = fit_mrcd(x, MRCDParams(alpha=T2MRCD_MRCD_ALPHA))
    assert not fit.ok[4]
    mask = best_subset_criterion(fit, x)
    assert not mask[4]
    assert np.array_equal(np.flatnonzero(mask), np.flatnonzero(fit.ok)[fit.best])


def test_phase2_uses_phase2_limit_when_recalibrated(model: T2MRCDModel) -> None:
    recalibrated = dataclasses.replace(model, limit_regime=LimitRegime.PHASE2)
    assert recalibrated.operative_limit == model.limits.phase2_limit
    res = T2MRCDChart().score_phase2(recalibrated, small_data(5, 4, seed=8))
    assert res.limit == model.limits.phase2_limit
    assert res.limit_kind is LimitRegime.PHASE2
    assert np.array_equal(res.signal, res.t2 > model.limits.phase2_limit)


def test_human_exclusion_is_applied_before_fitting() -> None:
    x = small_data()
    x[5] += 50.0  # fila con causa asignable confirmada
    excluded = np.zeros(40, dtype=np.bool_)
    excluded[5] = True
    model = T2MRCDChart().fit_phase1(
        x, fast_params(max_depuration_rounds=0), mapper=SerialTaskMapper(), excluded=excluded
    )
    fit = fit_mrcd(np.delete(x, 5, axis=0), MRCDParams(alpha=T2MRCD_MRCD_ALPHA))
    assert np.array_equal(model.mrcd.cov, fit.cov)
    assert not model.base_mask[5]
    assert model.n_base == 39
    assert model.row_disposition[5] is RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE
    assert not model.clean_mask[5]
    # La fila excluida también se puntúa con el ajuste final.
    assert model.historical_t2.shape == (40,)
    assert model.historical_outlier[5]


@pytest.mark.parametrize(
    "bad",
    [np.zeros(39, dtype=np.bool_), np.zeros(40), [0, 1] * 20],
)
def test_invalid_excluded_mask(bad: object) -> None:
    with pytest.raises(InvalidInputError) as info:
        T2MRCDChart().fit_phase1(
            small_data(), fast_params(), mapper=SerialTaskMapper(), excluded=bad
        )
    assert info.value.details["input"] == "excluded"


def test_all_rows_excluded_is_an_error() -> None:
    with pytest.raises(chart_module.EstimationError) as info:
        T2MRCDChart().fit_phase1(
            small_data(),
            fast_params(),
            mapper=SerialTaskMapper(),
            excluded=np.ones(40, dtype=np.bool_),
        )
    assert info.value.code == T2MRCD_NO_CLEAN_OBSERVATIONS


def test_automatic_depuration_removes_rows_above_phase1_limit() -> None:
    # Q3: ajuste + límite de Fase I, quitar T² > límite y repetir; la base final no tiene filas
    # por encima del límite si converge.
    x = small_data(60, 3, seed=5)
    x[:3] += 6.0
    model = T2MRCDChart().fit_phase1(x, fast_params(), mapper=SerialTaskMapper())
    auto = [
        i for i, d in enumerate(model.row_disposition) if d is RowDisposition.EXCLUDED_AUTOMATIC
    ]
    assert {0, 1, 2} <= set(auto)
    assert model.depuration_rounds >= 1
    assert model.limits.spawn_key == (SLOT_PHASE1, model.depuration_rounds)
    assert not model.base_mask[auto].any()
    assert model.depuration_converged
    assert not (model.historical_t2[model.base_mask] > model.limits.phase1_limit).any()
    fit = fit_mrcd(x[model.base_mask], MRCDParams(alpha=T2MRCD_MRCD_ALPHA))
    assert np.array_equal(model.mrcd.cov, fit.cov)


def test_depuration_without_rounds_does_not_converge_but_continues() -> None:
    # Q5: si se agotan las rondas se sigue con converged = False (no es un error).
    x = small_data(60, 3, seed=5)
    x[:3] += 6.0
    model = T2MRCDChart().fit_phase1(
        x, fast_params(max_depuration_rounds=0), mapper=SerialTaskMapper()
    )
    assert model.depuration_rounds == 0
    assert not model.depuration_converged
    assert model.base_mask.all()
    assert model.historical_outlier[:3].all()
