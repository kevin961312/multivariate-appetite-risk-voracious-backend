"""``.MCDcons`` (``scfac``) y el port de ``nmath`` (``qchisq``, ``pgamma``…) contra R, bit a bit.

Decisión del dueño (revisión de P3): ``scfac`` debe ser bit a bit con R, así que ``qchisq`` y
``pgamma`` se portan de ``nmath`` (``pymrcd._nmath``). En la plataforma de referencia se exige
igualdad exacta; fuera de ella, las tolerancias fijadas aquí antes de comparar: clase ``L`` (libm,
rtol 1e-15) para ``qchisq``/``pgamma``/``dgamma``/``lgamma``/``pnorm``/``dnorm``/``dpois`` y
``scfac`` (rtol 1e-14) para ``.MCDcons``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import nmath_r_values as rv
from fixtures_r import Case, assert_r_equal, case_params
from pymrcd import _nmath as nm
from pymrcd.consistency import mcd_cons

_H = float.fromhex


def _col(values: tuple[tuple[object, ...], ...], j: int) -> np.ndarray:
    return np.array([_H(str(row[j])) for row in values])


# ------------------------------------------------------------------------- fixtures de primitivas


@pytest.mark.parametrize("case", case_params("MCDcons"))
def test_mcd_cons(case: Case) -> None:
    p = case.inputs["p"].ravel()
    alpha = case.inputs["alpha"].ravel()
    got = np.array([mcd_cons(int(pp), float(a)) for pp, a in zip(p, alpha, strict=True)])
    assert_r_equal(got, case.outputs["scfac"].ravel(), "scfac", case.id)


@pytest.mark.parametrize("case", case_params("qchisq"))
def test_qchisq(case: Case) -> None:
    alpha = case.inputs["alpha"].ravel()
    p = case.inputs["p"].ravel()
    got = np.array([nm.qchisq(float(a), float(d)) for a, d in zip(alpha, p, strict=True)])
    assert_r_equal(got, case.outputs["q"].ravel(), "L", case.id)


@pytest.mark.parametrize("case", case_params("pgamma"))
def test_pgamma(case: Case) -> None:
    q = case.inputs["q"].ravel()
    shape = case.inputs["shape"].ravel()
    got = np.array([nm.pgamma(float(x), float(s)) for x, s in zip(q, shape, strict=True)])
    assert_r_equal(got, case.outputs["pg"].ravel(), "L", case.id)


def test_mcd_cons_known_value() -> None:
    # robustbase-0.99-6/R/covMcd.R:602-607 con p = 1, alpha = 0.5.
    q = nm.qchisq(0.5, 1)
    assert mcd_cons(1, 0.5) == 1 / (nm.pgamma(q / 2, 1 / 2 + 1) / 0.5)


# ----------------------------------------------------------------------------- ramas (valores de R)


@pytest.mark.parametrize("table", ["QCHISQ", "QCHISQ2", "QCHISQ3"])
def test_qchisq_branches(table: str) -> None:
    rows = getattr(rv, table)
    got = np.array([nm.qchisq(_H(p), _H(d)) for p, d, _ in rows])
    assert_r_equal(got, _col(rows, 2), "L", table)


@pytest.mark.parametrize("table", ["PGAMMA", "PGAMMA2"])
def test_pgamma_branches(table: str) -> None:
    rows = getattr(rv, table)
    got = np.array([nm.pgamma(_H(x), _H(s)) for x, s, _, _ in rows])
    assert_r_equal(got, _col(rows, 2), "L", table)
    got_log = np.array([nm.pgamma(_H(x), _H(s), log_p=True) for x, s, _, _ in rows])
    assert_r_equal(got_log, _col(rows, 3), "L", f"{table} log")


def test_pgamma_edges() -> None:
    rows = rv.PGAMMA3
    got = np.array([nm.pgamma(_H(x), _H(s), _H(sc)) for x, s, sc, _, _ in rows])
    assert_r_equal(got, _col(rows, 3), "L", "PGAMMA3")
    got_log = np.array([nm.pgamma(_H(x), _H(s), _H(sc), log_p=True) for x, s, sc, _, _ in rows])
    assert_r_equal(got_log, _col(rows, 4), "L", "PGAMMA3 log")


def test_dgamma_log() -> None:
    rows = rv.DGAMMA_LOG_SCALE2
    got = np.array([nm.dgamma_log(_H(x), _H(s), 2.0) for x, s, _ in rows])
    assert_r_equal(got, _col(rows, 2), "L", "DGAMMA")
    rows3 = rv.DGAMMA3
    got3 = np.array([nm.dgamma_log(_H(x), _H(s), _H(sc)) for x, s, sc, _ in rows3])
    assert_r_equal(got3, _col(rows3, 3), "L", "DGAMMA3")


def test_lgammafn() -> None:
    got = np.array([nm.lgammafn(_H(x)) for x, _ in rv.LGAMMA])
    assert_r_equal(got, _col(rv.LGAMMA, 1), "L", "LGAMMA")


def test_normal_and_poisson() -> None:
    got = np.array([nm._pnorm_lower(_H(x), False) for x, _, _ in rv.PNORM])
    assert_r_equal(got, _col(rv.PNORM, 1), "L", "PNORM")
    got_log = np.array([nm._pnorm_lower(_H(x), True) for x, _, _ in rv.PNORM])
    assert_r_equal(got_log, _col(rv.PNORM, 2), "L", "PNORM log")
    got_d = np.array([nm._dnorm(_H(x)) for x, _ in rv.DNORM])
    assert_r_equal(got_d, _col(rv.DNORM, 1), "L", "DNORM")
    got_p = np.array([nm._dpois_raw(_H(x), _H(lam), lg) for x, lam, lg, _ in rv.DPOIS])
    assert_r_equal(got_p, _col(rv.DPOIS, 3), "L", "DPOIS")


# ----------------------------------------------------------------------------- guardas internas
# Ramas que la API pública no alcanza; el valor esperado se lee directamente del código C citado.


def test_internal_guards() -> None:
    assert math.isnan(nm._chebyshev_eval(2.0, (1.0,)))  # chebyshev.c:75
    assert math.isnan(nm._lgammacor(5.0))  # lgammacor.c:77
    assert nm._lgammacor(1e8) == 1 / (1e8 * 12)  # lgammacor.c:87
    assert nm._gammafn_small(1e-309) == math.inf  # gamma.c:156-159
    assert math.isnan(nm.lgammafn(math.nan))  # lgamma.c:66
    with pytest.raises(ValueError, match="no positivo"):
        nm.lgammafn(0.0)
    assert nm._log1pmx(2.0) == math.log1p(2.0) - 2.0  # pgamma.c:125-126
    assert nm._log1pmx(-0.9) == math.log1p(-0.9) + 0.9
    # ebd0 (bd0.c:247-260, :343)
    assert nm._ebd0(3.0, 3.0) == (0.0, 0.0)
    assert nm._ebd0(0.0, 2.0) == (2.0, 0.0)
    assert nm._ebd0(2.0, 0.0) == (math.inf, 0.0)
    assert nm._ebd0(1e-300, 1e300) == (1e300, 0.0)
    assert nm._ebd0(1e307, 0.3) == (math.inf, 0.0)
    assert nm._ebd0(1e308, 1e300) == (math.inf, 0.0)
    # dpois_raw y dpois_wrap (dpois.c:48-54; pgamma.c:289-290)
    assert nm._dpois_raw(1.0, math.inf, True) == -math.inf
    assert nm._dpois_raw(math.inf, 1.0, False) == 0.0
    assert nm._dpois_raw(0.0, 0.0, True) == 0.0
    assert nm._dpois_wrap(2.0, math.inf, False) == 0.0
    # dnorm/pnorm y la fracción continua (pgamma.c:407)
    assert nm._pd_lower_cf(0.0, 1.0) == 0.0
    assert math.isnan(nm._pnorm_lower(math.nan, True))
    # qchisq_appr fuera de dominio (qgamma.c:64-68)
    assert math.isnan(nm._qchisq_appr(math.nan, 2.0, 0.0, 1e-2))
    assert math.isnan(nm._qchisq_appr(1.5, 2.0, 0.0, 1e-2))
    # qgamma: alpha < 0 o escala no positiva (qgamma.c:146)
    assert math.isnan(nm.qgamma(0.5, 1.0, 0.0))
