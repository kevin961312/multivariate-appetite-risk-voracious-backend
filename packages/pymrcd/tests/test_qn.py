"""``Qn`` de robustbase: fixtures de R (bit a bit, incluido el signo del cero) y oráculos.

Tolerancias (especificación §3.12.9 f, declaradas antes de comparar): ``qn0``/``Qn`` frente a R,
**exacta en bits incluido el signo del cero**, en cualquier plataforma (sin libm ni BLAS); se
compara con ``view(np.uint64)``, que distingue ``±0``. Los fixtures antiguos (sin ``.bits``) se
comparan como hasta ahora (``assert_r_equal``, clase E).
"""

from __future__ import annotations

import gzip
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import r_sort_literal as lit
from fixtures_r import PRIMITIVAS, Case, assert_r_equal, case_params
from pymrcd._rbase import r_qnorm
from pymrcd.qn import (
    QN_CONSTANT,
    QN_SMALL_N_FACTORS,
    default_k,
    qn,
    qn0_columns,
    qn_columns,
    qn_finite_c,
    threads_arg,
)
from qn_python_ref import qn0_columns_ref

QN_DIR = PRIMITIVAS / "Qn"


def _f32(z: float) -> float:
    return float(np.float32(z))


def _bits(a: object) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(a, dtype=np.float64)).view(np.uint64)


def qn0_oracle(x: np.ndarray) -> float:
    """Oráculo exacto O(n²) (decisión M2): k-ésimo de ``|x_i - x_j|``, ``i < j``."""
    n = x.shape[0]
    d = np.abs(x[:, None] - x[None, :])[np.triu_indices(n, 1)]
    return float(np.sort(d)[default_k(n) - 1])


def _read_bits(path: Path) -> np.ndarray:
    """Lee un ``.bits.csv.gz`` (``HEX,SIGNO``; ``HEX = sprintf("%a")`` de R)."""
    with gzip.open(path, "rt", encoding="ascii") as fh:
        rows = [line.split(",") for line in fh.read().splitlines() if line]
    vals = np.array([float.fromhex(h) for h, _ in rows], dtype=np.float64)
    signs = np.array([int(s) for _, s in rows], dtype=np.int64)
    assert np.array_equal(np.signbit(vals).astype(np.int64), signs), path.name
    return vals


def _bits_cases() -> list[Any]:
    index = json.loads((QN_DIR / "indice.json").read_text(encoding="utf-8"))
    out = []
    for c in index["casos"]:
        xin = c["entradas"]["x"]
        if "archivo_bits" not in xin:
            continue
        out.append(pytest.param(c, id=f"Qn-bits-{c['id']}"))
    return out


def qn_with_k(x: np.ndarray, k: int) -> float:
    """``Qn(x, k = k, finite.corr = FALSE)`` (``qnsn.R:41-49`` con ``k`` explícito).

    ``constant = 1/(sqrt(2) * qnorm(((k - 1/2)/nn2 + 1)/2))`` con ``nn2 = choose(n, 2)``
    (``:32``, ``:45``) y ``r = constant * qn0`` sin corrección (``:51``, ``finite.corr = FALSE``).
    """
    n = x.shape[0]
    nn2 = float(math.comb(n, 2))
    q = float(r_qnorm(np.array([((k - 0.5) / nn2 + 1) / 2]))[0])
    constant = 1 / (math.sqrt(2) * q)
    return constant * float(qn0_columns(x[:, None], k=k)[0])


# ----------------------------------------------------------------------------- fixtures de R


@pytest.mark.parametrize("case", case_params("Qn"))
def test_qn_fixture(case: Case) -> None:
    x = case.inputs["x"].ravel()
    got = qn_with_k(x, int(case.extra["k"])) if "k" in case.extra else qn(x)
    assert_r_equal(got, case.outputs["qn"].item(), "E", case.id)
    rama = case.extra.get("rama")
    if x.shape[0] >= 2 and rama in {"double", "float32"}:
        raw = qn0_columns(x[:, None])[0]
        d = qn0_oracle(x)
        # M2: el oráculo acepta d y f32(d); la rama de R fija cuál de los dos.
        assert raw in (d, _f32(d))
        assert (raw == d) if rama == "double" else (raw == _f32(d) != d or raw == d == _f32(d))


