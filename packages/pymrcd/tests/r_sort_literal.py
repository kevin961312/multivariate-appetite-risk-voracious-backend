"""Oráculo de test: transliteración literal de ``R_qsort``, ``rPsort``, ``whimed_i`` y ``qn0``.

Escalar y lenta; solo sirve para comprobar **la posición de cada ``±0``** que dejan los ganchos
privados de la extensión C (``_r_qsort``, ``_rpsort``, ``_whimed_i``) y el signo del cero de
``qn0`` (especificación §3.12.9 c, f). Es la sonda S15 del analista (0 de 20000 bits distintos
frente a ``.C(Qn0)`` de R), versionada como apoyo de los tests.

Fuentes: ``R-4.5.2/src/main/qsort-body.c:27-169`` (``R_qsort``, base 1, con los ``goto`` como
estados), ``R-4.5.2/src/main/sort.c:45-54``, ``:668-727`` (``rcmp``, ``psort_body``, ``rPsort``),
``robustbase-0.99-6/src/wgt_himed_templ.h:27-122`` (``whimed_i``) y ``src/qn_sn.c:118-296``
(``qn0``).
"""

from __future__ import annotations

import math

import numpy as np


def f32(z: float) -> float:
    """``(float)`` de C (``qn_sn.c:195``): redondeo a binary32 devuelto como ``float``."""
    with np.errstate(over="ignore"):
        return float(np.float32(z))


def r_qsort(v0: list[float], i: int, j: int) -> None:
    """``R_qsort(v, i, j)`` en sitio (``qsort-body.c:27-169``); ``i``, ``j`` en base 1.

    La variable ``l`` de C se llama ``ll`` (E741).
    """
    v: list[float] = [math.nan, *v0]  # --v (:55)
    il = [0] * 40
    iu = [0] * 40
    big_r = 0.375
    ii = i
    m = 1
    k = ll = 0
    vt = 0.0
    state = "L10"
    while True:
        if state == "L10":
            if i < j:
                if big_r < 0.5898437:
                    big_r += 0.0390625
                else:
                    big_r -= 0.21875
                state = "L20"
            else:
                state = "L80"
        elif state == "L20":
            k = i
            ij = i + int((j - i) * big_r)
            vt = v[ij]
            if v[i] > vt:
                v[ij] = v[i]
                v[i] = vt
                vt = v[ij]
            ll = j
            if v[j] < vt:
                v[ij] = v[j]
                v[j] = vt
                vt = v[ij]
                if v[i] > vt:
                    v[ij] = v[i]
                    v[i] = vt
                    vt = v[ij]
            while True:
                ll -= 1
                while v[ll] > vt:
                    ll -= 1
                vtt = v[ll]
                k += 1
                while v[k] < vt:
                    k += 1
                if k > ll:
                    break
                v[ll] = v[k]
                v[k] = vtt
            m += 1
            if ll - i <= j - k:
                il[m] = k
                iu[m] = j
                j = ll
            else:
                il[m] = i
                iu[m] = ll
                i = k
            state = "AFTER"
        elif state == "L80":
            if m == 1:
                v0[:] = v[1:]
                return
            i = il[m]
            j = iu[m]
            m -= 1
            state = "AFTER"
        elif state == "AFTER":
            if j - i > 10:
                state = "L20"
            elif i == ii:
                state = "L10"
            else:
                i -= 1
                state = "L100"
        else:  # L100
            while True:
                i += 1
                if i == j:
                    break
                vt = v[i + 1]
                if not v[i] <= vt:
                    break
            if i == j:
                state = "L80"
                continue
            k = i
            while True:
                v[k + 1] = v[k]
                k -= 1
                if not vt < v[k]:
                    break
            v[k + 1] = vt
            state = "L100"


def _rcmp(x: float, y: float) -> int:
    """``rcmp`` sin NaN (``sort.c:45-54``)."""
    if x < y:
        return -1
    if x > y:
        return 1
    return 0


def r_psort(x: list[float], n: int, k: int) -> None:
    """``rPsort(x, n, k)`` en sitio (``sort.c:668-681``, ``:692-698``, ``:724-727``)."""
    big_l, big_r = 0, n - 1
    while big_l < big_r:
        v = x[k]
        i, j = big_l, big_r
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
            big_l = i
        if k < i:
            big_r = j


def whimed_i(a: list[float], w: list[int], n: int) -> float:
    """``whimed_i(a, w, n, …)`` (``wgt_himed_templ.h:27-122``); modifica ``a`` y ``w``."""
    w_tot = sum(w[:n])
    wrest = 0
    if n == 0:
        return math.nan
    a_cand = [0.0] * n
    w_cand = [0] * n
    while True:
        n2 = n // 2
        a_srt = a[:n]
        r_psort(a_srt, n, n2)
        trial = a_srt[n2]
        wleft = wmid = 0
        for i in range(n):
            if a[i] < trial:
                wleft += w[i]
            elif not a[i] > trial:
                wmid += w[i]
        kcand = 0
        if 2 * (wrest + wleft) > w_tot:
            for i in range(n):
                if a[i] < trial:
                    a_cand[kcand] = a[i]
                    w_cand[kcand] = w[i]
                    kcand += 1
        elif 2 * (wrest + wleft + wmid) <= w_tot:
            for i in range(n):
                if a[i] > trial:
                    a_cand[kcand] = a[i]
                    w_cand[kcand] = w[i]
                    kcand += 1
            wrest += wleft + wmid
        else:
            return trial
        n = kcand
        for i in range(n):
            a[i] = a_cand[i]
            w[i] = w_cand[i]


def qn0(x: list[float], k: int) -> float:
    """``qn0`` literal (``qn_sn.c:133-296``) con ``len_k = 1``."""
    n = len(x)
    y = list(x)
    nn2 = n * (n + 1) // 2
    n2 = n * n
    k_l = int(5 - 1.75 * (n % 2) + ((0.3939 - 0.0067 * (n % 2)) * n) * (n - 1))
    h = n // 2 + 1
    r_qsort(y, 1, n)
    nl, nr, knew = nn2, n2, k + nn2
    found = False
    trial = math.nan
    left = [n - i + 1 for i in range(n)]
    right = [n] * n if k >= k_l else [n if i <= h else n - (i - h) for i in range(n)]
    p = [0] * n
    q = [0] * n
    while not found and nr - nl > n:
        work: list[float] = []
        weight: list[int] = []
        for i in range(1, n):
            if left[i] <= right[i]:
                wgt = right[i] - left[i] + 1
                jh = left[i] + wgt // 2
                work.append(f32(y[i] - y[n - jh]))
                weight.append(wgt)
        trial = whimed_i(work, weight, len(work))
        j = 0
        for i in range(n - 1, -1, -1):
            while j < n and f32(y[i] - y[n - j - 1]) < trial:
                j += 1
            p[i] = j
        j = n + 1
        for i in range(n):
            while f32(y[i] - y[n - j + 1]) > trial:
                j -= 1
            q[i] = j
        sump = sum(p)
        sumq = sum(v - 1 for v in q)
        if knew <= sump:
            right = p[:]
            nr = sump
        elif knew > sumq:
            left = q[:]
            nl = sumq
        else:
            found = True
    if found:
        return trial
    cand = [y[i] - y[n - jj] for i in range(1, n) for jj in range(left[i], right[i] + 1)]
    kk = knew - (nl + 1)
    kk = min(max(kk, 0), len(cand) - 1)
    r_psort(cand, len(cand), kk)
    return cand[kk]
