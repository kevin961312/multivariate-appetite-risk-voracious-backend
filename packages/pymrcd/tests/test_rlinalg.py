"""Réplica de BLAS/LAPACK de R (``%*%``, ``crossprod``, ``eigen``, ``chol``, ``det``) contra
fixtures."""

from __future__ import annotations

import math

import numpy as np
import pytest

from fixtures_r import EPS, Case, assert_r_equal, case_params
from pymrcd import _rlapack
from pymrcd._errors import RError
from pymrcd._rbase import r_pow
from pymrcd._rlinalg import (
    _fortran,
    _may_have_nan_or_inf,
    r_chol,
    r_chol2inv,
    r_crossprod,
    r_det,
    r_determinant,
    r_eigen_sym,
    r_mahalanobis_inverted,
    r_matprod,
    r_matvec,
    r_vecmat,
)

# ----------------------------------------------------------------------------- BLAS


@pytest.mark.parametrize("case", case_params("matprod"))
def test_matprod(case: Case) -> None:
    got = r_matprod(case.inputs["A"], case.inputs["B"])
    assert_r_equal(got, case.outputs["C"], "B", case.id)


@pytest.mark.parametrize("case", case_params("matvec"))
def test_matvec(case: Case) -> None:
    got = r_matvec(case.inputs["A"], case.inputs["v"].ravel())
    assert_r_equal(got, case.outputs["y"].ravel(), "B", case.id)


@pytest.mark.parametrize("case", case_params("vecmat"))
def test_vecmat(case: Case) -> None:
    got = r_vecmat(case.inputs["v"].ravel(), case.inputs["B"])
    assert_r_equal(got, case.outputs["y"].ravel(), "B", case.id)


@pytest.mark.parametrize("case", case_params("crossprod"))
def test_crossprod(case: Case) -> None:
    assert_r_equal(r_crossprod(case.inputs["X"]), case.outputs["C"], "B", case.id)


@pytest.mark.parametrize("case", case_params("mahalanobis"))
def test_mahalanobis(case: Case) -> None:
    got = r_mahalanobis_inverted(
        case.inputs["x"], case.inputs["center"].ravel(), case.inputs["icov"]
    )
    assert_r_equal(got, case.outputs["d2"].ravel(), "B", case.id)


# ----------------------------------------------------------------------------- LAPACK de referencia


@pytest.mark.parametrize("case", case_params("chol"))
def test_chol(case: Case) -> None:
    assert_r_equal(r_chol(case.inputs["A"]), case.outputs["R"], "B", case.id)


@pytest.mark.parametrize("case", case_params("chol2inv_chol"))
def test_chol2inv(case: Case) -> None:
    got = r_chol2inv(r_chol(case.inputs["A"]))
    assert_r_equal(got, case.outputs["inv"], "B", case.id)


@pytest.mark.parametrize("case", case_params("determinant"))
def test_determinant(case: Case) -> None:
    a = case.inputs["A"]
    modulus, sign = r_determinant(a)
    assert_r_equal(modulus, case.outputs["modulus"].item(), "B", case.id)
    assert sign == int(case.outputs["sign"].item())
    det = r_det(a)
    assert_r_equal(det, case.outputs["det"].item(), "B", case.id)
    p = a.shape[0]
    # obj = det(A)^(1/p) (detmrcd.R:409-413, objective='geom'); con det < 0 R da NaN.
    assert_r_equal(r_pow(det, 1 / p), case.outputs["obj"].item(), "B", case.id)


# ----------------------------------------------------------------------------- eigen (LAPACK de
# Accelerate). Decisión del dueño: se acepta la divergencia con Rlapack (1-4 ulp en autovalores,
# signo de autovectores) con tolerancias clase B (especificación §11); no hay test bit a bit.

_EIGEN_CASES = case_params("eigen_sym") + case_params("eigen_auto")


def _eigen_input(case: Case) -> np.ndarray:
    # eigen_auto exporta A = 1.3 * S calculada en R: la matriz exacta que recibe eigen()
    # (tools/r/exportar_primitivas.R).
    return case.inputs["A"]


@pytest.mark.parametrize("case", _EIGEN_CASES)
def test_eigen_declared_tolerance(case: Case) -> None:
    """Clase B de la especificación §11 (autovalores y autovectores con gap > 1e-8, módulo
    signo)."""
    res = r_eigen_sym(_eigen_input(case))
    ev = case.outputs["valores"].ravel()
    vec = case.outputs["vectores"]
    p = ev.shape[0]
    lam_max = float(np.max(np.abs(ev)))
    atol = 10 * p * EPS * lam_max
    np.testing.assert_allclose(res.values, ev, rtol=0, atol=atol)
    for i in range(p):
        gaps = [abs(ev[i] - ev[j]) for j in (i - 1, i + 1) if 0 <= j < p]
        gap = min(gaps) if gaps else math.inf
        if lam_max == 0 or gap / lam_max <= 1e-8:
            continue  # autoespacio casi degenerado: base arbitraria (R1, especificación §6)
        v = res.vectors[:, i]
        vr = vec[:, i]
        s = 1.0 if float(v @ vr) >= 0 else -1.0
        tol = 10 * p * EPS * lam_max / gap
        assert np.max(np.abs(s * v - vr)) <= tol, f"{case.id}: vector {i}"


# ----------------------------------------------------------------------------- casos límite


