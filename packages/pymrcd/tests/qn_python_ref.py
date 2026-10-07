"""Oráculo de test: la implementación numpy vectorizada de ``qn0`` anterior a la extensión C (M5).

Es el ``packages/pymrcd/src/pymrcd/qn.py`` del commit ``54ede77`` (funciones ``_f32``,
``_count_prefix``, ``_whimed_columns``, ``_kth_exact``, ``_qn0_chunk`` y ``qn0_columns``),
trasladado aquí sin cambios de lógica (decisión del dueño, 2026-10-07): **no** forma parte de
``pymrcd``. Coincide con R en el valor de ``qn0`` pero no siempre en el signo de un cero
(especificación §3.12.9 c; ``np.sort(axis=0)`` coloca los ``±0`` de forma no determinista), así que
las comparaciones con la extensión C excluyen ``a == 0 and b == 0`` con signo distinto (P5: manda
R).

Incluye ``ogk_u_ref``, la ``U`` de OGK anterior (``pymrcd/ogk.py`` del mismo commit), por lotes.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from pymrcd.qn import QN_CONSTANT, QN_SMALL_N_FACTORS, qn_finite_c

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

_CHUNK_ELEMENTS = 1 << 22
"""Tamaño máximo (``n x columnas``) de cada lote, para acotar la memoria."""

_PAIR_CHUNK_ELEMENTS = 1 << 22
"""Elementos (``n x columnas``) por lote de pares, para acotar la memoria."""


def _f32(a: FloatArray) -> FloatArray:
    """Redondeo ``(float)`` de C elemento a elemento, devuelto como ``float64``.

    Fuente: ``robustbase-0.99-6/src/qn_sn.c:195``, ``:215``, ``:224``.

    Args:
        a: Arreglo ``float64``.

    Returns:
        Arreglo ``float64`` con valores representables en ``float32``.
    """
    with np.errstate(over="ignore"):
        return a.astype(np.float32).astype(np.float64)


def _count_prefix(
    y: FloatArray,
    rows: IntArray,
    trial: FloatArray,
    reverse: bool,
) -> IntArray:
    """Cuenta por fila y columna el prefijo donde vale el predicado de ``qn0``.

    Fuente: ``robustbase-0.99-6/src/qn_sn.c:213-227``. Con ``reverse=True`` el predicado es
    ``f32(y[i] - y[n-1-j]) < trial`` (bucle de ``p[]``, ``:215``); con ``reverse=False`` es
    ``f32(y[i] - y[m]) > trial`` (bucle de ``q[]``, ``:224``, con ``m = n - j + 1``). En ambos
    casos el
    predicado es monótono en ``j``/``m`` y el puntero arrastrado de C se detiene en el primer falso,
    así
    que el resultado de C es la longitud del prefijo verdadero (especificación §7.2).

    Args:
        y: Columnas ordenadas ``n x m``.
        rows: Índices de fila ``0..n-1`` como columna ``n x 1``.
        trial: Candidato por columna (longitud ``m``).
        reverse: ``True`` para ``p[]``, ``False`` para ``q[]``.

    Returns:
        Matriz entera ``n x m`` con la longitud del prefijo.
    """
    n, m = y.shape
    lo = np.zeros((n, m), dtype=np.int64)
    hi = np.full((n, m), n, dtype=np.int64)
    cols = np.arange(m)[None, :]
    yi = y[rows[:, 0], :]
    while True:
        active = lo < hi
        if not active.any():
            return lo
        mid = (lo + hi) // 2
        idx = np.minimum(mid, n - 1)
        if reverse:
            other = y[n - 1 - idx, cols]
            pred = _f32(yi - other) < trial[None, :]
        else:
            other = y[idx, cols]
            pred = _f32(yi - other) > trial[None, :]
        go_right = active & pred
        go_left = active & ~pred
        lo = np.where(go_right, mid + 1, lo)
        hi = np.where(go_left, mid, hi)


def _whimed_columns(work: FloatArray, weight: IntArray) -> FloatArray:
    """``whimed_i`` por columnas: menor ``a`` con ``2·Σ_{a_i ≤ a} w_i > Σ w``.

    Fuente: ``robustbase-0.99-6/src/wgt_himed_templ.h:27-122`` (ramas ``:85``, ``:93``,
        ``:105-110``);
    ``n == 0`` ⇒ ``NA`` (``:56``). Las entradas no válidas llegan con peso 0 y valor ``+inf`` y
    quedan
    fuera de la selección (especificación §7.2).

    Args:
        work: Valores ``(n-1) x m`` (``+inf`` donde no hay candidato).
        weight: Pesos enteros ``(n-1) x m`` (0 donde no hay candidato).

    Returns:
        Vector ``m`` con el *weighted high median* (``NaN`` si la columna no tiene candidatos).
    """
    order = np.argsort(work, axis=0, kind="stable")
    w_sorted = np.take_along_axis(work, order, axis=0)
    wt_sorted = np.take_along_axis(weight, order, axis=0)
    csum = np.cumsum(wt_sorted, axis=0)
    total = csum[-1, :]
    first = np.argmax(2 * csum > total[None, :], axis=0)
    out = w_sorted[first, np.arange(work.shape[1])]
    return np.where(total > 0, out, np.nan)


def _kth_exact(y: FloatArray, left: IntArray, right: IntArray, kk: IntArray) -> FloatArray:
    """Rama «no encontrado» de ``qn0``: k-ésimo menor de las diferencias exactas candidatas.

    Fuente: ``robustbase-0.99-6/src/qn_sn.c:262-293``: ``work = {y[i] - y[n - jj]}`` para
    ``i = 1..n-1`` y ``jj = left[i]..right[i]`` **sin** redondeo a ``float``; ``knew`` se acota a
    ``[0, j-1]`` y ``rPsort`` devuelve el valor de esa posición.

    Args:
        y: Columnas ordenadas ``n x m``.
        left: Límites izquierdos ``n x m`` (base 1, como en C).
        right: Límites derechos ``n x m`` (base 1).
        kk: ``knew - (nl + 1)`` por columna, sin acotar.

    Returns:
        Vector ``m`` con el valor seleccionado.
    """
    n, m = y.shape
    lft = left[1:, :].T  # m x (n-1), cada columna contigua al aplanar
    rgt = right[1:, :].T
    counts = np.maximum(rgt - lft + 1, 0)
    flat_counts = counts.ravel()
    total = int(flat_counts.sum())
    per_col = counts.sum(axis=1)
    col_of = np.repeat(np.repeat(np.arange(m), n - 1), flat_counts)
    i_of = np.repeat(np.tile(np.arange(1, n), m), flat_counts)
    starts = np.repeat(np.cumsum(flat_counts) - flat_counts, flat_counts)
    jj = np.repeat(lft.ravel(), flat_counts) + (np.arange(total) - starts)
    vals = y[i_of, col_of] - y[n - jj, col_of]
    order = np.lexsort((vals, col_of))
    srt = vals[order]
    col_start = np.cumsum(per_col) - per_col
    k = np.minimum(np.maximum(kk, 0), per_col - 1)
    pick = np.clip(col_start + k, 0, max(total - 1, 0))
    out = srt[pick] if total > 0 else np.full(m, np.nan)
    return np.where(per_col > 0, out, np.nan)


def _qn0_chunk(x: FloatArray) -> FloatArray:
    """``qn0`` (``k`` por defecto) sobre un lote de columnas con la misma ``n >= 2``.

    Requiere columnas sin ``NaN``/``Inf``.

    Fuente: ``robustbase-0.99-6/src/qn_sn.c:133-296`` con ``len_k = 1`` y
    ``k = choose(n %/% 2 + 1, 2)`` (``R/qnsn.R:21``).

    Args:
        x: Matriz ``n x m``; cada columna es una muestra.

    Returns:
        Vector ``m`` con ``qn0`` (sin constante ni corrección).
    """
    n, m = x.shape
    y = np.sort(x, axis=0)  # :156-158 R_qsort (solo valores)
    nn2 = n * (n + 1) // 2  # :145
    n2 = n * n  # :146
    k = math.comb(n // 2 + 1, 2)
    k_l = int(5 - 1.75 * (n % 2) + ((0.3939 - 0.0067 * (n % 2)) * n) * (n - 1))  # :154
    h = n // 2 + 1  # :155
    nl = np.full(m, nn2, dtype=np.int64)  # :167
    nr = np.full(m, n2, dtype=np.int64)
    knew = k + nn2
    rows = np.arange(n, dtype=np.int64)[:, None]
    left = np.repeat(n - rows + 1, m, axis=1)  # :176-177
    if k >= k_l:  # :178-180
        right = np.full((n, m), n, dtype=np.int64)
    else:  # :181-185
        right = np.repeat(np.where(rows <= h, n, n - (rows - h)), m, axis=1)
    found = np.zeros(m, dtype=bool)
    res = np.full(m, np.nan)

    while True:  # :187
        act = np.flatnonzero(~found & (nr - nl > n))
        if act.size == 0:
            break
        ya = y[:, act]
        la = left[:, act]
        ra = right[:, act]
        cols = np.arange(act.size)[None, :]
        # :191-198 work/weight con truncado a float
        lft = la[1:, :]
        rgt = ra[1:, :]
        valid = lft <= rgt
        wgt = rgt - lft + 1
        jh = lft + wgt // 2
        idx = np.clip(n - jh, 0, n - 1)
        work = _f32(ya[1:, :] - ya[idx, cols])
        work = np.where(valid, work, np.inf)
        wgt = np.where(valid, wgt, 0)
        trial = _whimed_columns(work, wgt)  # :199
        p_cnt = _count_prefix(ya, rows, trial, reverse=True)  # :213-218
        q_cnt = (n + 1) - _count_prefix(ya, rows, trial, reverse=False)  # :222-227
        sump = p_cnt.sum(axis=0)  # :228-234
        sumq = (q_cnt - 1).sum(axis=0)
        go_right = knew <= sump  # :238-241
        go_left = ~go_right & (knew > sumq)  # :245-248
        done = ~go_right & ~go_left  # :252-253
        right[:, act[go_right]] = p_cnt[:, go_right]
        nr[act[go_right]] = sump[go_right]
        left[:, act[go_left]] = q_cnt[:, go_left]
        nl[act[go_left]] = sumq[go_left]
        found[act[done]] = True
        res[act[done]] = trial[done]  # :260-261 (valor redondeado a float)

    rest = np.flatnonzero(~found)
    if rest.size:
        kk = knew - (nl[rest] + 1)  # :278
        res[rest] = _kth_exact(y[:, rest], left[:, rest], right[:, rest], kk)
    return res


def qn0_columns_ref(x: FloatArray) -> FloatArray:
    """``qn0`` (sin constante) por columnas, en lotes acotados en memoria.

    Fuente: ``robustbase-0.99-6/src/qn_sn.c:118-296``. Requiere ``n >= 2`` y valores finitos.

    Args:
        x: Matriz ``n x m``.

    Returns:
        Vector ``m``.
    """
    arr = np.asarray(x, dtype=np.float64)
    n, m = arr.shape
    out = np.empty(m, dtype=np.float64)
    step = max(1, _CHUNK_ELEMENTS // max(n, 1))
    # Las restas pueden desbordar a ±Inf como en C (IEEE); no es un error.
    with np.errstate(over="ignore", invalid="ignore"):
        for start in range(0, m, step):
            out[start : start + step] = _qn0_chunk(arr[:, start : start + step])
    return out


def qn_columns_ref(x: FloatArray) -> FloatArray:
    """``apply(x, 2, Qn)`` con el oráculo (``qn.py`` de ``54ede77``, ``qnsn.R:20-68``)."""
    arr = np.asarray(x, dtype=np.float64)
    n, m = arr.shape
    if n == 0:
        return np.full(m, np.nan)
    if n == 1:
        out1 = np.zeros(m, dtype=np.float64)
        out1[np.isnan(arr[0, :])] = np.nan
        return out1
    has_nan = np.isnan(arr).any(axis=0)
    if np.isinf(arr[:, ~has_nan]).any():
        raise ValueError("Qn con valores infinitos no está soportado por el port")
    out = np.full(m, np.nan)
    ok = np.flatnonzero(~has_nan)
    if ok.size:
        r = QN_CONSTANT * qn0_columns_ref(arr[:, ok])
        if n <= 12:
            out[ok] = r * QN_SMALL_N_FACTORS[n - 2]
        else:
            out[ok] = r / qn_finite_c(n)
    return out


def ogk_u_ref(y: FloatArray) -> FloatArray:
    """``U`` de ``ogkscatter`` con el oráculo (``ogk.py`` de ``54ede77``, ``detmrcd.R:86-98``)."""
    arr = np.asarray(y, dtype=np.float64)
    n, p = arr.shape
    u = np.eye(p, dtype=np.float64)
    if p < 2:
        return u
    ii, jj = np.tril_indices(p, -1)
    step = max(1, _PAIR_CHUNK_ELEMENTS // max(2 * n, 1))
    for start in range(0, ii.shape[0], step):
        bi = ii[start : start + step]
        bj = jj[start : start + step]
        yi = arr[:, bi]
        yj = arr[:, bj]
        both = np.concatenate((yi + yj, yi - yj), axis=1)
        q = qn_columns_ref(both)
        m = bi.shape[0]
        s = q[:m]
        d = q[m:]
        u[bi, bj] = (s * s - d * d) / 4
    u[jj, ii] = u[ii, jj]
    return u
