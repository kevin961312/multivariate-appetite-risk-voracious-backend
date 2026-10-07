"""Extensión C ``pymrcd._qn_ext`` (especificación §3.12.9, M5).

Tolerancias declaradas antes de comparar (§3.12.9 f), todas por bits (``view(np.uint64)``):

- ``qn0`` C frente al oráculo numpy anterior (``qn_python_ref``): exacta **salvo** ``a == 0 and
  b == 0`` con signo distinto (P5: manda R, que coincide con el C; ver ``test_qn.py``).
- ``R_qsort``, ``rPsort`` y ``whimed_i`` C frente a su transliteración literal (``r_sort_literal``):
  exacta en bits de **todo** el arreglo resultante (posición de cada ``±0``).
- ``U`` de OGK C frente a ``ogk.py`` anterior (``ogk_u_ref``): exacta sin excepción.
- Independencia de hilos, orden de columnas, *strides* y modo de depuración A1: exacta.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys

import numpy as np
import pytest

import r_sort_literal as lit
from fixtures_r import FIXTURES, INTER_CASES, Inter, read_csv_gz
from pymrcd import _qn_ext, cov_mrcd
from pymrcd.ogk import ogk_u
from pymrcd.qn import QN_CONSTANT, default_k, qn0_columns, qn_finite_c
from pymrcd.scaling import do_scale
from qn_python_ref import ogk_u_ref, qn0_columns_ref

THREADS = (1, 2, 3, 7, 17, 64)


def _bits(a: object) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(a, dtype=np.float64)).view(np.uint64)


def _same_but_zero_sign(a: np.ndarray, b: np.ndarray) -> tuple[int, int]:
    """(bits distintos, de ellos no explicados por el signo de un cero)."""
    diff = _bits(a) != _bits(b)
    zero_sign = (a == 0) & (b == 0)
    return int(diff.sum()), int((diff & ~zero_sign).sum())


# ----------------------------------------------------------------------------- salvaguardas


def test_build_info() -> None:
    info = _qn_ext.build_info()
    assert info["fp_contract_off_macro"] is True
    assert info["flt_eval_method"] == 0
    assert info["fast_math"] is False
    assert info["finite_math_only"] is False
    assert info["rounding_to_nearest"] is True
    assert info["subnormals_preserved"] is True
    assert info["optimize"] is True
    assert info["sizeof_double"] == 8
    assert info["sizeof_float"] == 4
    assert info["compiler"] in {"clang", "gcc"}


def test_import_without_extension_fails_explicitly() -> None:
    code = "import sys; sys.modules['pymrcd._qn_ext'] = None; import pymrcd"
    proc = subprocess.run(  # noqa: S603 - intérprete propio, argumentos fijos
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode != 0
    assert "ImportError" in proc.stderr
    assert "uv sync --reinstall-package pymrcd" in proc.stderr


def test_k_l_matches_python_formula() -> None:
    """``k_L`` (``qn_sn.c:154``) en C (sin contracción FMA) frente a la fórmula en Python."""
    ns = [*range(0, 20001), 46340, 46341, 65535, 100001, 1 << 20, 2**31 - 1]
    for n in ns:
        expected = int(5 - 1.75 * (n % 2) + ((0.3939 - 0.0067 * (n % 2)) * n) * (n - 1))
        assert _qn_ext._k_l(n) == expected, n
    with pytest.raises(ValueError, match="rango"):
        _qn_ext._k_l(-1)


def test_default_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYMRCD_NUM_THREADS", raising=False)
    affinity = getattr(os, "sched_getaffinity", None)
    expected = len(affinity(0)) if affinity is not None else os.cpu_count()
    assert _qn_ext.default_threads() == expected
    monkeypatch.setenv("PYMRCD_NUM_THREADS", "3")
    assert _qn_ext.default_threads() == 3
    for bad in ("0", "-2", "abc", "3x", "99999"):
        monkeypatch.setenv("PYMRCD_NUM_THREADS", bad)
        with pytest.raises(ValueError, match="PYMRCD_NUM_THREADS"):
            _qn_ext.default_threads()
        with pytest.raises(ValueError, match="PYMRCD_NUM_THREADS"):
            qn0_columns(np.ones((3, 2)))
    monkeypatch.setenv("PYMRCD_NUM_THREADS", "")
    assert _qn_ext.default_threads() == expected


def test_buffer_validation() -> None:
    x = np.ones((4, 3))
    out = np.empty(3)
    with pytest.raises(ValueError, match="float64"):
        _qn_ext.qn0_columns(np.ones((4, 3), dtype=np.float32), out, 1, 1)
    with pytest.raises(ValueError, match="float64"):
        _qn_ext.qn0_columns(np.ones(4), out, 1, 1)
    with pytest.raises(ValueError, match="elementos"):
        _qn_ext.qn0_columns(x, np.empty(2), 1, 1)
    with pytest.raises(ValueError, match="INT_MAX"):
        _qn_ext.qn0_columns(np.ones((1, 3)), out, 1, 1)
    with pytest.raises(ValueError, match="k debe"):
        _qn_ext.qn0_columns(x, out, 0, 1)
    with pytest.raises(ValueError, match="n_threads"):
        _qn_ext.qn0_columns(x, out, 1, -1)
    big = np.zeros(12)
    with pytest.raises(ValueError, match="compartir memoria"):
        _qn_ext.qn0_columns(big.reshape(4, 3), big[:3], 1, 1)
    with pytest.raises(ValueError, match="INT_MAX"):
        _qn_ext.ogk_u(np.ones((1, 3)), np.eye(3), QN_CONSTANT, 1.0, False, 1)
    with pytest.raises(ValueError, match="elementos"):
        _qn_ext.ogk_u(np.ones((4, 3)), np.eye(2), QN_CONSTANT, 1.0, False, 1)
    sq = np.eye(4)
    with pytest.raises(ValueError, match="compartir memoria"):
        _qn_ext.ogk_u(sq, sq, QN_CONSTANT, 1.0, False, 1)
    with pytest.raises(ValueError, match="n_threads"):
        _qn_ext.ogk_u(np.ones((4, 3)), np.eye(3), QN_CONSTANT, 1.0, False, -3)
    with pytest.raises(ValueError, match="int32"):
        _qn_ext._whimed_i(np.ones(3), np.ones(3, dtype=np.int64))
    with pytest.raises(ValueError, match="longitud"):
        _qn_ext._whimed_i(np.ones(3), np.ones(2, dtype=np.int32))
    with pytest.raises(ValueError, match="k < n"):
        _qn_ext._rpsort(np.ones(3), 3)
    with pytest.raises(ValueError, match="float64"):
        _qn_ext._r_qsort(np.ones((2, 2)))


def test_infinite_values_in_ogk_pairs() -> None:
    y = np.ones((5, 3))
    y[0, 1] = np.inf
    with pytest.raises(ValueError, match="infinitos"):
        ogk_u(y)
    y[1, 1] = np.nan  # NaN prevalece: U con NaN, sin error
    u = ogk_u(y)
    assert np.isnan(u[1, 0])
    assert np.isnan(u[0, 1])
    assert not np.isnan(u[2, 0])


def test_ogk_small_cases() -> None:
    assert np.array_equal(ogk_u(np.ones((5, 1))), np.eye(1))
    one = ogk_u(np.array([[1.0, 2.0, 3.0]]))
    assert np.array_equal(one, np.eye(3))  # n == 1: Qn = 0 (qnsn.R:29)
    empty = ogk_u(np.zeros((0, 2)))
    assert np.isnan(empty[1, 0])
    assert np.isnan(empty[0, 1])


# ----------------------------------------------------------------------------- primitivas de R


def _vectors(seed: int, count: int) -> list[np.ndarray]:
    """Vectores con ``±0``, empates y longitudes ``1..200``."""
    rng = np.random.default_rng(seed)
    out = []
    for t in range(count):
        n = int(rng.integers(1, 201))
        kind = t % 4
        if kind == 0:
            v = rng.integers(-3, 4, size=n).astype(np.float64)
        elif kind == 1:
            v = np.where(rng.random(n) < 0.7, 0.0, rng.normal(size=n))
        elif kind == 2:
            v = rng.normal(size=n)
        else:
            v = np.round(rng.standard_t(3, size=n), 1)
        v = np.where(rng.random(n) < 0.5, -v, v)  # ceros con signo aleatorio
        out.append(np.ascontiguousarray(v, dtype=np.float64))
    return out


def test_r_qsort_literal_bits() -> None:
    for v in _vectors(1, 600):
        c = v.copy()
        _qn_ext._r_qsort(c)
        ref = v.tolist()
        lit.r_qsort(ref, 1, len(ref))
        assert np.array_equal(_bits(c), _bits(ref))


def test_rpsort_literal_bits() -> None:
    rng = np.random.default_rng(2)
    for v in _vectors(2, 600):
        k = int(rng.integers(0, v.shape[0]))
        c = v.copy()
        _qn_ext._rpsort(c, k)
        ref = v.tolist()
        lit.r_psort(ref, len(ref), k)
        assert np.array_equal(_bits(c), _bits(ref))


def test_whimed_i_literal_bits() -> None:
    rng = np.random.default_rng(3)
    for v in _vectors(3, 600):
        w = rng.integers(1, 20, size=v.shape[0]).astype(np.int32)
        a_c, w_c = v.copy(), w.copy()
        res = _qn_ext._whimed_i(a_c, w_c)
        a_r, w_r = v.tolist(), [int(t) for t in w]
        ref = lit.whimed_i(a_r, w_r, len(a_r))
        assert _bits(res) == _bits(ref)
        assert np.array_equal(_bits(a_c), _bits(a_r))
        assert np.array_equal(w_c, np.array(w_r, dtype=np.int32))
    assert math.isnan(_qn_ext._whimed_i(np.empty(0), np.empty(0, dtype=np.int32)))


# ----------------------------------------------------------------------------- C ↔ oráculo


def _oracle_columns() -> dict[str, np.ndarray]:
    """Al menos 20 000 columnas de las familias de §3.12.9 f."""
    rng = np.random.default_rng(20261007)
    fams: dict[str, list[np.ndarray]] = {}
    sizes = (2, 3, 4, 5, 7, 8, 11, 12, 13, 20, 33, 50, 101, 200)
    for n in sizes:
        m = 300
        fams.setdefault("normal", []).append(rng.normal(size=(n, m)))
        fams.setdefault("t3", []).append(rng.standard_t(3, size=(n, m)))
        fams.setdefault("enteros", []).append(rng.integers(-5, 6, size=(n, m)).astype(np.float64))
        zeros = np.where(rng.random((n, m)) < 0.9, 0.0, rng.normal(size=(n, m)))
        fams.setdefault("ceros90", []).append(np.where(rng.random((n, m)) < 0.5, -zeros, zeros))
        pm0 = np.where(rng.random((n, m)) < 0.5, -0.0, 0.0)
        pm0 = np.where(rng.random((n, m)) < 0.3, rng.integers(-2, 3, size=(n, m)), pm0)
        fams.setdefault("mas_menos_cero", []).append(pm0.astype(np.float64))
        fams.setdefault("escala_1e-300", []).append(rng.normal(size=(n, 100)) * 1e-300)
        fams.setdefault("escala_1e300", []).append(rng.normal(size=(n, 100)) * 1e300)
    for case in ("C7", "C11", "C8"):
        y = Inter(case).get("r6_x")
        ii, jj = np.tril_indices(y.shape[1], -1)
        sel = np.arange(0, ii.shape[0], max(1, ii.shape[0] // 400))
        fams.setdefault("pares_golden", []).extend(
            [y[:, ii[sel]] + y[:, jj[sel]], y[:, ii[sel]] - y[:, jj[sel]]]
        )
    return {f"{k}/{i}": a for k, v in fams.items() for i, a in enumerate(v)}


def test_c_matches_python_oracle_20000_columns() -> None:
    total = 0
    zero_sign_only = 0
    for name, x in _oracle_columns().items():
        got = qn0_columns(x)
        with np.errstate(over="ignore"):
            ref = qn0_columns_ref(x)
        n_diff, n_unexplained = _same_but_zero_sign(got, ref)
        assert n_unexplained == 0, name
        zero_sign_only += n_diff
        total += x.shape[1]
    assert total >= 20000
    # El oráculo numpy coloca los ±0 de otra forma (P5): se registra, no falla.
    assert zero_sign_only >= 0


def test_c_matches_literal_on_signed_zeros() -> None:
    """Donde C y el oráculo numpy pueden diferir (signo del cero), C coincide con el literal."""
    rng = np.random.default_rng(15)
    for _ in range(300):
        n = int(rng.integers(2, 41))
        v = np.where(rng.random(n) < rng.uniform(0.3, 0.95), 0.0, rng.integers(-3, 4, size=n))
        v = np.where(rng.random(n) < 0.5, -v, v).astype(np.float64)
        assert _bits(qn0_columns(v[:, None])[0]) == _bits(lit.qn0(v.tolist(), default_k(n)))


# ----------------------------------------------------------------------------- OGK


def _golden_cases() -> list[str]:
    dirs = (d for d in FIXTURES.iterdir() if d.name.startswith("C"))
    return sorted(d.name for d in dirs if (d / "manifest.json").exists())


def _ogk_input(case: str) -> np.ndarray:
    """Entrada de ``ogk_u`` del caso: ``r6_x`` de R si está, si no ``r6.x`` de ``cov_mrcd``."""
    if case in INTER_CASES and Inter(case).has("r6_x"):
        return Inter(case).get("r6_x")
    root = FIXTURES / case
    man = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    x = read_csv_gz(root / man["entrada"]["archivo"])
    par = man["parametros"]
    r6 = cov_mrcd(x, alpha=float(par["alpha"]), target=str(par["target"])).detail.r6
    assert r6 is not None
    return r6.x


@pytest.mark.parametrize("case", _golden_cases())
def test_ogk_u_matches_python_oracle_on_golden(case: str) -> None:
    """``U`` C frente a ``ogk_u_ref``: completa con ``p <= 60``; si no, un bloque de 60 columnas.

    Cada par es independiente, así que el bloque ``U[S, S]`` es la ``U`` de ``y[:, S]``; la ``U``
    completa de todos los casos se compara además con la instantánea anterior a M5 (informe).
    """
    y = _ogk_input(case)
    u = ogk_u(y)
    p = y.shape[1]
    sel = np.arange(p) if p <= 60 else np.linspace(0, p - 1, 60).astype(np.int64)
    np.testing.assert_array_equal(_bits(u[np.ix_(sel, sel)]), _bits(ogk_u_ref(y[:, sel])))


def test_ogk_u_n40_p600() -> None:
    rng = np.random.default_rng(600)
    y = do_scale(rng.standard_t(3, size=(40, 600))).x
    u = ogk_u(y)
    assert np.array_equal(u, u.T)
    assert np.all(np.diag(u) == 1)
    sel = np.sort(rng.choice(600, size=90, replace=False))
    np.testing.assert_array_equal(_bits(u[np.ix_(sel, sel)]), _bits(ogk_u_ref(y[:, sel])))
    assert not np.signbit(u[u == 0]).any()  # U nunca es -0 (§3.12.9 c)


def test_ogk_u_small_n_factor() -> None:
    rng = np.random.default_rng(9)
    for n in (2, 3, 7, 12, 13, 14):
        y = rng.normal(size=(n, 9))
        np.testing.assert_array_equal(_bits(ogk_u(y)), _bits(ogk_u_ref(y)))
    assert qn_finite_c(13) != 1.0


# ----------------------------------------------------------------------------- determinismo


def _zero_heavy(n: int, m: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.where(rng.random((n, m)) < 0.6, 0.0, rng.integers(-3, 4, size=(n, m)))
    x = np.where(rng.random((n, m)) < 0.5, -x, x).astype(np.float64)
    x[:, ::5] = rng.normal(size=(n, x[:, ::5].shape[1]))
    return x


@pytest.mark.parametrize("m", [1, 7, 1000, 10007])
def test_threads_and_order_do_not_change_bits(m: int) -> None:
    x = _zero_heavy(23, m, m)
    base = _bits(qn0_columns(x, n_threads=1))
    for t in THREADS[1:]:
        assert np.array_equal(_bits(qn0_columns(x, n_threads=t)), base), t
    rev = qn0_columns(np.ascontiguousarray(x[:, ::-1]), n_threads=3)
    assert np.array_equal(_bits(rev[::-1]), base)


def test_poison_mode_a1_does_not_change_bits() -> None:
    x = _zero_heavy(31, 500, 4)
    out_a = np.empty(500)
    out_b = np.empty(500)
    _qn_ext.qn0_columns(x, out_a, default_k(31), 4)
    _qn_ext.qn0_columns(x, out_b, default_k(31), 4, True)
    assert np.array_equal(_bits(out_a), _bits(out_b))
    y = do_scale(np.random.default_rng(5).normal(size=(30, 25))).x
    u_a = np.eye(25)
    u_b = np.eye(25)
    _qn_ext.ogk_u(y, u_a, QN_CONSTANT, qn_finite_c(30), False, 3)
    _qn_ext.ogk_u(y, u_b, QN_CONSTANT, qn_finite_c(30), False, 5, True)
    assert np.array_equal(_bits(u_a), _bits(u_b))


def test_strides_do_not_change_bits() -> None:
    base = _zero_heavy(40, 60, 6)
    expected = _bits(qn0_columns(base))
    assert np.array_equal(_bits(qn0_columns(np.asfortranarray(base))), expected)
    big = np.zeros((80, 180))
    big[::2, ::3] = base
    assert np.array_equal(_bits(qn0_columns(big[::2, ::3])), expected)
    flipped = np.ascontiguousarray(base[::-1, ::-1])
    assert np.array_equal(_bits(qn0_columns(flipped[::-1, ::-1])), expected)
    y = do_scale(np.random.default_rng(8).normal(size=(30, 20))).x
    u = _bits(ogk_u(y))
    assert np.array_equal(_bits(ogk_u(np.asfortranarray(y))), u)
    assert np.array_equal(_bits(ogk_u(np.ascontiguousarray(y[::-1])[::-1])), u)


def test_ogk_threads_do_not_change_bits() -> None:
    y = do_scale(np.random.default_rng(11).normal(size=(50, 45))).x
    base = _bits(ogk_u(y, n_threads=1))
    for t in THREADS[1:]:
        assert np.array_equal(_bits(ogk_u(y, n_threads=t)), base), t


def _flatten(obj: object, prefix: str, out: dict[str, np.ndarray]) -> None:
    if obj is None:
        return
    if isinstance(obj, np.ndarray):
        out[prefix] = obj
    elif isinstance(obj, tuple) and hasattr(obj, "_fields"):
        for name in obj._fields:
            _flatten(getattr(obj, name), f"{prefix}/{name}", out)
    elif isinstance(obj, tuple | list):
        for i, item in enumerate(obj):
            _flatten(item, f"{prefix}/{i}", out)
    elif hasattr(obj, "__dataclass_fields__"):
        for name in obj.__dataclass_fields__:
            _flatten(getattr(obj, name), f"{prefix}/{name}", out)
    elif isinstance(obj, int | float | np.number):
        out[prefix] = np.asarray(obj)


@pytest.mark.parametrize("case", ["C1", "C11"])
def test_cov_mrcd_one_vs_many_threads(case: str) -> None:
    root = FIXTURES / case
    man = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    x = read_csv_gz(root / man["entrada"]["archivo"])
    one: dict[str, np.ndarray] = {}
    many: dict[str, np.ndarray] = {}
    _flatten(cov_mrcd(x, n_threads=1), "r", one)
    _flatten(cov_mrcd(x, n_threads=8), "r", many)
    assert one.keys() == many.keys()
    assert len(one) > 50
    for key, val in one.items():
        assert val.dtype == many[key].dtype, key
        assert val.tobytes() == many[key].tobytes(), key
