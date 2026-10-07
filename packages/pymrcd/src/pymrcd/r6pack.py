"""Seis subconjuntos iniciales deterministas (``r6pack`` local de ``rrcov``) e ``initset``.

Port de la definición **local** de ``r6pack`` en ``rrcov-1.7-7/R/detmrcd.R:57-197`` (no la de
``robustbase``), llamada en ``detmrcd.R:446`` con ``full.h = FALSE``,
``adjust.eignevalues = FALSE``, ``scaled = FALSE`` y ``scalefn = Qn`` (especificación §3.5). Los
índices se devuelven en **base 0**.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np

from pymrcd._errors import RError
from pymrcd._rbase import (
    r_colmedians,
    r_cor,
    r_cor_spearman,
    r_cov,
    r_order,
    r_qnorm,
    r_rank_cols,
    r_rowsums,
    r_tanh,
)
from pymrcd._rlinalg import r_crossprod, r_eigen_sym, r_mahalanobis_d, r_matprod, r_vecmat
from pymrcd._types import FloatArray, IntArray
from pymrcd.ogk import ogk_u
from pymrcd.scaling import do_scale

__all__ = [
    "InitSet",
    "R6Pack",
    "initset",
    "r6pack",
    "set1_matrix",
    "set2_matrix",
    "set3_matrix",
    "set4_matrix",
    "set5_matrix",
]

_DBL_EPSILON = float(np.finfo(np.float64).eps)


class InitSet(NamedTuple):
    """Salida de ``initset`` con sus intermedios (especificación §10, ``is.k.*``).

    Attributes:
        proj: ``data %*% P`` (``n x p``).
        lam: Escalas ``lambda`` de ``doScale(proj)``.
        sqrtcov: ``P %*% (lambda * t(P))``.
        sqrtinvcov: ``P %*% (t(P) / lambda)``.
        colmed: ``colMedians(data %*% sqrtinvcov)``.
        estloc: ``colmed %*% sqrtcov``.
        centeredx: ``(data - estloc) %*% P``.
        dist: Distancias ``mahalanobisD(centeredx, FALSE, lambda)``.
        ord: Primeras ``h`` posiciones de ``sort.list(dist)`` (base 0).
    """

    proj: FloatArray
    lam: FloatArray
    sqrtcov: FloatArray
    sqrtinvcov: FloatArray
    colmed: FloatArray
    estloc: FloatArray
    centeredx: FloatArray
    dist: FloatArray
    ord: IntArray


def initset(data: FloatArray, p_mat: FloatArray, h: int) -> InitSet:
    """``initset(data, scalefn=Qn, P, h)``, función local de ``r6pack``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:65-76`` (especificación §3.5.1): ``stopifnot`` de
    ``:67-69``; ``lambda = doScale(data %*% P, median, Qn)$scale`` (``:70``);
    ``sqrtcov = P %*% (lambda * t(P))`` (``:71``, ``lambda`` recicla por filas de ``t(P)``);
    ``sqrtinvcov = P %*% (t(P) / lambda)`` (``:72``, división); ``estloc = colMedians(data %*%
    sqrtinvcov) %*% sqrtcov`` (``:73``, ``colMedians`` en C y ``dgemv('T')``);
    ``centeredx = (data - rep(estloc, each=n)) %*% P`` (``:74``);
    ``sort.list(mahalanobisD(centeredx, FALSE, lambda))[1:h]`` (``:75``, radix estable).

    Args:
        data: Datos ``n x p``.
        p_mat: Autovectores ``P`` (``p x p``).
        h: Tamaño del subconjunto.

    Returns:
        ``InitSet`` con ``ord`` en base 0.

    Raises:
        RError: si ``h < 1`` o ``h > n`` (``stopifnot``).
    """
    x = np.asarray(data, dtype=np.float64)
    p_arr = np.asarray(p_mat, dtype=np.float64)
    n = x.shape[0]
    if h < 1:
        raise RError("h >= 1 is not TRUE")
    if h > n:
        raise RError("h <= n is not TRUE")
    proj = r_matprod(x, p_arr)
    lam = do_scale(proj).scale
    pt = np.array(p_arr.T, dtype=np.float64)
    sqrtcov = r_matprod(p_arr, lam[:, None] * pt)
    sqrtinvcov = r_matprod(p_arr, pt / lam[:, None])
    colmed = r_colmedians(r_matprod(x, sqrtinvcov))
    estloc = r_vecmat(colmed, sqrtcov)
    centeredx = r_matprod(x - estloc[None, :], p_arr)
    dist = r_mahalanobis_d(centeredx, lam)
    ord_ = r_order(dist)[:h]
    return InitSet(
        proj=proj,
        lam=lam,
        sqrtcov=sqrtcov,
        sqrtinvcov=sqrtinvcov,
        colmed=colmed,
        estloc=estloc,
        centeredx=centeredx,
        dist=dist,
        ord=ord_,
    )


def set1_matrix(x: FloatArray) -> FloatArray:
    """Conjunto 1: ``cor(tanh(x))``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:132-133`` (``tanh`` de libm por elemento, trampa T12).

    Args:
        x: Datos estandarizados ``n x p``.

    Returns:
        ``R1`` (``p x p``).
    """
    return r_cor(r_tanh(x))


def set2_matrix(x: FloatArray) -> FloatArray:
    """Conjunto 2: correlación de Spearman.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:138`` (``cor(x, method="spearman")``, ``cor.R:66-70``).

    Args:
        x: Datos estandarizados ``n x p``.

    Returns:
        ``R2`` (``p x p``).
    """
    return r_cor_spearman(x)


def set3_matrix(x: FloatArray) -> FloatArray:
    """Conjunto 3: puntuaciones normales de Tukey.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:143-144``:
    ``qnorm((apply(x, 2, rank) - 1/3)/(n + 1/3))`` y ``cor(y3, use="complete.obs")``.

    Args:
        x: Datos estandarizados ``n x p``.

    Returns:
        ``R3`` (``p x p``).
    """
    n = x.shape[0]
    y3 = r_qnorm((r_rank_cols(x) - 1 / 3) / (n + 1 / 3))
    return r_cor(y3, use="complete.obs")


def _znorm(x: FloatArray) -> FloatArray:
    """``sqrt(rowSums(x^2))`` (``detmrcd.R:149``; ``x^2`` es ``x*x``).

    Args:
        x: Datos ``n x p``.

    Returns:
        Normas euclídeas por fila.
    """
    return np.asarray(np.sqrt(r_rowsums(x * x)), dtype=np.float64)


def set4_matrix(x: FloatArray) -> FloatArray:
    """Conjunto 4: matriz de signos espaciales.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:149-153``: ``ii = znorm > .Machine$double.eps``;
    ``x.nrmd[ii,] = x[ii,] / znorm[ii]`` (división por filas); ``crossprod(x.nrmd)`` (``dsyrk``
    + espejo, trampa T8).

    Args:
        x: Datos estandarizados ``n x p``.

    Returns:
        ``SCM`` (``p x p``).
    """
    znorm = _znorm(x)
    ii = znorm > _DBL_EPSILON
    x_nrmd = np.array(x, dtype=np.float64, copy=True)
    x_nrmd[ii, :] = x[ii, :] / znorm[ii, None]
    return r_crossprod(x_nrmd)


def set5_matrix(x: FloatArray) -> FloatArray:
    """Conjunto 5: covarianza de la mitad de menor norma (BACON).

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:158-161``: ``ind5 = order(znorm)``;
    ``Hinit = ind5[1:ceiling(n/2)]``; ``cov(x[Hinit, , drop=FALSE])`` con las filas en el orden de
    ``Hinit`` (fija el orden de las sumas).

    Args:
        x: Datos estandarizados ``n x p``.

    Returns:
        ``covx`` (``p x p``).
    """
    n = x.shape[0]
    hinit = r_order(_znorm(x))[: math.ceil(n / 2)]
    return r_cov(x[hinit, :])


class R6Pack(NamedTuple):
    """Salida de ``r6pack``.

    Attributes:
        x: Datos tras ``doScale`` (``n x p``).
        hsets: Subconjuntos ``h x 6`` en base 0, en orden de distancia.
        p_mats: Las seis matrices ``P`` de autovectores.
    """

    x: FloatArray
    hsets: IntArray
    p_mats: tuple[FloatArray, ...]


def r6pack(x: FloatArray, h: int) -> R6Pack:
    """``r6pack(x, h, full.h=FALSE, adjust.eignevalues=FALSE, scaled=FALSE, scalefn=Qn)``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:57-174``: ``doScale(x, median, Qn)`` (``:123-125``);
    conjuntos 1-6 (``:132-167``), cada uno ``P = eigen(·, symmetric=TRUE)$vectors`` e
    ``initset``; ``return(hsets)`` en ``:173-174`` (``:176-196`` es código muerto, §8). El
    conjunto 6 es ``ogkscatter`` (``:166``). Los autovectores dependen del LAPACK de la plataforma
    (divergencia aceptada, ver ``r_eigen_sym``; riesgo R1, especificación §6).

    Args:
        x: Datos ``n x p`` (``mU`` o ``mW``).
        h: Tamaño de los subconjuntos.

    Returns:
        ``R6Pack`` con ``hsets`` en base 0.
    """
    xs = do_scale(np.asarray(x, dtype=np.float64)).x
    builders = (set1_matrix, set2_matrix, set3_matrix, set4_matrix, set5_matrix, ogk_u)
    hsets = np.empty((h, 6), dtype=np.int64)
    p_mats: list[FloatArray] = []
    for k, build in enumerate(builders):
        p_k = r_eigen_sym(build(xs)).vectors
        p_mats.append(p_k)
        hsets[:, k] = initset(xs, p_k, h).ord
    return R6Pack(x=xs, hsets=hsets, p_mats=tuple(p_mats))
