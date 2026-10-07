"""BLAS de ``scipy`` llamado **en sitio** sobre submatrices, con la ``lda`` de la matriz completa.

El LAPACK de referencia de R (``libRlapack``) llama a BLAS con punteros a submatrices dentro del
mismo búfer y la dimensión principal (``lda``) de la matriz completa. El BLAS de Accelerate da bits
distintos según la alineación del operando y su ``lda`` (especificación §3.12.6, trampas T27-T28;
medido: ``dgetrf`` de una matriz 200x200 difiere de R en 13 pivotes si los bloques se copian a
matrices contiguas). Los envoltorios de ``scipy.linalg.blas`` copian cualquier vista no contigua,
así que aquí se usan las funciones de bajo nivel que ``scipy`` publica en
``scipy.linalg.cython_blas.__pyx_capi__`` (mismas rutinas Fortran, interfaz con punteros) y se
llaman con ``ctypes`` (biblioteca estándar) pasando punteros al búfer original.

Todas las matrices son ``float64`` en orden Fortran; ``(r, c)`` son desplazamientos en base 0 y
``lda`` es ``a.shape[0]``.

Salvaguardas (``ctypes`` no comprueba tipos ni límites): al importar se verifica que la firma C de
cada cápsula sea la LP64 esperada (``int *`` de 32 bits; si no, ``ImportError``), y antes de cada
llamada se comprueba que los bloques y vectores indicados por ``(r, c)``, las dimensiones y ``lda``
caben en el array (si no, ``ValueError``).
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from typing import Any

import numpy as np
from scipy.linalg import cython_blas

from pymrcd._types import FloatArray

__all__ = ["ddot", "dgemm", "dgemv", "dscal", "dsyrk", "dtrmm", "dtrmv", "dtrsm", "idamax"]

_P = ctypes.c_void_p
_C = ctypes.c_char_p

_PyCapsule_GetName = ctypes.pythonapi.PyCapsule_GetName
_PyCapsule_GetName.restype = ctypes.c_char_p
_PyCapsule_GetName.argtypes = [ctypes.py_object]
_PyCapsule_GetPointer = ctypes.pythonapi.PyCapsule_GetPointer
_PyCapsule_GetPointer.restype = ctypes.c_void_p
_PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]


_D = "__pyx_t_5scipy_6linalg_11cython_blas_d"
"""Nombre C del ``ctypedef double d`` de ``scipy/linalg/cython_blas.pxd`` en las firmas."""

_KINDS = {"c": "char *", "i": "int *", "d": f"{_D} *"}
_RETURNS = {"v": "void", "d": _D, "i": "int"}

# Firma LP64 esperada (convención Fortran, todo por referencia; enteros de 32 bits). Clave: retorno
# y tipos de los argumentos (``c`` = ``char *``, ``i`` = ``int *``, ``d`` = ``double *``).
_SIGNATURES = {
    "dgemm": ("v", "cciiiddididdi"),
    "dtrsm": ("v", "cccciiddidi"),
    "dsyrk": ("v", "cciiddiddi"),
    "dtrmm": ("v", "cccciiddidi"),
    "dtrmv": ("v", "cccididi"),
    "dgemv": ("v", "ciiddididdi"),
    "ddot": ("d", "ididi"),
    "dscal": ("v", "iddi"),
    "idamax": ("i", "idi"),
}


def expected_signature(name: str) -> bytes:
    """Firma C que ``scipy.linalg.cython_blas`` debe declarar para ``name`` en LP64.

    Fuente: ``scipy/linalg/cython_blas.pxd`` (``ctypedef double d``; enteros ``int``): la cápsula
    de ``__pyx_capi__`` lleva como nombre la firma C de la función.

    Args:
        name: Rutina BLAS.

    Returns:
        La firma esperada en bytes (``"void (char *, int *, …)"``).
    """
    ret, args = _SIGNATURES[name]
    return f"{_RETURNS[ret]} ({', '.join(_KINDS[k] for k in args)})".encode("ascii")


def _routine(
    name: str, restype: type[ctypes.c_double] | type[ctypes.c_int] | None, nargs: int
) -> Callable[..., Any]:
    """Función ``ctypes`` para la rutina ``name`` de ``scipy.linalg.cython_blas``.

    Antes de tomar el puntero verifica que el nombre de la cápsula (la firma C que publica
    ``scipy``) sea exactamente la LP64 esperada (``int *`` de 32 bits, ``double *``): si ``scipy``
    cambiara a ILP64 u otra firma, llamar con ``ctypes`` corrompería memoria en silencio.

    Args:
        name: Nombre BLAS (``dgemm``…).
        restype: Tipo de retorno ``ctypes`` (``None`` para ``void``).
        nargs: Número de argumentos (todos por referencia, convención Fortran).

    Returns:
        Función invocable con punteros.

    Raises:
        ImportError: si la cápsula no existe o su firma no es la LP64 esperada.
    """
    capsule = cython_blas.__pyx_capi__.get(name)
    if capsule is None:
        raise ImportError(f"pymrcd: scipy.linalg.cython_blas no publica '{name}'")
    signature = _PyCapsule_GetName(capsule)
    expected = expected_signature(name)
    if (
        signature != expected
        or len(_SIGNATURES[name][1]) != nargs
        or ctypes.sizeof(ctypes.c_int) != 4
    ):
        raise ImportError(
            f"pymrcd: firma inesperada de cython_blas.{name}: {signature!r}; se esperaba la LP64 "
            f"{expected!r}. pymrcd está validado con scipy>=1.18.1,<1.19 (ver pyproject.toml)."
        )
    address = _PyCapsule_GetPointer(capsule, signature)
    proto = ctypes.CFUNCTYPE(restype, *([_P] * nargs))
    fn: Callable[..., Any] = proto(address)
    return fn


_DGEMM = _routine("dgemm", None, 13)
_DTRSM = _routine("dtrsm", None, 11)
_DSYRK = _routine("dsyrk", None, 10)
_DTRMM = _routine("dtrmm", None, 11)
_DTRMV = _routine("dtrmv", None, 8)
_DGEMV = _routine("dgemv", None, 11)
_DDOT = _routine("ddot", ctypes.c_double, 5)
_DSCAL = _routine("dscal", None, 4)
_IDAMAX = _routine("idamax", ctypes.c_int, 3)


class _Args:
    """Mantiene vivos los escalares ``ctypes`` pasados por referencia."""

    def __init__(self) -> None:
        self.keep: list[Any] = []

    def ch(self, value: str) -> ctypes.c_void_p:
        buf = ctypes.create_string_buffer(value.encode("ascii"))
        self.keep.append(buf)
        return ctypes.cast(buf, _P)

    def i(self, value: int) -> ctypes.c_void_p:
        v = ctypes.c_int(value)
        self.keep.append(v)
        return ctypes.cast(ctypes.pointer(v), _P)

    def d(self, value: float) -> ctypes.c_void_p:
        v = ctypes.c_double(value)
        self.keep.append(v)
        return ctypes.cast(ctypes.pointer(v), _P)


def _check(a: FloatArray) -> None:
    """Exige ``float64`` contiguo en orden Fortran (los punteros se calculan con ``lda``)."""
    if a.dtype != np.float64 or not a.flags.f_contiguous or a.ndim != 2:
        raise ValueError("se requiere una matriz float64 contigua en orden Fortran")


def _block(a: FloatArray, r: int, c: int, rows: int, cols: int, what: str) -> None:
    """Comprueba que el bloque ``rows x cols`` en ``(r, c)`` cabe en ``a`` (``lda = a.shape[0]``).

    Raises:
        ValueError: si el bloque se sale de la matriz o las dimensiones son negativas.
    """
    _check(a)
    lda, ncol = a.shape
    if min(r, c, rows, cols) < 0 or r + rows > lda or c + cols > ncol or lda < max(1, rows):
        raise ValueError(
            f"{what}: bloque {rows}x{cols} en ({r}, {c}) fuera de la matriz {lda}x{ncol}"
        )


def _vector(x: FloatArray, r: int, c: int, n: int, inc: int, what: str) -> None:
    """Comprueba que el vector de ``n`` elementos con paso ``inc`` desde ``x(r, c)`` cabe en ``x``.

    Raises:
        ValueError: si se sale del búfer, ``n < 0`` o ``inc <= 0``.
    """
    _check(x)
    bad = n < 0 or inc <= 0 or r < 0 or c < 0
    if not bad and n > 0:
        bad = r >= x.shape[0] or r + c * x.shape[0] + (n - 1) * inc >= x.size
    if bad:
        raise ValueError(f"{what}: vector n={n}, inc={inc} en ({r}, {c}) fuera de {x.shape}")


def _ptr(a: FloatArray, r: int, c: int) -> ctypes.c_void_p:
    """Puntero a ``a[r, c]`` (orden Fortran)."""
    return ctypes.c_void_p(a.ctypes.data + 8 * (r + c * a.shape[0]))


def dgemm(
    transa: str,
    transb: str,
    m: int,
    n: int,
    k: int,
    alpha: float,
    a: FloatArray,
    ar: int,
    ac: int,
    b: FloatArray,
    br: int,
    bc: int,
    beta: float,
    c: FloatArray,
    cr: int,
    cc: int,
) -> None:
    """``DGEMM`` en sitio sobre ``C(cr, cc)``."""
    ta, tb = transa.upper() == "N", transb.upper() == "N"
    _block(a, ar, ac, m if ta else k, k if ta else m, "dgemm A")
    _block(b, br, bc, k if tb else n, n if tb else k, "dgemm B")
    _block(c, cr, cc, m, n, "dgemm C")
    g = _Args()
    _DGEMM(
        g.ch(transa), g.ch(transb), g.i(m), g.i(n), g.i(k), g.d(alpha),
        _ptr(a, ar, ac), g.i(a.shape[0]), _ptr(b, br, bc), g.i(b.shape[0]),
        g.d(beta), _ptr(c, cr, cc), g.i(c.shape[0]),
    )  # fmt: skip


def dtrsm(
    side: str,
    uplo: str,
    transa: str,
    diag: str,
    m: int,
    n: int,
    alpha: float,
    a: FloatArray,
    ar: int,
    ac: int,
    b: FloatArray,
    br: int,
    bc: int,
) -> None:
    """``DTRSM`` en sitio sobre ``B(br, bc)``."""
    na = m if side.upper() == "L" else n
    _block(a, ar, ac, na, na, "dtrsm A")
    _block(b, br, bc, m, n, "dtrsm B")
    g = _Args()
    _DTRSM(
        g.ch(side), g.ch(uplo), g.ch(transa), g.ch(diag), g.i(m), g.i(n), g.d(alpha),
        _ptr(a, ar, ac), g.i(a.shape[0]), _ptr(b, br, bc), g.i(b.shape[0]),
    )  # fmt: skip


def dtrmm(
    side: str,
    uplo: str,
    transa: str,
    diag: str,
    m: int,
    n: int,
    alpha: float,
    a: FloatArray,
    ar: int,
    ac: int,
    b: FloatArray,
    br: int,
    bc: int,
) -> None:
    """``DTRMM`` en sitio sobre ``B(br, bc)``."""
    na = m if side.upper() == "L" else n
    _block(a, ar, ac, na, na, "dtrmm A")
    _block(b, br, bc, m, n, "dtrmm B")
    g = _Args()
    _DTRMM(
        g.ch(side), g.ch(uplo), g.ch(transa), g.ch(diag), g.i(m), g.i(n), g.d(alpha),
        _ptr(a, ar, ac), g.i(a.shape[0]), _ptr(b, br, bc), g.i(b.shape[0]),
    )  # fmt: skip


def dsyrk(
    uplo: str,
    trans: str,
    n: int,
    k: int,
    alpha: float,
    a: FloatArray,
    ar: int,
    ac: int,
    beta: float,
    c: FloatArray,
    cr: int,
    cc: int,
) -> None:
    """``DSYRK`` en sitio sobre ``C(cr, cc)``."""
    tn = trans.upper() == "N"
    _block(a, ar, ac, n if tn else k, k if tn else n, "dsyrk A")
    _block(c, cr, cc, n, n, "dsyrk C")
    g = _Args()
    _DSYRK(
        g.ch(uplo), g.ch(trans), g.i(n), g.i(k), g.d(alpha), _ptr(a, ar, ac), g.i(a.shape[0]),
        g.d(beta), _ptr(c, cr, cc), g.i(c.shape[0]),
    )  # fmt: skip


def dtrmv(
    uplo: str,
    trans: str,
    diag: str,
    n: int,
    a: FloatArray,
    ar: int,
    ac: int,
    x: FloatArray,
    xr: int,
    xc: int,
    incx: int,
) -> None:
    """``DTRMV`` en sitio sobre el vector que empieza en ``X(xr, xc)`` con paso ``incx``."""
    _block(a, ar, ac, n, n, "dtrmv A")
    _vector(x, xr, xc, n, incx, "dtrmv x")
    g = _Args()
    _DTRMV(
        g.ch(uplo), g.ch(trans), g.ch(diag), g.i(n), _ptr(a, ar, ac), g.i(a.shape[0]),
        _ptr(x, xr, xc), g.i(incx),
    )  # fmt: skip


def dgemv(
    trans: str,
    m: int,
    n: int,
    alpha: float,
    a: FloatArray,
    ar: int,
    ac: int,
    x: FloatArray,
    xr: int,
    xc: int,
    incx: int,
    beta: float,
    y: FloatArray,
    yr: int,
    yc: int,
    incy: int,
) -> None:
    """``DGEMV`` en sitio sobre el vector ``Y(yr, yc)`` con paso ``incy``."""
    tn = trans.upper() == "N"
    _block(a, ar, ac, m, n, "dgemv A")
    _vector(x, xr, xc, n if tn else m, incx, "dgemv x")
    _vector(y, yr, yc, m if tn else n, incy, "dgemv y")
    g = _Args()
    _DGEMV(
        g.ch(trans), g.i(m), g.i(n), g.d(alpha), _ptr(a, ar, ac), g.i(a.shape[0]),
        _ptr(x, xr, xc), g.i(incx), g.d(beta), _ptr(y, yr, yc), g.i(incy),
    )  # fmt: skip


def ddot(
    n: int, x: FloatArray, xr: int, xc: int, incx: int, y: FloatArray, yr: int, yc: int, incy: int
) -> float:
    """``DDOT`` de dos vectores con paso dentro de matrices."""
    _vector(x, xr, xc, n, incx, "ddot x")
    _vector(y, yr, yc, n, incy, "ddot y")
    g = _Args()
    return float(_DDOT(g.i(n), _ptr(x, xr, xc), g.i(incx), _ptr(y, yr, yc), g.i(incy)))


def dscal(n: int, alpha: float, x: FloatArray, xr: int, xc: int, incx: int) -> None:
    """``DSCAL`` en sitio."""
    _vector(x, xr, xc, n, incx, "dscal x")
    g = _Args()
    _DSCAL(g.i(n), g.d(alpha), _ptr(x, xr, xc), g.i(incx))


def idamax(n: int, x: FloatArray, xr: int, xc: int, incx: int) -> int:
    """``IDAMAX`` (base 1, como Fortran)."""
    _vector(x, xr, xc, n, incx, "idamax x")
    g = _Args()
    return int(_IDAMAX(g.i(n), _ptr(x, xr, xc), g.i(incx)))
