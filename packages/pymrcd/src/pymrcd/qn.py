"""Estimador de escala ``Qn`` de Rousseeuw y Croux, fiel a ``robustbase`` 0.99-6.

Port de ``robustbase::Qn`` (``R/qnsn.R:20-68``). El núcleo ``qn0`` (``src/qn_sn.c:118-296``) con
``whimed_i`` (``src/wgt_himed_templ.h:27-122``), ``R_qsort`` (``R-4.5.2/src/main/qsort-body.c``)
y ``rPsort`` (``R-4.5.2/src/main/sort.c:668-727``) es un port **literal en C** en la extensión
``pymrcd._qn_ext`` (especificación §3.12.9, M5): reproduce el valor **y el signo de los ceros** de
R, incluido el redondeo a ``float`` de ``qn_sn.c:195``, ``:215`` y ``:224`` (trampa T1). Las
columnas se reparten entre hilos POSIX; el resultado no depende del número de hilos.

No hay respaldo en Python (decisión P1 del dueño): si la extensión no está compilada, importar
``pymrcd`` falla con un ``ImportError`` que explica cómo compilarla (``pymrcd._cext``).
"""

from __future__ import annotations

import math

import numpy as np

from pymrcd._cext import qn_ext
from pymrcd._types import FloatArray

__all__ = [
    "QN_CONSTANT",
    "QN_SMALL_N_FACTORS",
    "default_k",
    "qn",
    "qn0_columns",
    "qn_columns",
    "qn_finite_c",
    "threads_arg",
]

QN_CONSTANT = 2.21914
"""Constante por defecto de ``Qn`` (``robustbase-0.99-6/R/qnsn.R:44``)."""

QN_SMALL_N_FACTORS = (
    0.399356,
    0.99365,
    0.51321,
    0.84401,
    0.61220,
    0.85877,
    0.66993,
    0.87344,
    0.72014,
    0.88906,
    0.75743,
)
"""Corrección de muestra finita para ``n = 2..12`` (``robustbase-0.99-6/R/qnsn.R:58-63``)."""


def qn_finite_c(n: int) -> float:
    """Factor de corrección de muestra finita de ``Qn`` para ``n > 12``.

    Fuente: ``robustbase-0.99-6/R/qnsn.R:13-16`` (la segunda definición sobrescribe a la de
    ``:8-11``): impar ``(1.60188 + (-2.1284 - 5.172/n)/n)/n + 1``; par
    ``(3.67561 + (1.9654 + (6.987 - 77/n)/n)/n)/n + 1``.

    Args:
        n: Tamaño de muestra.

    Returns:
        El factor ``Qn.finite.c(n)``.
    """
    if n % 2:
        return (1.60188 + (-2.1284 - 5.172 / n) / n) / n + 1
    return (3.67561 + (1.9654 + (6.987 - 77 / n) / n) / n) / n + 1