def test_matprod_shapes_and_errors() -> None:
    a = np.arange(6.0).reshape(2, 3)
    with pytest.raises(RError, match="non-conformable"):
        r_matprod(a, a)
    assert r_matprod(np.zeros((2, 0)), np.zeros((0, 3))).shape == (2, 3)
    assert (r_matprod(np.zeros((2, 0)), np.zeros((0, 3))) == 0).all()
    np.testing.assert_array_equal(r_matvec(a, np.ones(3)), [3.0, 12.0])
    np.testing.assert_array_equal(r_vecmat(np.ones(2), a), [3.0, 5.0, 7.0])


def test_matprod_nan_uses_simple_loop() -> None:
    a = np.array([[1.0, np.nan], [2.0, 3.0]])
    b = np.array([[1.0, 2.0], [3.0, 4.0]])
    out = r_matprod(a, b)
    assert np.isnan(out[0]).all()
    np.testing.assert_array_equal(out[1], [11.0, 16.0])
    big = np.array([[1e308, 1e308, 1.0, 1.0]])
    assert _may_have_nan_or_inf(big)  # suma de pares desborda: R usa simple_matprod
    assert _may_have_nan_or_inf(np.array([np.inf, 1.0, 2.0]))
    assert not _may_have_nan_or_inf(np.array([1.0, 2.0, 3.0]))
    cp = r_crossprod(np.array([[1.0, np.inf], [2.0, 1.0]]))
    assert np.isinf(cp[1, 1])
    assert r_crossprod(np.zeros((0, 2))).shape == (2, 2)


def test_fortran_alignment_mimics_r() -> None:
    big = _fortran(np.ones((20, 10)))
    assert big.flags.f_contiguous
    assert big.ctypes.data % 64 == 48
    small = _fortran(np.ones((3, 3)))
    assert small.flags.f_contiguous


def test_eigen_errors() -> None:
    with pytest.raises(RError, match="non-square"):
        r_eigen_sym(np.ones((2, 3)))
    with pytest.raises(RError, match="0 x 0"):
        r_eigen_sym(np.zeros((0, 0)))
    with pytest.raises(RError, match="infinite or missing"):
        r_eigen_sym(np.array([[1.0, np.nan], [np.nan, 1.0]]))


def test_chol_errors_and_inverse() -> None:
    with pytest.raises(RError, match="square"):
        r_chol(np.ones((2, 3)))
    with pytest.raises(RError, match="dims > 0"):
        r_chol(np.zeros((0, 0)))
    with pytest.raises(RError, match="leading minor of order 2"):
        r_chol(np.array([[1.0, 2.0], [2.0, 1.0]]))
    with pytest.raises(RError, match="leading minor of order 1"):
        r_chol(np.array([[np.nan]]))
    with pytest.raises(RError, match="numeric matrix"):
        r_chol2inv(np.zeros((0, 0)))
    with pytest.raises(RError, match="is zero"):
        r_chol2inv(np.array([[1.0, 1.0], [0.0, 0.0]]))


def test_reference_lapack_blocked_paths() -> None:
    # n > 64 ejercita las ramas por bloques de DPOTRF, DTRTRI, DLAUUM y DGETRF.
    rng = np.random.default_rng(7)
    x = rng.normal(size=(200, 150))
    s = x.T @ x / 199 + np.eye(150)
    r = r_chol(s)
    np.testing.assert_allclose(r.T @ r, s, rtol=1e-12, atol=1e-12)
    inv = r_chol2inv(r)
    np.testing.assert_allclose(inv @ s, np.eye(150), atol=1e-9)
    modulus, sign = r_determinant(s)
    assert sign == 1
    assert math.isclose(modulus, float(np.linalg.slogdet(s)[1]), rel_tol=1e-12)
    g = rng.normal(size=(140, 140))
    mg, sg = r_determinant(g)
    s2, l2 = np.linalg.slogdet(g)
    assert sg == int(s2)
    assert math.isclose(mg, float(l2), rel_tol=1e-11)
    bad = s.copy()
    bad[100, 100] = -1e6
    with pytest.raises(RError, match="leading minor of order 101"):
        r_chol(bad)


def test_reference_lapack_small_branches() -> None:
    a = _fortran(np.array([[0.0, 1.0], [0.0, 2.0]]))
    _ipiv, info = _rlapack.dgetrf(a)
    assert info == 1  # columna nula: pivote cero
    assert r_determinant(np.array([[0.0, 0.0], [0.0, 1.0]])) == (-math.inf, 1)
    assert r_determinant(np.zeros((0, 0))) == (0.0, 1)
    with pytest.raises(RError, match="square"):
        r_determinant(np.ones((2, 3)))
    tiny = _fortran(np.array([[1e-310, 1.0], [2e-310, 3.0]]))
    _ipiv2, info2 = _rlapack.dgetrf(tiny)
    assert info2 == 0  # pivote subnormal: división en lugar de DSCAL
    assert _rlapack.dgetrf(np.zeros((0, 3), order="F"))[1] == 0
    one_row = _fortran(np.array([[0.0, 1.0, 2.0]]))
    assert _rlapack.dgetrf(one_row)[1] == 1
    assert _rlapack.dpotrf_upper(np.zeros((0, 0), order="F")) == 0
    assert _rlapack.dpotri_upper(np.zeros((0, 0), order="F")) == 0
    sing = _fortran(np.zeros((70, 70)))
    _ipiv3, info3 = _rlapack.dgetrf(sing)
    assert info3 == 1
    assert r_det(np.diag([1e200, 1e200, 1e200, 1e200])) == math.inf
    assert r_det(np.diag([-1.0, 2.0])) == -2.0
