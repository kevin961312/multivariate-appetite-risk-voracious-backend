"""``.MCDcons`` (``scfac``) contra R, con la tolerancia declarada rtol 1e-14 (decisión P3)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import special, stats

from fixtures_r import TOL_SCFAC_ALWAYS, Case, case_params
from pymrcd.consistency import mcd_cons


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Supera la tolerancia declarada (rtol 1e-14, P3): punto 196 de la rejilla (p=250, "
        "alpha=0.500000000001) da rel 1.22e-14 (qchisq de scipy a 1 ulp de R, amplificado "
        "por pgamma). Pendiente de decisión del dueño: portar nmath o revisar P3."
    ),
)
@pytest.mark.parametrize("case", case_params("MCDcons"))
def test_mcd_cons(case: Case) -> None:
    p = case.inputs["p"].ravel()
    alpha = case.inputs["alpha"].ravel()
    got = np.array([mcd_cons(int(pp), float(a)) for pp, a in zip(p, alpha, strict=True)])
    np.testing.assert_allclose(got, case.outputs["scfac"].ravel(), rtol=TOL_SCFAC_ALWAYS, atol=0)


@pytest.mark.parametrize("case", case_params("qchisq"))
def test_qchisq_scipy(case: Case) -> None:
    got = stats.chi2.ppf(case.inputs["alpha"].ravel(), case.inputs["p"].ravel())
    np.testing.assert_allclose(got, case.outputs["q"].ravel(), rtol=TOL_SCFAC_ALWAYS, atol=0)


@pytest.mark.parametrize("case", case_params("pgamma"))
def test_pgamma_scipy(case: Case) -> None:
    got = special.gammainc(case.inputs["shape"].ravel(), case.inputs["q"].ravel())
    np.testing.assert_allclose(got, case.outputs["pg"].ravel(), rtol=TOL_SCFAC_ALWAYS, atol=0)


def test_mcd_cons_known_value() -> None:
    # p = 1, alpha = 0.5: 1 / (pgamma(qchisq(.5,1)/2, 1.5)/.5)
    q = float(stats.chi2.ppf(0.5, 1))
    assert mcd_cons(1, 0.5) == 1 / (float(special.gammainc(1.5, q / 2)) / 0.5)
