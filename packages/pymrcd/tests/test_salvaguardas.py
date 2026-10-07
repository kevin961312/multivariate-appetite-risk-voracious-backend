"""Salvaguardas de las llamadas por puntero (``_blasptr``) y de la carga de libm (``_nmath``)."""

from __future__ import annotations

import ctypes
import sys

import numpy as np
import pytest
from scipy.linalg import cython_blas

from pymrcd import _blasptr as bp
from pymrcd import _nmath


@pytest.mark.parametrize("name", sorted(bp._SIGNATURES))
def test_capsule_signatures_are_lp64(name: str) -> None:
    """La firma de scipy coincide con la LP64 esperada (la que se verifica al importar)."""
    get_name = ctypes.pythonapi.PyCapsule_GetName
    get_name.restype = ctypes.c_char_p
    get_name.argtypes = [ctypes.py_object]
    assert get_name(cython_blas.__pyx_capi__[name]) == bp.expected_signature(name)


def test_routine_rejects_unexpected_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(bp._SIGNATURES, "dscal", ("v", "iddd"))
    with pytest.raises(ImportError, match="firma inesperada"):
        bp._routine("dscal", None, 4)


def test_routine_rejects_missing_capsule() -> None:
    with pytest.raises(ImportError, match="no publica"):
        bp._routine("dnoexiste", None, 1)


def test_bounds_checks() -> None:
    a = np.asfortranarray(np.eye(3))
    with pytest.raises(ValueError, match="dgemm A"):
        bp.dgemm("N", "N", 3, 3, 3, 1.0, a, 1, 0, a, 0, 0, 0.0, a, 0, 0)
    with pytest.raises(ValueError, match="dgemm B"):
        bp.dgemm("T", "T", 2, 2, 3, 1.0, a, 0, 0, a, 0, 1, 0.0, a, 0, 0)
    with pytest.raises(ValueError, match="dtrsm A"):
        bp.dtrsm("R", "U", "N", "N", 3, 4, 1.0, a, 0, 0, a, 0, 0)
    with pytest.raises(ValueError, match="dtrmm B"):
        bp.dtrmm("L", "U", "N", "N", 3, 3, 1.0, a, 0, 0, a, 0, 1)
    with pytest.raises(ValueError, match="dsyrk C"):
        bp.dsyrk("U", "T", 3, 2, 1.0, a, 0, 0, 0.0, a, 1, 1)
    with pytest.raises(ValueError, match="dtrmv x"):
        bp.dtrmv("U", "N", "N", 3, a, 0, 0, a, 1, 2, 1)
    with pytest.raises(ValueError, match="dgemv y"):
        bp.dgemv("N", 3, 2, 1.0, a, 0, 0, a, 0, 0, 1, 0.0, a, 1, 2, 1)
    with pytest.raises(ValueError, match="ddot x"):
        bp.ddot(3, a, 0, 0, 0, a, 0, 0, 1)
    with pytest.raises(ValueError, match="dscal x"):
        bp.dscal(-1, 2.0, a, 0, 0, 1)
    with pytest.raises(ValueError, match="idamax x"):
        bp.idamax(2, a, 3, 0, 1)
    with pytest.raises(ValueError, match="float64"):
        bp.dscal(1, 2.0, np.eye(3, dtype=np.float32), 0, 0, 1)
    # Vector vacío en el borde: válido (lo usa dgetrf2 con m = 1).
    bp.dscal(0, 2.0, a, 3, 2, 1)
    assert np.array_equal(a, np.eye(3))


def test_libm_resolution_by_platform() -> None:
    with pytest.raises(ImportError, match="no soportada"):
        _nmath._load_libm_lgamma("win32")
    with pytest.raises(ImportError, match="no se pudo cargar"):
        _nmath._load_libm_lgamma("linux") if sys.platform == "darwin" else _nmath._load_libm_lgamma(
            "darwin"
        )
    assert _nmath._load_libm_lgamma()(1.0) == 0.0
