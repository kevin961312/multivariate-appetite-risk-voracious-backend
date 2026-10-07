"""Estadística T² de la carta T²MRCD.

T² de una observación = distancia de Mahalanobis al cuadrado respecto a la ubicación y
dispersión MRCD (``docs/metodos/t2mrcd.md``, tabla «Estadística»; cita del artículo pendiente,
P6). Hay una sola rutina: ``MRCDFit.distances`` (``pymrcd.mahalanobis``, la de
``rrcov::CovMrcd``, ``CovMrcd.R:46``), así que ``t2(fit, x[fit.ok])`` es igual bit a bit a
``fit.mah``.
"""

import numpy.typing as npt

from voracious.domain.common import FloatVector
from voracious.domain.estimators.mrcd import MRCDFit

__all__ = ["t2"]


def t2(fit: MRCDFit, x: npt.ArrayLike) -> FloatVector:
    """T² de cada fila de ``x`` respecto al ajuste MRCD.

    Args:
        fit: Ajuste MRCD.
        x: Observaciones ``m x p``.

    Returns:
        Vector de ``m`` valores T².

    Raises:
        InvalidInputError: Si ``x`` no es una matriz con ``p`` columnas.
    """
    return fit.distances(x)
