"""Pruebas de cambio de la recalibración «SOLO TEST» (las de producción están pendientes, Q4).

Pruebas de permutación con estadísticos **clásicos** (baratos) para poder ejercitar la regla de
decisión y los escenarios EXTEND/REPLACE de T²MRCD. No son una propuesta estadística: el método de
producción (pruebas por remuestreo con MRCD) sigue sin decidir y sin cita.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from voracious.domain.charts.t2mrcd import ChangeTestResult

FloatArray = npt.NDArray[np.float64]
Statistic = Callable[[FloatArray, FloatArray], float]

SOLO_TEST_LEVEL = 0.01
"""Nivel de las pruebas de permutación SOLO TEST."""


def covariance_statistic(a: FloatArray, b: FloatArray) -> float:
    """Frobenius relativa entre covarianzas muestrales (cada grupo centrado en su media)."""
    sa = np.cov(a, rowvar=False)
    sb = np.cov(b, rowvar=False)
    return float(np.linalg.norm(sb - sa) / np.linalg.norm(sa))


def mean_statistic(a: FloatArray, b: FloatArray) -> float:
    """T² de Hotelling de dos muestras con covarianza combinada."""
    na, nb = a.shape[0], b.shape[0]
    pooled = ((na - 1) * np.cov(a, rowvar=False) + (nb - 1) * np.cov(b, rowvar=False)) / (
        na + nb - 2
    )
    diff = a.mean(axis=0) - b.mean(axis=0)
    return float(diff @ np.linalg.solve(pooled, diff) * na * nb / (na + nb))


def permutation_p_value(
    a: FloatArray,
    b: FloatArray,
    statistic: Statistic,
    seed: np.random.SeedSequence,
    n_resamples: int,
    *,
    center: bool,
) -> tuple[float, float]:
    """Estadístico observado y valor p de permutación ``(1 + #{T* >= T}) / (1 + R)``."""
    observed = statistic(a, b)
    if center:
        # Para la dispersión se permutan filas centradas en su grupo (el cambio de media no cuenta).
        a, b = a - a.mean(axis=0), b - b.mean(axis=0)
    pooled = np.vstack([a, b])
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(n_resamples):
        perm = rng.permutation(pooled.shape[0])
        hits += statistic(pooled[perm[: a.shape[0]]], pooled[perm[a.shape[0] :]]) >= observed
    return observed, (1 + hits) / (1 + n_resamples)


@dataclass(frozen=True)
class _PermutationTest:
    test_name: str
    statistic: Statistic
    center: bool
    level: float = SOLO_TEST_LEVEL

    @property
    def name(self) -> str:
        return self.test_name

    def __call__(
        self,
        base: FloatArray,
        new: FloatArray,
        *,
        fit0: object,
        fit1: object,
        estimator: object,
        seed: np.random.SeedSequence,
        n_resamples: int,
        mapper: object,
    ) -> ChangeTestResult:
        stat, p_value = permutation_p_value(
            base, new, self.statistic, seed, n_resamples, center=self.center
        )
        return ChangeTestResult(
            name=self.name, statistic=stat, p_value=p_value, changed=p_value < self.level
        )


permutation_covariance_test = _PermutationTest(
    "permutation_covariance_solo_test", covariance_statistic, center=True
)
"""Prueba de igualdad de dispersiones SOLO TEST."""

permutation_mean_test = _PermutationTest("permutation_mean_solo_test", mean_statistic, center=False)
"""Prueba de igualdad de medias SOLO TEST."""


@dataclass(frozen=True)
class FixedTest:
    """Prueba que devuelve siempre el mismo veredicto (para probar la regla de decisión)."""

    changed: bool
    test_name: str = "fixed_solo_test"

    @property
    def name(self) -> str:
        return self.test_name

    def __call__(self, base: FloatArray, new: FloatArray, **kwargs: object) -> ChangeTestResult:
        return ChangeTestResult(name=self.name, statistic=0.0, p_value=None, changed=self.changed)
