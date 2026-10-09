"""Datos y parámetros pequeños para que la suite de T²MRCD sea rápida.

Los parámetros usan los defaults de producción de la carta salvo ``n_replicates`` pequeño (B = 5),
que solo acelera los tests y no es una propuesta para producción (B = 100,
``DEFAULT_N_REPLICATES``). Los valores estadísticos «SOLO TEST» de la recalibración (pruebas de
cambio, que en producción están pendientes) están en ``solo_test_recalibration``.
"""

from dataclasses import replace

import numpy as np
import numpy.typing as npt

from support.change_tests import FixedTest, permutation_covariance_test, permutation_mean_test
from voracious.domain.charts.t2mrcd import (
    DEFAULT_STRATEGIES,
    T2MRCDBootstrap,
    T2MRCDChart,
    T2MRCDParams,
    T2MRCDRecalibrationParams,
)

SOLO_TEST_N_TEST_RESAMPLES = 199
"""Remuestreos de las pruebas de permutación SOLO TEST (en producción: pendiente)."""


def fast_bootstrap(seed: int = 7, n_replicates: int = 5) -> T2MRCDBootstrap:
    """Bootstrap con los defaults de producción y B pequeño (B reducido por velocidad)."""
    return T2MRCDBootstrap(n_replicates=n_replicates, seed=seed)


def fast_params(seed: int = 7, n_replicates: int = 5) -> T2MRCDParams:
    """Parámetros de T²MRCD con los defaults de producción y B reducido por velocidad."""
    return T2MRCDParams(bootstrap=fast_bootstrap(seed, n_replicates))


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


SOLO_TEST_STRATEGIES = replace(
    DEFAULT_STRATEGIES,
    covariance_tests={
        permutation_covariance_test.name: permutation_covariance_test,
        FixedTest(changed=True, test_name="always_changed_solo_test").name: FixedTest(
            changed=True, test_name="always_changed_solo_test"
        ),
        FixedTest(changed=False, test_name="never_changed_solo_test").name: FixedTest(
            changed=False, test_name="never_changed_solo_test"
        ),
    },
    mean_tests={
        permutation_mean_test.name: permutation_mean_test,
        FixedTest(changed=False, test_name="never_changed_solo_test").name: FixedTest(
            changed=False, test_name="never_changed_solo_test"
        ),
    },
)
"""Registro de estrategias con las pruebas de cambio SOLO TEST (producción: pendientes)."""


def solo_test_chart() -> T2MRCDChart:
    """Carta T²MRCD con el registro SOLO TEST (para poder persistir las pruebas por nombre)."""
    return T2MRCDChart(strategies=SOLO_TEST_STRATEGIES)


def fixed_tests_recalibration(
    seed: int = 11, *, changed: bool = False, **overrides: object
) -> T2MRCDRecalibrationParams:
    """Recalibración con pruebas de veredicto fijo SOLO TEST (EXTEND o REPLACE a voluntad)."""
    cov = FixedTest(
        changed=changed,
        test_name="always_changed_solo_test" if changed else "never_changed_solo_test",
    )
    kwargs: dict[str, object] = {
        "seed": seed,
        "covariance_test": cov,
        "mean_test": FixedTest(changed=False, test_name="never_changed_solo_test"),
        "n_test_resamples": 1,
    }
    kwargs.update(overrides)
    return T2MRCDRecalibrationParams(**kwargs)
