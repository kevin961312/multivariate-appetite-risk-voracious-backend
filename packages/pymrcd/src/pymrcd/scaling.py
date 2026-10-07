"""Estandarización robusta ``doScale(x, median, Qn)`` de ``robustbase`` con el respaldo ``non0Q``.

``rrcov`` la usa en ``r6pack`` local (``detmrcd.R:123-125``) y en ``initset`` (``detmrcd.R:70``),
siempre con ``center = median`` y ``scale = Qn`` (especificación §3.5, §3.5.1 y §3.12.5).
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from pymrcd._errors import RError
from pymrcd._rbase import r_median_cols, r_qnorm, r_quantile7
from pymrcd._types import FloatArray
from pymrcd.qn import qn_columns

__all__ = ["NON0Q_PROBS", "DoScaleResult", "do_scale", "non0q"]

NON0Q_PROBS = np.array([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 19.75], dtype=np.float64) / 20
"""``alph <- c(10:19, 19.75)/20`` (``robustbase-0.99-6/R/detmcd.R:276``)."""


class DoScaleResult(NamedTuple):
    """Salida de ``doScale``.

    Attributes:
        x: Datos centrados y escalados ``n x p``.
        center: Medianas por columna.
        scale: Escalas por columna (``Qn`` o ``non0Q`` donde ``Qn == 0``).
    """

    x: FloatArray
    center: FloatArray
    scale: FloatArray


def non0q(u: FloatArray) -> float:
    """Escala de respaldo de ``doScale`` cuando ``Qn`` de una columna es 0.

    Fuente: ``robustbase-0.99-6/R/detmcd.R:273-282``. Con ``center = median`` la función ``S`` es
    ``abs`` (``:273-274``); ``qq = quantile(abs(u), alph)`` (tipo 7, ``:277``); si algún ``qq != 0``
    se devuelve ``qq[i] / qnorm((alph[i] + 1)/2)`` con ``i`` el primero no nulo (``:278-280``);
    si no,
    ``1`` (``:281``).

    Args:
        u: Columna ya centrada en la mediana.

    Returns:
        La escala sustituta.
    """
    qq = r_quantile7(np.abs(np.asarray(u, dtype=np.float64)), NON0Q_PROBS)
    pos = np.flatnonzero(qq != 0)
    if pos.size == 0:
        return 1.0
    i = int(pos[0])
    denom = float(r_qnorm(np.array([(NON0Q_PROBS[i] + 1) / 2]))[0])
    return float(qq[i]) / denom


def do_scale(x: FloatArray) -> DoScaleResult:
    """``doScale(x, center=median, scale=Qn)`` de ``robustbase``.

    Fuente: ``robustbase-0.99-6/R/detmcd.R:229-289``: ``center = apply(x, 2, median)`` (``:237``,
    ``median`` de R con media de dos pasadas, trampa T4); ``x = sweep(x, 2, center)`` (``:249``);
    ``scale = apply(x, 2, Qn)`` **sobre la columna centrada** (``:253``, trampa T2); error si alguna
    escala es ``NA`` o negativa (``:266-267``); escalas nulas ⇒ ``non0Q`` (``:268-283``);
    ``x = sweep(x, 2, scale, "/")`` (``:285``).

    Args:
        x: Matriz ``n x p``.

    Returns:
        ``DoScaleResult`` con ``x`` estandarizada, ``center`` y ``scale``.

    Raises:
        RError: si alguna escala es ``NA`` o negativa.
    """
    arr = np.asarray(x, dtype=np.float64)
    center = r_median_cols(arr)
    xc = arr - center[None, :]
    scale = qn_columns(xc)
    if np.isnan(scale).any() or (scale < 0).any():
        raise RError("provide better scale; must be all positive")
    for j in np.flatnonzero(scale == 0).tolist():
        scale[j] = non0q(xc[:, j])
    return DoScaleResult(x=xc / scale[None, :], center=center, scale=scale)
