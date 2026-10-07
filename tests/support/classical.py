"""Estimador clásico (media y covarianza muestral) «SOLO TEST».

**Nunca** es un estimador de T²MRCD ni un *fallback* (ADR 0002): existe solo para comprobar el
procedimiento bootstrap de límites contra la teoría clásica de Hotelling (Beta en Fase I, F en
Fase II), que se conoce en forma cerrada para la media y la covarianza muestral con ``n - 1``.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, eq=False)
class ClassicalFit:
    """Media y covarianza muestral (``ddof = 1``)."""

    center: FloatArray
    cov: FloatArray
    icov: FloatArray

    def distances(self, x: npt.ArrayLike) -> FloatArray:
        diff = np.asarray(x, dtype=np.float64) - self.center
        return np.einsum("ij,jk,ik->i", diff, self.icov, diff)


@dataclass(frozen=True)
class ClassicalEstimator:
    """``LocationScatterEstimator`` clásico, SOLO TEST."""

    @property
    def name(self) -> str:
        return "classical_solo_test"

    def fit(self, x: FloatArray) -> ClassicalFit:
        center = x.mean(axis=0)
        cov = np.cov(x, rowvar=False, ddof=1)
        return ClassicalFit(center=center, cov=cov, icov=np.linalg.inv(cov))
