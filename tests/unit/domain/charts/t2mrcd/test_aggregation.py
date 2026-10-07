import numpy as np
import pytest

from support.solo_test import small_data
from voracious.domain.charts.t2mrcd import (
    DEFAULT_ALPHA_LIMIT,
    QUANTILE_METHOD,
    T2MRCD_MRCD_ALPHA,
    ReplicateContext,
    calibrate_limits,
    mean_of_replicate_quantiles,
    replicate_tasks,
    run_replicate,
)
from voracious.domain.common import SerialTaskMapper
from voracious.domain.estimators.mrcd import MRCDParams


def test_quantile_probability_is_one_minus_alpha_limit() -> None:
    # alpha_limit = 0.005 es una proporción: la probabilidad del cuantil es 0.995 (no 99.5).
    values = np.arange(1.0, 201.0)
    got = mean_of_replicate_quantiles([values], DEFAULT_ALPHA_LIMIT)
    assert QUANTILE_METHOD == "linear"
    assert got == float(np.quantile(values, 0.995, method="linear"))
    assert got != float(np.quantile(values, 0.005, method="linear"))
    # Tipo 7 de R: 1 + (n - 1) * 0.995 = 199.005.
    assert got == pytest.approx(199.005, rel=0, abs=1e-12)


def test_limit_is_mean_of_per_replicate_quantiles() -> None:
    reps = [np.array([1.0, 2.0, 3.0, 4.0]), np.array([10.0, 20.0]), np.array([5.0])]
    alpha = 0.1
    expected = np.mean([np.quantile(r, 0.9, method="linear") for r in reps])
    assert mean_of_replicate_quantiles(reps, alpha) == float(expected)
    # Distinto del cuantil del pool (la opción (a), descartada).
    assert mean_of_replicate_quantiles(reps, alpha) != float(
        np.quantile(np.concatenate(reps), 0.9, method="linear")
    )


def test_calibrated_limits_are_mean_of_replicate_quantiles() -> None:
    x = small_data(30, 4)
    mrcd = MRCDParams(alpha=T2MRCD_MRCD_ALPHA)
    limits = calibrate_limits(
        x,
        mrcd=mrcd,
        n_replicates=4,
        seed=5,
        alpha=DEFAULT_ALPHA_LIMIT,
        aggregation=mean_of_replicate_quantiles,
        mapper=SerialTaskMapper(),
    )
    context = ReplicateContext(x_clean=x, mrcd=mrcd)
    outcomes = [run_replicate(context, task) for task in replicate_tasks(5, 4)]
    quantiles = [np.quantile(o.t2, 0.995, method="linear") for o in outcomes]
    assert limits.limit == float(np.mean(quantiles))
    assert limits.alpha_limit == DEFAULT_ALPHA_LIMIT
    assert limits.n_clean == 30
