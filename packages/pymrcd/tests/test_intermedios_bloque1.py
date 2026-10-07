"""Primitivas del bloque 1 sobre los intermedios reales de ``.detmrcd`` (protocolo i, por etapa).

Cada etapa se alimenta con el intermedio **de R** de la etapa anterior y se compara con el de R. Los
intermedios pesados de los casos grandes no se versionan: si faltan, el test se salta con motivo
explícito (nunca falla en silencio).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from fixtures_r import (
    EPS,
    FIXTURES,
    TOL_SCFAC_ALWAYS,
    FloatArray,
    assert_r_equal,
    read_csv_gz,
)
from pymrcd import _rbase as rb
from pymrcd._rlinalg import r_crossprod, r_eigen_sym, r_scale
from pymrcd.consistency import mcd_cons
from pymrcd.qn import qn_columns
from pymrcd.scaling import do_scale

MINSCALE = 0.001  # detmrcd.R:27

CASES = sorted(
    p.parent.parent.name for p in FIXTURES.glob("*/intermedios/indice.json") if p.is_file()
)


class Inter:
    """Acceso a los intermedios de un caso, con *skip* explícito si falta alguno."""

    def __init__(self, case: str) -> None:
        self.case = case
        self.folder = FIXTURES / case / "intermedios"
        self.index = json.loads((self.folder / "indice.json").read_text(encoding="utf-8"))
        self.manifest = json.loads((FIXTURES / case / "manifest.json").read_text("utf-8"))

    def get(self, name: str) -> FloatArray:
        meta = self.index.get(name)
        if meta is None:
            pytest.skip(f"{self.case}: intermedio {name} no exportado para este caso")
        path: Path = self.folder / str(meta["archivo"])
        if not path.exists():
            pytest.skip(f"{self.case}: intermedio {name} no versionado; regenerar con tools/r/")
        return read_csv_gz(path).reshape(tuple(int(v) for v in meta["forma"]))

    @property
    def equicorrelation(self) -> bool:
        return str(self.manifest.get("variante_target")) == "equicorrelation"

    def r6_input(self) -> FloatArray:
        return self.get("eq_mW") if self.equicorrelation else self.get("std_mU")


@pytest.fixture(params=CASES)
def inter(request: pytest.FixtureRequest) -> Inter:
    return Inter(str(request.param))


def test_standardization(inter: Inter) -> None:
    x = inter.get("in_x")
    vmx = rb.r_median_cols(x)  # detmrcd.R:417 apply(mX, 1, median)
    assert_r_equal(vmx, inter.get("std_vmx").ravel(), "E", "std_vmx")
    vsd_raw = qn_columns(x)  # detmrcd.R:418
    assert_r_equal(vsd_raw, inter.get("std_vsd_raw").ravel(), "E", "std_vsd_raw")
    vsd = np.where(vsd_raw < MINSCALE, MINSCALE, vsd_raw)  # detmrcd.R:419
    assert_r_equal(vsd, inter.get("std_vsd").ravel(), "E", "std_vsd")
    mu = r_scale(x, vmx, vsd)  # detmrcd.R:421
    assert_r_equal(mu, inter.get("std_mU"), "E", "std_mU")


def test_target_correlation_primitives(inter: Inter) -> None:
    if not inter.equicorrelation:
        pytest.skip(f"{inter.case}: target identity (sin .TargetCorr)")
    mu = inter.get("std_mU")
    rank = rb.r_cor_spearman(mu)  # detmrcd.R:217
    assert_r_equal(rank, inter.get("tgt_cortmp_rank"), "E", "tgt_cortmp_rank")
    sinr = rb.r_sin((0.5 * math.pi) * inter.get("tgt_cortmp_rank"))  # detmrcd.R:218
    assert_r_equal(sinr, inter.get("tgt_cortmp_sin"), "L", "tgt_cortmp_sin")
    p = sinr.shape[0]
    rows, cols = np.tril_indices(p, -1)
    constcor = rb.r_mean(inter.get("tgt_cortmp_sin")[cols, rows])  # detmrcd.R:219 (upper.tri)
    bound = min(0.0, -1 / (p - 1) + 0.01)
    if constcor <= bound:
        constcor = bound
    assert_r_equal(constcor, inter.get("tgt_constcor").item(), "E", "tgt_constcor")


def test_r6pack_doscale(inter: Inter) -> None:
    res = do_scale(inter.r6_input())  # detmrcd.R:123-125
    assert_r_equal(res.center, inter.get("r6_center").ravel(), "E", "r6_center")
    assert_r_equal(res.scale, inter.get("r6_scale").ravel(), "E", "r6_scale")
    assert_r_equal(res.x, inter.get("r6_x"), "E", "r6_x")


def test_r6pack_sets_1_2_3(inter: Inter) -> None:
    x = inter.get("r6_x")
    n = x.shape[0]
    y1 = rb.r_tanh(x)  # detmrcd.R:132
    assert_r_equal(y1, inter.get("r6_y1"), "L", "r6_y1")
    assert_r_equal(rb.r_cor(inter.get("r6_y1")), inter.get("r6_R1"), "E", "r6_R1")
    rank = rb.r_rank_cols(x)  # detmrcd.R:138, 143
    assert_r_equal(rank, inter.get("r6_rank"), "E", "r6_rank")
    assert_r_equal(rb.r_cor_spearman(x), inter.get("r6_R2"), "E", "r6_R2")
    y3 = rb.r_qnorm((rank - 1 / 3) / (n + 1 / 3))  # detmrcd.R:143
    assert_r_equal(y3, inter.get("r6_y3"), "L", "r6_y3")
    r3 = rb.r_cor(inter.get("r6_y3"), use="complete.obs")  # detmrcd.R:144
    assert_r_equal(r3, inter.get("r6_R3"), "E", "r6_R3")


def test_r6pack_sets_4_5(inter: Inter) -> None:
    x = inter.get("r6_x")
    n = x.shape[0]
    znorm = np.sqrt(rb.r_rowsums(x * x))  # detmrcd.R:149
    assert_r_equal(znorm, inter.get("r6_znorm").ravel(), "E", "r6_znorm")
    ii = znorm > EPS  # detmrcd.R:150
    xn = x.copy()
    xn[ii, :] = x[ii, :] / znorm[ii, None]  # detmrcd.R:151-152
    assert_r_equal(xn, inter.get("r6_xnrmd"), "E", "r6_xnrmd")
    assert_r_equal(r_crossprod(inter.get("r6_xnrmd")), inter.get("r6_SCM"), "B", "r6_SCM")
    ind5 = rb.r_order(znorm) + 1  # detmrcd.R:158
    np.testing.assert_array_equal(ind5, inter.get("r6_ind5").ravel().astype(np.int64))
    hinit = ind5[: math.ceil(n / 2)]
    np.testing.assert_array_equal(hinit, inter.get("r6_Hinit").ravel().astype(np.int64))
    covx = rb.r_cov(x[hinit - 1, :])  # detmrcd.R:161
    assert_r_equal(covx, inter.get("r6_covx"), "E", "r6_covx")


@pytest.mark.parametrize(
    ("ev", "src"),
    [("r6_ev1", "r6_R1"), ("r6_ev2", "r6_R2"), ("r6_ev3", "r6_R3"), ("r6_ev4", "r6_SCM")],
)
def test_r6pack_eigenvalues_declared_tolerance(inter: Inter, ev: str, src: str) -> None:
    """Autovalores (clase B, §11): ``atol = 10·p·eps·λmax`` (LAPACK de Accelerate ≠ Rlapack)."""
    ref = inter.get(ev).ravel()
    vals = r_eigen_sym(inter.get(src)).values
    lam_max = float(np.max(np.abs(ref)))
    np.testing.assert_allclose(vals, ref, rtol=0, atol=10 * ref.shape[0] * EPS * lam_max)


def test_consistency_factor(inter: Inter) -> None:
    n = int(inter.get("pre_n").item())
    p = int(inter.get("pre_p").item())
    h = int(inter.get("pre_h").item())
    got = mcd_cons(p, h / n)  # detmrcd.R:460
    np.testing.assert_allclose(got, inter.get("scfac").item(), rtol=TOL_SCFAC_ALWAYS, atol=0)
