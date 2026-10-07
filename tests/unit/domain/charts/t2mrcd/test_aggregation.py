import numpy as np
import pytest

from voracious.domain.charts.t2mrcd import (
    DEFAULT_ALPHA_LIMIT,
    MC_ERROR_RESAMPLES,
    QUANTILE_METHOD,
    PooledQuantile,
    pooled_quantile,
)


def test_quantile_probability_is_one_minus_alpha_limit() -> None:
    # alpha_limit = 0.005 es una proporción: la probabilidad del cuantil es 0.995 (no 99.5).
    values = np.arange(1.0, 201.0)
    got = pooled_quantile([values], DEFAULT_ALPHA_LIMIT)
    assert QUANTILE_METHOD == "linear"
    assert got == float(np.quantile(values, 0.995, method="linear"))
    assert got != float(np.quantile(values, 0.005, method="linear"))
    # Tipo 7 de R: 1 + (n - 1) * 0.995 = 199.005.
    assert got == pytest.approx(199.005, rel=0, abs=1e-12)


def test_limit_is_quantile_of_the_pool() -> None:
    # Paso 2b, Q1: pool; un único cuantil del conjunto de los T² de todas las réplicas.
    reps = [np.array([1.0, 2.0, 3.0, 4.0]), np.array([10.0, 20.0]), np.array([5.0])]
    pooled = float(np.quantile(np.concatenate(reps), 0.9, method="linear"))
    assert pooled_quantile(reps, 0.1) == pooled
    # Distinto del promedio de cuantiles por réplica (la agregación sustituida).
    per_replicate = float(np.mean([np.quantile(r, 0.9, method="linear") for r in reps]))
    assert pooled != per_replicate


def test_production_aggregation_has_stable_name() -> None:
    assert pooled_quantile.name == "pooled_quantile"
    assert isinstance(pooled_quantile, PooledQuantile)


def test_mc_error_is_cluster_bootstrap_sd() -> None:
    rng = np.random.default_rng(0)
    reps = [rng.chisquare(3, size=40) for _ in range(12)]
    seed = np.random.SeedSequence(5)
    got = pooled_quantile.mc_error(reps, 0.05, seed)
    # Mismo cálculo a mano: remuestrear réplicas completas con reemplazo.
    manual_rng = np.random.default_rng(np.random.SeedSequence(5))
    limits = []
    for _ in range(MC_ERROR_RESAMPLES):
        picks = manual_rng.integers(0, len(reps), size=len(reps))
        pool = np.concatenate([reps[i] for i in picks])
        limits.append(np.quantile(pool, 0.95, method="linear"))
    assert got == float(np.std(limits, ddof=1))
    assert got > 0.0
    assert pooled_quantile.mc_error(reps, 0.05, np.random.SeedSequence(5)) == got


def test_mc_error_with_one_replicate_is_not_available() -> None:
    # Con B = 1 no hay variabilidad entre réplicas que medir: None (no disponible), no 0.
    assert pooled_quantile.mc_error([np.arange(10.0)], 0.1, np.random.SeedSequence(1)) is None
