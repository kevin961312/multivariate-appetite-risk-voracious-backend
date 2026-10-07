"""``doScale(x, median, Qn)`` y ``non0Q`` contra los fixtures de R."""

from __future__ import annotations

import numpy as np
import pytest

from fixtures_r import Case, assert_r_equal, case_params
from pymrcd._errors import RError
from pymrcd.scaling import NON0Q_PROBS, do_scale, non0q


@pytest.mark.parametrize("case", case_params("doScale"))
def test_do_scale(case: Case) -> None:
    res = do_scale(case.inputs["X"])
    assert_r_equal(res.x, case.outputs["x"], "E", case.id)
    assert_r_equal(res.center, case.outputs["center"].ravel(), "E", case.id)
    assert_r_equal(res.scale, case.outputs["scale"].ravel(), "E", case.id)


def test_non0q_probs_and_fallbacks() -> None:
    np.testing.assert_array_equal(NON0Q_PROBS, np.array([*range(10, 20), 19.75]) / 20)
    assert non0q(np.zeros(10)) == 1.0
    u = np.concatenate([np.zeros(8), [1.0, -2.0]])
    assert non0q(u) > 0


def test_do_scale_constant_column_and_errors() -> None:
    x = np.column_stack([np.ones(10), np.arange(10.0)])
    res = do_scale(x)
    assert res.scale[0] == 1.0
    np.testing.assert_array_equal(res.x[:, 0], np.zeros(10))
    with pytest.raises(RError, match="better scale"):
        do_scale(np.array([[1.0, 2.0], [np.nan, 3.0], [2.0, 1.0]]))
