"""Datos y parámetros pequeños para que la suite de T²MRCD sea rápida.

Los parámetros usan los defaults de producción de la carta salvo ``n_replicates`` pequeño (B = 5),
que solo acelera los tests y no es una propuesta para producción (B = 100,
``DEFAULT_N_REPLICATES``). Los valores estadísticos «SOLO TEST» de la recalibración (pruebas de
cambio, que en producción están pendientes) están en ``solo_test_recalibration``.
"""

import numpy as np
import numpy.typing as npt

from support.change_tests import permutation_covariance_test, permutation_mean_test
from voracious.domain.charts.t2mrcd import (
    T2MRCDBootstrap,
    T2MRCDParams,
    T2MRCDRecalibrationParams,
)

SOLO_TEST_N_TEST_RESAMPLES = 199
"""Remuestreos de las pruebas de permutación SOLO TEST (en producción: pendiente)."""


def fast_bootstrap(seed: int = 7, n_replicates: int = 5) -> T2MRCDBootstrap:
    """Bootstrap con los defaults de producción y B pequeño (B reducido por velocidad)."""
    return T2MRCDBootstrap(n_replicates=n_replicates, seed=seed)


def fast_params(
    seed: int = 7, n_replicates: int = 5, max_depuration_rounds: int | None = None
) -> T2MRCDParams:
    """Parámetros de T²MRCD con los defaults de producción y B reducido por velocidad."""
    boot = fast_bootstrap(seed, n_replicates)
    if max_depuration_rounds is None:
        return T2MRCDParams(bootstrap=boot)
    return T2MRCDParams(bootstrap=boot, max_depuration_rounds=max_depuration_rounds)


def solo_test_recalibration(seed: int = 11, **overrides: object) -> T2MRCDRecalibrationParams:
    """Recalibración con las pruebas de permutación SOLO TEST (producción: pendientes)."""
    kwargs: dict[str, object] = {
        "seed": seed,
        "covariance_test": permutation_covariance_test,
        "mean_test": permutation_mean_test,
        "n_test_resamples": SOLO_TEST_N_TEST_RESAMPLES,
    }
    kwargs.update(overrides)
    return T2MRCDRecalibrationParams(**kwargs)


def small_data(n: int = 40, p: int = 4, seed: int = 3) -> npt.NDArray[np.float64]:
    """Datos normales pequeños (≈ 40 x 4) para que la suite sea rápida."""
    return np.random.default_rng(seed).normal(size=(n, p))
