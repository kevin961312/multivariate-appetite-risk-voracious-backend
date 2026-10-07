"""Primitivas de R base/stats contra los fixtures de R (``primitivas/``) y casos límite."""

from __future__ import annotations

import math

import numpy as np
import pytest

from fixtures_r import Case, assert_r_equal, case_params
from pymrcd import _rbase as rb
from pymrcd._errors import RError
from pymrcd._rlinalg import r_mahalanobis_d, r_scale

# ----------------------------------------------------------------------------- fixtures de R


@pytest.mark.parametrize("case", case_params("median"))
def test_median(case: Case) -> None:
    m = case.inputs["M"]
    got = np.array([rb.r_median(row) for row in m])
    assert_r_equal(got, case.outputs["mediana"].ravel(), "E", case.id)
    # Vectorizado por columnas: mismo resultado.
    assert_r_equal(rb.r_median_cols(m.T), case.outputs["mediana"].ravel(), "E", case.id)


@pytest.mark.parametrize("case", case_params("mean"))
def test_mean(case: Case) -> None:
    assert_r_equal(rb.r_mean(case.inputs["x"].ravel()), case.outputs["m"].item(), "E", case.id)


@pytest.mark.parametrize("case", case_params("colMedians"))
def test_colmedians(case: Case) -> None:
    got = rb.r_colmedians(case.inputs["X"])
    assert_r_equal(got, case.outputs["colmed"].ravel(), "E", case.id)


@pytest.mark.parametrize("case", case_params("rowMeans"))
def test_rowmeans(case: Case) -> None:
    assert_r_equal(rb.r_rowmeans(case.inputs["X"]), case.outputs["m"].ravel(), "E", case.id)


@pytest.mark.parametrize("case", case_params("rowSums"))
def test_rowsums(case: Case) -> None:
    assert_r_equal(rb.r_rowsums(case.inputs["X"]), case.outputs["s"].ravel(), "E", case.id)


@pytest.mark.parametrize("case", case_params("rank"))
def test_rank(case: Case) -> None:
    if "X" in case.inputs:
        got = rb.r_rank_cols(case.inputs["X"])
        assert_r_equal(got, case.outputs["rangos"], "E", case.id)
    else:
        got = rb.r_rank_average(case.inputs["x"].ravel())
        assert_r_equal(got, case.outputs["rango"].ravel(), "E", case.id)


@pytest.mark.parametrize("case", case_params("order"))
def test_order(case: Case) -> None:
    got = rb.r_order(case.inputs["x"].ravel()) + 1
    np.testing.assert_array_equal(got, case.outputs["ord"].ravel().astype(np.int64))


@pytest.mark.parametrize("case", case_params("cor_pearson"))
def test_cor_pearson(case: Case) -> None:
    assert_r_equal(rb.r_cor(case.inputs["X"]), case.outputs["R"], "E", case.id)


@pytest.mark.parametrize("case", case_params("cor_complete_obs"))
def test_cor_complete_obs(case: Case) -> None:
    got = rb.r_cor(case.inputs["X"], use="complete.obs")
    assert_r_equal(got, case.outputs["R"], "E", case.id)


@pytest.mark.parametrize("case", case_params("cor_spearman"))
def test_cor_spearman(case: Case) -> None:
    assert_r_equal(rb.r_cor_spearman(case.inputs["X"]), case.outputs["R"], "E", case.id)


@pytest.mark.parametrize("case", case_params("cov"))
def test_cov(case: Case) -> None:
    assert_r_equal(rb.r_cov(case.inputs["X"]), case.outputs["C"], "E", case.id)


@pytest.mark.parametrize("case", case_params("quantile7"))
def test_quantile7(case: Case) -> None:
    got = rb.r_quantile7(case.inputs["x"].ravel(), case.inputs["probs"].ravel())
    assert_r_equal(got, case.outputs["q"].ravel(), "E", case.id)


@pytest.mark.parametrize("case", case_params("qnorm"))
def test_qnorm(case: Case) -> None:
    got = rb.r_qnorm(case.inputs["p"].ravel())
    assert_r_equal(got, case.outputs["q"].ravel(), "L", case.id)


@pytest.mark.parametrize("case", case_params("tanh"))
def test_tanh(case: Case) -> None:
    assert_r_equal(rb.r_tanh(case.inputs["x"]), case.outputs["y"], "L", case.id)


@pytest.mark.parametrize("case", case_params("sin"))
def test_sin(case: Case) -> None:
    got = rb.r_sin(0.5 * math.pi * case.inputs["r"])
    assert_r_equal(got, case.outputs["y"], "L", case.id)


@pytest.mark.parametrize("case", case_params("exp"))
def test_exp_libm(case: Case) -> None:
    x = case.inputs["x"].ravel()
    got = []
    for v in x.tolist():
        try:
            got.append(math.exp(v))
        except OverflowError:
            got.append(math.inf)
    assert_r_equal(np.array(got), case.outputs["y"].ravel(), "L", case.id)


