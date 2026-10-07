"""Lectura de los fixtures golden de pymrcd (``packages/pymrcd/tests/golden/fixtures``)."""

import gzip
from pathlib import Path

import numpy as np
import numpy.typing as npt

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "packages" / "pymrcd" / "tests" / "golden" / "fixtures"


def read_case_x(case: str) -> npt.NDArray[np.float64]:
    """Lee la entrada ``x`` de un caso golden con ``float()`` exacto (``%.17g`` de R).

    Args:
        case: Caso (p. ej. ``"C7"``).

    Returns:
        Matriz ``n x p``.
    """
    with gzip.open(FIXTURES / case / "x.csv.gz", "rt", encoding="ascii") as fh:
        rows = [[float(tok) for tok in line.split(",")] for line in fh.read().splitlines() if line]
    return np.array(rows, dtype=np.float64)