@pytest.mark.parametrize("meta", _bits_cases())
def test_qn_fixture_bits(meta: dict[str, Any]) -> None:
    """Los 188 casos con ``.bits.csv.gz``: exactos en bits, incluido el signo del cero."""
    x = _read_bits(QN_DIR / meta["entradas"]["x"]["archivo_bits"])
    expected = _read_bits(QN_DIR / meta["salidas"]["qn"]["archivo_bits"])
    extra = meta["extra"]
    assert float.fromhex(extra["salida_hex"]) == expected[0] or expected[0] == 0
    assert int(np.signbit(expected[0])) == int(extra["salida_signo_bit"])
    if "parametros" in meta:
        k = int(meta["parametros"]["k"])
        assert meta["parametros"]["finite.corr"] is False
        assert lit.qn0(x.tolist(), k) == qn0_columns(x[:, None], k=k)[0]
        got = qn_with_k(x, k)
    else:
        got = qn(x)
    assert _bits(got) == _bits(expected[0]), (meta["id"], got, expected[0])


def test_bits_cases_count() -> None:
    assert len(_bits_cases()) == 188


# ----------------------------------------------------------------------------- oráculos


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 17, 20, 31, 50, 64, 101])
def test_c_equals_literal_and_oracle(n: int) -> None:
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
            v = np.where(rng.random(n) < 0.5, -v, v)  # ±0
        cols.append(v)
    x = np.column_stack(cols)
    got = qn0_columns(x)
    for j in range(x.shape[1]):
        lit_val = lit.qn0(x[:, j].tolist(), default_k(n))
        assert _bits(got[j]) == _bits(lit_val), (n, j)
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
    assert [default_k(n) for n in (2, 3, 4, 5, 10, 11)] == [1, 1, 3, 3, 15, 15]


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
    with pytest.raises(ValueError, match="infinitos"):
        qn0_columns(np.array([[1.0, 2.0], [np.inf, 3.0], [4.0, -np.inf]]))
    # NaN prevalece sobre Inf en la misma columna (qnsn.R:27).
    assert math.isnan(qn(np.array([1.0, np.inf, np.nan, 2.0])))
    with pytest.raises(ValueError, match="matriz"):
        qn_columns(np.ones(3))
    with pytest.raises(ValueError, match="matriz"):
        qn0_columns(np.ones(3))
    with pytest.raises(ValueError, match="n >= 2"):
        qn0_columns(np.ones((1, 3)))
    with pytest.raises(ValueError, match="choose"):
        qn0_columns(np.ones((4, 2)), k=7)
    with pytest.raises(ValueError, match="choose"):
        qn0_columns(np.ones((4, 2)), k=0)
    assert qn(np.zeros(20)) == 0.0
    huge = np.array([1e308, -1e308, 1.5e308, 0.0, 1e300])
    assert qn(huge) > 0  # restas que desbordan: IEEE como en C
    assert qn0_columns(np.zeros((5, 0))).shape == (0,)


def test_threads_arg() -> None:
    assert threads_arg(None) == 0
    assert threads_arg(3) == 3
    for bad in (0, -1):
        with pytest.raises(ValueError, match="n_threads"):
            threads_arg(bad)
    with pytest.raises(ValueError, match="n_threads"):
        qn_columns(np.ones((3, 2)), n_threads=0)


def test_c_matches_python_oracle_generic() -> None:
    """C frente al oráculo numpy en columnas genéricas (sin ceros): bits idénticos."""
    rng = np.random.default_rng(77)
    x = rng.normal(size=(37, 400))
    np.testing.assert_array_equal(_bits(qn0_columns(x)), _bits(qn0_columns_ref(x)))
