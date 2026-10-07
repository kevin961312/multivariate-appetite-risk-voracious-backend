"""``uniroot``/``R_zeroin2`` portados iteración por iteración, contra los fixtures de R."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pytest

from fixtures_r import Case, assert_r_equal, case_params
from pymrcd._errors import RError
from pymrcd._rbase import r_pow
from pymrcd._rzeroin import UNIROOT_TOL, _fcn2, r_uniroot, r_zeroin2


def _fncond(e1: float, ep: float, maxcond: float) -> Callable[[float], float]:
    # detmrcd.R:479-484 (aritmética de R elemento a elemento, sin fusión).
    def f(rho: float) -> float:
        return (rho + (1 - rho) * ep) / (rho + (1 - rho) * e1) - maxcond

    return f


_NAMED: dict[str, Callable[[float], float]] = {
    "x^3 - 2": lambda x: r_pow(x, 3.0) - 2,
    "cos(x) - x": lambda x: math.cos(x) - x,
    "exp(x) - 5": lambda x: math.exp(x) - 5,
    "x*x - 2": lambda x: x * x - 2,
    "3*x - 1": lambda x: 3 * x - 1,
    "x - 1e-5": lambda x: x - 1e-5,
    "x*x + 1": lambda x: x * x + 1,
    "(x-0.3)^3 (raiz triple)": lambda x: r_pow(x - 0.3, 3.0),
    "tanh(x) - 0.5": lambda x: math.tanh(x) - 0.5,
    "1/x - 7": lambda x: 1 / x - 7,
}


def _function(case: Case) -> Callable[[float], float]:
    if "e1" in case.inputs:
        return _fncond(
            case.inputs["e1"].item(), case.inputs["ep"].item(), case.inputs["maxcond"].item()
        )
    return _NAMED[str(case.extra["f"])]


@pytest.mark.parametrize("case", case_params("uniroot"))
def test_uniroot(case: Case) -> None:
    f = _function(case)
    lower = case.inputs["lower"].item() if "lower" in case.inputs else float(case.extra["lower"])
    upper = case.inputs["upper"].item() if "upper" in case.inputs else float(case.extra["upper"])
    path = int(case.outputs["path"].item())
    if "f_lower" in case.outputs:
        assert_r_equal(f(lower), case.outputs["f_lower"].item(), "E", case.id)
        assert_r_equal(f(upper), case.outputs["f_upper"].item(), "E", case.id)
    if path == 2:
        with pytest.raises(RError):
            r_uniroot(f, lower, upper)
        return
    res = r_uniroot(f, lower, upper)
    assert_r_equal(res.root, case.outputs["root"].item(), "E", case.id)
    assert_r_equal(res.f_root, case.outputs["f_root"].item(), "E", case.id)
    assert res.iter == int(case.outputs["iter"].item())
    assert_r_equal(res.estim_prec, case.outputs["estim_prec"].item(), "E", case.id)


def test_tolerance_constant() -> None:
    assert np.finfo(np.float64).eps ** 0.25 == UNIROOT_TOL


def test_uniroot_errors() -> None:
    with pytest.raises(RError, match="lower < upper"):
        r_uniroot(lambda x: x, 1.0, 0.0)
    with pytest.raises(RError, match=r"f\.lower"):
        r_uniroot(lambda x: math.nan if x < 0.5 else x, 0.0, 1.0)
    with pytest.raises(RError, match=r"f\.upper"):
        r_uniroot(lambda x: math.nan if x > 0.5 else x - 0.2, 0.0, 1.0)
    with pytest.raises(RError, match="opposite sign"):
        r_uniroot(lambda x: x * x + 1, 0.0, 1.0)


def test_zeroin_endpoint_roots_and_nonconvergence() -> None:
    assert r_zeroin2(lambda x: x, 0.0, 1.0, 0.0, 1.0, 1e-8, 10) == (0.0, 0, 0.0)
    assert r_zeroin2(lambda x: x - 1, 0.0, 1.0, -1.0, 0.0, 1e-8, 10) == (1.0, 0, 0.0)
    res = r_zeroin2(lambda x: math.cos(x) - x, 0.0, 1.0, 1.0, math.cos(1.0) - 1.0, 1e-300, 2)
    assert res.iterations == -1
    u = r_uniroot(lambda x: math.cos(x) - x, 0.0, 1.0, tol=1e-300, maxiter=3)
    assert not u.converged
    assert u.iter == 3
    # Extremos infinitos se truncan a ±DBL_MAX (nlm.R:75-78).
    v = r_uniroot(lambda x: -math.inf if x == 0.0 else x - 0.5, 0.0, 1.0)
    assert abs(v.root - 0.5) < 1e-3


def test_fcn2_replacements() -> None:
    big = np.finfo(np.float64).max
    assert _fcn2(lambda _x: -math.inf, 0.0) == -big
    assert _fcn2(lambda _x: math.inf, 0.0) == big
    assert _fcn2(lambda _x: math.nan, 0.0) == big
    assert _fcn2(lambda x: x, 2.0) == 2.0
