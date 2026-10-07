"""Primitivas de R base/stats reproducidas operación a operación.

Cada función replica la aritmética exacta de la fuente de R 4.5.2 citada (orden de las sumas,
número de
pasadas, redondeos intermedios) para que el port de ``rrcov::CovMrcd`` coincida bit a bit con el
oráculo
(especificación ``docs/metodos/mrcd-especificacion.md`` §3.12, trampas T4, T5, T7, T12).

Convenciones:

- En el oráculo ``LDOUBLE`` es ``double`` (especificación §0, sonda S0), así que todos los
acumuladores
  ``LDOUBLE`` de R se reproducen en ``float64``.
- Las sumas son **secuenciales** de izquierda a derecha empezando en ``0.0`` (``seqsum``); nunca
se usa
  ``np.sum``/``np.mean`` (suma por pares).
- Las funciones transcendentales usan ``math.*`` elemento a elemento (libm de la plataforma, T12).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from pymrcd._errors import RError
from pymrcd._fma import fma, fma_array
from pymrcd._types import FloatArray, IntArray

__all__ = [
    "FloatArray",
    "IntArray",
    "f32",
    "r_colmedians",
    "r_cor",
    "r_cor_spearman",
    "r_cov",
    "r_mean",
    "r_mean_cols",
    "r_median",
    "r_median_cols",
    "r_order",
    "r_pow",
    "r_qnorm",
    "r_quantile7",
    "r_rank_average",
    "r_rank_cols",
    "r_rowmeans",
    "r_rowsums",
    "r_sin",
    "r_tanh",
    "seqsum",
]


# --------------------------------------------------------------------------------------------------
# Redondeo a float32 y potencias
# --------------------------------------------------------------------------------------------------


def f32(z: float) -> float:
    """Redondea un ``double`` a ``float`` (cast de C) y lo devuelve como ``double``.

    Reproduce el ``(float)(…)`` de ``robustbase-0.99-6/src/qn_sn.c:195``, ``:215`` y ``:224``:
    redondeo al más cercano con empates a par; los valores fuera de rango van a ``±inf``.

    Args:
        z: Valor ``double``.

    Returns:
        ``float(np.float32(z))``.
    """
    with np.errstate(over="ignore"):
        return float(np.float32(z))


def r_pow(x: float, y: float) -> float:
    """Potencia ``x ^ y`` de R (``R_POW``/``R_pow``).

    Fuente: ``R-4.5.2/src/main/arithmetic.c:204-247`` (``R_pow``) y ``src/main/arithmetic.h:35``
    (``R_POW``: ``y == 2`` ⇒ ``x * x``). El caso finito delega en ``pow`` de libm (``math.pow``);
    ``math.pow`` lanza excepciones donde C devuelve ``NaN``/``±Inf``, y aquí se traducen al valor
    IEEE
    que devolvería ``pow`` de C.

    Args:
        x: Base.
        y: Exponente.

    Returns:
        ``x ^ y`` tal como lo calcula R.
    """
    if y == 2.0:
        return x * x
    if x == 1.0 or y == 0.0:
        return 1.0
    if x == 0.0:
        if y > 0.0:
            return 0.0
        if y < 0.0:
            return math.inf
        return y  # NA o NaN
    if math.isfinite(x) and math.isfinite(y):
        try:
            return math.pow(x, y)
        except ValueError:
            # base negativa con exponente no entero: pow() de C devuelve NaN.
            return math.nan
        except OverflowError:
            # pow() de C devuelve ±HUGE_VAL; negativo solo si x < 0 e y entero impar.
            negative = x < 0.0 and y == math.floor(y) and math.fmod(y, 2.0) != 0.0
            return -math.inf if negative else math.inf
    if math.isnan(x) or math.isnan(y):
        return x + y
    if not math.isfinite(x):
        if x > 0:
            return 0.0 if y < 0.0 else math.inf
        if math.isfinite(y) and y == math.floor(y):
            if y < 0.0:
                return 0.0
            return x if math.fmod(y, 2.0) != 0.0 else -x
    if not math.isfinite(y) and x >= 0:
        if y > 0:
            return math.inf if x >= 1 else 0.0
        return math.inf if x < 1 else 0.0
    return math.nan


def r_tanh(x: FloatArray) -> FloatArray:
    """``tanh`` de R aplicado elemento a elemento con libm (``math.tanh``).

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:132`` (``y1 <- tanh(x)``); la especificación (§3.12.7,
        sonda S8)
    exige ``math.tanh`` porque ``np.tanh`` difiere de R en 1 ulp en ~20 % de los casos.

    Args:
        x: Arreglo de ``float64`` de cualquier forma.

    Returns:
        Arreglo de la misma forma con ``tanh`` de libm.
    """
    arr = np.asarray(x, dtype=np.float64)
    flat = [math.tanh(v) for v in arr.ravel().tolist()]
    return np.array(flat, dtype=np.float64).reshape(arr.shape)


def r_sin(x: FloatArray) -> FloatArray:
    """``sin`` de R aplicado elemento a elemento con libm (``math.sin``).

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:218`` (``sin(1/2*pi*cortmp)``); especificación §3.12.7.

    Args:
        x: Arreglo de ``float64`` de cualquier forma.

    Returns:
        Arreglo de la misma forma con ``sin`` de libm.
    """
    arr = np.asarray(x, dtype=np.float64)
    flat = [math.sin(v) for v in arr.ravel().tolist()]
    return np.array(flat, dtype=np.float64).reshape(arr.shape)


# --------------------------------------------------------------------------------------------------
# Sumas y medias secuenciales
# --------------------------------------------------------------------------------------------------


def seqsum(v: FloatArray) -> float:
    """Suma secuencial izquierda→derecha empezando en ``0.0`` (acumulador ``LDOUBLE`` = ``double``).

    Fuente: patrón ``s = 0.0; for(...) s += x[i];`` de ``src/main/summary.c:482-486``
        (``real_mean``)
    y ``src/library/stats/src/cov.c:205-208``. Especificación §0 (``seqsum``) y trampa T5.

    Args:
        v: Vector de ``float64``.

    Returns:
        La suma acumulada en orden, con un redondeo por término.
    """
    arr = np.asarray(v, dtype=np.float64).ravel()
    acc = np.cumsum(np.concatenate((np.zeros(1), arr)))
    return float(acc[-1])


def _seqsum_axis0(a: FloatArray) -> FloatArray:
    """Sumas secuenciales por columna (a lo largo del eje 0), empezando en ``0.0``.

    Fuente: mismo patrón que ``seqsum`` (``src/main/summary.c:482-486``), vectorizado entre columnas
    independientes.

    Args:
        a: Matriz ``n x m``.

    Returns:
        Vector de longitud ``m`` con la suma secuencial de cada columna.
    """
    arr = np.asarray(a, dtype=np.float64)
    padded = np.concatenate((np.zeros((1, arr.shape[1])), arr), axis=0)
    # add.accumulate es secuencial por definición (cada parcial depende del anterior).
    return np.asarray(np.add.accumulate(padded, axis=0)[-1], dtype=np.float64)


def r_mean_cols(a: FloatArray) -> FloatArray:
    """``mean()`` de R (``real_mean``, dos pasadas) aplicado a cada columna de ``a``.

    Fuente: ``R-4.5.2/src/main/summary.c:479-518`` (``real_mean``). Con ``LDOUBLE = double``:
    ``s = Σ x / n``; si la primera suma desborda se rehace como ``Σ (x/n)``; después se corrige con
    ``t = Σ (x - s)`` (``s += t/n``) o, en la rama desbordada, ``t = Σ ((x - s)/n)`` (``s += t``).

    Args:
        a: Matriz ``n x m``; cada columna es un vector independiente.

    Returns:
        Vector de longitud ``m`` con la media de R de cada columna (``NaN`` si ``n == 0``).
    """
    arr = np.asarray(a, dtype=np.float64)
    n = arr.shape[0]
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        s = _seqsum_axis0(arr)
        finite_s = np.isfinite(s)
        s = np.where(finite_s, s / n, _seqsum_axis0(arr / n))
        finite_now = np.isfinite(s)
        t_normal = _seqsum_axis0(arr - s[None, :])
        t_overflow = _seqsum_axis0((arr - s[None, :]) / n)
        out = np.where(
            finite_s & finite_now,
            s + t_normal / n,
            np.where(finite_now, s + t_overflow, s),
        )
    return np.asarray(out, dtype=np.float64)


def r_mean(v: FloatArray) -> float:
    """``mean()`` de R sobre un vector (``real_mean``, dos pasadas).

    Fuente: ``R-4.5.2/src/main/summary.c:479-518``. Especificación §3.12.2.

    Args:
        v: Vector de ``float64``.

    Returns:
        La media de R (``NaN`` para un vector vacío).
    """
    arr = np.asarray(v, dtype=np.float64).ravel()
    return float(r_mean_cols(arr[:, None])[0])


def r_rowsums(a: FloatArray) -> FloatArray:
    """``rowSums(a)`` de R: acumulación secuencial por columnas.

    Fuente: ``R-4.5.2/src/main/array.c:2001-2098`` (rama de filas: ``rans`` empieza en 0 y suma la
    columna ``j`` para ``j = 0..p-1``). Especificación §3.12.2, trampa T5.

    Args:
        a: Matriz ``n x p``.

    Returns:
        Vector de longitud ``n``.
    """
    arr = np.asarray(a, dtype=np.float64)
    acc = np.zeros(arr.shape[0], dtype=np.float64)
    for j in range(arr.shape[1]):
        acc = acc + arr[:, j]
    return acc


def r_rowmeans(a: FloatArray) -> FloatArray:
    """``rowMeans(a)`` de R: ``rowSums`` secuencial y después ``/ p``.

    Fuente: ``R-4.5.2/src/main/array.c:2001-2098`` (``rans[i] /= p`` tras la acumulación).

    Args:
        a: Matriz ``n x p``.

    Returns:
        Vector de longitud ``n``.
    """
    arr = np.asarray(a, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.asarray(r_rowsums(arr) / np.float64(arr.shape[1]), dtype=np.float64)


# --------------------------------------------------------------------------------------------------
# Medianas
# --------------------------------------------------------------------------------------------------


def _rcmp(x: float, y: float) -> int:
    """Comparación ``rcmp`` de R con ``nalast = TRUE``.

    Fuente: ``R-4.5.2.tar.gz`` ``src/main/sort.c:45-54``.

    Args:
        x: Valor.
        y: Valor.

    Returns:
        ``-1``, ``0`` o ``1``.
    """
    nax = math.isnan(x)
    nay = math.isnan(y)
    if nax and nay:
        return 0
    if nax:
        return 1
    if nay:
        return -1
    if x < y:
        return -1
    if x > y:
        return 1
    return 0


def _rpsort2(x: list[float], lo: int, hi: int, k: int) -> None:
    """Selección parcial ``rPsort2`` de R (Hoare), en sitio.

    Fuente: ``R-4.5.2.tar.gz`` ``src/main/sort.c:668-698`` (``psort_body`` con ``rcmp``). Se porta
    literalmente porque decide **qué** representante de un empate queda en la posición ``k``; solo
    importa para el signo de un cero (``-0.0`` frente a ``0.0``).

    Args:
        x: Vector (se modifica).
        lo: Inicio (base 0).
        hi: Fin (base 0, inclusivo).
        k: Posición objetivo (base 0).
    """
    left, right = lo, hi
    while left < right:
        v = x[k]
        i, j = left, right
        while i <= j:
            while _rcmp(x[i], v) < 0:
                i += 1
            while _rcmp(v, x[j]) < 0:
                j -= 1
            if i <= j:
                x[i], x[j] = x[j], x[i]
                i += 1
                j -= 1
        if j < k:
            left = i
        if k < i:
            right = j


def _rpsort0(x: list[float], lo: int, hi: int, ind: list[int]) -> None:
    """``Psort0`` de R: selección parcial en varias posiciones (base 1, ordenadas), en sitio.

    Fuente: ``R-4.5.2.tar.gz`` ``src/main/sort.c:759-775`` (llamado desde ``do_psort``,
    ``sort.c:779-829``, vía ``sort.int(x, partial=)``, ``base/R/sort.R:136-150``).

    Args:
        x: Vector (se modifica).
        lo: Inicio (base 0).
        hi: Fin (base 0, inclusivo).
        ind: Posiciones en base 1, crecientes.
    """
    if len(ind) < 1 or hi - lo < 1:
        return
    if len(ind) <= 1:
        _rpsort2(x, lo, hi, ind[0] - 1)
        return
    this = 0
    mid = (lo + hi) // 2
    for t, val in enumerate(ind):
        if val - 1 <= mid:
            this = t
    z = ind[this] - 1
    _rpsort2(x, lo, hi, z)
    _rpsort0(x, lo, z - 1, ind[:this])
    _rpsort0(x, z + 1, hi, ind[this + 1 :])


def _resolve_zero_sign(col: FloatArray, picks: list[float], positions: list[int]) -> list[float]:
    """Recupera el signo de los ceros elegidos por la selección parcial de R.

    ``np.sort`` da el mismo **valor** que la selección de R en cada posición; solo puede diferir el
    signo de un cero cuando la columna mezcla ``-0.0`` y ``0.0``. En ese caso (raro) se ejecuta el
    ``Psort0`` literal de R para saber qué cero queda en cada posición.

    Args:
        col: Columna original (sin ``NaN``).
        picks: Valores en ``positions`` según ``np.sort``.
        positions: Posiciones en base 1, crecientes.

    Returns:
        Los valores con el signo de cero de R.
    """
    if not any(v == 0.0 for v in picks):
        return picks
    zeros = col[col == 0.0]
    if not (np.signbit(zeros).any() and (~np.signbit(zeros)).any()):
        return picks
    work = col.tolist()
    _rpsort0(work, 0, len(work) - 1, positions)
    return [work[pos - 1] for pos in positions]


def _rpsort_single(col: FloatArray, picks: list[float], kk: list[int]) -> list[float]:
    """Como ``_resolve_zero_sign`` pero con las llamadas sucesivas a ``rPsort`` de ``rowMedians``.

    Fuente: ``robustbase-0.99-6/src/rowMedians_TYPE-template.h:157-166``: ``rPsort(x, n, qq+1)`` y,
    si ``n`` es par, ``rPsort(x, qq+1, qq)`` sobre el prefijo.

    Args:
        col: Columna original (sin ``NaN``).
        picks: Valores según ``np.sort`` en las posiciones ``kk``.
        kk: Posiciones en base 0 (``[qq+1]`` o ``[qq+1, qq]``).

    Returns:
        Los valores con el signo de cero de R.
    """
    if not any(v == 0.0 for v in picks):
        return picks
    zeros = col[col == 0.0]
    if not (np.signbit(zeros).any() and (~np.signbit(zeros)).any()):
        return picks
    work = col.tolist()
    _rpsort2(work, 0, len(work) - 1, kk[0])
    if len(kk) > 1:
        _rpsort2(work, 0, kk[0] - 1, kk[1])
    return [work[k] for k in kk]


def r_median_cols(a: FloatArray) -> FloatArray:
    """``median()`` de R (``median.default``) aplicado a cada columna de ``a``.

    Fuente: ``R-4.5.2/src/library/stats/R/median.R:21-33``: con ``NA`` devuelve ``NA``; longitud
    impar ⇒
    elemento central; longitud par ⇒ ``mean()`` de los dos centrales, es decir la media de **dos
    pasadas** de ``summary.c:479-518`` (trampa T4; no es ``(a+b)/2``).

    Args:
        a: Matriz ``n x m``.

    Returns:
        Vector de longitud ``m`` (``NaN`` en columnas con ``NaN`` o si ``n == 0``).
    """
    arr = np.asarray(a, dtype=np.float64)
    n, m = arr.shape
    if n == 0:
        return np.full(m, np.nan)
    srt = np.sort(arr, axis=0)
    half = (n + 1) // 2
    positions = [half] if n % 2 == 1 else [half, half + 1]
    mids = srt[[pos - 1 for pos in positions], :].copy()
    for j in np.flatnonzero((mids == 0.0).any(axis=0)).tolist():
        mids[:, j] = _resolve_zero_sign(arr[:, j], mids[:, j].tolist(), positions)
    out = mids[0, :].copy() if n % 2 == 1 else r_mean_cols(mids)
    out[np.isnan(arr).any(axis=0)] = np.nan
    return out


def r_median(v: FloatArray) -> float:
    """``median()`` de R sobre un vector.

    Fuente: ``R-4.5.2/src/library/stats/R/median.R:21-33`` (ver ``r_median_cols``).

    Args:
        v: Vector de ``float64``.

    Returns:
        La mediana de R.
    """
    arr = np.asarray(v, dtype=np.float64).ravel()
    return float(r_median_cols(arr[:, None])[0])


def r_colmedians(a: FloatArray) -> FloatArray:
    """``robustbase::colMedians(a)`` (C): par ⇒ ``(lo + hi) / 2`` sin corrección.

    Fuente: ``robustbase-0.99-6/R/comedian.R:21-22`` → ``src/rowMedians_TYPE-template.h:123-168``
    (``hasNA=TRUE``, ``na.rm=FALSE``: una columna con ``NaN`` da ``NA``; ``:138``/``:166``:
    ``(rowData[qq] + value)/2``). Trampa T4.

    Args:
        a: Matriz ``n x m``.

    Returns:
        Vector de longitud ``m``.
    """
    arr = np.asarray(a, dtype=np.float64)
    n, m = arr.shape
    if n == 0:
        return np.full(m, np.nan)
    srt = np.sort(arr, axis=0)
    qq = n // 2 - 1
    kk = [qq + 1] if n % 2 == 1 else [qq + 1, qq]
    mids = srt[kk, :].copy()
    for j in np.flatnonzero((mids == 0.0).any(axis=0)).tolist():
        mids[:, j] = _rpsort_single(arr[:, j], mids[:, j].tolist(), kk)
    out = mids[0, :].copy() if n % 2 == 1 else (mids[1, :] + mids[0, :]) / 2.0
    out[np.isnan(arr).any(axis=0)] = np.nan
    return np.asarray(out, dtype=np.float64)


# --------------------------------------------------------------------------------------------------
# Rangos y orden
# --------------------------------------------------------------------------------------------------


def r_order(v: FloatArray) -> IntArray:
    """``order(v)``/``sort.list(v)`` de R para un vector numérico (base 0).

    Fuente: ``R-4.5.2/src/library/base/R/sort.R:211-228`` (``method="auto"`` ⇒ radix para
        numéricos),
    ``[tar]radixsort.c``: orden **estable**, ``-0.0`` y ``0.0`` empatan, ``NaN`` al final
    (``na.last=TRUE``). Especificación §3.12.3.

    Args:
        v: Vector de ``float64``.

    Returns:
        Permutación en base 0 (``np.argsort`` estable).
    """
    arr = np.asarray(v, dtype=np.float64).ravel()
    return np.asarray(np.argsort(arr, kind="stable"), dtype=np.int64)


def r_rank_average(v: FloatArray) -> FloatArray:
    """``rank(v, ties.method="average", na.last="keep")`` de R.

    Fuente: ``R-4.5.2/src/library/base/R/rank.R:19-50`` y ``[tar]sort.c:1540-1556``: cada grupo de
    empates ``i..j`` (base 0, en el orden estable) recibe ``(i + j + 2) / 2.``; los ``NA`` conservan
    ``NA`` y no cuentan. Especificación §3.12.3.

    Args:
        v: Vector de ``float64``.

    Returns:
        Rangos promedio (semienteros exactos) con ``NaN`` donde ``v`` es ``NaN``.
    """
    arr = np.asarray(v, dtype=np.float64).ravel()
    out = np.full(arr.shape[0], np.nan)
    ok = np.flatnonzero(~np.isnan(arr))
    vals = arr[ok]
    m = vals.shape[0]
    if m == 0:
        return out
    idx = np.argsort(vals, kind="stable")
    srt = vals[idx]
    new_group = np.empty(m, dtype=bool)
    new_group[0] = True
    new_group[1:] = srt[1:] != srt[:-1]
    starts = np.flatnonzero(new_group)
    ends = np.append(starts[1:], m) - 1
    group_of = np.cumsum(new_group) - 1
    ranks_sorted = (starts[group_of] + ends[group_of] + 2) / 2.0
    out[ok[idx]] = ranks_sorted
    return out


def r_rank_cols(x: FloatArray) -> FloatArray:
    """``apply(x, 2, rank)`` con empates promedio (``Rank`` interno de ``cor``).

    Fuente: ``R-4.5.2/src/library/stats/R/cor.R:43-49`` (``apply(u, 2L, rank, na.last="keep")`` si
    ``nrow > 1``, ``row(u)`` si ``nrow == 1``) y ``rrcov-1.7-7/R/detmrcd.R:138``, ``:143``.

    Args:
        x: Matriz ``n x p``.

    Returns:
        Matriz ``n x p`` de rangos promedio.
    """
    arr = np.asarray(x, dtype=np.float64)
    if arr.shape[0] <= 1:
        return np.ones_like(arr)
    return np.column_stack([r_rank_average(arr[:, j]) for j in range(arr.shape[1])])


# --------------------------------------------------------------------------------------------------
# Covarianza y correlación
# --------------------------------------------------------------------------------------------------


def _cov_core(x: FloatArray, cor: bool, vectorized: bool) -> FloatArray:
    """Núcleo común de ``cov_na_1``/``cov_complete1`` sin ``NA`` (Pearson).

    Fuente: ``R-4.5.2/src/library/stats/src/cov.c:201-240`` (``MEAN``/``MEAN_``: media de dos
    pasadas), ``:259-267``/``:325-335`` (``sum += (x_k - m_i)*(y_k - m_j)`` secuencial, ``/
    (n-1)``) y
    ``:284-299``/``:353-368`` (``cor``: ``sum / (sd_i*sd_j)`` con ``CLAMP`` a ``[-1, 1]``,
    diagonal 1;
    desviación 0 ⇒ ``NA``). En el binario del oráculo (``stats.so``, ``clang -O2`` arm64) la
    acumulación ``sum += a*b`` es una instrucción ``fmadd`` (desensamblado de ``corcov``): se
    reproduce con ``fma`` exacto.

    Args:
        x: Matriz ``n x p`` sin ``NaN`` con ``n >= 2``.
        cor: ``True`` para correlación, ``False`` para covarianza.
        vectorized: ``True`` para ``cov_na_1`` (``use="everything"``), cuyo bucle está
            vectorizado en
            el binario del oráculo; ``False`` para ``cov_complete1``.

    Returns:
        Matriz ``p x p``.
    """
    n, p = x.shape
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        tmp = _seqsum_axis0(x) / n
        corr = _seqsum_axis0(x - tmp[None, :]) / n
        means = np.where(np.isfinite(tmp), tmp + corr, tmp)
        centered = x - means[None, :]
        ans = np.empty((p, p), dtype=np.float64)
        n1 = float(n - 1)
        rows, cols = np.tril_indices(p)
        acc = np.zeros(rows.shape[0], dtype=np.float64)
        # Compilación del oráculo (desensamblado de ``corcov`` en ``stats.so``):
        # - cov_complete1 (bucle con ``if(ind[k])``): ``sum += a*b`` es ``fmadd`` en todo k.
        # - cov_na_1 (sin ``ind``): clang vectoriza en bloques de 8 si n >= 8: productos ``fmul``
        #   redondeados y sumas ``fadd`` secuenciales en el orden de k; el resto (k >= 8*floor(n/8))
        #   usa ``fmadd``.
        n_unfused = (n // 8) * 8 if (vectorized and n >= 8) else 0
        for k in range(n):
            if k < n_unfused:
                acc = acc + centered[k, rows] * centered[k, cols]
            else:
                acc = fma_array(centered[k, rows], centered[k, cols], acc)
        lower = acc / n1
        ans[rows, cols] = lower
        ans[cols, rows] = lower
        if not cor:
            return ans
        sd = np.sqrt(np.diag(ans).copy())
        out = ans / (sd[:, None] * sd[None, :])
        out = np.minimum(np.maximum(out, -1.0), 1.0)
        zero = (sd[:, None] == 0) | (sd[None, :] == 0)
        out[zero] = np.nan
        np.fill_diagonal(out, 1.0)
    return np.asarray(out, dtype=np.float64)


def _cov_dispatch(x: FloatArray, use: str, cor: bool) -> FloatArray:
    """Selecciona la rama de ``cov.c`` según ``use`` y gestiona ``NA``.

    Fuente: ``R-4.5.2/src/library/stats/src/cov.c:640-830`` (``corcov``): ``"everything"`` ⇒
    ``cov_na_1`` (columnas con ``NA`` dan ``NA``, ``:304-370``); ``"complete.obs"`` ⇒
    ``cov_complete1``
    sobre las filas completas (``:243-301``); ``n <= 1`` observaciones ⇒ todo ``NA``
    (``COV_n_le_1``,
    ``:180-186``).

    Args:
        x: Matriz ``n x p``.
        use: ``"everything"`` o ``"complete.obs"``.
        cor: ``True`` para correlación.

    Returns:
        Matriz ``p x p``.

    Raises:
        RError: si ``use`` no es válido o ``x`` está vacía.
    """
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim != 2 or arr.size == 0:
        raise RError("'x' is empty")
    p = arr.shape[1]
    if use == "everything":
        has_na = np.isnan(arr).any(axis=0)
        if arr.shape[0] <= 1:
            return np.full((p, p), np.nan)
        out = np.full((p, p), np.nan)
        ok = np.flatnonzero(~has_na)
        if ok.size:
            sub = _cov_core(arr[:, ok], cor, vectorized=True)
            out[np.ix_(ok, ok)] = sub
        if cor:
            np.fill_diagonal(out, 1.0)
        return out
    if use == "complete.obs":
        rows = ~np.isnan(arr).any(axis=1)
        sub_x = arr[rows, :]
        if sub_x.shape[0] <= 1:
            return np.full((p, p), np.nan)
        return _cov_core(sub_x, cor, vectorized=False)
    raise RError("invalid 'use' argument")


def r_cov(x: FloatArray, use: str = "everything") -> FloatArray:
    """``cov(x, use=use)`` de R (Pearson).

    Fuente: ``R-4.5.2/src/library/stats/src/cov.c:201-370`` (ver ``_cov_core``). Especificación
    §3.12.4; sonda S3: la versión secuencial reproduce ``cov()`` bit a bit.

    Args:
        x: Matriz ``n x p``.
        use: ``"everything"`` (por defecto en R) o ``"complete.obs"``.

    Returns:
        Matriz ``p x p``.
    """
    return _cov_dispatch(x, use, cor=False)


def r_cor(x: FloatArray, use: str = "everything") -> FloatArray:
    """``cor(x, use=use)`` de R (Pearson).

    Fuente: ``R-4.5.2/src/library/stats/R/cor.R:50-51`` → ``src/cov.c`` (ver ``_cov_core``). Una
    columna constante da ``NA`` fuera de la diagonal (``cov.c:358-360``; R además avisa
    ``"the standard deviation is zero"``), trampa T20.

    Args:
        x: Matriz ``n x p``.
        use: ``"everything"`` o ``"complete.obs"``.

    Returns:
        Matriz ``p x p``.
    """
    return _cov_dispatch(x, use, cor=True)


def r_cor_spearman(x: FloatArray) -> FloatArray:
    """``cor(x, method="spearman")`` de R con ``use="everything"``.

    Fuente: ``R-4.5.2/src/library/stats/R/cor.R:66-70``: ``Rank(x)`` por columnas (empates
        promedio) y
    después ``C_cor`` Pearson sobre los rangos.

    Args:
        x: Matriz ``n x p``.

    Returns:
        Matriz ``p x p``.
    """
    return r_cor(r_rank_cols(x), use="everything")


# --------------------------------------------------------------------------------------------------
# Cuantiles
# --------------------------------------------------------------------------------------------------


def r_quantile7(x: FloatArray, probs: Sequence[float] | FloatArray) -> FloatArray:
    """``quantile(x, probs, names=FALSE)`` de R con ``type = 7`` (por defecto).

    Fuente: ``R-4.5.2/src/library/stats/R/quantile.R:43-67``: ``index = 1 + max(n-1, 0) * probs``;
    ``lo = floor(index)``; ``hi = ceiling(index)``; ``qs = x[lo]``; si ``index > lo`` y
    ``x[hi] != qs``: ``h = index - lo``; ``qs = (1 - h) * qs + h * x[hi]``. No es ``np.quantile``
    (especificación §3.12.5).

    Args:
        x: Vector sin ``NaN``.
        probs: Probabilidades en ``[0, 1]``.

    Returns:
        Cuantiles en el orden de ``probs``.

    Raises:
        RError: si ``x`` tiene ``NaN`` o alguna probabilidad está fuera de ``[0, 1]``.
    """
    arr = np.asarray(x, dtype=np.float64).ravel()
    pr = np.asarray(probs, dtype=np.float64).ravel()
    if np.isnan(arr).any():
        raise RError("missing values and NaN's not allowed if 'na.rm' is FALSE")
    eps = 100 * np.finfo(np.float64).eps
    if np.any((pr < -eps) | (pr > 1 + eps)):
        raise RError("'probs' outside [0,1]")
    pr = np.maximum(0.0, np.minimum(1.0, pr))
    n = arr.shape[0]
    srt = np.sort(arr)
    out = np.empty(pr.shape[0], dtype=np.float64)
    for t, prob in enumerate(pr.tolist()):
        index = 1.0 + max(n - 1, 0) * prob
        lo = math.floor(index)
        hi = math.ceil(index)
        qs = float(srt[lo - 1])
        x_hi = float(srt[hi - 1])
        if index > lo and x_hi != qs:
            h = index - lo
            qs = (1.0 - h) * qs + h * x_hi
        out[t] = qs
    return out


# --------------------------------------------------------------------------------------------------
# qnorm (AS 241)
# --------------------------------------------------------------------------------------------------

_A = (
    3.387132872796366608,
    133.14166789178437745,
    1971.5909503065514427,
    13731.693765509461125,
    45921.953931549871457,
    67265.770927008700853,
    33430.575583588128105,
    2509.0809287301226727,
)
_B = (
    1.0,
    42.313330701600911252,
    687.1870074920579083,
    5394.1960214247511077,
    21213.794301586595867,
    39307.89580009271061,
    28729.085735721942674,
    5226.495278852854561,
)
_C = (
    1.42343711074968357734,
    4.6303378461565452959,
    5.7694972214606914055,
    3.64784832476320460504,
    1.27045825245236838258,
    0.24178072517745061177,
    0.0227238449892691845833,
    7.7454501427834140764e-4,
)
_D = (
    1.0,
    2.05319162663775882187,
    1.6763848301838038494,
    0.68976733498510000455,
    0.14810397642748007459,
    0.0151986665636164571966,
    5.475938084995344946e-4,
    1.05075007164441684324e-9,
)
_E = (
    6.6579046435011037772,
    5.4637849111641143699,
    1.7848265399172913358,
    0.29656057182850489123,
    0.026532189526576123093,
    0.0012426609473880784386,
    2.71155556874348757815e-5,
    2.01033439929228813265e-7,
)
_F = (
    1.0,
    0.59983220655588793769,
    0.13692988092273580531,
    0.0148753612908506148525,
    7.868691311456132591e-4,
    1.8463183175100546818e-5,
    1.4215117583164458887e-7,
    2.04426310338993978564e-15,
)


def _horner_fma(coef: tuple[float, ...], r: FloatArray) -> FloatArray:
    """Polinomio de AS 241 con la contracción ``fmadd`` del binario de R.

    Fuente: ``R-4.5.2/src/nmath/qnorm.c:82-90``, ``:107-118``, ``:127-138``. En el ``libR.dylib``
    del
    oráculo (``clang -O2``, arm64) cada paso de Horner ``acc*r + c`` es una instrucción
    ``fmadd``/``fmla``
    con un solo redondeo (desensamblado de ``Rf_qnorm5``); se reproduce con ``fma`` exacto.

    Args:
        coef: Coeficientes ``c0..c7``.
        r: Variable del polinomio.

    Returns:
        ``(((((((r*c7 + c6)*r + c5)*r + c4)*r + c3)*r + c2)*r + c1)*r + c0)`` con FMA.
    """
    acc = fma_array(r, np.float64(coef[7]), np.float64(coef[6]))
    for c in coef[5::-1]:
        acc = fma_array(acc, r, np.float64(c))
    return acc


def _qnorm_far_tail(lp: float, r: float) -> float:
    """Rama ``r > 27`` de ``qnorm5`` (fórmulas asintóticas de Maechler 2022).

    Fuente: ``R-4.5.2/src/nmath/qnorm.c:140-163``. Los términos ``… + 2*log1p(…)`` se compilan como
    ``fmadd`` en el oráculo y se reproducen con ``fma``.

    Args:
        lp: ``log(min(p, 1-p))``.
        r: ``sqrt(-lp)``.

    Returns:
        ``|qnorm(p)|`` antes de aplicar el signo.
    """
    if r >= 6.4e8:
        return r * math.sqrt(2.0)
    m_2pi = 6.283185307179586476925286766559
    s2 = -math.ldexp(lp, 1)
    x2 = s2 - math.log(m_2pi * s2)
    if r < 36000.0:
        x2 = s2 - math.log(m_2pi * x2) - 2.0 / (2.0 + x2)
        if r < 840.0:
            x2 = fma(
                math.log1p(-(1 - 1 / (4 + x2)) / (2.0 + x2)),
                2.0,
                s2 - math.log(m_2pi * x2),
            )
            if r < 109.0:
                x2 = fma(
                    math.log1p(-(1 - (1 - 5 / (6 + x2)) / (4.0 + x2)) / (2.0 + x2)),
                    2.0,
                    s2 - math.log(m_2pi * x2),
                )
                if r < 55.0:
                    x2 = fma(
                        math.log1p(
                            -(1 - (1 - (5 - 9 / (8.0 + x2)) / (6.0 + x2)) / (4.0 + x2)) / (2.0 + x2)
                        ),
                        2.0,
                        s2 - math.log(m_2pi * x2),
                    )
    return math.sqrt(x2)


def r_qnorm(p: FloatArray) -> FloatArray:
    """``qnorm(p)`` de R elemento a elemento (AS 241 portado, no ``scipy.special.ndtri``).

    Fuente: ``R-4.5.2/src/nmath/qnorm.c:47-169`` (``qnorm5`` con ``mu = 0``, ``sigma = 1``,
    ``lower.tail = TRUE``, ``log.p = FALSE``): fronteras ``R_Q_P01_boundaries`` (``p = 0`` ⇒
    ``-Inf``,
    ``p = 1`` ⇒ ``Inf``, fuera de ``[0, 1]`` ⇒ ``NaN``); ``|q| <= .425`` ⇒ ``r = .180625 - q*q`` y
    cociente de polinomios; si no, ``r = sqrt(-log(min(p, 1-p)))`` con las ramas ``r <= 5``,
    ``r <= 27`` y la asintótica. Reproduce las contracciones ``fmadd``/``fmsub`` del binario del
    oráculo
    (``r = fmsub(q, q, .180625)``, Horner fusionado, ``mu + sigma*val`` fusionado). ``log`` es
    el de libm
    (``math.log``). Especificación §3.12.7 (sonda S8: ``ndtri`` difiere en 2/3 de los puntos).

    Args:
        p: Arreglo de probabilidades de cualquier forma.

    Returns:
        Arreglo de la misma forma.
    """
    arr = np.asarray(p, dtype=np.float64)
    flat = np.atleast_1d(arr.ravel()).copy()
    out = np.full(flat.shape, np.nan)
    out[flat == 0.0] = -np.inf
    out[flat == 1.0] = np.inf
    inside = (flat > 0.0) & (flat < 1.0)
    q = flat - 0.5
    central = inside & (np.abs(q) <= 0.425)
    if central.any():
        qc = q[central]
        r = fma_array(-qc, qc, np.float64(0.180625))
        out[central] = (qc * _horner_fma(_A, r)) / _horner_fma(_B, r)
    tail = np.flatnonzero(inside & ~central)
    if tail.size:
        qt = q[tail]
        pt = flat[tail]
        lp = np.array(
            [
                math.log((0.5 - pv + 0.5) if qv > 0 else pv)
                for pv, qv in zip(pt.tolist(), qt.tolist(), strict=True)
            ]
        )
        r = np.sqrt(-lp)
        val = np.empty(tail.size)
        near = r <= 5.0
        if near.any():
            rn = r[near] + (-1.6)
            val[near] = _horner_fma(_C, rn) / _horner_fma(_D, rn)
        mid = ~near & (r <= 27)
        if mid.any():
            rm = r[mid] + (-5.0)
            val[mid] = _horner_fma(_E, rm) / _horner_fma(_F, rm)
        for t in np.flatnonzero(~near & ~mid).tolist():
            val[t] = _qnorm_far_tail(float(lp[t]), float(r[t]))
        out[tail] = np.where(qt < 0.0, -val, val)
    # mu + sigma*val = fma(1, val, 0): igual a val salvo -0 -> +0.
    return np.asarray(out + 0.0, dtype=np.float64).reshape(arr.shape)
