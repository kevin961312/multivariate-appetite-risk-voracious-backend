"""Bloque 2 por etapa contra los intermedios de R (protocolo de fidelidad, nivel i).

Cada etapa se alimenta con las **entradas de R de esa etapa** (intermedios exportados por
``tools/r/exportar_intermedios.R``) y su salida se compara con la de R:

- bit a bit en la plataforma de referencia (``assert_r_equal``) para todo lo que no pasa por
  ``eigen``;
- autovalores/autovectores con la tolerancia clase B de la especificación §11 (divergencia
  Accelerate vs Rlapack aceptada por el dueño, ver ``r_eigen_sym``).

Si un intermedio pesado no está versionado, el test se salta con el motivo explícito.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable

import numpy as np
import pytest

from fixtures_r import EPS, INTER_CASES, FloatArray, Inter, assert_r_equal
from pymrcd._rbase import r_colmedians, r_order, r_rowmeans
from pymrcd._rlinalg import (
    r_eigen_sym,
    r_eigen_values,
    r_mahalanobis_d,
    r_matprod,
    r_vecmat,
)
from pymrcd.csteps import cstep_mrcd, mahalanobis_all, next_index
from pymrcd.detmrcd import back_transform, final_estimate, mrcd_objective
from pymrcd.ogk import ogk_u
from pymrcd.r6pack import initset, set1_matrix, set2_matrix, set3_matrix, set4_matrix, set5_matrix
from pymrcd.rcov import rcov
from pymrcd.rho import UNIROOT_LOWER, UNIROOT_UPPER, fncond_factory, rho_for_subset, select_rho
from pymrcd.scaling import do_scale
from pymrcd.target import eigen_eq, equicorrelation_transform, target_corr

MAXCOND = 50.0  # CovControl.R:27 (todos los casos usan el valor por defecto)
MAXCSTEPS = 200  # CovControl.R:24


class SignosAutovectores(UserWarning):
    """Aviso informativo: autovectores de ``eigen`` con signo opuesto al de R (T3, D9)."""


@pytest.fixture(params=INTER_CASES)
def inter(request: pytest.FixtureRequest) -> Inter:
    return Inter(str(request.param))


def assert_eigvals_b(got: FloatArray, ref: FloatArray, what: str) -> None:
    """Autovalores, clase B (§11): ``atol = 10·p·eps·λmax``."""
    lam_max = float(np.max(np.abs(ref)))
    atol = 10 * ref.shape[0] * EPS * lam_max
    np.testing.assert_allclose(got, ref, rtol=0, atol=atol, err_msg=what)


def assert_eigvecs_b(got: FloatArray, vals: FloatArray, ref: FloatArray, what: str) -> int:
    """Autovectores, clase B (§11): módulo signo en autoespacios con gap relativo > 1e-8.

    Returns:
        Número de columnas con el signo opuesto al de R (trampa T3; se informa, no se exige).
    """
    p = vals.shape[0]
    lam_max = float(np.max(np.abs(vals)))
    flips = 0
    for i in range(p):
        gaps = [abs(vals[i] - vals[j]) for j in (i - 1, i + 1) if 0 <= j < p]
        gap = min(gaps) if gaps else math.inf
        if lam_max == 0 or gap / lam_max <= 1e-8:
            continue
        s = 1.0 if float(got[:, i] @ ref[:, i]) >= 0 else -1.0
        flips += int(s < 0)
        tol = 10 * p * EPS * lam_max / gap
        err = float(np.max(np.abs(s * got[:, i] - ref[:, i])))
        assert err <= tol, f"{what}: vector {i} |Δ|={err:.3g} > {tol:.3g}"
    return flips


# --------------------------------------------------------------------------------- target (§3.4)


def test_target_corr(inter: Inter) -> None:
    mu = inter.get("std_mU")
    if not inter.equicorrelation:
        res = target_corr(mu, 0)
        assert np.array_equal(res.R, np.eye(mu.shape[1]))
        return
    res = target_corr(mu, 1)  # detmrcd.R:207-229
    assert res.constcor is not None
    assert_r_equal(res.cortmp_rank, inter.get("tgt_cortmp_rank"), "E", "tgt_cortmp_rank")
    assert_r_equal(res.cortmp_sin, inter.get("tgt_cortmp_sin"), "L", "tgt_cortmp_sin")
    assert_r_equal(res.constcor, inter.scalar("tgt_constcor"), "L", "tgt_constcor")
    assert_r_equal(res.R, inter.get("tgt_R"), "L", "tgt_R")


def test_eigen_eq_and_rotation(inter: Inter) -> None:
    if not inter.equicorrelation:
        pytest.skip(f"{inter.case}: target identity (sin eigenEQ)")
    eq = eigen_eq(inter.get("tgt_R"))  # detmrcd.R:231-248, entradas de R
    assert_r_equal(eq.values, inter.get("eq_values").ravel(), "E", "eq_values")
    assert_r_equal(eq.vectors, inter.get("eq_mQ"), "E", "eq_mQ")
    tr = equicorrelation_transform(inter.get("std_mU"), inter.get("tgt_R"))  # :426-433
    assert_r_equal(tr.m_w, inter.get("eq_mW"), "B", "eq_mW")


# --------------------------------------------------------------------------------- r6pack (§3.5)


def test_r6pack_set_matrices(inter: Inter) -> None:
    x = inter.get("r6_x")
    assert_r_equal(set1_matrix(x), inter.get("r6_R1"), "L", "r6_R1")
    assert_r_equal(set2_matrix(x), inter.get("r6_R2"), "E", "r6_R2")
    assert_r_equal(set3_matrix(x), inter.get("r6_R3"), "L", "r6_R3")
    assert_r_equal(set4_matrix(x), inter.get("r6_SCM"), "B", "r6_SCM")
    assert_r_equal(set5_matrix(x), inter.get("r6_covx"), "E", "r6_covx")


def test_ogk_u(inter: Inter) -> None:
    """``U`` de ``ogkscatter`` (detmrcd.R:86-98): Qn por pares, exacto."""
    assert_r_equal(ogk_u(inter.get("r6_x")), inter.get("r6_U"), "E", "r6_U")


@pytest.mark.parametrize(
    ("k", "src"),
    [(1, "r6_R1"), (2, "r6_R2"), (3, "r6_R3"), (4, "r6_SCM"), (5, "r6_covx"), (6, "r6_U")],
)
def test_r6pack_eigen_declared_tolerance(
    inter: Inter, k: int, src: str, record_property: Callable[[str, object], None]
) -> None:
    """``P_k = eigen(·)$vectors`` (clase B; divergencia de LAPACK aceptada).

    El número de columnas con signo opuesto al de R (T3, D9) se informa como propiedad del test
    (``record_property``, visible en el XML de JUnit) y como aviso ``SignosAutovectores`` en el
    resumen de pytest si es distinto de cero; no hace fallar el test (§11).
    """
    res = r_eigen_sym(inter.get(src))
    ev = inter.get(f"r6_ev{k}").ravel()
    assert_eigvals_b(res.values, ev, f"r6_ev{k}")
    flips = assert_eigvecs_b(res.vectors, ev, inter.get(f"r6_P{k}"), f"r6_P{k}")
    record_property(f"flips_P{k}", flips)
    if flips:
        warnings.warn(
            f"{inter.case}: P{k} con {flips} autovector(es) de signo opuesto a R (T3/D9)",
            SignosAutovectores,
            stacklevel=1,
        )


@pytest.mark.parametrize("k", [1, 2, 3, 4, 5, 6])
def test_initset_stages(inter: Inter, k: int) -> None:
    """``initset`` (detmrcd.R:65-76), cada etapa con las entradas de R."""
    x = inter.get("r6_x")
    p_mat = inter.get(f"r6_P{k}")
    h = int(inter.scalar("pre_h"))
    proj = inter.get(f"is_proj_k{k}")
    assert_r_equal(r_matprod(x, p_mat), proj, "B", "is_proj")  # :70
    lam = inter.get(f"is_lambda_k{k}").ravel()
    assert_r_equal(do_scale(proj).scale, lam, "E", "is_lambda")  # :70
    pt = np.array(p_mat.T)
    sqrtcov = inter.get(f"is_sqrtcov_k{k}")
    sqrtinvcov = inter.get(f"is_sqrtinvcov_k{k}")
    assert_r_equal(r_matprod(p_mat, lam[:, None] * pt), sqrtcov, "B", "is_sqrtcov")  # :71
    assert_r_equal(r_matprod(p_mat, pt / lam[:, None]), sqrtinvcov, "B", "is_sqrtinvcov")  # :72
    colmed = inter.get(f"is_colmed_k{k}").ravel()
    assert_r_equal(r_colmedians(r_matprod(x, sqrtinvcov)), colmed, "B", "is_colmed")  # :73
    estloc = inter.get(f"is_estloc_k{k}").ravel()
    assert_r_equal(r_vecmat(colmed, sqrtcov), estloc, "B", "is_estloc")  # :73
    centeredx = inter.get(f"is_centeredx_k{k}")
    assert_r_equal(r_matprod(x - estloc[None, :], p_mat), centeredx, "B", "is_centeredx")  # :74
    dist = inter.get(f"is_dist_k{k}").ravel()
    assert_r_equal(r_mahalanobis_d(centeredx, lam), dist, "E", "is_dist")  # :75
    ord_r = inter.ints(f"is_ord_k{k}")
    np.testing.assert_array_equal(r_order(dist)[:h] + 1, ord_r)  # :75
    full = initset(x, p_mat, h)  # cadena completa con P de R
    np.testing.assert_array_equal(full.ord + 1, ord_r)
    np.testing.assert_array_equal(_hs(inter)[:, k - 1] + 1, ord_r)


# --------------------------------------------------------------------------------- rho (§3.7)


def _hs(inter: Inter) -> np.ndarray:
    return np.asarray(inter.get("hs_init"), dtype=np.int64) - 1


@pytest.mark.parametrize("k", [1, 2, 3, 4, 5, 6])
def test_rho_subset_scatter(inter: Inter, k: int) -> None:
    """``mu``, ``mS`` y autovalores del subconjunto k (detmrcd.R:467-475)."""
    mx = inter.mx()
    h = int(inter.scalar("pre_h"))
    idx = _hs(inter)[:, k - 1]
    xs = mx[:, idx]
    mu = r_rowmeans(xs)
    assert_r_equal(mu, inter.get(f"rs_mu_k{k}").ravel(), "E", "rs_mu")
    me = xs - inter.get(f"rs_mu_k{k}").ravel()[:, None]
    m_s = inter.get(f"rs_mS_k{k}")
    assert_r_equal(r_matprod(me, np.array(me.T)) / (h - 1), m_s, "B", "rs_mS")
    vals = r_eigen_values(inter.scalar("scfac") * m_s)
    ref = inter.get(f"rs_veigen_k{k}").ravel()
    assert_eigvals_b(vals, ref, "rs_veigen")
    atol = 10 * ref.shape[0] * EPS * float(np.max(np.abs(ref)))  # e1, ep: clase B (§11)
    assert abs(float(vals.min()) - inter.scalar(f"rs_e1_k{k}")) <= atol
    assert abs(float(vals.max()) - inter.scalar(f"rs_ep_k{k}")) <= atol
    assert inter.scalar(f"rs_e1_k{k}") == ref.min()
    assert inter.scalar(f"rs_ep_k{k}") == ref.max()


@pytest.mark.parametrize("k", [1, 2, 3, 4, 5, 6])
def test_rho_k_from_r_eigenvalues(inter: Inter, k: int) -> None:
    """``rho_k`` dado ``(e1, ep)`` de R: escalar puro, exacto (uniroot o rejilla)."""
    e1 = inter.scalar(f"rs_e1_k{k}")
    ep = inter.scalar(f"rs_ep_k{k}")
    f = fncond_factory(e1, ep, MAXCOND)
    assert_r_equal(f(UNIROOT_LOWER), inter.scalar(f"rs_flower_k{k}"), "E", "rs_flower")
    assert_r_equal(f(UNIROOT_UPPER), inter.scalar(f"rs_fupper_k{k}"), "E", "rs_fupper")
    rk = rho_for_subset(e1, ep, MAXCOND)
    assert rk.path == int(inter.scalar(f"rs_path_k{k}"))
    assert_r_equal(rk.rho, inter.scalar(f"rs_rhok_k{k}"), "E", "rs_rhok")
    if rk.path == 1:
        assert_r_equal(rk.root, inter.scalar(f"rs_root_k{k}"), "E", "rs_root")
        assert rk.iter == int(inter.scalar(f"rs_iter_k{k}"))
        assert_r_equal(rk.estim_prec, inter.scalar(f"rs_estimprec_k{k}"), "E", "rs_estimprec")


def test_rho_selection(inter: Inter) -> None:
    """``cutoff``, ``rho``, ``Vselection``, ``initV``, ``setsV`` (detmrcd.R:518-535)."""
    rho6 = inter.get("rs_rho6").ravel()
    sel = select_rho(rho6)
    assert_r_equal(sel.cutoff, inter.scalar("rs_cutoff"), "E", "rs_cutoff")
    assert_r_equal(sel.rho, inter.scalar("rs_rho"), "E", "rs_rho")
    vsel_r = inter.ints("rs_Vsel")
    np.testing.assert_array_equal(np.where(sel.vsel >= 0, sel.vsel + 1, -1), vsel_r)
    assert sel.init_v + 1 == int(inter.scalar("rs_initV"))
    sets_r = inter.ints("rs_setsV") if inter.has("rs_setsV") else np.array([], dtype=np.int64)
    np.testing.assert_array_equal(sel.sets_v + 1, sets_r)


# --------------------------------------------------------------------------------- C-steps (§3.8)


def _processed(inter: Inter) -> list[int]:
    return [k for k in range(1, 7) if f"cs_numit_k{k}" in inter.index]


def test_csteps_iterations(inter: Inter) -> None:
    """Cada iteración de ``.cstep_mrcd`` con las entradas de R de esa iteración."""
    mx = inter.mx()
    h = int(inter.scalar("pre_h"))
    rho = inter.scalar("rs_rho")
    scfac = inter.scalar("scfac")
    p = mx.shape[0]
    checked = 0
    for k in _processed(inter):
        t = 0
        while f"cs_index_k{k}_it{t}" in inter.index:
            index = inter.ints(f"cs_index_k{k}_it{t}") - 1
            xx = mx[:, index]
            v_mu = inter.get(f"cs_vMu_k{k}_it{t}").ravel()
            assert_r_equal(r_rowmeans(xx), v_mu, "E", f"cs_vMu k{k} t{t}")  # :353/:367
            rc = rcov(xx, v_mu, rho, scfac)  # .RCOV, :269-290
            if p > h:
                assert rc.smw is not None
                inv = rc.inv
            else:
                assert_r_equal(rc.m_s, inter.get(f"cs_mS_k{k}_it{t}"), "B", "cs_mS")
                assert_r_equal(rc.rcov, inter.get(f"cs_rcov_k{k}_it{t}"), "B", "cs_rcov")
                inv = inter.get(f"cs_inv_k{k}_it{t}")
                assert_r_equal(rc.inv, inv, "B", "cs_inv")
            vdst = inter.get(f"cs_vdst_k{k}_it{t}").ravel()
            assert_r_equal(mahalanobis_all(mx, v_mu, inv), vdst, "B", "cs_vdst")  # :360/:371
            nndex = inter.ints(f"cs_nndex_k{k}_it{t}")
            np.testing.assert_array_equal(next_index(vdst, h) + 1, nndex)  # :361/:372
            t += 1
            checked += 1
    assert checked > 0


def test_csteps_smw_ms_rcov(inter: Inter) -> None:
    """Rama SMW (``p > h``): ``mS`` y ``rcov`` de ``.RCOV`` (``detmrcd.R:274-275``) contra R.

    En la rama SMW R también calcula ``mS`` y ``rcov`` antes de invertir; se comparan cuando el caso
    exporta esas matrices ``p x p`` (C11; en C7-C9 y C8_eq ``p <= h`` y las cubre
    ``test_csteps_iterations``). Si no están versionadas se salta con el motivo.
    """
    mx = inter.mx()
    h = int(inter.scalar("pre_h"))
    p = mx.shape[0]
    if p <= h:
        pytest.skip(f"{inter.case}: p <= h (rama Cholesky; mS/rcov en test_csteps_iterations)")
    names = [
        (k, t)
        for k in _processed(inter)
        for t in range(MAXCSTEPS + 1)
        if f"cs_index_k{k}_it{t}" in inter.index
    ]
    if not all(inter.has(f"cs_mS_k{k}_it{t}") for k, t in names):
        pytest.skip(
            f"{inter.case}: cs_mS/cs_rcov (p x p) de la rama SMW no versionados "
            "(golden/fixtures/README.md); regenerar con tools/r/"
        )
    rho = inter.scalar("rs_rho")
    scfac = inter.scalar("scfac")
    for k, t in names:
        index = inter.ints(f"cs_index_k{k}_it{t}") - 1
        rc = rcov(mx[:, index], inter.get(f"cs_vMu_k{k}_it{t}").ravel(), rho, scfac)
        assert rc.smw is not None
        assert_r_equal(rc.m_s, inter.get(f"cs_mS_k{k}_it{t}"), "B", f"cs_mS k{k} t{t}")
        assert_r_equal(rc.rcov, inter.get(f"cs_rcov_k{k}_it{t}"), "B", f"cs_rcov k{k} t{t}")
    assert names


def test_csteps_full(inter: Inter) -> None:
    """``.cstep_mrcd`` completo desde ``hsets.init[, k]`` de R, con ``rho`` y ``scfac`` de R."""
    mx = inter.mx()
    h = int(inter.scalar("pre_h"))
    hs = _hs(inter)
    p = mx.shape[0]
    for k in _processed(inter):
        res = cstep_mrcd(
            mx, inter.scalar("rs_rho"), h, inter.scalar("scfac"), hs[:, k - 1], MAXCSTEPS, True
        )
        assert res.numit == int(inter.scalar(f"cs_numit_k{k}"))
        for t, it in enumerate(res.iterations):
            np.testing.assert_array_equal(it.subset + 1, inter.ints(f"cs_index_k{k}_it{t}"))
            np.testing.assert_array_equal(it.nndex + 1, inter.ints(f"cs_nndex_k{k}_it{t}"))
        assert_r_equal(mrcd_objective(res.cov, p), inter.scalar(f"cs_obj_k{k}"), "B", "cs_obj")


# --------------------------------------------------------------------------------- final (§3.10)


def _best_mu(inter: Inter) -> FloatArray:
    """``ret$mu`` del mejor subconjunto: ``vMu`` de su última iteración (T18)."""
    best = int(inter.ints("sel_best6pack")[0])
    t = 0
    while f"cs_vMu_k{best}_it{t + 1}" in inter.index:
        t += 1
    return inter.get(f"cs_vMu_k{best}_it{t}").ravel()


def test_final_estimate(inter: Inter) -> None:
    mx = inter.mx()
    h = int(inter.scalar("pre_h"))
    rho = inter.scalar("rs_rho")
    c_alpha = inter.scalar("scfac")
    hindex = inter.ints("sel_hindex") - 1
    fin = final_estimate(mx, hindex, _best_mu(inter), rho, c_alpha, h)
    assert_r_equal(fin.m_e, inter.get("fin_mE"), "E", "fin_mE")
    assert_r_equal(fin.mu, inter.get("fin_mu_std").ravel(), "E", "fin_mu_std")
    w = inter.get("fin_W")
    assert_r_equal(fin.W, w, "B", "fin_W")
    eye = np.eye(mx.shape[0])
    assert_r_equal(rho * eye + ((1 - rho) * c_alpha) * w, inter.get("fin_cov_std"), "E", "cov_std")
    if fin.smw is not None:
        assert_r_equal(fin.smw.G, inter.get("fin_smwG"), "B", "fin_smwG")
        assert_r_equal(fin.smw.Temp, inter.get("fin_smwTemp"), "B", "fin_smwTemp")
    assert_r_equal(fin.icov, inter.get("fin_icov_std"), "B", "fin_icov_std")


def test_back_transform(inter: Inter) -> None:
    eq = None
    if inter.equicorrelation:
        eq = equicorrelation_transform(inter.get("std_mU"), inter.get("tgt_R"))
    back = back_transform(
        inter.get("fin_mu_std").ravel(),
        inter.get("fin_cov_std"),
        inter.get("fin_icov_std"),
        inter.get("std_vsd").ravel(),
        inter.get("std_vmx").ravel(),
        eq,
    )
    assert_r_equal(back.center, inter.get("fin_center").ravel(), "B", "fin_center")
    assert_r_equal(back.cov, inter.get("fin_cov"), "B", "fin_cov")
    assert_r_equal(back.icov, inter.get("fin_icov"), "B", "fin_icov")
    assert_r_equal(back.target, inter.get("fin_target"), "B", "fin_target")
    assert_r_equal(back.crit, inter.scalar("fin_crit"), "B", "fin_crit")
