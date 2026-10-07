"""``Qn`` de robustbase: fixtures de R, oráculo O(n²) (M2) y port literal de ``qn0`` de
referencia."""

from __future__ import annotations

import math

import numpy as np
import pytest

from fixtures_r import Case, assert_r_equal, case_params
from pymrcd import qn as qn_mod
from pymrcd.qn import QN_CONSTANT, QN_SMALL_N_FACTORS, qn, qn0_columns, qn_columns, qn_finite_c


def _f32(z: float) -> float:
    return float(np.float32(z))


def qn0_literal(x: np.ndarray) -> float:
    """Port escalar literal de ``qn0`` (``qn_sn.c:133-296``) para validar la versión vectorizada."""
    n = x.shape[0]
    y = sorted(x.tolist())
    nn2 = n * (n + 1) // 2
    n2 = n * n
    k = math.comb(n // 2 + 1, 2)
    k_l = int(5 - 1.75 * (n % 2) + ((0.3939 - 0.0067 * (n % 2)) * n) * (n - 1))
    h = n // 2 + 1
    nl, nr, knew = nn2, n2, k + nn2
    left = [n - i + 1 for i in range(n)]
    right = [n] * n if k >= k_l else [n if i <= h else n - (i - h) for i in range(n)]
    found = False
    trial = math.nan
    p = [0] * n
    q = [0] * n
    while not found and nr - nl > n:
        work: list[float] = []
        wgt: list[int] = []
        for i in range(1, n):
            if left[i] <= right[i]:
                w = right[i] - left[i] + 1
                jh = left[i] + w // 2
                work.append(_f32(y[i] - y[n - jh]))
                wgt.append(w)
        order = sorted(range(len(work)), key=lambda t: work[t])
        tot = sum(wgt)
        acc = 0
        for t in order:
            acc += wgt[t]
            if 2 * acc > tot:
                trial = work[t]
                break
        j = 0
        for i in range(n - 1, -1, -1):
            while j < n and _f32(y[i] - y[n - j - 1]) < trial:
                j += 1
            p[i] = j
        j = n + 1
        for i in range(n):
            while _f32(y[i] - y[n - j + 1]) > trial:
                j -= 1
            q[i] = j
        sump = sum(p)
        sumq = sum(q) - n
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
    kk = min(max(knew - (nl + 1), 0), len(cand) - 1)
    return sorted(cand)[kk]


def qn0_oracle(x: np.ndarray) -> float:
    """Oráculo exacto O(n²) (decisión M2): k-ésimo de ``|x_i - x_j|``, ``i < j``."""
    n = x.shape[0]
    d = np.abs(x[:, None] - x[None, :])[np.triu_indices(n, 1)]
    k = math.comb(n // 2 + 1, 2)
    return float(np.sort(d)[k - 1])


# ----------------------------------------------------------------------------- fixtures de R


@pytest.mark.parametrize("case", case_params("Qn"))
def test_qn_fixture(case: Case) -> None:
    x = case.inputs["x"].ravel()
    assert_r_equal(qn(x), case.outputs["qn"].item(), "E", case.id)
    rama = case.extra.get("rama")
    if x.shape[0] >= 2 and rama in {"double", "float32"}:
        raw = qn0_columns(x[:, None])[0]
        d = qn0_oracle(x)
        # M2: el oráculo acepta d y f32(d); la rama de R fija cuál de los dos.
        assert raw in (d, _f32(d))
        assert (raw == d) if rama == "double" else (raw == _f32(d) != d or raw == d == _f32(d))


# ----------------------------------------------------------------------------- equivalencia y
# oráculo


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 17, 20, 31, 50, 64, 101])
def test_vectorized_equals_literal_and_oracle(n: int) -> None:
    rng = np.random.default_rng(1000 + n)
    cols = []
    for r in range(40):
        kind = r % 5
        if kind == 0:
            v = rng.normal(size=n)
        elif kind == 1:
            v = np.round(rng.normal(size=n), 1)
        elif kind == 2:
            v = rng.integers(0, 4, size=n).astype(np.float64)
        elif kind == 3:
            v = rng.exponential(size=n) * 10.0 ** rng.integers(-4, 4)
        else:
            v = np.where(rng.random(n) < 0.6, 0.0, rng.normal(size=n))
        cols.append(v)
    x = np.column_stack(cols)
    got = qn0_columns(x)
    for j in range(x.shape[1]):
        lit = qn0_literal(x[:, j])
        assert got[j] == lit or (math.isnan(got[j]) and math.isnan(lit))
        d = qn0_oracle(x[:, j])
        assert got[j] in (d, _f32(d))


def test_constants_and_small_n() -> None:
    assert QN_CONSTANT == 2.21914
    assert len(QN_SMALL_N_FACTORS) == 11
    x = np.array([1.0, 3.0, 4.0, 10.0])
    assert qn(x) == QN_CONSTANT * qn0_columns(x[:, None])[0] * QN_SMALL_N_FACTORS[2]
    y = np.arange(13.0) ** 1.5
    assert qn(y) == QN_CONSTANT * qn0_columns(y[:, None])[0] / qn_finite_c(13)
    assert qn_finite_c(14) == (3.67561 + (1.9654 + (6.987 - 77 / 14) / 14) / 14) / 14 + 1


def test_qn_edge_cases() -> None:
    assert math.isnan(qn(np.array([])))
    assert qn(np.array([5.0])) == 0.0
    assert math.isnan(qn(np.array([np.nan])))
    assert math.isnan(qn(np.array([1.0, np.nan, 3.0])))
    out = qn_columns(np.array([[1.0, np.nan], [2.0, 1.0], [4.0, 2.0]]))
    assert math.isfinite(out[0])
    assert math.isnan(out[1])
    assert np.isnan(qn_columns(np.zeros((0, 3)))).all()
    with pytest.raises(ValueError, match="infinitos"):
        qn(np.array([1.0, np.inf, 2.0]))
    with pytest.raises(ValueError, match="matriz"):
        qn_columns(np.ones(3))
    assert qn(np.zeros(20)) == 0.0
    huge = np.array([1e308, -1e308, 1.5e308, 0.0, 1e300])
    assert qn(huge) > 0  # restas que desbordan: IEEE como en C


def test_chunking_matches_single_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(30, 25))
    full = qn0_columns(x)
    monkeypatch.setattr(qn_mod, "_CHUNK_ELEMENTS", 60)
    np.testing.assert_array_equal(qn0_columns(x), full)


def test_whimed_and_kth_without_candidates() -> None:
    work = np.full((3, 1), np.inf)
    wgt = np.zeros((3, 1), dtype=np.int64)
    assert np.isnan(qn_mod._whimed_columns(work, wgt)).all()
    y = np.sort(np.array([[1.0], [2.0], [3.0]]), axis=0)
    left = np.array([[4], [4], [4]], dtype=np.int64)
    right = np.array([[3], [3], [3]], dtype=np.int64)
    assert np.isnan(qn_mod._kth_exact(y, left, right, np.array([0]))).all()
