"""Matriz objetivo (``.TargetCorr``) y su descomposición exacta (``eigenEQ``) de ``rrcov``.

Especificación §3.4. Con ``target = "equicorrelation"`` (``target == 1`` en ``.detmrcd``) los datos
estandarizados se rotan con la matriz de Helmert y se reescalan con ``sqrt(valores)^(-1)``
(``detmrcd.R:426-434``); después ``mT <- diag(p)`` (``:436``) para cualquier objetivo.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np

from pymrcd._errors import RError
from pymrcd._rbase import r_cor_spearman, r_mean, r_pow, r_sin
from pymrcd._rlinalg import r_matprod
from pymrcd._types import FloatArray

__all__ = [
    "EigenEQ",
    "EquicorrTransform",
    "TargetCorr",
    "eigen_eq",
    "equicorrelation_transform",
    "target_corr",
]


class TargetCorr(NamedTuple):
    """Salida de ``.TargetCorr`` con sus intermedios.

    Attributes:
        R: Matriz objetivo ``p x p``.
        cortmp_rank: ``cor(t(mX), method="spearman")`` (``None`` si ``target == 0``).
        cortmp_sin: ``sin(1/2*pi*cortmp)`` (``None`` si ``target == 0``).
        constcor: Correlación común tras la cota (``None`` si ``target == 0``).
    """

    R: FloatArray
    cortmp_rank: FloatArray | None
    cortmp_sin: FloatArray | None
    constcor: float | None


def target_corr(mu: FloatArray, target: int) -> TargetCorr:
    """``.TargetCorr(mX, target)`` con ``mX = t(mU)``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:207-229``. ``target == 0`` ⇒ ``R = I`` (``:212-213``).
    ``target == 1`` (``:214-227``): Spearman de ``t(mX) = mU`` (``:217``); ``sin(1/2*pi*cortmp)``
    (``:218``, ``1/2*pi == 0.5*pi`` exacto, ``sin`` de libm); ``constcor = mean(upper.tri)`` en
    orden de columna (``:219``, media de dos pasadas, trampa T7); cota
    ``min(0, -1/(p-1) + 0.01)`` (``:222-224``); ``R = constcor*J + (1-constcor)*I``
    (``:225-226``).

    Args:
        mu: Datos estandarizados ``n x p`` (``mU``).
        target: ``0`` (identidad) o ``1`` (equicorrelación).

    Returns:
        ``TargetCorr``.

    Raises:
        RError: con ``p == 1`` y ``target == 1`` (``mean`` de un vector vacío es ``NaN`` y el
            ``if`` de ``:222`` falla en R; decisión P7).
    """
    arr = np.asarray(mu, dtype=np.float64)
    p = arr.shape[1]
    eye = np.eye(p, dtype=np.float64)
    if target == 0:
        return TargetCorr(R=eye, cortmp_rank=None, cortmp_sin=None, constcor=None)
    cortmp_rank = r_cor_spearman(arr)
    cortmp_sin = r_sin((1 / 2 * math.pi) * cortmp_rank)
    rows, cols = np.tril_indices(p, -1)
    constcor = r_mean(cortmp_sin[cols, rows])
    with np.errstate(divide="ignore"):
        bound = min(0.0, -1 / (p - 1) + 0.01) if p > 1 else math.nan
    if math.isnan(constcor) or math.isnan(bound):
        raise RError("missing value where TRUE/FALSE needed")
    if constcor <= bound:
        constcor = bound
    j = np.ones((p, p), dtype=np.float64)
    r = constcor * j + (1 - constcor) * eye
    return TargetCorr(R=r, cortmp_rank=cortmp_rank, cortmp_sin=cortmp_sin, constcor=constcor)


class EigenEQ(NamedTuple):
    """Salida de ``eigenEQ``.

    Attributes:
        values: Autovalores ``c(1 + (d-1)*rho, rep(1-rho, d-1))``.
        vectors: Matriz de Helmert ``d x d``.
    """

    values: FloatArray
    vectors: FloatArray


def eigen_eq(t: FloatArray) -> EigenEQ:
    """``eigenEQ(T)``: descomposición exacta de una matriz de equicorrelación (sin LAPACK).

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:231-248``: ``rho = T[1,2]``; Helmert con
    ``helmert[,1] = 1/sqrt(d)`` (``:237``), ``helmert[1:(j-1), j] = 1/sqrt(j*(j-1))`` y
    ``helmert[j,j] = -(j-1)/sqrt(j*(j-1))`` (``:238-242``, ``j*(j-1)`` entero exacto);
    valores ``c(1 + (d-1)*rho, rep(1-rho, d-1))`` (``:245``).

    Args:
        t: Matriz de equicorrelación ``d x d`` con ``d >= 2``.

    Returns:
        ``EigenEQ``.

    Raises:
        RError: si ``d < 2`` (``T[1,2]`` fuera de rango en R).
    """
    arr = np.asarray(t, dtype=np.float64)
    d = arr.shape[1]
    if d < 2:
        raise RError("subscript out of bounds")
    rho = float(arr[0, 1])
    helmert = np.zeros((d, d), dtype=np.float64)
    helmert[:, 0] = 1 / math.sqrt(d)
    for j in range(2, d + 1):
        s = math.sqrt(j * (j - 1))
        helmert[0 : j - 1, j - 1] = 1 / s
        helmert[j - 1, j - 1] = -(j - 1) / s
    values = np.array([1 + (d - 1) * rho] + [1 - rho] * (d - 1), dtype=np.float64)
    return EigenEQ(values=values, vectors=helmert)


class EquicorrTransform(NamedTuple):
    """Transformación de los datos para el objetivo de equicorrelación.

    Attributes:
        values: Autovalores de ``eigenEQ``.
        m_q: Matriz de Helmert.
        msq_l: ``diag(sqrt(values))``.
        misq_l: ``diag(sqrt(values)^(-1))``.
        m_w: ``mU %*% mQ %*% misqL`` (``n x p``).
    """

    values: FloatArray
    m_q: FloatArray
    msq_l: FloatArray
    misq_l: FloatArray
    m_w: FloatArray


def equicorrelation_transform(mu: FloatArray, r: FloatArray) -> EquicorrTransform:
    """Paso 2 de ``.detmrcd`` con ``target == 1``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:426-434``: ``eigenEQ(mT)``; ``msqL = diag(sqrt(values))``;
    ``misqL = diag(sqrt(values)^(-1))`` (``R_pow(·, -1)``, no ``1/x``); ``mW = mU %*% mQ %*% misqL``
    (asociatividad izquierda, dos ``dgemm`` reales).

    Args:
        mu: Datos estandarizados ``n x p``.
        r: Matriz objetivo de ``.TargetCorr``.

    Returns:
        ``EquicorrTransform``.
    """
    eq = eigen_eq(r)
    sq = np.sqrt(eq.values)
    msql = np.diag(sq)
    misql = np.diag(np.array([r_pow(float(v), -1.0) for v in sq.tolist()], dtype=np.float64))
    mw = r_matprod(r_matprod(mu, eq.vectors), misql)
    return EquicorrTransform(values=eq.values, m_q=eq.vectors, msq_l=msql, misq_l=misql, m_w=mw)
