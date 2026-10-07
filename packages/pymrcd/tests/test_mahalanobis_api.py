"""API pública ``mahalanobis`` (``stats::mahalanobis`` de R 4.5.2, ``CovMrcd.R:46``).

La rutina es la misma con la que ``cov_mrcd`` calcula ``mah``: sobre el resultado del port debe
coincidir bit a bit con ``res.mah`` en cualquier plataforma, y sobre ``center``/``icov`` de R debe
reproducir el ``mah`` de R con la regla de fidelidad de clase B (bit a bit en la referencia).
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures_r import Inter, assert_r_equal
from pymrcd import RError, cov_mrcd, mahalanobis


def test_equals_cov_mrcd_mah_bitwise() -> None:
    inter = Inter("C7")
    res = cov_mrcd(inter.input_x(), alpha=float(inter.manifest["parametros"]["alpha"]))
    assert np.array_equal(mahalanobis(res.x, res.center, res.icov), res.mah)


def test_reproduces_r_mah_from_r_center_and_icov() -> None:
    inter = Inter("C7")
    x = inter.input_x()
    p = x.shape[1]
    got = mahalanobis(x, inter.output("center").ravel(), inter.output("icov").reshape(p, p))
    assert_r_equal(got, inter.output("mah").ravel(), "B", "mah")


def test_vector_is_one_row() -> None:
    # mahalanobis.R:33: un vector es matrix(x, ncol = length(x)), una sola fila.
    rng = np.random.default_rng(1)
    x = rng.normal(size=(5, 3))
    center = rng.normal(size=3)
    icov = np.eye(3)
    full = mahalanobis(x, center, icov)
    one = mahalanobis(x[2], center, icov)
    assert one.shape == (1,)
    assert one[0] == full[2]


def test_rejects_non_matrix_and_non_conformable() -> None:
    with pytest.raises(RError, match="matrix or a vector"):
        mahalanobis(np.zeros((2, 2, 2)), np.zeros(2), np.eye(2))
    with pytest.raises(RError, match="non-conformable"):
        mahalanobis(np.zeros((4, 3)), np.zeros(2), np.eye(2))
    with pytest.raises(RError, match="non-conformable"):
        mahalanobis(np.zeros((4, 3)), np.zeros(3), np.eye(2))


def test_rejects_icov_not_square_p_by_p() -> None:
    # mahalanobis.R:46: x %*% cov * x. nrow(icov) != p falla en %*%; ncol(icov) != p, en *.
    x = np.zeros((4, 3))
    center = np.zeros(3)
    with pytest.raises(RError, match=r"^non-conformable arrays$"):
        mahalanobis(x, center, np.ones((3, 1)))
    with pytest.raises(RError, match=r"^non-conformable arrays$"):
        mahalanobis(x, center, np.ones(3))  # vector = columna 3 x 1
    with pytest.raises(RError, match=r"^non-conformable arrays$"):
        mahalanobis(x, center, np.ones((3, 4)))
    with pytest.raises(RError, match=r"^non-conformable arguments$"):
        mahalanobis(x, center, np.ones((1, 3)))
    with pytest.raises(RError, match=r"^non-conformable arguments$"):
        mahalanobis(x, center, np.ones(2))
    with pytest.raises(RError, match=r"^non-conformable arguments$"):
        mahalanobis(x, center, np.ones((3, 3, 1)))


def test_one_variable_accepts_scalar_vector_icov() -> None:
    x = np.array([[1.0], [2.0], [-3.0]])
    got = mahalanobis(x, np.zeros(1), np.array([2.0]))
    assert np.array_equal(got, mahalanobis(x, np.zeros(1), np.array([[2.0]])))
