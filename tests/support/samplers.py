"""Muestreadores «SOLO TEST» de réplicas bootstrap.

``NormalSampler`` sustituye el remuestreo por muestras **nuevas e independientes** de una normal
estándar: la muestra de ajuste (``n x p``, con la forma de ``x_clean``) y ``n_new`` observaciones
nuevas de la misma normal. Así los T² de la muestra siguen la Beta de Fase I y los de las nuevas
la F de Fase II, y se puede comprobar el procedimiento contra la teoría. Nunca va en ``src/``.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class NormalSampler:
    """Muestra de ajuste y observaciones nuevas independientes de ``N_p(0, I)``."""

    n_new: int

    @property
    def name(self) -> str:
        return "normal_solo_test"

    def sample(
        self, x_clean: FloatArray, rng: np.random.Generator
    ) -> tuple[FloatArray, FloatArray]:
        n, p = x_clean.shape
        return rng.standard_normal((n, p)), rng.standard_normal((self.n_new, p))


@dataclass(frozen=True)
class EmptyNewSampler:
    """Devuelve la muestra tal cual y ninguna observación nueva (``BOOTSTRAP_OOB_EMPTY``)."""

    @property
    def name(self) -> str:
        return "empty_new_solo_test"

    def sample(
        self, x_clean: FloatArray, rng: np.random.Generator
    ) -> tuple[FloatArray, FloatArray]:
        return x_clean, x_clean[:0]