def default_k(n: int) -> int:
    """``k`` por defecto de ``Qn``: ``choose(n %/% 2 + 1, 2)``.

    Fuente: ``robustbase-0.99-6/R/qnsn.R:21``; ``Qn0`` lo convierte a ``int64_t``
    (``src/qn_sn.c:101-102``). ``choose`` con ``k = 2`` es exacto (``R-4.5.2/src/nmath/choose.c``,
    especificación §3.12.9 a).

    Args:
        n: Tamaño de muestra.

    Returns:
        El entero ``k``.
    """
    return math.comb(n // 2 + 1, 2)


def threads_arg(n_threads: int | None) -> int:
    """Traduce ``n_threads`` al argumento de la extensión C.

    ``None`` ⇒ ``0`` (la extensión usa ``PYMRCD_NUM_THREADS`` o los CPU visibles por afinidad;
    especificación §3.12.9 e). Parámetro de **rendimiento**: no cambia ningún bit del resultado.

    Args:
        n_threads: Número de hilos (``>= 1``) o ``None``.

    Returns:
        ``0`` o ``n_threads``.

    Raises:
        ValueError: si ``n_threads < 1``.
    """
    if n_threads is None:
        return 0
    if int(n_threads) < 1:
        raise ValueError("n_threads debe ser >= 1 (o None para el valor por defecto)")
    return int(n_threads)


def qn0_columns(x: FloatArray, k: int | None = None, n_threads: int | None = None) -> FloatArray:
    """``qn0`` (sin constante) por columnas, en la extensión C.

    Fuente: ``robustbase-0.99-6/src/qn_sn.c:118-296`` con ``len_k = 1`` (especificación §3.12.9).
    La copia ``x → y`` (``:156-157``) se hace en C leyendo por *strides* y comprobando
    ``NaN``/``Inf`` en la misma pasada (ahorros A3, A4): columna con ``NaN`` ⇒ ``NaN``
    (``qnsn.R:27``).

    Args:
        x: Matriz ``n x m`` con ``n >= 2``.
        k: Estadístico de orden (``1 <= k <= choose(n, 2)``, ``qnsn.R:35``); ``None`` ⇒ el de por
            defecto (``default_k``).
        n_threads: Hilos (rendimiento); ``None`` ⇒ por defecto.

    Returns:
        Vector ``m``.

    Raises:
        ValueError: si ``x`` no es una matriz con ``n >= 2``, si ``k`` está fuera de rango o si
            alguna columna sin ``NaN`` contiene ``±Inf``.
    """
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("x debe ser una matriz n x m")
    n, m = arr.shape
    if n < 2:
        raise ValueError("qn0 requiere n >= 2 (qnsn.R:29)")
    kk = default_k(n) if k is None else int(k)
    if not 1 <= kk <= n * (n - 1) // 2:
        raise ValueError("k debe cumplir 1 <= k <= choose(n, 2) (qnsn.R:35)")
    out = np.empty(m, dtype=np.float64)
    qn_ext.qn0_columns(arr, out, kk, threads_arg(n_threads))
    return out


def qn_columns(x: FloatArray, n_threads: int | None = None) -> FloatArray:
    """``apply(x, 2, Qn)`` con los valores por defecto de ``robustbase::Qn``.

    Fuente: ``robustbase-0.99-6/R/qnsn.R:20-68``: ``NA`` en la columna ⇒ ``NA`` (``:27``);
    ``n == 0`` ⇒ ``NA``, ``n == 1`` ⇒ ``0`` (``:29``); ``r = 2.21914 * qn0`` (``:44``, ``:48-49``);
    ``n <= 12`` ⇒ ``r * c(.399356, …)[n - 1]`` (``:56-63``); si no, ``r / Qn.finite.c(n)``
    (``:65``). Especificación §3.12.1 y §3.12.9.

    Args:
        x: Matriz ``n x m``.
        n_threads: Hilos de la extensión C (rendimiento); ``None`` ⇒ por defecto.

    Returns:
        Vector ``m`` con ``Qn`` de cada columna.

    Raises:
        ValueError: si alguna columna sin ``NaN`` contiene ``±Inf`` (fuera del camino de
            ``CovMrcd``, que filtra filas no finitas en ``CovMrcd.R:19-20``; ver desviaciones del
            port).
    """
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("x debe ser una matriz n x m")
    n, m = arr.shape
    if n == 0:
        return np.full(m, np.nan)
    if n == 1:
        out1 = np.zeros(m, dtype=np.float64)
        out1[np.isnan(arr[0, :])] = np.nan
        return out1
    r = QN_CONSTANT * qn0_columns(arr, n_threads=n_threads)
    if n <= 12:
        return r * QN_SMALL_N_FACTORS[n - 2]
    return r / qn_finite_c(n)


def qn(x: FloatArray, n_threads: int | None = None) -> float:
    """``robustbase::Qn(x)`` con los valores por defecto.

    Fuente: ``robustbase-0.99-6/R/qnsn.R:20-68`` (ver ``qn_columns``).

    Args:
        x: Vector.
        n_threads: Hilos (rendimiento; con un vector se usa uno).

    Returns:
        ``Qn(x)``.
    """
    arr = np.asarray(x, dtype=np.float64).ravel()
    return float(qn_columns(arr[:, None], n_threads=n_threads)[0])
