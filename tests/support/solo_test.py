"""Datos y parámetros pequeños para que la suite de T²MRCD sea rápida.

Ya no hay decisiones estadísticas pendientes en T²MRCD (P2, P4 y P6 decididas por el dueño el
2026-10-07), así que aquí no queda ningún valor estadístico «SOLO TEST»: los parámetros usan los
defaults de producción. La única excepción es ``n_replicates`` pequeño (B = 5), que solo acelera
los tests y no es una propuesta para producción (B = 100, ``DEFAULT_N_REPLICATES``).
"""

import numpy as np
import numpy.typing as npt

from voracious.domain.charts.t2mrcd import T2MRCDBootstrap, T2MRCDParams


def fast_bootstrap(seed: int = 7, n_replicates: int = 5) -> T2MRCDBootstrap:
    """Bootstrap con los defaults de producción y B pequeño (B reducido por velocidad)."""
    return T2MRCDBootstrap(n_replicates=n_replicates, seed=seed)


def fast_params(seed: int = 7, n_replicates: int = 5) -> T2MRCDParams:
    """Parámetros de T²MRCD con los defaults de producción y B reducido por velocidad."""
    return T2MRCDParams(bootstrap=fast_bootstrap(seed, n_replicates))


def small_data(n: int = 40, p: int = 4, seed: int = 3) -> npt.NDArray[np.float64]:
    """Datos normales pequeños (≈ 40 x 4) para que la suite sea rápida."""
    return np.random.default_rng(seed).normal(size=(n, p))
