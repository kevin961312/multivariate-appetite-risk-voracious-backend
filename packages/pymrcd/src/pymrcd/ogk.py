"""Matriz de dispersión OGK cruda (``ogkscatter``) del sexto subconjunto inicial de ``r6pack``.

Port de la función local ``ogkscatter`` de ``rrcov-1.7-7/R/detmrcd.R:84-111`` con ``scalefn = Qn``
para **todo** ``p`` (la versión oficial de CRAN; la variante modificada con MAD para ``p >= 46`` no
se porta, ADR 0002/0006). Los pares independientes se reparten entre hilos en la extensión C
(especificación §3.12.9): cada ``Qn`` es el ``qn0`` literal de R, así que el resultado es idéntico
al doble bucle de R para cualquier número de hilos.
"""

from __future__ import annotations

import numpy as np

from pymrcd._cext import qn_ext
from pymrcd._rlinalg import r_eigen_sym
from pymrcd._types import FloatArray
from pymrcd.qn import QN_CONSTANT, QN_SMALL_N_FACTORS, qn_columns, qn_finite_c, threads_arg

__all__ = ["ogk_u", "ogkscatter"]


def ogk_u(y: FloatArray, n_threads: int | None = None) -> FloatArray:
    """Matriz ``U`` de ``ogkscatter`` antes de ``eigen`` (``detmrcd.R:86-98``).

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:87`` (``U <- diag(p)``: diagonal 1), ``:89-95``
    (``U[i,j] <- (Qn(Y_i + Y_j)^2 - Qn(Y_i - Y_j)^2) / 4`` para ``i > j``, orientación
    ``Y_i - Y_j`` fija, trampa T2; ``^2`` es ``x*x`` por ``R_POW``) y ``:97`` (espejo al triángulo
    superior). Con ``n >= 2`` los pares, ``qn0`` y ``(s*s - d*d)/4`` se calculan en la extensión C
    por hilo (M1, especificación §3.12.9 a, última fila): la constante ``2.21914`` y el factor
    ``TAB[n-2]`` o ``Qn.finite.c(n)`` (``qnsn.R:44-65``) se calculan aquí y se pasan como
    ``double``. Con ``n <= 1`` ``Qn`` es ``NA``/``0`` (``qnsn.R:29``) y se resuelve en Python.

    Args:
        y: Datos ``n x p`` (ya estandarizados por ``doScale``).
        n_threads: Hilos de la extensión C (rendimiento, no cambia ningún bit); ``None`` ⇒ por
            defecto.

    Returns:
        Matriz simétrica ``p x p``.

    Raises:
        ValueError: si algún par sin ``NaN`` contiene ``±Inf`` (como ``qn_columns``).
    """
    arr = np.asarray(y, dtype=np.float64)
    n, p = arr.shape
    u = np.eye(p, dtype=np.float64)
    if p < 2:
        return u
    if n < 2:
        ii, jj = np.tril_indices(p, -1)  # i > j
        s = qn_columns(arr[:, ii] + arr[:, jj])
        d = qn_columns(arr[:, ii] - arr[:, jj])
        u[ii, jj] = (s * s - d * d) / 4
        u[jj, ii] = u[ii, jj]
        return u
    small_n = n <= 12
    factor = QN_SMALL_N_FACTORS[n - 2] if small_n else qn_finite_c(n)
    qn_ext.ogk_u(arr, u, QN_CONSTANT, factor, small_n, threads_arg(n_threads))
    return u


def ogkscatter(y: FloatArray, n_threads: int | None = None) -> FloatArray:
    """``ogkscatter(Y, Qn, only.P=TRUE)``: autovectores de ``U``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:84-103`` (``P <- eigen(U, symmetric=TRUE)$vectors`` en
    ``:101``; ``only.P = TRUE`` desde ``:166``). La rama ``only.P = FALSE`` (``:105-110``) es
    código muerto (especificación §8).

    Args:
        y: Datos ``n x p``.
        n_threads: Hilos de ``ogk_u`` (rendimiento).

    Returns:
        Matriz ``P`` de autovectores ``p x p`` (orden decreciente de autovalores).
    """
    return r_eigen_sym(ogk_u(y, n_threads=n_threads)).vectors
