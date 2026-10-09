import ast
import copy
import pickle
from pathlib import Path

import numpy as np
import pytest

from voracious.domain import charts, estimators
from voracious.domain.common import (
    DomainError,
    EstimationError,
    InvalidInputError,
    MethodDecisionPendingError,
    SerialTaskMapper,
    as_matrix,
)


def test_as_matrix_returns_float64_copy() -> None:
    data = np.arange(6, dtype=np.int64).reshape(3, 2)
    out = as_matrix(data)
    assert out.dtype == np.float64
    assert out.shape == (3, 2)
    out[0, 0] = 99
    assert data[0, 0] == 0


def test_as_matrix_accepts_lists() -> None:
    assert as_matrix([[1, 2], [3, 4]]).shape == (2, 2)


@pytest.mark.parametrize("bad", [[1.0, 2.0], 3.0, np.zeros((2, 2, 2))])
def test_as_matrix_rejects_non_2d(bad: object) -> None:
    with pytest.raises(InvalidInputError) as info:
        as_matrix(bad, name="datos")
    assert info.value.code == "INVALID_INPUT"
    assert info.value.details["input"] == "datos"


def test_as_matrix_rejects_non_numeric() -> None:
    with pytest.raises(InvalidInputError, match="numérica"):
        as_matrix([["a", "b"]])
    with pytest.raises(InvalidInputError):
        as_matrix([[1.0, 2.0], [3.0]])


def test_domain_errors_carry_code_message_details() -> None:
    err = EstimationError("X_FAILED", "falló", {"k": 1})
    assert isinstance(err, DomainError)
    assert (err.code, err.message, err.details) == ("X_FAILED", "falló", {"k": 1})
    assert str(err) == "falló"
    assert DomainError("C", "m").details == {}


def test_pending_error_lists_fields() -> None:
    err = MethodDecisionPendingError("M_PENDING", "pendiente", ("a", "b"))
    assert err.details == {"pending": ["a", "b"]}


@pytest.mark.parametrize(
    "err",
    [
        InvalidInputError("mal", {"input": "x"}),
        EstimationError("E", "m", {"r_message": "boom"}),
        MethodDecisionPendingError("P", "m", ["a"]),
    ],
)
def test_domain_errors_are_picklable(err: DomainError) -> None:
    # __reduce__ propio: se serializa y se reconstruye sin depender de la firma de la subclase.
    assert pickle.dumps(err)
    back = copy.deepcopy(err)
    assert type(back) is type(err)
    assert (back.code, back.message, back.details) == (err.code, err.message, err.details)


def test_serial_mapper_keeps_order_and_passes_context() -> None:
    out = SerialTaskMapper().map(lambda ctx, t: ctx * t, 10, [3, 1, 2])
    assert out == [30, 10, 20]


@pytest.mark.parametrize("package", [charts, estimators])
def test_charts_and_estimators_packages_are_empty(package: object) -> None:
    # D-A: el __init__ solo tiene docstring; importar el paquete no carga ninguna carta/estimador.
    path = Path(str(getattr(package, "__file__", "")))
    body = ast.parse(path.read_text(encoding="utf-8")).body
    assert len(body) == 1
    assert isinstance(body[0], ast.Expr)
    assert isinstance(body[0].value, ast.Constant)
    assert isinstance(body[0].value.value, str)


def test_recalibration_vocabulary_is_stable() -> None:
    from voracious.domain.common import RecalibrationDecision, RecalibrationOutcome, RowDisposition

    assert [d.value for d in RecalibrationDecision] == [
        "initial",
        "extend",
        "replace",
        "insufficient",
    ]
    assert [d.value for d in RowDisposition] == [
        "kept",
        "excluded_assignable_cause",
        "already_in_base",
    ]
    out = RecalibrationOutcome(RecalibrationDecision.INSUFFICIENT, None, {"r": 1})
    assert out.model is None
    assert pickle.dumps(out)
    assert copy.deepcopy(out).report == {"r": 1}


def test_solo_test_doubles_never_live_in_src() -> None:
    # Los estimadores y muestreadores «SOLO TEST» solo existen en tests/support.
    src = Path(__file__).resolve().parents[4] / "src"
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("Classical", "NormalSampler", "solo_test", "SOLO_TEST"):
            assert name not in text, f"{name} en {path}"
