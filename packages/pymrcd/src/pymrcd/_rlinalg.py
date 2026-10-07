"""Réplica de las llamadas BLAS/LAPACK de R (``%*%``, ``crossprod``, ``eigen``, ``chol``, ``det``).

R no hace álgebra lineal propia: llama a BLAS/LAPACK con matrices en orden de columna. Para
coincidir
bit a bit en la plataforma del oráculo hay que hacer **las mismas llamadas con los mismos
argumentos**
(especificación §3.12.6, trampas T8, T13, T22; decisión P2 del dueño). Por eso estos helpers usan
``scipy.linalg.blas``/``scipy.linalg.lapack`` con operandos en orden Fortran y prohíben ``@`` y
``np.linalg``: ``A @ A.T`` usa ``syrk`` y no reproduce ``dgemm`` (sonda S7).
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np
from scipy.linalg import blas, lapack

from pymrcd._errors import RError
from pymrcd._fma import fma_array
from pymrcd._rbase import r_order, r_rowsums, seqsum
from pymrcd._rlapack import dgetrf, dpotrf_upper, dpotri_upper
from pymrcd._types import FloatArray

__all__ = [
    "EigenResult",
    "r_chol",
    "r_chol2inv",
    "r_crossprod",
    "r_det",
    "r_determinant",
    "r_eigen_sym",
    "r_eigen_values",
    "r_is_symmetric",
    "r_mahalanobis_d",
    "r_mahalanobis_inverted",
    "r_matprod",
    "r_matvec",
    "r_scale",
    "r_vecmat",
]


_R_SMALL_LIMIT = 120
"""Vectores de más de 120 ``double`` los reserva R con ``malloc`` en la región *small* de macOS."""

_R_DATA_OFFSET = 48
"""Desplazamiento de los datos respecto a la cabecera ``SEXPREC_ALIGN`` (48 bytes en 64 bits)."""


def _fortran(a: FloatArray) -> FloatArray:
    """Copia ``a`` en orden Fortran (columna mayor) con la alineación de memoria de un vector de R.

    R guarda las matrices por columnas. Además, el ``dgemv`` de Accelerate da bits distintos según
    la
    alineación del operando (medido: ``v %*% B`` con ``B`` 200x40 solo coincide con R si los datos
    empiezan en ``48 mod 64`` bytes). En el oráculo, un vector de más de 120 ``double`` se reserva
    con
    ``malloc`` (región *small* de macOS, alineada a 512) y sus datos empiezan tras la cabecera
    ``SEXPREC_ALIGN`` de 48 bytes (``R-4.5.2.tar.gz`` ``src/include/Defn.h:219-224``, ``:418``;
    medido con ``.Internal(inspect())``: dirección ``≡ 0 mod 64``). Se reproduce esa alineación; los
    vectores pequeños de R (pools propios y región *tiny*) no tienen alineación fija y se dejan
    con la
    de numpy.

    Args:
        a: Matriz.

    Returns:
        Copia contigua en orden Fortran.
    """
    arr = np.asarray(a, dtype=np.float64)
    if arr.size <= _R_SMALL_LIMIT:
        return np.array(arr, dtype=np.float64, order="F", copy=True)
    buf = np.empty(arr.size + 8, dtype=np.float64)
    start = ((_R_DATA_OFFSET - buf.ctypes.data % 64) % 64) // 8
    out = buf[start : start + arr.size].reshape(arr.shape, order="F")
    out[...] = arr
    return out


def _may_have_nan_or_inf(a: FloatArray) -> bool:
    """Prueba imprecisa de ``NaN``/``Inf`` de R antes de llamar a BLAS.

    Fuente: ``R-4.5.2/src/main/array.c:645-666`` (``mayHaveNaNOrInf``): si la longitud es impar se
    prueba ``x[0]``; después ``!R_FINITE(x[i] + x[i+1])`` por pares, en orden de columna. Da
    positivo
    también si la suma de dos finitos desborda (comportamiento de R que se replica).

    Args:
        a: Matriz en cualquier orden de memoria.

    Returns:
        ``True`` si R usaría ``simple_matprod``/``simple_crossprod``.
    """
    flat = np.asarray(a, dtype=np.float64).ravel(order="F")
    n = flat.shape[0]
    start = n & 1
    if start and not math.isfinite(float(flat[0])):
        return True
    with np.errstate(over="ignore", invalid="ignore"):
        pair_sums = flat[start::2] + flat[start + 1 :: 2]
    return bool(not np.isfinite(pair_sums).all())


def _simple_matprod(x: FloatArray, y: FloatArray) -> FloatArray:
    """Triple bucle de R con acumulación secuencial en ``double``.

    Fuente: ``R-4.5.2/src/main/array.c:719-740`` (``MATPROD_BODY``/``simple_matprod``):
    ``z[i,k] = Σ_j x[i,j] * y[j,k]`` empezando en ``0.0``, ``j`` creciente, con ``sum += x*y``
    contraído a ``fmadd`` en el ``libR.dylib`` del oráculo.

    Args:
        x: Matriz ``m x k``.
        y: Matriz ``k x n``.

    Returns:
        Matriz ``m x n``.
    """
    acc = np.zeros((x.shape[0], y.shape[1]), dtype=np.float64)
    for j in range(x.shape[1]):
        # sum += x*y: fmadd en el binario del oráculo (desensamblado de do_matprod).
        acc = fma_array(x[:, j : j + 1], y[j : j + 1, :], acc)
    return acc


def r_matprod(x: FloatArray, y: FloatArray) -> FloatArray:
    """``x %*% y`` de R para dos matrices.

    Fuente: ``R-4.5.2/src/main/array.c:788-843`` (``matprod``): dimensiones nulas ⇒ ceros; con
    ``NaN``/``Inf`` (prueba ``mayHaveNaNOrInf``) ⇒ ``simple_matprod``; si ``ncol(y) == 1`` ⇒
    ``dgemv('N')``; si ``nrow(x) == 1`` ⇒ ``dgemv('T')`` sobre ``y``; si no ⇒ ``dgemm('N','N')``.
    Especificación §3.12.6, trampa T8 (las traspuestas deben llegar materializadas).

    Args:
        x: Matriz ``m x k``.
        y: Matriz ``k x n``.

    Returns:
        Matriz ``m x n``.

    Raises:
        RError: si las dimensiones no son conformes.
    """
    a = np.asarray(x, dtype=np.float64)
    b = np.asarray(y, dtype=np.float64)
    if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[0]:
        raise RError("non-conformable arguments")
    nrx, ncx = a.shape
    nry, ncy = b.shape
    if nrx == 0 or ncx == 0 or nry == 0 or ncy == 0:
        return np.zeros((nrx, ncy), dtype=np.float64)
    if _may_have_nan_or_inf(a) or _may_have_nan_or_inf(b):
        return _simple_matprod(a, b)
    if ncy == 1:
        v = blas.dgemv(1.0, _fortran(a), _fortran(b[:, 0]))
        return np.asarray(v, dtype=np.float64).reshape(nrx, 1)
    if nrx == 1:
        v = blas.dgemv(1.0, _fortran(b), _fortran(a[0, :]), trans=1)
        return np.asarray(v, dtype=np.float64).reshape(1, ncy)
    out = blas.dgemm(1.0, _fortran(a), _fortran(b))
    return np.asarray(out, dtype=np.float64)


def r_matvec(x: FloatArray, v: FloatArray) -> FloatArray:
    """``x %*% v`` de R con ``v`` vector (se trata como columna ``k x 1``).

    Fuente: ``R-4.5.2/src/main/array.c:831-833`` (``ncy == 1`` ⇒ ``dgemv('N')``) y la promoción de
    vectores de ``do_matprod`` (``array.c``). Especificación §3.12.6.

    Args:
        x: Matriz ``m x k``.
        v: Vector de longitud ``k``.

    Returns:
        Vector de longitud ``m``.
    """
    col = np.asarray(v, dtype=np.float64).reshape(-1, 1)
    return r_matprod(x, col)[:, 0]


def r_vecmat(v: FloatArray, y: FloatArray) -> FloatArray:
    """``v %*% y`` de R con ``v`` vector (se trata como fila ``1 x k``).

    Fuente: ``R-4.5.2/src/main/array.c:834-838`` (``nrx == 1`` ⇒ ``dgemv('T')`` sobre ``y``).
    Usado en ``rrcov-1.7-7/R/detmrcd.R:73`` (``colMedians(...) %*% sqrtcov``).

    Args:
        v: Vector de longitud ``k``.
        y: Matriz ``k x n``.

    Returns:
        Vector de longitud ``n``.
    """
    row = np.asarray(v, dtype=np.float64).reshape(1, -1)
    return r_matprod(row, y)[0, :]


def r_crossprod(x: FloatArray) -> FloatArray:
    """``crossprod(x)`` de R (``t(x) %*% x``) con ``dsyrk`` y espejo.

    Fuente: ``R-4.5.2/src/main/array.c:983-1020`` (``symcrossprod``): con ``NaN``/``Inf`` ⇒
    ``simple_crossprod``; si no ⇒ ``dsyrk('U', 'T')`` y copia del triángulo superior al inferior.
    Trampa T8 (sonda S7: ``x.T @ x`` no coincide).

    Args:
        x: Matriz ``n x p``.

    Returns:
        Matriz simétrica ``p x p``.
    """
    a = np.asarray(x, dtype=np.float64)
    nr, nc = a.shape
    if nr == 0 or nc == 0:
        return np.zeros((nc, nc), dtype=np.float64)
    if _may_have_nan_or_inf(a):
        return _simple_matprod(np.array(a.T, copy=True), a)
    z = np.array(blas.dsyrk(1.0, _fortran(a), trans=1, lower=0), dtype=np.float64)
    upper = np.triu_indices(nc, 1)
    z[upper[1], upper[0]] = z[upper]
    return z


class EigenResult(NamedTuple):
    """Resultado de ``eigen(x, symmetric=TRUE)`` de R.

    Attributes:
        values: Autovalores en orden decreciente.
        vectors: Autovectores por columnas, en el mismo orden.
    """

    values: FloatArray
    vectors: FloatArray


def r_eigen_sym(x: FloatArray) -> EigenResult:
    """``eigen(x, symmetric=TRUE)`` de R (``La_rs``, ``dsyevr``), con vectores.

    Fuente: ``R-4.5.2/src/library/base/R/eigen.R:45-74`` (error si hay no finitos, ``:55``; orden
    decreciente con ``rev``, ``:62``) y ``src/modules/lapack/Lapack.c:166-237`` (``dsyevr`` con
    ``jobz='V'``, ``range='A'``, ``uplo='L'``, ``abstol=0``; ``lwork``/``liwork`` por consulta
    previa).
    Especificación §3.12.6, trampas T13 y T22. Solo lee el triángulo inferior, como R.

    Divergencia aceptada (decisión del dueño, 2026-10-06): en el oráculo, ``eigen`` llama al
    ``dsyevr`` de **Rlapack 3.12.1** (Fortran de referencia compilado con R), mientras que
    ``scipy.linalg.lapack.dsyevr`` usa el LAPACK de **Accelerate** (vecLib), con otra
    implementación de ``dsytrd``/``dstemr`` y otro bloqueo. Con la misma llamada y los mismos
    argumentos, los autovalores difieren en 1-4 ulp y los autovectores en unos ulp y, a veces,
    en el **signo** de una columna. No es bit a bit ni siquiera en la plataforma de referencia:
    rigen las tolerancias clase B de la especificación §11 (autovalores ``atol = 10·p·eps·λmax``;
    autovectores módulo signo en autoespacios con gap relativo > 1e-8). Consecuencias aguas abajo
    (``initset`` vía Qn, trampa T3; ``e1``/``ep`` de la selección de ``rho``) se documentan en los
    tests de extremo a extremo.

    Args:
        x: Matriz cuadrada ``p x p``.

    Returns:
        ``EigenResult`` con valores decrecientes y vectores en columnas.

    Raises:
        RError: matriz no cuadrada, vacía, con no finitos o error de LAPACK.
    """
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise RError("non-square matrix in 'eigen'")
    n = a.shape[0]
    if n == 0:
        raise RError("0 x 0 matrix")
    if not np.isfinite(a).all():
        raise RError("infinite or missing values in 'x'")
    work, iwork, info = lapack.dsyevr_lwork(n, lower=1)
    if info != 0:
        raise RError(f"error code {info} from Lapack routine 'dsyevr'")
    w, z, _m, _isuppz, info = lapack.dsyevr(
        _fortran(a),
        compute_v=1,
        range="A",
        lower=1,
        abstol=0.0,
        lwork=int(work),
        liwork=int(iwork),
    )
    if info != 0:
        raise RError(f"error code {info} from Lapack routine 'dsyevr'")
    values = np.asarray(w, dtype=np.float64)[::-1].copy()
    vectors = np.asarray(z, dtype=np.float64)[:, ::-1].copy()
    return EigenResult(values=values, vectors=vectors)


def _all_equal_numeric(target: FloatArray, current: FloatArray, tolerance: float) -> bool:
    """``isTRUE(all.equal.numeric(target, current, tolerance))`` para vectores finitos.

    Fuente: ``R-4.5.2/src/library/base/R/all.equal.R:99-174``: se descartan las posiciones con
    ``target == current`` (``:134-145``); ``scale = sum(abs(target)/N)`` (``:149``, ``sum`` de R
    secuencial con ``LDOUBLE = double``); si ``scale`` es finita y ``> tolerance`` la diferencia es
    relativa, si no absoluta (``:150-155``); ``xy = sum(abs(target - current)/(N*scale))``
    (``:161``); ``TRUE`` si ``xy <= tolerance`` (``:164-165``).

    Args:
        target: Vector.
        current: Vector de la misma longitud.
        tolerance: Tolerancia.

    Returns:
        ``True`` si R los considera iguales.
    """
    t = np.asarray(target, dtype=np.float64).ravel()
    c = np.asarray(current, dtype=np.float64).ravel()
    out = (t == c) | (np.isnan(t) & np.isnan(c))
    if bool(out.all()):
        return True
    keep = ~out
    tk = t[keep]
    ck = c[keep]
    n_keep = float(tk.shape[0])
    scale = seqsum(np.abs(tk) / n_keep)
    if not (math.isfinite(scale) and scale > tolerance):
        scale = 1.0
    xy = seqsum(np.abs(tk - ck) / (n_keep * scale))
    return not (math.isnan(xy) or xy > tolerance)


def r_is_symmetric(x: FloatArray) -> bool:
    """``isSymmetric.matrix(x)`` de R para una matriz real.

    Fuente: ``R-4.5.2/src/library/base/R/eigen.R:22-43``: ``tol = 100*eps``, ``tol1 = 8*tol``;
    pre-pruebas con las filas/columnas ``unique(c(1, 2, n-1, n))`` (``:31-35``) y después
    ``all.equal(x, t(x), tolerance = tol)`` en orden de columna (``:37-41``).

    Args:
        x: Matriz.

    Returns:
        ``True`` si R la trata como simétrica.
    """
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        return False
    n = a.shape[0]
    eps = float(np.finfo(np.float64).eps)
    tol = 100 * eps
    tol1 = 8 * tol
    if n > 1:
        for i in dict.fromkeys((1, 2, n - 1, n)):
            if not _all_equal_numeric(a[i - 1, :], a[:, i - 1], tol1):
                return False
    return _all_equal_numeric(a.ravel(order="F"), a.T.ravel(order="F"), tol)


def r_eigen_values(x: FloatArray) -> FloatArray:
    """``eigen(x)$values`` de R **sin** ``symmetric=`` (rama automática, trampa T13).

    Fuente: ``R-4.5.2/src/library/base/R/eigen.R:45-74``: ``symmetric = isSymmetric.matrix(x)``
    (``:57``); si es simétrica, ``La_rs`` con vectores (``only.values = FALSE``; ``dsyevr`` con
    ``jobz='V'``, ``Lapack.c:166-237``) y orden decreciente (``:60-62``); si no, ``La_rg``
    (``dgeev`` con ``jobVR='V'``, ``Lapack.c:263-336``) y orden por ``Mod`` decreciente
    (``:63-66``). Si ``La_rg`` devuelve valores complejos (``|wI| > 10·eps·|wR|``,
    ``Lapack.c:309-315``), ``rrcov`` fallaría después en ``min()`` (``detmrcd.R:474``): se lanza
    el error equivalente. Usado en ``rrcov-1.7-7/R/detmrcd.R:473``. Hereda la divergencia de
    LAPACK documentada en ``r_eigen_sym`` (clase B).

    **D9 se extiende a ``dgeev``** (especificación §11, decisión D9 de 2026-10-06): la rama
    ``La_rg`` usa el ``dgeev`` de Accelerate (``scipy.linalg.lapack``), no el de Rlapack 3.12.1, y
    sus autovalores se aceptan con la misma tolerancia B que ``dsyevr``. La rama es casi
    inalcanzable en ``.detmrcd``: requiere que ``scfac * mS`` (producto ``dgemm`` de ``mE`` por su
    traspuesta) **falle** ``isSymmetric`` (tolerancia ``100·eps``), cosa que no ocurre en ningún
    caso golden (trampa T13).

    Args:
        x: Matriz cuadrada.

    Returns:
        Autovalores reales en el orden de R.

    Raises:
        RError: si ``eigen`` falla o los autovalores son complejos.
    """
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise RError("non-square matrix in 'eigen'")
    if a.shape[0] == 0:
        raise RError("0 x 0 matrix")
    if not np.isfinite(a).all():
        raise RError("infinite or missing values in 'x'")
    if r_is_symmetric(a):
        return r_eigen_sym(a).values
    wr, wi, _vl, _vr, info = lapack.dgeev(_fortran(a), compute_vl=0, compute_vr=1)
    if info != 0:
        raise RError(f"error code {info} from Lapack routine 'dgeev'")
    w_r = np.asarray(wr, dtype=np.float64)
    w_i = np.asarray(wi, dtype=np.float64)
    eps = float(np.finfo(np.float64).eps)
    if bool((np.abs(w_i) > 10 * eps * np.abs(w_r)).any()):
        raise RError("invalid 'type' (complex) of argument")
    # sort.list(Mod(values), decreasing=TRUE): radix estable sobre -|w|.
    return np.asarray(w_r[r_order(-np.abs(w_r))], dtype=np.float64)


def r_chol(x: FloatArray) -> FloatArray:
    """``chol(x)`` de R (sin pivoteo): factor triangular superior ``R`` con ``t(R) %*% R = x``.

    Fuente: ``R-4.5.2/src/library/base/R/chol.R:21-29`` → ``src/modules/lapack/Lapack.c:1077-1104``
    (``La_chol``: pone a cero el triángulo inferior y llama a ``dpotrf('U')``; ``info > 0`` ⇒
    error).

    Args:
        x: Matriz simétrica definida positiva ``p x p`` (solo se lee el triángulo superior).

    Returns:
        Factor de Cholesky triangular superior.

    Raises:
        RError: si la matriz no es cuadrada o no es definida positiva.
    """
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise RError("'a' must be a square matrix")
    if a.shape[0] == 0:
        raise RError("'a' must have dims > 0")
    ans = _fortran(np.triu(a))
    info = dpotrf_upper(ans)
    if info != 0:
        raise RError(f"the leading minor of order {info} is not positive")
    return np.array(ans, dtype=np.float64)


def r_chol2inv(x: FloatArray) -> FloatArray:
    """``chol2inv(x)`` de R: inversa de ``t(x) %*% x`` a partir del factor de Cholesky.

    Fuente: ``R-4.5.2/src/library/base/R/chol.R:31-36`` → ``src/modules/lapack/Lapack.c:1139-1182``
    (``La_chol2inv``: copia el triángulo superior, ``dpotri('U')`` y espejo superior → inferior).

    Args:
        x: Factor triangular superior ``p x p``.

    Returns:
        Matriz simétrica ``p x p``.

    Raises:
        RError: si algún elemento diagonal es cero.
    """
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2 or a.shape[0] != a.shape[1] or a.shape[0] == 0:
        raise RError("'a' must be a numeric matrix")
    sz = a.shape[0]
    inv = _fortran(np.triu(a))
    info = dpotri_upper(inv)
    if info != 0:
        raise RError(f"element ({info}, {info}) is zero, so the inverse cannot be computed")
    out = np.array(inv, dtype=np.float64)
    upper = np.triu_indices(sz, 1)
    out[upper[1], upper[0]] = out[upper]
    return out


def r_determinant(x: FloatArray) -> tuple[float, int]:
    """``determinant(x, logarithm=TRUE)`` de R: ``(modulus, sign)``.

    Fuente: ``R-4.5.2/src/library/base/R/det.R:33-46`` → ``src/modules/lapack/Lapack.c:1403-1458``
    (``det_ge_real``): ``dgetrf``; ``info > 0`` ⇒ ``modulus = -Inf``; si no, signo por pivotes y
    ``modulus += log(|U_ii|)`` secuencial (``log`` de libm).

    Args:
        x: Matriz cuadrada.

    Returns:
        Tupla ``(modulus, sign)``.

    Raises:
        RError: si la matriz no es cuadrada.
    """
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise RError("'x' must be a square matrix")
    n = a.shape[0]
    if n < 1:
        return 0.0, 1
    lu = _fortran(a)
    piv, info = dgetrf(lu)
    if info > 0:
        return -math.inf, 1
    sign = 1
    for i, pv in enumerate(np.asarray(piv).tolist()):
        if pv != i + 1:  # pivotes en base 1, como jpvt en Lapack.c:1431
            sign = -sign
    modulus = 0.0
    for i in range(n):
        dii = float(lu[i, i])
        modulus += math.log(-dii if dii < 0 else dii)
        if dii < 0:
            sign = -sign
    return modulus, sign


def r_det(x: FloatArray) -> float:
    """``det(x)`` de R: ``sign * exp(modulus)`` de ``determinant``.

    Fuente: ``R-4.5.2/src/library/base/R/det.R:25-29``. Trampa T19: no sustituir por el logaritmo.

    Args:
        x: Matriz cuadrada.

    Returns:
        El determinante tal como lo calcula R (puede subdesbordar a ``0``).
    """
    modulus, sign = r_determinant(x)
    try:
        expo = math.exp(modulus)
    except OverflowError:
        expo = math.inf  # exp() de C desborda a +Inf; math.exp lanza OverflowError
    return sign * expo


def r_mahalanobis_inverted(x: FloatArray, center: FloatArray, icov: FloatArray) -> FloatArray:
    """``mahalanobis(x, center, icov, inverted=TRUE)`` de R.

    Fuente: ``R-4.5.2/src/library/stats/R/mahalanobis.R:31-47``: ``x <- sweep(x, 2, center)``
    (resta por columnas) y ``rowSums(x %*% cov * x)`` (``%*%`` vía BLAS, producto elemento a
    elemento
    y ``rowSums`` secuencial). Usado en ``rrcov-1.7-7/R/CovMrcd.R:46`` (especificación §3.11).

    Args:
        x: Matriz ``n x p``.
        center: Vector de longitud ``p``.
        icov: Inversa de la covarianza ``p x p``.

    Returns:
        Vector de ``n`` distancias al cuadrado.
    """
    xc = np.asarray(x, dtype=np.float64) - np.asarray(center, dtype=np.float64)[None, :]
    return r_rowsums(r_matprod(xc, icov) * xc)


def r_mahalanobis_d(x: FloatArray, sd: FloatArray) -> FloatArray:
    """``robustbase:::mahalanobisD(x, FALSE, sd)``: distancias con covarianza diagonal.

    Fuente: ``robustbase-0.99-6/R/OGK.R:48-53``: ``rowSums(sweep(x, 2, sd, "/")^2)`` (``^2`` es
    ``x*x`` por ``R_POW``, ``arithmetic.h:35``; ``rowSums`` secuencial). Usado en
    ``rrcov-1.7-7/R/detmrcd.R:75`` (especificación §3.5.1).

    Args:
        x: Matriz ``n x p``.
        sd: Vector de longitud ``p``.

    Returns:
        Vector de ``n`` distancias al cuadrado.
    """
    z = np.asarray(x, dtype=np.float64) / np.asarray(sd, dtype=np.float64)[None, :]
    return r_rowsums(z * z)


def r_scale(x: FloatArray, center: FloatArray, scale: FloatArray) -> FloatArray:
    """``scale(x, center=, scale=)`` de R con vectores dados: dos ``sweep`` (resta y división).

    Fuente: ``R-4.5.2/src/library/base/R/scale.R:21-58`` (``sweep(x, 2, center)`` y después
    ``sweep(x, 2, scale, "/")``; dos redondeos). Usado en ``rrcov-1.7-7/R/detmrcd.R:421``.

    Args:
        x: Matriz ``n x p``.
        center: Vector de longitud ``p``.
        scale: Vector de longitud ``p``.

    Returns:
        Matriz ``n x p``.
    """
    xc = np.asarray(x, dtype=np.float64) - np.asarray(center, dtype=np.float64)[None, :]
    return np.asarray(xc / np.asarray(scale, dtype=np.float64)[None, :], dtype=np.float64)
