"""``fma`` exacto (un redondeo) frente a aritmética racional."""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np

from pymrcd._fma import fma, fma_array


def _exact(a: float, b: float, c: float) -> float:
    if a == 0.0 or b == 0.0:
        return a * b + c
    v = Fraction(a) * Fraction(b) + Fraction(c)
    return 0.0 if v == 0 else float(v)


def test_fma_random_and_cancellation() -> None:
    rng = np.random.default_rng(11)
    a = rng.normal(size=4000) * 10.0 ** rng.integers(-30, 30, size=4000)
    b = rng.normal(size=4000) * 10.0 ** rng.integers(-30, 30, size=4000)
    c = rng.normal(size=4000) * 10.0 ** rng.integers(-60, 60, size=4000)
    c[::4] = -(a[::4] * b[::4])  # cancelación catastrófica: el caso que distingue fma
    c[1::8] = 0.0
    out = fma_array(a, b, c)
    for i in range(a.shape[0]):
        e = _exact(float(a[i]), float(b[i]), float(c[i]))
        assert out[i] == e
        assert fma(float(a[i]), float(b[i]), float(c[i])) == e


def test_fma_tie_cases_round_to_odd() -> None:
    # Productos con mitad exacta de ulp: sólo el redondeo a impar intermedio da el resultado
    # correcto.
    for k in range(1, 200):
        a = 1.0 + k * 2.0**-52
        b = 1.0 + 2.0**-53 * 3
        for c in (-1.0, 2.0**-60, -(2.0**-54), 1e-17 * k):
            assert fma(a, b, c) == _exact(a, b, c)
            assert fma_array(np.array([a]), np.array([b]), np.array([c]))[0] == _exact(a, b, c)


def test_fma_extreme_and_nonfinite() -> None:
    assert fma(1e300, 1e300, -math.inf) == -math.inf
    assert math.isnan(fma(math.inf, 0.0, 1.0))
    assert fma(math.inf, 2.0, 1.0) == math.inf
    assert fma(2.0, 3.0, math.nan) != fma(2.0, 3.0, math.nan)
    assert fma(1e-200, 1e-200, 1.0) == 1.0
    assert fma(1e-200, 1e-200, 0.0) == _exact(1e-200, 1e-200, 0.0)
    assert fma(1e200, 1e200, -1e300) == math.inf
    assert fma(-1e200, 1e200, 1e300) == -math.inf
    assert fma(1e-160, 1e-160, 1e-310) == _exact(1e-160, 1e-160, 1e-310)
    assert fma(3.0, 0.0, -0.0) == 0.0
    assert math.copysign(1.0, fma(-0.0, 1.0, -0.0)) == -1.0
    assert fma(2.0**1000, 0.5, -(2.0**999)) == 0.0
    out = fma_array(
        np.array([1e300, 2.0, np.inf]), np.array([1e300, 3.0, 1.0]), np.array([1.0, 1.0, 0.0])
    )
    assert out[0] == math.inf
    assert out[1] == 7.0
    assert out[2] == math.inf
