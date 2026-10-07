"""Rutinas de LAPACK de referencia que usa R, portadas sobre el BLAS de ``scipy``.

R no usa el LAPACK de Accelerate: enlaza su propio ``libRlapack`` (LAPACK 3.12.1 de referencia,
``R-4.5.2/src/modules/lapack/dlapack.f``), que a su vez llama al BLAS del sistema (Accelerate en el
oráculo). ``scipy.linalg.lapack`` llama al LAPACK de Accelerate, cuyos algoritmos internos no son
los
de referencia: ``chol``, ``chol2inv`` y ``determinant`` difieren en 1-2 ulp (medido contra los
fixtures
de primitivas). Estas rutinas son traducciones literales del Fortran de referencia: toda su
aritmética
está en llamadas a BLAS (``dtrsm``, ``dsyrk``, ``dgemm``, ``dtrmm``, ``dtrmv``, ``dgemv``, ``ddot``)
o en operaciones escalares exactas (``sqrt``, ``1/x``, intercambios), así que con el mismo BLAS
reproducen los bits de R. Los tamaños de bloque son los de ``ILAENV`` de referencia (64 para
``DPOTRF``, ``DTRTRI``, ``DLAUUM`` y ``DGETRF``; ``dlapack.f:165090-165303``).

Convenciones: ``a`` es una matriz ``float64`` en orden Fortran que se modifica en sitio; los índices
de los comentarios son los de Fortran (base 1).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.linalg import blas

from pymrcd._types import FloatArray, IntArray

__all__ = ["dgetrf", "dpotrf_upper", "dpotri_upper"]

_NB = 64
"""``ILAENV(1, 'DPOTRF'|'DTRTRI'|'DLAUUM'|'DGETRF', …)`` de referencia."""

_SFMIN = float(np.finfo(np.float64).tiny)
"""``DLAMCH('S')``: menor normal tal que ``1/sfmin`` no desborda (``dlamch.f``)."""


def _put(a: FloatArray, r0: int, c0: int, block: object) -> None:
    """Escribe ``block`` en ``a[r0:, c0:]`` con su forma.

    Args:
        a: Matriz destino.
        r0: Fila inicial (base 0).
        c0: Columna inicial (base 0).
        block: Resultado de BLAS (matriz).
    """
    b = np.asarray(block, dtype=np.float64)
    a[r0 : r0 + b.shape[0], c0 : c0 + b.shape[1]] = b


# --------------------------------------------------------------------------------------------------
# Cholesky
# --------------------------------------------------------------------------------------------------


def _dpotrf2_upper(a: FloatArray, r0: int, n: int) -> int:
    """``DPOTRF2('U')`` recursivo sobre el bloque ``a[r0:r0+n, r0:r0+n]``.

    Fuente: ``R-4.5.2/src/modules/lapack/dlapack.f:112000-112095`` (``n = 1``: ``sqrt`` o
    ``info = 1`` si ``a11 <= 0`` o ``NaN``; si no, ``n1 = n/2``, recursión,
    ``DTRSM('L','U','T','N')``,
    ``DSYRK('U','T', -1, 1)`` y recursión sobre ``A22``).

    Args:
        a: Matriz en orden Fortran (se modifica).
        r0: Desplazamiento del bloque (base 0).
        n: Orden del bloque.

    Returns:
        ``info`` (0 si es definida positiva).
    """
    if n == 0:
        return 0
    if n == 1:
        v = float(a[r0, r0])
        if v <= 0.0 or math.isnan(v):
            return 1
        a[r0, r0] = math.sqrt(v)
        return 0
    n1 = n // 2
    n2 = n - n1
    info = _dpotrf2_upper(a, r0, n1)
    if info:
        return info
    s1 = slice(r0, r0 + n1)
    s2 = slice(r0 + n1, r0 + n)
    _put(a, r0, r0 + n1, blas.dtrsm(1.0, a[s1, s1], a[s1, s2], side=0, lower=0, trans_a=1, diag=0))
    _put(a, r0 + n1, r0 + n1, blas.dsyrk(-1.0, a[s1, s2], beta=1.0, c=a[s2, s2], trans=1, lower=0))
    info = _dpotrf2_upper(a, r0 + n1, n2)
    return info + n1 if info else 0


def dpotrf_upper(a: FloatArray) -> int:
    """``DPOTRF('U')`` de referencia (bloques de 64 con ``DPOTRF2``), en sitio.

    Fuente: ``R-4.5.2/src/modules/lapack/dlapack.f:111753-111850`` (rama ``UPPER``: por bloques
    ``j``: ``DSYRK('U','T')``, ``DPOTRF2``, ``DGEMM('T','N')`` y ``DTRSM('L','U','T','N')``).

    Args:
        a: Matriz ``n x n`` en orden Fortran (se lee y escribe el triángulo superior).

    Returns:
        ``info``: 0 si es definida positiva; si no, el orden del menor no positivo.
    """
    n = a.shape[0]
    if n == 0:
        return 0
    if n <= _NB:
        return _dpotrf2_upper(a, 0, n)
    for j in range(0, n, _NB):
        jb = min(_NB, n - j)
        sj = slice(j, j + jb)
        if j > 0:
            _put(a, j, j, blas.dsyrk(-1.0, a[0:j, sj], beta=1.0, c=a[sj, sj], trans=1, lower=0))
        info = _dpotrf2_upper(a, j, jb)
        if info:
            return info + j
        if j + jb < n:
            sr = slice(j + jb, n)
            if j > 0:
                _put(
                    a,
                    j,
                    j + jb,
                    blas.dgemm(-1.0, a[0:j, sj], a[0:j, sr], beta=1.0, c=a[sj, sr], trans_a=1),
                )
            _put(a, j, j + jb, blas.dtrsm(1.0, a[sj, sj], a[sj, sr], side=0, lower=0, trans_a=1))
    return 0


# --------------------------------------------------------------------------------------------------
# Inversa a partir de Cholesky
# --------------------------------------------------------------------------------------------------


def _dtrti2_upper(a: FloatArray, r0: int, n: int) -> None:
    """``DTRTI2('U','N')`` sobre el bloque ``a[r0:r0+n, r0:r0+n]``.

    Fuente: ``R-4.5.2/src/modules/lapack/dlapack.f:162602-162720``: para ``j = 1..n``:
    ``A(j,j) = 1/A(j,j)``; ``ajj = -A(j,j)``; ``DTRMV('U','N','N', j-1, A, A(1,j))``;
    ``DSCAL(j-1, ajj, A(1,j))``.

    Args:
        a: Matriz en orden Fortran (se modifica).
        r0: Desplazamiento del bloque (base 0).
        n: Orden del bloque.
    """
    for j in range(n):
        jj = r0 + j
        a[jj, jj] = 1.0 / a[jj, jj]
        ajj = -float(a[jj, jj])
        if j == 0:
            continue
        col = slice(r0, r0 + j)
        x = blas.dtrmv(a[col, col], np.array(a[col, jj]), lower=0, trans=0, diag=0)
        a[col, jj] = blas.dscal(ajj, np.asarray(x, dtype=np.float64))


def _dtrtri_upper(a: FloatArray) -> int:
    """``DTRTRI('U','N')`` de referencia (bloques de 64), en sitio.

    Fuente: ``R-4.5.2/src/modules/lapack/dlapack.f:162810-162950``: comprueba diagonal nula
    (``info``); si ``n <= 64`` ``DTRTI2``; si no, por bloques ``DTRMM('L','U','N','N')``,
    ``DTRSM('R','U','N','N', -1)`` y ``DTRTI2``.

    Args:
        a: Matriz triangular superior en orden Fortran (se modifica).

    Returns:
        ``info``: 0 o el índice (base 1) del primer elemento diagonal nulo.
    """
    n = a.shape[0]
    for i in range(n):
        if a[i, i] == 0.0:
            return i + 1
    if n <= _NB:
        _dtrti2_upper(a, 0, n)
        return 0
    for j in range(0, n, _NB):
        jb = min(_NB, n - j)
        sj = slice(j, j + jb)
        if j > 0:
            _put(a, 0, j, blas.dtrmm(1.0, a[0:j, 0:j], a[0:j, sj], side=0, lower=0))
            _put(a, 0, j, blas.dtrsm(-1.0, a[sj, sj], a[0:j, sj], side=1, lower=0))
        _dtrti2_upper(a, j, jb)
    return 0


def _dlauu2_upper(a: FloatArray, r0: int, n: int) -> None:
    """``DLAUU2('U')`` sobre el bloque ``a[r0:r0+n, r0:r0+n]``: ``U·Uᵀ`` en el triángulo superior.

    Fuente: ``R-4.5.2/src/modules/lapack/dlapack.f:96393-96510``: para ``i = 1..n``:
    ``aii = A(i,i)``; si ``i < n``: ``A(i,i) = DDOT(n-i+1, A(i,i), lda, A(i,i), lda)`` y
    ``DGEMV('N', i-1, n-i, 1, A(1,i+1), lda, A(i,i+1), lda, aii, A(1,i), 1)``; si no,
    ``DSCAL(i, aii, A(1,i), 1)``. Los accesos por fila (``lda``) se hacen sobre la memoria de la
    matriz, como en Fortran.

    Args:
        a: Matriz en orden Fortran (se modifica).
        r0: Desplazamiento del bloque (base 0).
        n: Orden del bloque.
    """
    lda = a.shape[0]
    flat = a.reshape(-1, order="F")  # vista (a es contigua en orden Fortran)
    for i in range(n):
        ii = r0 + i
        aii = float(a[ii, ii])
        if i < n - 1:
            off = ii + ii * lda
            a[ii, ii] = blas.ddot(flat, flat, n=n - i, offx=off, incx=lda, offy=off, incy=lda)
            if i > 0:
                rows = slice(r0, ii)
                cols = slice(ii + 1, r0 + n)
                y = blas.dgemv(
                    1.0,
                    a[rows, cols],
                    flat,
                    beta=aii,
                    y=np.array(a[rows, ii]),
                    offx=ii + (ii + 1) * lda,
                    incx=lda,
                )
                a[rows, ii] = y
        else:
            col = slice(r0, ii + 1)
            a[col, ii] = blas.dscal(aii, np.array(a[col, ii]))


def _dlauum_upper(a: FloatArray) -> None:
    """``DLAUUM('U')`` de referencia (bloques de 64), en sitio.

    Fuente: ``R-4.5.2/src/modules/lapack/dlapack.f:96591-96700``: si ``n <= 64`` ``DLAUU2``; si no,
    por bloques ``DTRMM('R','U','T','N')``, ``DLAUU2``, ``DGEMM('N','T')`` y ``DSYRK('U','N')``.

    Args:
        a: Matriz triangular superior en orden Fortran (se modifica).
    """
    n = a.shape[0]
    if n <= _NB:
        _dlauu2_upper(a, 0, n)
        return
    for i in range(0, n, _NB):
        ib = min(_NB, n - i)
        si = slice(i, i + ib)
        if i > 0:
            _put(a, 0, i, blas.dtrmm(1.0, a[si, si], a[0:i, si], side=1, lower=0, trans_a=1))
        _dlauu2_upper(a, i, ib)
        if i + ib < n:
            sr = slice(i + ib, n)
            if i > 0:
                _put(
                    a,
                    0,
                    i,
                    blas.dgemm(1.0, a[0:i, sr], a[si, sr], beta=1.0, c=a[0:i, si], trans_b=1),
                )
            _put(a, i, i, blas.dsyrk(1.0, a[si, sr], beta=1.0, c=a[si, si], trans=0, lower=0))


def dpotri_upper(a: FloatArray) -> int:
    """``DPOTRI('U')`` de referencia: ``DTRTRI`` y después ``DLAUUM``, en sitio.

    Fuente: ``R-4.5.2/src/modules/lapack/dlapack.f:112223-112260``.

    Args:
        a: Factor de Cholesky triangular superior en orden Fortran (se modifica).

    Returns:
        ``info`` de ``DTRTRI`` (0 si no hay diagonal nula).
    """
    if a.shape[0] == 0:
        return 0
    info = _dtrtri_upper(a)
    if info > 0:
        return info
    _dlauum_upper(a)
    return 0


# --------------------------------------------------------------------------------------------------
# LU
# --------------------------------------------------------------------------------------------------


def _dlaswp(a: FloatArray, c0: int, ncols: int, k1: int, k2: int, ipiv: IntArray) -> None:
    """``DLASWP(ncols, A(1,c0+1), lda, k1, k2, ipiv, 1)``: intercambios de filas (exactos).

    Fuente: ``R-4.5.2/src/modules/lapack/dlapack.f:91410-91490`` (``incx = 1``: ``i = k1..k2``,
    intercambia la fila ``i`` con ``ipiv(i)``).

    Args:
        a: Matriz (se modifica).
        c0: Primera columna (base 0).
        ncols: Número de columnas.
        k1: Primer índice de pivote (base 1).
        k2: Último índice de pivote (base 1).
        ipiv: Pivotes absolutos en base 1.
    """
    if ncols <= 0:
        return
    cols = slice(c0, c0 + ncols)
    for i in range(k1, k2 + 1):
        ip = int(ipiv[i - 1])
        if ip != i:
            tmp = a[i - 1, cols].copy()
            a[i - 1, cols] = a[ip - 1, cols]
            a[ip - 1, cols] = tmp


def _dgetrf2(a: FloatArray, r0: int, c0: int, m: int, n: int, ipiv: IntArray) -> int:
    """``DGETRF2`` recursivo sobre ``a[r0:r0+m, c0:c0+n]``; ``ipiv`` relativo al bloque (base 1).

    Fuente: ``R-4.5.2/src/modules/lapack/dlapack.f:30944-31090``: ``m = 1`` ⇒ pivote 1; ``n = 1`` ⇒
    ``IDAMAX``, intercambio y ``DSCAL(1/a11)`` (o división si ``|a11| < sfmin``); si no, ``n1 =
    min(m,n)/2``, recursión, ``DLASWP``, ``DTRSM('L','L','N','U')``, ``DGEMM('N','N', -1, 1)``,
    recursión sobre ``A22``, ajuste de pivotes y ``DLASWP`` de vuelta.

    Args:
        a: Matriz en orden Fortran (se modifica).
        r0: Fila inicial (base 0).
        c0: Columna inicial (base 0).
        m: Filas del bloque.
        n: Columnas del bloque.
        ipiv: Salida de pivotes (longitud ``min(m, n)``, base 1 relativa al bloque).

    Returns:
        ``info``.
    """
    if m == 0 or n == 0:
        return 0
    if m == 1:
        ipiv[0] = 1
        return 1 if a[r0, c0] == 0.0 else 0
    if n == 1:
        col = np.array(a[r0 : r0 + m, c0])
        i = int(blas.idamax(col)) + 1
        ipiv[0] = i
        if a[r0 + i - 1, c0] == 0.0:
            return 1
        if i != 1:
            tmp = float(a[r0, c0])
            a[r0, c0] = a[r0 + i - 1, c0]
            a[r0 + i - 1, c0] = tmp
        pivot = float(a[r0, c0])
        if abs(pivot) >= _SFMIN:
            a[r0 + 1 : r0 + m, c0] = blas.dscal(1.0 / pivot, np.array(a[r0 + 1 : r0 + m, c0]))
        else:
            a[r0 + 1 : r0 + m, c0] = a[r0 + 1 : r0 + m, c0] / pivot
        return 0
    n1 = min(m, n) // 2
    n2 = n - n1
    info = 0
    iinfo = _dgetrf2(a, r0, c0, m, n1, ipiv[:n1])
    if info == 0 and iinfo > 0:
        info = iinfo
    sub = a[r0 : r0 + m, :]
    _dlaswp(sub, c0 + n1, n2, 1, n1, ipiv)
    s1r = slice(r0, r0 + n1)
    s1c = slice(c0, c0 + n1)
    s2c = slice(c0 + n1, c0 + n)
    s2r = slice(r0 + n1, r0 + m)
    _put(a, r0, c0 + n1, blas.dtrsm(1.0, a[s1r, s1c], a[s1r, s2c], side=0, lower=1, diag=1))
    _put(
        a,
        r0 + n1,
        c0 + n1,
        blas.dgemm(-1.0, a[s2r, s1c], a[s1r, s2c], beta=1.0, c=a[s2r, s2c]),
    )
    tail = ipiv[n1 : min(m, n)]
    iinfo = _dgetrf2(a, r0 + n1, c0 + n1, m - n1, n2, tail)
    if info == 0 and iinfo > 0:
        info = iinfo + n1
    tail += n1
    _dlaswp(sub, c0, n1, n1 + 1, min(m, n), ipiv)
    return info


def dgetrf(a: FloatArray) -> tuple[IntArray, int]:
    """``DGETRF`` de referencia (bloques de 64 con ``DGETRF2``), en sitio.

    Fuente: ``R-4.5.2/src/modules/lapack/dlapack.f:30713-30800``.

    Args:
        a: Matriz ``m x n`` en orden Fortran (se modifica: ``L`` y ``U``).

    Returns:
        ``(ipiv, info)`` con pivotes en base 1.
    """
    m, n = a.shape
    k = min(m, n)
    ipiv = np.zeros(k, dtype=np.int64)
    if m == 0 or n == 0:
        return ipiv, 0
    if k <= _NB:
        return ipiv, _dgetrf2(a, 0, 0, m, n, ipiv)
    info = 0
    for j in range(0, k, _NB):
        jb = min(k - j, _NB)
        piv = ipiv[j : j + jb]
        iinfo = _dgetrf2(a, j, j, m - j, jb, piv)
        if info == 0 and iinfo > 0:
            info = iinfo + j
        piv += j
        _dlaswp(a, 0, j, j + 1, j + jb, ipiv)
        if j + jb < n:
            _dlaswp(a, j + jb, n - j - jb, j + 1, j + jb, ipiv)
            sj = slice(j, j + jb)
            sr = slice(j + jb, n)
            _put(a, j, j + jb, blas.dtrsm(1.0, a[sj, sj], a[sj, sr], side=0, lower=1, diag=1))
            if j + jb < m:
                sm = slice(j + jb, m)
                _put(
                    a,
                    j + jb,
                    j + jb,
                    blas.dgemm(-1.0, a[sm, sj], a[sj, sr], beta=1.0, c=a[sm, sr]),
                )
    return ipiv, info
