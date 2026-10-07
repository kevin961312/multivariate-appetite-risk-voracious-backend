"""Resultado de un ajuste MRCD, independiente de la librería que lo calcula."""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

import pymrcd
from voracious.domain.common import FloatMatrix, FloatVector, InvalidInputError, as_matrix

__all__ = ["IndexVector", "MRCDFit"]

IndexVector = npt.NDArray[np.int64]
"""Vector de índices de fila, base 0."""


@dataclass(frozen=True, eq=False)
class MRCDFit:
    """Ajuste MRCD (nombres de los *slots* de ``rrcov::CovMrcd``).

    Attributes:
        center: Ubicación MRCD (``center``), longitud ``p``.
        cov: Dispersión MRCD (``cov``), ``p x p``.
        icov: Inversa de ``cov`` (``icov``).
        rho: Regularización elegida (``rho``).
        cnp2: Factor de consistencia (``cnp2``).
        crit: ``log(det(cov))`` (``crit``).
        best: Subconjunto óptimo, **base 0**, ordenado (``best``).
        mah: Distancias de Mahalanobis al cuadrado de las filas usadas (``mah``).
        alpha: ``alpha`` efectivo (``alpha``).
        h: Tamaño del subconjunto (``quan``).
        n_obs: Observaciones usadas (``n.obs``).
        ok: Máscara de filas finitas de la entrada (``CovMrcd.R:19``); ``mah`` corresponde a
            ``x[ok]``.
        i_best: Diagnóstico: subconjuntos iniciales empatados en el óptimo, **base 0**
            (``iBest``).
        n_csteps: Diagnóstico: C-steps de cada subconjunto inicial (``n.csteps``).
    """

    center: FloatVector
    cov: FloatMatrix
    icov: FloatMatrix
    rho: float
    cnp2: float
    crit: float
    best: IndexVector
    mah: FloatVector
    alpha: float
    h: int
    n_obs: int
    ok: npt.NDArray[np.bool_]
    i_best: IndexVector
    n_csteps: IndexVector

    @property
    def n_features(self) -> int:
        """Número de variables ``p``."""
        return int(self.center.shape[0])

    def distances(self, x: npt.ArrayLike) -> FloatVector:
        """Distancias de Mahalanobis al cuadrado respecto a ``center`` e ``icov``.

        Usa la misma rutina que produce ``mah`` (``pymrcd.mahalanobis``, ``CovMrcd.R:46``), así
        que ``distances(x[ok])`` es igual bit a bit a ``mah``.

        Args:
            x: Observaciones ``m x p``.

        Returns:
            Vector de ``m`` distancias al cuadrado.

        Raises:
            InvalidInputError: Si ``x`` no es una matriz con ``p`` columnas.
        """
        arr = as_matrix(x)
        if arr.shape[1] != self.n_features:
            raise InvalidInputError(
                "el número de variables no coincide con el del ajuste MRCD",
                details={"expected_features": self.n_features, "got_features": arr.shape[1]},
            )
        return pymrcd.mahalanobis(arr, self.center, self.icov)