@pytest.mark.parametrize("case", case_params("log"))
def test_log_libm(case: Case) -> None:
    x = case.inputs["x"].ravel()
    got = []
    for v in x.tolist():
        if v > 0 or math.isnan(v) or math.isinf(v):
            got.append(math.log(v) if not math.isnan(v) else v)
        else:
            got.append(-math.inf if v == 0 else math.nan)
    assert_r_equal(np.array(got), case.outputs["y"].ravel(), "L", case.id)


@pytest.mark.parametrize("case", case_params("sqrt"))
def test_sqrt_ieee(case: Case) -> None:
    with np.errstate(invalid="ignore"):
        got = np.sqrt(case.inputs["x"])
    assert_r_equal(got, case.outputs["y"], "E", case.id)


@pytest.mark.parametrize("case", case_params("r_pow"))
def test_r_pow(case: Case) -> None:
    xs = case.inputs["x"].ravel().tolist()
    ys = case.inputs["y"].ravel().tolist()
    got = np.array([rb.r_pow(a, b) for a, b in zip(xs, ys, strict=True)])
    assert_r_equal(got, case.outputs["z"].ravel(), "L", case.id)


@pytest.mark.parametrize("case", case_params("scale"))
def test_scale(case: Case) -> None:
    got = r_scale(case.inputs["X"], case.inputs["center"].ravel(), case.inputs["scale"].ravel())
    assert_r_equal(got, case.outputs["Z"], "E", case.id)


@pytest.mark.parametrize("case", case_params("mahalanobisD"))
def test_mahalanobis_d(case: Case) -> None:
    got = r_mahalanobis_d(case.inputs["X"], case.inputs["lambda"].ravel())
    assert_r_equal(got, case.outputs["d"].ravel(), "E", case.id)


# ----------------------------------------------------------------------------- casos límite


def test_median_two_pass_s1b() -> None:
    # Especificación S1b: median(c(0.1,0.7,5,-3)) = 0.40000000000000002.
    assert rb.r_median(np.array([0.1, 0.7, 5.0, -3.0])) == 0.40000000000000002
    assert (0.1 + 0.7) / 2 != 0.40000000000000002


def test_median_na_and_empty() -> None:
    assert math.isnan(rb.r_median(np.array([1.0, np.nan, 2.0])))
    assert math.isnan(rb.r_median(np.array([])))
    assert np.isnan(rb.r_colmedians(np.zeros((0, 3)))).all()
    assert np.isnan(rb.r_colmedians(np.array([[1.0], [np.nan]]))).all()


def test_median_signed_zero_uses_r_partial_sort() -> None:
    # Mezcla de -0.0 y 0.0: R elige el representante con rPsort (sort.c:668-698).
    v = np.array([0.0, -0.0, 1.0, -0.0, -1.0])
    out = rb.r_median(v)
    assert out == 0.0
    work = v.tolist()
    rb._rpsort0(work, 0, len(work) - 1, [3])
    assert math.copysign(1.0, out) == math.copysign(1.0, work[2])
    w = np.array([-0.0, 0.0, 2.0, -0.0, 0.0, -1.0])
    assert rb.r_median(w) == 0.0
    cm = rb.r_colmedians(np.column_stack([v, v]))
    assert (cm == 0.0).all()
    cm2 = rb.r_colmedians(w[:, None])
    assert cm2[0] == 0.0
    # Sin mezcla de signos: atajo sin selección literal.
    assert math.copysign(1.0, rb.r_median(np.array([-0.0, -0.0, 3.0]))) == -1.0


def test_rpsort_nan_last() -> None:
    work = [3.0, math.nan, 1.0, 2.0, math.nan]
    rb._rpsort2(work, 0, 4, 1)
    assert work[1] == 2.0
    assert rb._rcmp(math.nan, math.nan) == 0
    assert rb._rcmp(math.nan, 1.0) == 1
    assert rb._rcmp(1.0, math.nan) == -1
    rb._rpsort0(work, 0, 0, [1])  # rango trivial: no hace nada


def test_mean_overflow_branch() -> None:
    v = np.array([1.5e308, 1.5e308, -1e308])
    m = rb.r_mean(v)
    assert math.isfinite(m)
    assert math.isnan(rb.r_mean(np.array([])))
    assert rb.r_mean(np.array([np.inf, 1.0])) == np.inf
    assert rb.seqsum(np.array([-0.0])) == 0.0
    assert not math.copysign(1.0, rb.seqsum(np.array([-0.0]))) < 0


def test_rank_nan_keep_and_one_row() -> None:
    r = rb.r_rank_average(np.array([2.0, np.nan, 1.0, 2.0]))
    assert np.isnan(r[1])
    np.testing.assert_array_equal(r[[0, 2, 3]], [2.5, 1.0, 2.5])
    assert np.isnan(rb.r_rank_average(np.array([np.nan]))).all()
    np.testing.assert_array_equal(rb.r_rank_cols(np.array([[3.0, 4.0]])), [[1.0, 1.0]])


