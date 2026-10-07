"""API pública ``cov_mrcd`` y ramas de borde del bloque 2 (errores equivalentes a R, P7/P8).

Los valores de referencia de R se obtuvieron con ``rrcov`` 1.7-7 oficial (``referencias/R-lib``)
donde se indica; el resto son propiedades que se derivan directamente del código R citado.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from fixtures_r import Inter
from pymrcd import MrcdResult, RError, cov_mrcd
from pymrcd._rlinalg import r_eigen_values, r_is_symmetric
from pymrcd.csteps import cstep_mrcd, next_index
from pymrcd.detmrcd import _check_hsets, _r_diag, detmrcd, resolve_h
from pymrcd.ogk import ogk_u, ogkscatter
from pymrcd.r6pack import initset
from pymrcd.rcov import inv_smw, rcov
from pymrcd.rho import RHO_GRID, fncond_factory, rho_for_subset, select_rho
from pymrcd.target import eigen_eq, target_corr


def _data(n: int = 40, p: int = 4, seed: int = 3) -> np.ndarray:
    return np.random.default_rng(seed).normal(size=(n, p))


# --------------------------------------------------------------------------------- API


def test_result_fields_and_aliases() -> None:
    res = cov_mrcd(_data())
    assert isinstance(res, MrcdResult)
    assert res.h == res.quan == math.ceil(0.5 * 40)
    assert res.best.shape == (res.quan,)
    assert np.all(np.diff(res.best) > 0)
    assert res.init_hsets.shape == (res.quan, 6)
    assert res.n_csteps_total == int(res.n_csteps.sum())
    assert res.cov.shape == res.icov.shape == res.target.shape == (4, 4)
    assert res.ok.all()
    np.testing.assert_allclose(res.cov @ res.icov, np.eye(4), atol=1e-10)


def test_invalid_target_is_error_p8() -> None:
    with pytest.raises(RError, match="should be one of"):
        cov_mrcd(_data(), target="diagonal")


def test_rows_with_nan_or_inf_are_dropped() -> None:
    x = _data(42)
    x[3, 1] = np.nan
    x[7, 0] = np.inf
    res = cov_mrcd(x)
    assert res.n_obs == 40
    assert not res.ok[3]
    assert not res.ok[7]
    ref = cov_mrcd(np.delete(x, [3, 7], axis=0))
    assert np.array_equal(ref.cov, res.cov)


def test_all_rows_missing() -> None:
    x = np.full((5, 3), np.nan)
    with pytest.raises(RError, match="All observations"):
        cov_mrcd(x)


def test_vector_input_p1() -> None:
    # p = 1: Dx = diag(vsd) crea la identidad de orden as.integer(vsd) (diag.R:41-43); con vsd
    # en [1, 2) R funciona y el centro queda sin reescalar; si no, R falla (non-conformable).
    v = np.random.default_rng(5).normal(scale=1.5, size=60)
    res = cov_mrcd(v)
    assert res.cov.shape == (1, 1)
    vsd = float(res.detail.vsd[0])
    assert 1 <= vsd < 2
    assert res.center[0] == float(res.detail.fin_mu_std[0]) + float(res.detail.vmx[0])
    with pytest.raises(RError, match="non-conformable"):
        cov_mrcd(v * 10)


def test_bad_input_shape() -> None:
    with pytest.raises(RError, match="matrix or a vector"):
        cov_mrcd(np.zeros((2, 2, 2)))


def test_h_overrides_alpha_and_alpha_bounds() -> None:
    res = cov_mrcd(_data(), h=30)
    assert res.quan == 30
    assert res.alpha == 30 / 40
    with pytest.raises(RError, match=r"between 0\.5 and 1\.0"):
        cov_mrcd(_data(), alpha=0.4)
    with pytest.raises(RError, match=r"between 0\.5 and 1\.0"):
        resolve_h(10, None, 11)
    with pytest.raises(RError, match="has to be supplied"):
        resolve_h(10, None, None)
    assert resolve_h(10, 0.75, None) == (8, 0.75)


def test_rho_given_processes_set_one_twice_t17() -> None:
    # detmrcd.R:536-539: setsV = 1:6, initV = 1 (T17); el conjunto 1 empata consigo mismo.
    res = cov_mrcd(_data(), rho=0.3)
    assert res.rho == 0.3
    assert res.detail.selection is None
    procesados = [k for k, _cs, _obj in res.detail.csteps]
    assert procesados == [0, 0, 1, 2, 3, 4, 5]
    assert res.detail.csteps[0][2] == res.detail.csteps[1][2]  # mismo objetivo: empate exacto


def test_constant_column_fails_like_r_p7() -> None:
    # Columna constante ⇒ cor con NA ⇒ eigen() falla (T20, sonda S6).
    x = _data()
    x[:, 2] = 1.0
    with pytest.raises(RError, match="infinite or missing"):
        cov_mrcd(x)


def test_p1_equicorrelation_fails_like_r_p7() -> None:
    with pytest.raises(RError, match="missing value"):
        cov_mrcd(_data(p=1), target="equicorrelation")


def test_equicorrelation_runs() -> None:
    res = cov_mrcd(_data(p=5), target="equicorrelation")
    assert res.detail.eq is not None
    assert res.detail.tgt.constcor is not None
    np.testing.assert_allclose(res.cov @ res.icov, np.eye(5), atol=1e-9)


def test_maxcsteps_one_returns_new_index_with_old_mean_t18() -> None:
    x = _data(60, 3)
    res = cov_mrcd(x, maxcsteps=1)
    assert (res.n_csteps[res.n_csteps > 0] == 1).all()


def test_fat_data_uses_smw() -> None:
    res = cov_mrcd(_data(12, 20, seed=8))
    assert res.detail.fin_smw is not None
    np.testing.assert_allclose(res.cov @ res.icov, np.eye(20), atol=1e-8)


# --------------------------------------------------------------------------------- init_hsets


def test_init_hsets_validation() -> None:
    x = _data()
    h = 20
    good = np.tile(np.arange(h)[:, None], (1, 6))
    res = cov_mrcd(x, init_hsets=good)
    assert res.detail.r6 is None
    with pytest.raises(RError, match="h' x L"):
        cov_mrcd(x, init_hsets=good[:5])
    with pytest.raises(RError, match="must be in"):
        cov_mrcd(x, init_hsets=good + 100)
    with pytest.raises(RError, match="argument of length 0"):
        cov_mrcd(x, init_hsets=good[:, 0])  # una columna: [1:h, ] la convierte en vector
    with pytest.raises(RError, match="integer"):
        _check_hsets(np.asarray(good + 0.5), h, 40)  # índices no enteros
    with pytest.raises(RError, match="h' x L"):
        _check_hsets(np.zeros((2, 2, 2), dtype=np.int64), h, 40)


# --------------------------------------------------------------------------------- piezas


def test_r_diag_like_r() -> None:
    assert _r_diag(np.array([2.7])).shape == (2, 2)
    assert _r_diag(np.array([0.4])).shape == (0, 0)
    np.testing.assert_array_equal(_r_diag(np.array([1.0, 2.0])), np.diag([1.0, 2.0]))
    with pytest.raises(RError, match="nrow"):
        _r_diag(np.array([-1.0]))


def test_eigen_values_symmetric_and_general_branches() -> None:
    s = np.array([[2.0, 1.0], [1.0, 3.0]])
    assert r_is_symmetric(s)
    np.testing.assert_allclose(r_eigen_values(s), np.sort(np.linalg.eigvalsh(s))[::-1])
    a = np.array([[2.0, 1.0], [0.0, 3.0]])  # no simétrica, valores reales: La_rg ordena por Mod
    assert not r_is_symmetric(a)
    np.testing.assert_allclose(r_eigen_values(a), [3.0, 2.0])
    big = np.array([[1.0, 2.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    assert not r_is_symmetric(big)  # falla en la pre-prueba de filas/columnas
    rot = np.array([[0.0, -1.0], [1.0, 0.0]])
    with pytest.raises(RError, match="complex"):
        r_eigen_values(rot)
    assert not r_is_symmetric(np.ones((2, 3)))
    with pytest.raises(RError, match="non-square"):
        r_eigen_values(np.ones((2, 3)))
    with pytest.raises(RError, match="0 x 0"):
        r_eigen_values(np.zeros((0, 0)))
    with pytest.raises(RError, match="infinite"):
        r_eigen_values(np.array([[np.nan]]))
    near = s.copy()
    near[0, 1] += 1e-17  # dentro de la tolerancia de isSymmetric (100·eps relativa)
    assert r_is_symmetric(near)
    tiny = np.array([[0.0, 1e-300], [0.0, 0.0]])  # escala < tol: diferencia absoluta
    assert r_is_symmetric(tiny)


def test_rho_grid_and_fallbacks() -> None:
    assert RHO_GRID.shape == (992,)
    assert RHO_GRID[0] == 0.000001
    assert RHO_GRID[-1] == 0.999999
    np.testing.assert_array_equal(RHO_GRID[1:991], 0.001 + np.arange(990) * 0.001)
    # Bien condicionado: f(lower) y f(upper) < 0 ⇒ rejilla ⇒ 1e-6 (sonda S6).
    rk = rho_for_subset(1.0, 2.0, 50.0)
    assert rk.path == 2
    assert rk.rho == 0.000001
    assert math.isnan(rk.root)
    # Mal condicionado: uniroot.
    rk2 = rho_for_subset(1e-6, 10.0, 50.0)
    assert rk2.path == 1
    assert 1e-5 < rk2.rho < 0.99
    # e1 = NaN ⇒ uniroot falla y la rejilla da NA.
    rk3 = rho_for_subset(math.nan, 1.0, 50.0)
    assert rk3.path == 2
    assert math.isnan(rk3.rho)
    f = fncond_factory(0.0, 1.0, 50.0)
    assert math.isinf(f(0.0))


def test_select_rho_branches() -> None:
    sel = select_rho(np.array([0.05, 0.2, 0.01, 0.3, 0.02, 0.5]))
    assert sel.cutoff == 0.125
    assert sel.rho == 0.05
    assert sel.init_v == 0
    np.testing.assert_array_equal(sel.sets_v, [2, 4])
    np.testing.assert_array_equal(sel.vsel, [0, -1, 2, -1, 4, -1])
    with pytest.raises(RError, match="well-conditioned"):
        select_rho(np.array([0.1, math.nan, 0.2, 0.3, 0.4, 0.5]))


def test_target_and_eigen_eq_edges() -> None:
    with pytest.raises(RError, match="subscript"):
        eigen_eq(np.ones((1, 1)))
    eq = eigen_eq(np.array([[1.0, 0.5, 0.5], [0.5, 1.0, 0.5], [0.5, 0.5, 1.0]]))
    np.testing.assert_allclose(eq.values, [2.0, 0.5, 0.5])
    np.testing.assert_allclose(eq.vectors.T @ eq.vectors, np.eye(3), atol=1e-15)
    # constcor por debajo de la cota min(0, -1/(p-1)+0.01) ⇒ se recorta (detmrcd.R:222-224).
    x = np.array([[1.0, -1.0], [2.0, -2.0], [3.0, -3.0], [4.0, -4.0]])
    tc = target_corr(x, 1)
    assert tc.constcor == min(0.0, -1 / (2 - 1) + 0.01)


def test_initset_and_cstep_edges() -> None:
    x = _data(30, 3)
    p_mat = np.eye(3)
    with pytest.raises(RError, match="h >= 1"):
        initset(x, p_mat, 0)
    with pytest.raises(RError, match="h <= n"):
        initset(x, p_mat, 31)
    mx = np.array(x.T)
    res = cstep_mrcd(mx, 0.1, 15, 1.2, np.arange(15), maxcsteps=1, record=True)
    assert res.numit == 1
    assert len(res.iterations) == 1
    v = np.array([3.0, np.nan, 1.0, 2.0])
    np.testing.assert_array_equal(next_index(v, 2), [1, 2])  # índices del vector sin NA


def test_rcov_and_smw_agree_with_dense_inverse() -> None:
    rng = np.random.default_rng(11)
    xx = rng.normal(size=(8, 5))  # p = 8 > h = 5 ⇒ SMW
    mu = xx.mean(axis=1)
    rc = rcov(xx, mu, 0.2, 1.3)
    assert rc.smw is not None
    np.testing.assert_allclose(rc.inv @ rc.rcov, np.eye(8), atol=1e-10)
    smw = inv_smw(0.2, 0.8 * 1.3, (xx - mu[:, None]) / math.sqrt(5))
    np.testing.assert_array_equal(smw.inv, rc.inv)


def test_ogk_small_p() -> None:
    y = _data(20, 1)
    assert np.array_equal(ogk_u(y), np.eye(1))
    p_mat = ogkscatter(_data(20, 3))
    np.testing.assert_allclose(p_mat.T @ p_mat, np.eye(3), atol=1e-14)


def test_detmrcd_record_matches_golden_c7() -> None:
    """``record=True`` guarda cada iteración; coincide con los índices de R (caso C7)."""
    inter = Inter("C7")
    hs = np.asarray(inter.get("hs_init"), dtype=np.int64) - 1
    res = detmrcd(inter.input_x(), alpha=0.5, hsets_init=hs, record=True)
    for k, cs, _obj in res.csteps:
        for t, it in enumerate(cs.iterations):
            np.testing.assert_array_equal(it.subset + 1, inter.ints(f"cs_index_k{k + 1}_it{t}"))
