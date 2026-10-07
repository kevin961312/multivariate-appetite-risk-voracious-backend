"""C-steps generalizados de MRCD (``.cstep_mrcd``).

Port de ``rrcov-1.7-7/R/detmrcd.R:342-383`` (especificación §3.8, trampas T15 y T18). Índices en
**base 0**.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from pymrcd._rbase import r_order, r_rowmeans
from pymrcd._rlinalg import r_matprod
from pymrcd._types import FloatArray, IntArray
from pymrcd.rcov import RCov, rcov

__all__ = ["CStepIteration", "CStepResult", "cstep_mrcd", "mahalanobis_all", "next_index"]


class CStepIteration(NamedTuple):
    """Intermedios de una iteración (``t = 0`` es el paso inicial ``:350-361``).

    Attributes:
        subset: Subconjunto usado (base 0).
        v_mu: Media del subconjunto.
        rc: Salida de ``.RCOV``.
        vdst: Distancias de las ``n`` observaciones.
        nndex: Nuevo subconjunto ordenado (base 0).
    """

    subset: IntArray
    v_mu: FloatArray
    rc: RCov
    vdst: FloatArray
    nndex: IntArray


class CStepResult(NamedTuple):
    """Salida de ``.cstep_mrcd``.

    Attributes:
        subset: Subconjunto final (base 0, ordenado).
        numit: Iteraciones.
        mu: Media de la última ``.RCOV`` evaluada.
        cov: ``rcov`` de la última ``.RCOV``.
        icov: Inversa de la última ``.RCOV``.
        dist: Últimas distancias.
        iterations: Intermedios por iteración (solo si se pidieron).
    """

    subset: IntArray
    numit: int
    mu: FloatArray
    cov: FloatArray
    icov: FloatArray
    dist: FloatArray
    iterations: tuple[CStepIteration, ...]


def mahalanobis_all(mx: FloatArray, vmu: FloatArray, mis: FloatArray) -> FloatArray:
    """``diag(t(mX-vMu) %*% (mIS %*% (mX-vMu)))`` (``detmrcd.R:360``, ``:371``).

    Se calcula el producto ``n x n`` completo con dos ``dgemm``, como R (trampa T15, decisión P5).

    Args:
        mx: Datos ``p x n``.
        vmu: Centro ``p``.
        mis: Inversa ``p x p``.

    Returns:
        Vector ``n``.
    """
    d = np.asarray(mx, dtype=np.float64) - np.asarray(vmu, dtype=np.float64)[:, None]
    full = r_matprod(np.array(d.T, dtype=np.float64), r_matprod(mis, d))
    return np.asarray(np.diag(full).copy(), dtype=np.float64)


def next_index(vdst: FloatArray, h: int) -> IntArray:
    """``sort(sort.int(vdst, index.return=TRUE)$ix[1:h])`` en base 0.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:361``, ``:372`` y
    ``R-4.5.2/src/library/base/R/sort.R:80-115``:
    ``na.last = NA`` elimina los ``NA`` **antes** de ordenar, así que ``ix`` indexa el vector ya
    reducido (§3.12.3); radix estable; los ``NA`` de ``[1:h]`` (si quedan menos de ``h``) los
    elimina ``sort``.

    Args:
        vdst: Distancias.
        h: Tamaño del subconjunto.

    Returns:
        Índices ordenados (base 0).
    """
    v = np.asarray(vdst, dtype=np.float64)
    reduced = v[~np.isnan(v)]
    ix = r_order(reduced)[:h]
    return np.sort(ix)


def cstep_mrcd(
    mx: FloatArray,
    rho: float,
    h: int,
    scfac: float,
    index: IntArray,
    maxcsteps: int,
    record: bool = False,
) -> CStepResult:
    """``.cstep_mrcd(mX, rho, mT=diag(p), h, scfac, index, maxcsteps)``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:342-383``: paso inicial con ``index`` en su orden
    (``:350-361``: ``rowMeans``, ``.RCOV(invert=TRUE)``, distancias y nuevo índice); bucle
    ``while(iter < maxcsteps)`` (``:365-379``) que para si ``all(nndex == index)``. Si se sale por
    ``maxcsteps`` (o con ``maxcsteps <= 1``) se devuelve el índice **nuevo** con ``mu``/``cov`` de
    la iteración anterior (trampa T18). ``sample()`` (``:348-349``) es código muerto.

    Args:
        mx: Datos ``p x n``.
        rho: Parámetro de regularización.
        h: Tamaño del subconjunto.
        scfac: Factor de consistencia.
        index: Subconjunto inicial (base 0, en el orden de R).
        maxcsteps: Máximo de iteraciones.
        record: Si ``True``, guarda los intermedios de cada iteración.

    Returns:
        ``CStepResult``.
    """
    arr = np.asarray(mx, dtype=np.float64)
    its: list[CStepIteration] = []
    idx = np.asarray(index, dtype=np.int64)
    xx = arr[:, idx]
    vmu = r_rowmeans(xx)
    ret = rcov(xx, vmu, rho, scfac)
    vdst = mahalanobis_all(arr, vmu, ret.inv)
    new = next_index(vdst, h)
    if record:
        its.append(CStepIteration(subset=idx, v_mu=vmu, rc=ret, vdst=vdst, nndex=new))
    idx = new
    it = 1
    while it < maxcsteps:
        xx = arr[:, idx]
        vmu = r_rowmeans(xx)
        ret = rcov(xx, vmu, rho, scfac)
        vdst = mahalanobis_all(arr, vmu, ret.inv)
        nndex = next_index(vdst, h)
        if record:
            its.append(CStepIteration(subset=idx, v_mu=vmu, rc=ret, vdst=vdst, nndex=nndex))
        if nndex.shape == idx.shape and bool((nndex == idx).all()):
            break
        idx = nndex
        it += 1
    return CStepResult(
        subset=idx,
        numit=it,
        mu=vmu,
        cov=ret.rcov,
        icov=ret.inv,
        dist=vdst,
        iterations=tuple(its),
    )
