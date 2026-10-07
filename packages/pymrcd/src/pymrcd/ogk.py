"""Matriz de dispersión OGK cruda (``ogkscatter``) del sexto subconjunto inicial de ``r6pack``.

Port de la función local ``ogkscatter`` de ``rrcov-1.7-7/R/detmrcd.R:84-111`` con ``scalefn = Qn``
para **todo** ``p`` (la versión oficial de CRAN; la variante modificada con MAD para ``p >= 46`` no
se porta, ADR 0002/0006). Vectorización entre pares independientes (especificación §7): cada
``Qn`` se calcula con la misma secuencia de ``qn0`` que en C, así que el resultado es idéntico al
doble bucle de R.
"""

from __future__ import annotations

import numpy as np

from pymrcd._rlinalg import r_eigen_sym
from pymrcd._types import FloatArray
from pymrcd.qn import qn_columns

__all__ = ["ogk_u", "ogkscatter"]

_PAIR_CHUNK_ELEMENTS = 1 << 22
"""Elementos (``n x columnas``) por lote de pares, para acotar la memoria."""


def ogk_u(y: FloatArray) -> FloatArray:
    """Matriz ``U`` de ``ogkscatter`` antes de ``eigen`` (``detmrcd.R:86-98``).

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:87`` (``U <- diag(p)``: diagonal 1), ``:89-95``
    (``U[i,j] <- (Qn(Y_i + Y_j)^2 - Qn(Y_i - Y_j)^2) / 4`` para ``i > j``, orientación
    ``Y_i - Y_j`` fija, trampa T2; ``^2`` es ``x*x`` por ``R_POW``) y ``:97`` (espejo al triángulo
    superior). Los pares se procesan por lotes (especificación §7); ``Qn`` por columnas reproduce
    ``qn0`` exactamente, así que el orden de los pares no altera ningún valor.

    Args:
        y: Datos ``n x p`` (ya estandarizados por ``doScale``).

    Returns:
        Matriz simétrica ``p x p``.
    """
    arr = np.asarray(y, dtype=np.float64)
    n, p = arr.shape
    u = np.eye(p, dtype=np.float64)
    if p < 2:
        return u
    ii, jj = np.tril_indices(p, -1)  # i > j
    step = max(1, _PAIR_CHUNK_ELEMENTS // max(2 * n, 1))
    for start in range(0, ii.shape[0], step):
        bi = ii[start : start + step]
        bj = jj[start : start + step]
        yi = arr[:, bi]
        yj = arr[:, bj]
        both = np.concatenate((yi + yj, yi - yj), axis=1)
        q = qn_columns(both)
        m = bi.shape[0]
        s = q[:m]
        d = q[m:]
        u[bi, bj] = (s * s - d * d) / 4
    u[jj, ii] = u[ii, jj]
    return u


def ogkscatter(y: FloatArray) -> FloatArray:
    """``ogkscatter(Y, Qn, only.P=TRUE)``: autovectores de ``U``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:84-103`` (``P <- eigen(U, symmetric=TRUE)$vectors`` en
    ``:101``; ``only.P = TRUE`` desde ``:166``). La rama ``only.P = FALSE`` (``:105-110``) es
    código muerto (especificación §8).

    Args:
        y: Datos ``n x p``.

    Returns:
        Matriz ``P`` de autovectores ``p x p`` (orden decreciente de autovalores).
    """
    return r_eigen_sym(ogk_u(y)).vectors
