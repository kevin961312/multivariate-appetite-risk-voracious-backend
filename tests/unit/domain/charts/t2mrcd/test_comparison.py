import numpy as np
import pytest

from support.change_tests import FixedTest
from support.classical import ClassicalEstimator
from voracious.domain.charts.t2mrcd import (
    SLOT_COVARIANCE_TEST,
    SLOT_MEAN_TEST,
    AnyFormalTestChangeRule,
    ChangeTestResult,
    FrobeniusRelativeChange,
    any_formal_test_change,
    compare_bases,
    frobenius_relative_change,
)
from voracious.domain.common import SerialTaskMapper


def _result(changed: bool) -> ChangeTestResult:
    return ChangeTestResult(name="t", statistic=0.0, p_value=None, changed=changed)


def test_frobenius_relative_change() -> None:
    # Q4: ‖S1 - S0‖_F / ‖S0‖_F.
    s0 = np.eye(2)
    s1 = np.array([[1.5, 0.0], [0.0, 1.5]])
    assert frobenius_relative_change(s0, s1) == pytest.approx(0.5)
    assert frobenius_relative_change(s0, 2 * s0) == pytest.approx(1.0)
    assert frobenius_relative_change(s0, s0) == 0.0
    assert frobenius_relative_change.name == "frobenius_relative"
    assert isinstance(frobenius_relative_change, FrobeniusRelativeChange)


@pytest.mark.parametrize(
    ("cov", "mean", "expected"),
    [
        (False, False, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
def test_any_formal_test_change_rule(cov: bool, mean: bool, expected: bool) -> None:
    # Decisión del dueño: reemplazar si cualquiera de las dos pruebas formales detecta cambio;
    # el cambio relativo de la dispersión no entra en la regla.
    assert any_formal_test_change(_result(cov), _result(mean)) is expected
    assert any_formal_test_change.name == "any_formal_test_change"
    assert isinstance(any_formal_test_change, AnyFormalTestChangeRule)


class _RecordingTest(FixedTest):
    seeds: list[np.random.SeedSequence]

    def __init__(self, test_name: str) -> None:
        super().__init__(changed=False, test_name=test_name)
        object.__setattr__(self, "seeds", [])

    def __call__(self, base: np.ndarray, new: np.ndarray, **kwargs: object) -> ChangeTestResult:
        seed = kwargs["seed"]
        assert isinstance(seed, np.random.SeedSequence)
        self.seeds.append(seed)
        assert kwargs["n_resamples"] == 7
        return super().__call__(base, new)


def test_compare_bases_reports_threshold_and_uses_fixed_seed_slots() -> None:
    rng = np.random.default_rng(0)
    base, new = rng.standard_normal((30, 2)), 1.2 * rng.standard_normal((30, 2))
    est = ClassicalEstimator()
    fit0, fit1 = est.fit(base), est.fit(new)
    cov_test, mean_test = _RecordingTest("cov"), _RecordingTest("mean")
    relative = frobenius_relative_change(fit0.cov, fit1.cov)
    result = compare_bases(
        base,
        new,
        fit0=fit0,
        fit1=fit1,
        metric=frobenius_relative_change,
        threshold=relative,  # estricto: igual al umbral no lo supera
        threshold_decides=True,
        covariance_test=cov_test,
        mean_test=mean_test,
        decision_rule=any_formal_test_change,
        estimator=est,
        seed=9,
        n_test_resamples=7,
        mapper=SerialTaskMapper(),
    )
    assert result.relative_change == relative
    assert not result.exceeds_threshold
    assert result.threshold_decides
    assert not result.changed
    assert result.metric_name == "frobenius_relative"
    assert result.decision_rule_name == "any_formal_test_change"
    assert result.covariance.name == "cov"
    assert result.mean.name == "mean"
    assert cov_test.seeds[0].spawn_key == (SLOT_COVARIANCE_TEST,)
    assert mean_test.seeds[0].spawn_key == (SLOT_MEAN_TEST,)
    assert cov_test.seeds[0].entropy == mean_test.seeds[0].entropy == 9

    exceeded = compare_bases(
        base,
        new,
        fit0=fit0,
        fit1=fit1,
        metric=frobenius_relative_change,
        threshold=relative / 2,
        threshold_decides=False,
        covariance_test=FixedTest(changed=False),
        mean_test=FixedTest(changed=False),
        decision_rule=any_formal_test_change,
        estimator=est,
        seed=9,
        n_test_resamples=7,
        mapper=SerialTaskMapper(),
    )
    # El umbral es solo informativo: superarlo no decide el cambio si las pruebas no lo detectan.
    assert exceeded.exceeds_threshold
    assert not exceeded.threshold_decides
    assert not exceeded.changed


@pytest.mark.parametrize(
    ("threshold_decides", "exceeds", "cov", "mean", "expected"),
    [
        # Modo informativo (default): solo deciden las pruebas formales.
        (False, True, False, False, False),
        (False, False, True, False, True),
        (False, True, False, True, True),
        # Modo decisivo: «cualquiera» (umbral, prueba de S o prueba de μ).
        (True, True, False, False, True),
        (True, False, False, False, False),
        (True, False, True, False, True),
        (True, False, False, True, True),
    ],
)
def test_threshold_decides_only_when_enabled(
    threshold_decides: bool, exceeds: bool, cov: bool, mean: bool, expected: bool
) -> None:
    rng = np.random.default_rng(1)
    base, new = rng.standard_normal((30, 2)), 1.2 * rng.standard_normal((30, 2))
    est = ClassicalEstimator()
    fit0, fit1 = est.fit(base), est.fit(new)
    relative = frobenius_relative_change(fit0.cov, fit1.cov)
    result = compare_bases(
        base,
        new,
        fit0=fit0,
        fit1=fit1,
        metric=frobenius_relative_change,
        threshold=relative / 2 if exceeds else relative * 2,
        threshold_decides=threshold_decides,
        covariance_test=FixedTest(changed=cov),
        mean_test=FixedTest(changed=mean),
        decision_rule=any_formal_test_change,
        estimator=est,
        seed=9,
        n_test_resamples=7,
        mapper=SerialTaskMapper(),
    )
    assert result.exceeds_threshold is exceeds
    assert result.threshold_decides is threshold_decides
    assert result.changed is expected