def test_cor_constant_column_and_na() -> None:
    x = np.column_stack([np.arange(5.0), np.ones(5), np.array([1.0, 3, 2, 5, 4])])
    r = rb.r_cor(x)
    assert np.isnan(r[0, 1])
    assert np.isnan(r[1, 2])
    assert r[1, 1] == 1.0
    y = x.copy()
    y[2, 0] = np.nan
    r2 = rb.r_cor(y)
    assert np.isnan(r2[0, 2])
    assert r2[0, 0] == 1.0
    rc = rb.r_cor(y, use="complete.obs")
    assert np.isfinite(rc[0, 2])
    assert np.isnan(rb.r_cov(np.ones((1, 2)))).all()
    assert np.isnan(rb.r_cov(np.array([[np.nan, 1.0], [2.0, np.nan]]), use="complete.obs")).all()
    allna = np.full((3, 2), np.nan)
    assert np.isnan(rb.r_cov(allna)).all()
    with pytest.raises(RError, match="invalid 'use'"):
        rb.r_cov(x, use="pairwise")
    with pytest.raises(RError, match="empty"):
        rb.r_cov(np.zeros((0, 0)))


def test_cov_small_n_all_fused_and_blocks() -> None:
    # n < 8: todo fmadd; n >= 8: bloques sin fusionar + resto fusionado. Ambos simétricos.
    rng = np.random.default_rng(1)
    for n in (3, 8, 13):
        c = rb.r_cov(rng.normal(size=(n, 4)))
        np.testing.assert_array_equal(c, c.T)


def test_quantile7_errors_and_clamp() -> None:
    with pytest.raises(RError, match="missing values"):
        rb.r_quantile7(np.array([1.0, np.nan]), [0.5])
    with pytest.raises(RError, match="outside"):
        rb.r_quantile7(np.array([1.0, 2.0]), [1.5])
    got = rb.r_quantile7(np.array([3.0, 1.0, 2.0]), [0.0, 1.0 + 1e-15, 0.5, 0.25])
    np.testing.assert_array_equal(got, [1.0, 3.0, 2.0, 1.5])


def test_qnorm_boundaries_and_far_tail() -> None:
    got = rb.r_qnorm(np.array([0.0, 1.0, -0.1, 1.1, np.nan, 0.5]))
    assert got[0] == -np.inf
    assert got[1] == np.inf
    assert np.isnan(got[2:5]).all()
    assert got[5] == 0.0
    assert not np.signbit(got[5])
    # r > 27 solo con p subnormal: exp(-27^2) ~ 2.5e-317.
    tiny = rb.r_qnorm(np.array([1e-320, 5e-324]))
    assert (tiny < -37).all()
    assert rb.r_qnorm(np.array([[0.25, 0.75]])).shape == (1, 2)


def test_qnorm_far_tail_branches() -> None:
    # Ramas asintóticas (qnorm.c:140-163), alcanzables con log.p en R; aquí se ejercitan directo.
    for lp in (-(30.0**2), -(60.0**2), -(200.0**2), -(1000.0**2), -(40000.0**2), -(7e8**2)):
        r = math.sqrt(-lp)
        val = rb._qnorm_far_tail(lp, r)
        assert val > 0
        assert math.isfinite(val)


def test_r_pow_special_cases() -> None:
    assert rb.r_pow(3.0, 2.0) == 9.0
    assert rb.r_pow(1.0, math.nan) == 1.0
    assert rb.r_pow(math.nan, 0.0) == 1.0
    assert rb.r_pow(0.0, 3.0) == 0.0
    assert rb.r_pow(0.0, -1.0) == math.inf
    assert math.isnan(rb.r_pow(0.0, math.nan))
    assert math.isnan(rb.r_pow(-8.0, 1 / 3))
    assert rb.r_pow(10.0, 400.0) == math.inf
    assert rb.r_pow(-10.0, 401.0) == -math.inf
    assert math.isnan(rb.r_pow(math.nan, 2.5))
    assert rb.r_pow(math.inf, -1.0) == 0.0
    assert rb.r_pow(math.inf, 0.5) == math.inf
    assert rb.r_pow(-math.inf, 3.0) == -math.inf
    assert rb.r_pow(-math.inf, 4.0) == math.inf
    assert rb.r_pow(-math.inf, -3.0) == 0.0
    assert math.isnan(rb.r_pow(-math.inf, 0.5))
    assert rb.r_pow(2.0, math.inf) == math.inf
    assert rb.r_pow(0.5, math.inf) == 0.0
    assert rb.r_pow(0.5, -math.inf) == math.inf
    assert rb.r_pow(2.0, -math.inf) == 0.0
    assert math.isnan(rb.r_pow(-2.0, math.inf))
    assert rb.r_pow(4.0, -1.0) == 0.25


def test_f32_rounding() -> None:
    assert rb.f32(0.1) == float(np.float32(0.1))
    assert rb.f32(1e300) == math.inf


def test_order_stable_with_ties_and_nan() -> None:
    v = np.array([1.0, -0.0, 0.0, np.nan, -1.0, 0.0])
    np.testing.assert_array_equal(rb.r_order(v), [4, 1, 2, 5, 0, 3])
