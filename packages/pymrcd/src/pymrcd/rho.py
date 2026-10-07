"""Selección del parámetro de regularización ``rho`` de ``.detmrcd`` (pasos 3.4-3.5).

Port de ``rrcov-1.7-7/R/detmrcd.R:462-539`` (especificación §3.7). Para cada subconjunto inicial se
busca el menor ``rho_k`` con número de condición ``maxcond`` (``uniroot`` de R portado; si falla, la
rejilla de ``:503-511``); después ``cutoff``, ``rho``, ``initV`` y ``setsV``. La rama de
``fncond`` con objetivo no identidad (``:485-493``, ``:507-510``) es código muerto: ``mT`` es
siempre ``diag(p)`` en este punto (``:436``; especificación §8).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import NamedTuple

import numpy as np

from pymrcd._errors import RError
from pymrcd._rbase import r_median, r_rowmeans
from pymrcd._rlinalg import r_eigen_values, r_matprod
from pymrcd._rzeroin import r_uniroot
from pymrcd._types import FloatArray, IntArray

__all__ = [
    "RHO_GRID",
    "RhoK",
    "RhoSelection",
    "SubsetScatter",
    "fncond_factory",
    "rho_for_subset",
    "rho_grid",
    "select_rho",
    "subset_scatter",
]

UNIROOT_LOWER = 0.00001
"""``lower`` de ``uniroot`` (``detmrcd.R:495``)."""

UNIROOT_UPPER = 0.99
"""``upper`` de ``uniroot`` (``detmrcd.R:495``)."""


def _r_seq_by(start: float, end: float, by: float) -> FloatArray:
    """``seq(from, to, by)`` de R con argumentos ``double`` finitos y ``by > 0``.

    Fuente: ``R-4.5.2/src/library/base/R/seq.R:60-96``: ``del = to - from`` (``:62``);
    ``n = del/by`` (``:69-70``); ``n <- as.integer(n + 1e-10)`` (``:91``);
    ``x = from + (0L:n) * by`` (``:93``) y ``pmin(x, to)`` (``:96``).

    Args:
        start: ``from``.
        end: ``to``.
        by: Paso positivo.

    Returns:
        La secuencia de R.
    """
    n = int((end - start) / by + 1e-10)
    x = start + np.arange(n + 1, dtype=np.float64) * by
    return np.asarray(np.minimum(x, end), dtype=np.float64)


def rho_grid() -> FloatArray:
    """Rejilla ``c(0.000001, seq(0.001, 0.99, by=0.001), 0.999999)`` (``detmrcd.R:503``).

    Returns:
        Vector de 992 valores.
    """
    return np.concatenate(([0.000001], _r_seq_by(0.001, 0.99, 0.001), [0.999999]))


RHO_GRID = rho_grid()
"""Rejilla de respaldo de ``rho_k`` (``detmrcd.R:503``)."""


class SubsetScatter(NamedTuple):
    """Covarianza de un subconjunto inicial (``detmrcd.R:467-475``).

    Attributes:
        mu: ``rowMeans(mXsubset)``.
        m_s: ``mE %*% t(mE) / (h-1)``.
        veigen: ``eigen(scfac * mS)$values``.
        e1: Mínimo autovalor.
        ep: Máximo autovalor.
    """

    mu: FloatArray
    m_s: FloatArray
    veigen: FloatArray
    e1: float
    ep: float


def subset_scatter(mx: FloatArray, idx: IntArray, h: int, scfac: float) -> SubsetScatter:
    """Covarianza y autovalores extremos de un subconjunto inicial.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:467-475``: ``mXsubset = mX[, hsets.init[,k]]`` (orden de
    la columna tal cual, trampa T6); ``rowMeans`` secuencial; ``mE = mXsubset - vMusubset``;
    ``mS = mE %*% t(mE)/(h-1)`` (``dgemm``, divisor ``h-1``, trampa T10);
    ``veigen = eigen(scfac * mS)$values`` (rama automática ``isSymmetric``, trampa T13);
    ``e1 = min``, ``ep = max``.

    Args:
        mx: Datos ``p x n`` (``mX`` de ``.detmrcd``).
        idx: Índices del subconjunto en base 0 (orden de distancia).
        h: Tamaño del subconjunto.
        scfac: Factor de consistencia.

    Returns:
        ``SubsetScatter``.
    """
    xs = mx[:, idx]
    mu = r_rowmeans(xs)
    me = xs - mu[:, None]
    ms = r_matprod(me, np.array(me.T, dtype=np.float64)) / (h - 1)
    veigen = r_eigen_values(scfac * ms)
    return SubsetScatter(
        mu=mu, m_s=ms, veigen=veigen, e1=float(np.min(veigen)), ep=float(np.max(veigen))
    )


def fncond_factory(e1: float, ep: float, maxcond: float) -> Callable[[float], float]:
    """``fncond`` de la rama identidad (``detmrcd.R:479-484``).

    ``condnr = (rho + (1-rho)*ep) / (rho + (1-rho)*e1)``; devuelve ``condnr - maxcond``. Aritmética
    escalar de R: un redondeo por operación (sin FMA; el intérprete evalúa cada operador aparte).

    Args:
        e1: Mínimo autovalor.
        ep: Máximo autovalor.
        maxcond: Número de condición objetivo.

    Returns:
        La función escalar.
    """

    def fncond(rho: float) -> float:
        with np.errstate(divide="ignore", invalid="ignore"):
            num = np.float64(rho) + (1 - np.float64(rho)) * np.float64(ep)
            den = np.float64(rho) + (1 - np.float64(rho)) * np.float64(e1)
            return float(num / den - maxcond)

    return fncond


class RhoK(NamedTuple):
    """``rho_k`` de un subconjunto con la traza de su cálculo.

    Attributes:
        rho: ``rho_k`` elegido.
        path: ``1`` si ``uniroot`` tuvo éxito, ``2`` si se usó la rejilla.
        root: Raíz de ``uniroot`` (``NaN`` en la rejilla).
        iter: Iteraciones de ``uniroot`` (``-1`` en la rejilla).
        estim_prec: ``estim.prec`` de ``uniroot`` (``NaN`` en la rejilla).
    """

    rho: float
    path: int
    root: float
    iter: int
    estim_prec: float


def rho_for_subset(e1: float, ep: float, maxcond: float) -> RhoK:
    """``rho_k`` por ``uniroot`` o, si falla, por la rejilla.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:495-511``: ``try(uniroot(fncond, lower=0.00001,
    upper=0.99))``; cualquier error (``f`` no finita en un extremo o signos iguales,
    ``nlm.R:66-67``, ``:138-141``) ⇒ rejilla: ``objgrid = abs(fncond(grid))`` y
    ``irho = min(grid[objgrid == min(objgrid)])`` (igualdad exacta, trampa T16). Si ``objgrid``
    es todo ``NaN``, ``min`` es ``NaN`` y ``grid[NA]`` da ``NA``: ``rho_k = NaN`` como en R.

    Args:
        e1: Mínimo autovalor de ``scfac * mS``.
        ep: Máximo autovalor.
        maxcond: Número de condición objetivo.

    Returns:
        ``RhoK``.
    """
    f = fncond_factory(e1, ep, maxcond)
    try:
        out = r_uniroot(f, UNIROOT_LOWER, UNIROOT_UPPER)
    except RError:
        objgrid = np.abs(np.array([f(float(g)) for g in RHO_GRID.tolist()], dtype=np.float64))
        if np.isnan(objgrid).any():
            irho = math.nan
        else:
            irho = float(np.min(RHO_GRID[objgrid == np.min(objgrid)]))
        return RhoK(rho=irho, path=2, root=math.nan, iter=-1, estim_prec=math.nan)
    return RhoK(rho=out.root, path=1, root=out.root, iter=out.iter, estim_prec=out.estim_prec)


class RhoSelection(NamedTuple):
    """Selección global de ``rho`` (``detmrcd.R:518-535``).

    Attributes:
        cutoff: ``max(0.1, median(rho6))``.
        rho: ``max(rho6[rho6 <= cutoff])``.
        vsel: ``Vselection`` en base 0 (``-1`` donde R pone ``NA``).
        init_v: ``initV`` en base 0.
        sets_v: ``setsV`` en base 0.
    """

    cutoff: float
    rho: float
    vsel: IntArray
    init_v: int
    sets_v: IntArray


def select_rho(rho6: FloatArray) -> RhoSelection:
    """``cutoffrho``, ``rho``, ``initV`` y ``setsV``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:518-535``: ``cutoffrho = max(c(0.1, median(rho6pack)))``
    (``median`` de R, media de dos pasadas de los centrales); ``rho = max(rho6[rho6 <= cutoff])``;
    ``Vselection[rho6 > cutoff] = NA``; si todos son ``NA`` ⇒ error (``:529-531``);
    ``initV = min(Vselection, na.rm=TRUE)`` y ``setsV`` = resto en orden creciente.

    Args:
        rho6: Los ``rho_k`` de los subconjuntos.

    Returns:
        ``RhoSelection`` (índices en base 0).

    Raises:
        RError: si ningún subconjunto está bien condicionado o hay ``NA`` donde R falla.
    """
    r6 = np.asarray(rho6, dtype=np.float64)
    med = r_median(r6)
    if math.isnan(med):
        # median con NA es NA ⇒ cutoff NA ⇒ Vselection todo NA ⇒ stop() de :529-531.
        raise RError("None of the initial subsets is well-conditioned")
    cutoff = max(0.1, med)
    keep = r6 <= cutoff
    rho = float(np.max(r6[keep])) if keep.any() else -math.inf
    vsel = np.arange(r6.shape[0], dtype=np.int64)
    vsel[r6 > cutoff] = -1
    valid = vsel[vsel >= 0]
    if valid.shape[0] == 0:
        raise RError("None of the initial subsets is well-conditioned")
    return RhoSelection(
        cutoff=cutoff,
        rho=rho,
        vsel=vsel,
        init_v=int(valid[0]),
        sets_v=np.asarray(valid[1:], dtype=np.int64),
    )
