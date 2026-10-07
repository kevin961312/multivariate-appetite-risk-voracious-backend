import dataclasses
import inspect
from typing import cast

import numpy as np
import pytest

import pymrcd
from support.golden import read_case_x
from support.solo_test import small_data
from voracious.domain.common import EstimationError, InvalidInputError
from voracious.domain.estimators.mrcd import (
    ESTIMATOR_NAME,
    MRCD_FIT_FAILED,
    PYMRCD_VERSION,
    MRCDEstimator,
    MRCDParams,
    MRCDTarget,
    fit_mrcd,
)


def test_defaults_match_cov_mrcd_signature() -> None:
    # Los defaults de MRCDParams son los de pymrcd.cov_mrcd (= CovControlMrcd de rrcov 1.7-7).
    # n_threads es de rendimiento (no estadístico): va aparte, no en MRCDParams.
    signature = inspect.signature(pymrcd.cov_mrcd).parameters
    for f in dataclasses.fields(MRCDParams):
        assert f.default == signature[f.name].default, f.name
    assert {f.name for f in dataclasses.fields(MRCDParams)} == set(signature) - {
        "x",
        "init_hsets",
        "n_threads",
    }


def test_fit_is_bitwise_equal_to_cov_mrcd_on_golden_c7() -> None:
    x = read_case_x("C7")
    fit = fit_mrcd(x, MRCDParams())
    ref = pymrcd.cov_mrcd(x)
    for name in ("center", "cov", "icov", "mah", "best", "ok", "i_best", "n_csteps"):
        assert np.array_equal(getattr(fit, name), getattr(ref, name)), name
    assert fit.rho == ref.rho
    assert fit.cnp2 == ref.cnp2
    assert fit.crit == ref.crit
    assert fit.alpha == ref.alpha
    assert fit.h == ref.quan
    assert fit.n_obs == ref.n_obs == x.shape[0]
    assert fit.best.dtype == np.int64
    assert fit.best.min() >= 0  # base 0
    assert fit.n_features == x.shape[1]


def test_distances_reproduce_mah() -> None:
    x = small_data()
    fit = fit_mrcd(x, MRCDParams())
    assert np.array_equal(fit.distances(x[fit.ok]), fit.mah)


def test_distances_reject_wrong_number_of_features() -> None:
    fit = fit_mrcd(small_data(), MRCDParams())
    with pytest.raises(InvalidInputError) as info:
        fit.distances(np.zeros((3, 5)))
    assert info.value.details == {"expected_features": 4, "got_features": 5}


def test_alpha_below_half_is_mrcd_fit_failed() -> None:
    with pytest.raises(EstimationError) as info:
        fit_mrcd(small_data(), MRCDParams(alpha=0.4))
    assert info.value.code == MRCD_FIT_FAILED
    assert "between 0.5 and 1" in str(info.value.details["r_message"])


def test_constant_column_is_mrcd_fit_failed() -> None:
    # rrcov falla de verdad aquí (la escala Qn de la columna es 0); el port lanza RError y el
    # adaptador lo traduce, sin fallback.
    x = small_data()
    x[:, 2] = 3.0
    with pytest.raises(pymrcd.RError):
        pymrcd.cov_mrcd(x)
    with pytest.raises(EstimationError) as info:
        fit_mrcd(x, MRCDParams())
    assert info.value.code == MRCD_FIT_FAILED
    assert info.value.details["r_message"]


def test_invalid_target_is_mrcd_fit_failed() -> None:
    # Un target fuera del Literal solo puede llegar sin tipar (p. ej. desde JSON).
    params = MRCDParams(target=cast("MRCDTarget", "diagonal"))
    with pytest.raises(EstimationError) as info:
        fit_mrcd(small_data(), params)
    assert info.value.code == MRCD_FIT_FAILED


def test_non_finite_rows_are_reported_in_ok() -> None:
    x = small_data(42)
    x[5, 0] = np.nan
    fit = fit_mrcd(x, MRCDParams())
    assert not fit.ok[5]
    assert fit.n_obs == 41
    assert fit.mah.shape == (41,)


def test_pymrcd_version_is_exposed() -> None:
    assert pymrcd.__version__ == PYMRCD_VERSION


def test_estimator_delegates_to_fit_mrcd_and_is_picklable() -> None:
    import copy
    import pickle

    x = small_data()
    params = MRCDParams(alpha=0.75)
    estimator = MRCDEstimator(params)
    assert estimator.name == ESTIMATOR_NAME == "mrcd"
    fit = estimator.fit(x)
    ref = fit_mrcd(x, params)
    assert np.array_equal(fit.cov, ref.cov)
    assert np.array_equal(fit.center, ref.center)
    assert pickle.dumps(estimator)
    assert copy.deepcopy(estimator) == estimator


def test_n_threads_is_performance_only() -> None:
    x = read_case_x("C7")
    one = fit_mrcd(x, MRCDParams(), n_threads=1)
    many = MRCDEstimator(MRCDParams(), n_threads=4).fit(x)
    for name in ("center", "cov", "icov", "mah", "best", "ok", "i_best", "n_csteps"):
        a, b = getattr(one, name), getattr(many, name)
        assert a.dtype == b.dtype, name
        assert a.tobytes() == b.tobytes(), name
    assert (one.rho, one.cnp2, one.crit) == (many.rho, many.cnp2, many.crit)
    assert MRCDEstimator(MRCDParams()).n_threads is None
