"""Límite de Fase II por *out-of-bag* y comprobación del procedimiento contra la teoría clásica.

Escenario (f): con el estimador clásico (media y covarianza muestral, ``ddof = 1``) y muestras
normales independientes (ambos «SOLO TEST», ``tests/support/``), las distribuciones exactas son
conocidas (Tracy, Young y Mason, 1992; Mason y Young, 2002):

- Fase I, T² de una observación **usada** en la estimación:
  ``(n - 1)² / n · Beta(p/2, (n - p - 1)/2)``;
- Fase II, T² de una observación **nueva e independiente**:
  ``p (n + 1)(n - 1) / (n (n - p)) · F(p, n - p)``.

El procedimiento de ``calibrate_limits`` (un ajuste por réplica, T² de la muestra → Fase I, T² de
las nuevas con **ese** ajuste → Fase II, cuantil del *pool*) debe reproducir ambos cuantiles. Usar
una dispersión fija en lugar de la de cada réplica daría el cuantil de la ``χ²_p``, bastante menor.

Tolerancia declarada: diferencia relativa ``<= 2 %`` **y** ``<= 4`` errores Monte Carlo (M6).
"""

import numpy as np
import pytest
from scipy import stats

from support.classical import ClassicalEstimator
from support.samplers import NormalSampler
from support.solo_test import fast_params
from voracious.domain.charts.t2mrcd import (
    BootstrapLimits,
    T2MRCDChart,
    calibrate_limits,
    pooled_quantile,
)
from voracious.domain.common import SerialTaskMapper

N, P, ALPHA = 50, 5, 0.005
B_THEORY = 2000
REL_TOL = 0.02
MC_ERRORS = 4.0


def _classical_limits(seed: int, b: int) -> BootstrapLimits:
    return calibrate_limits(
        np.zeros((N, P)),  # solo fija n y p: NormalSampler genera datos nuevos en cada réplica
        estimator=ClassicalEstimator(),
        sampler=NormalSampler(n_new=N),
        n_replicates=b,
        seed=seed,
        alpha=ALPHA,
        phase2_alpha=ALPHA,
        aggregation=pooled_quantile,
        phase2_aggregation=pooled_quantile,
        mapper=SerialTaskMapper(),
    )


def _beta_quantile() -> float:
    return (N - 1) ** 2 / N * float(stats.beta.ppf(1 - ALPHA, P / 2, (N - P - 1) / 2))


def _f_quantile() -> float:
    factor = P * (N + 1) * (N - 1) / (N * (N - P))
    return factor * float(stats.f.ppf(1 - ALPHA, P, N - P))


@pytest.fixture(scope="module")
def theory_limits() -> BootstrapLimits:
    return _classical_limits(seed=2026, b=B_THEORY)


def test_phase1_limit_matches_beta_quantile(theory_limits: BootstrapLimits) -> None:
    expected = _beta_quantile()
    got = theory_limits.phase1_limit
    assert abs(got - expected) <= REL_TOL * expected
    assert abs(got - expected) <= MC_ERRORS * theory_limits.phase1_mc_error


def test_phase2_limit_matches_f_quantile(theory_limits: BootstrapLimits) -> None:
    expected = _f_quantile()
    got = theory_limits.phase2_limit
    assert abs(got - expected) <= REL_TOL * expected
    assert abs(got - expected) <= MC_ERRORS * theory_limits.phase2_mc_error


def test_phase2_limit_is_above_chi2_and_phase1(theory_limits: BootstrapLimits) -> None:
    # Con la dispersión fija (la poblacional) el T² sería χ²_p: el límite de Fase II debe quedar
    # claramente por encima, y por encima del de Fase I (observaciones no usadas en el ajuste).
    chi2 = float(stats.chi2.ppf(1 - ALPHA, P))
    assert theory_limits.phase2_limit > chi2 + 10 * theory_limits.phase2_mc_error
    assert theory_limits.phase1_limit < chi2
    assert theory_limits.phase2_exceeds_phase1
    assert theory_limits.oob_size_min == N
    assert theory_limits.estimator_name == "classical_solo_test"
    assert theory_limits.sampler_name == "normal_solo_test"


def test_mc_error_tracks_the_spread_between_seeds() -> None:
    # M6: el error Monte Carlo informado estima la variabilidad del límite entre semillas.
    runs = [_classical_limits(seed=s, b=200) for s in range(8)]
    spread = float(np.std([r.phase2_limit for r in runs], ddof=1))
    reported = float(np.mean([r.phase2_mc_error for r in runs]))
    assert 0.4 < reported / spread < 2.5


def test_phase2_exceeds_phase1_with_p_greater_than_n() -> None:
    # (g) diagnóstico Q9 con MRCD y p > n (semilla fija): no es una invariante, solo se informa.
    x = np.random.default_rng(4).standard_normal((30, 40))
    model = T2MRCDChart().fit_phase1(x, fast_params(seed=3), mapper=SerialTaskMapper())
    assert model.limits.phase2_limit > model.limits.phase1_limit
    assert model.limits.phase2_exceeds_phase1
