"""Cargador de fixtures de R y comparación con las tolerancias declaradas.

Contrato de los fixtures (``tests/golden/fixtures/README.md``): ``.csv.gz`` sin cabecera, ``%.17g``,
índices en base 1; cada familia de primitivas tiene ``indice.json`` con ``casos`` (``id``,
``entradas``/``salidas`` con ``archivo`` y ``forma``). Los valores se leen con ``float()`` de Python
(conversión correctamente redondeada; ``as.numeric`` de R no lo es en arm64).

Tolerancias (especificación ``docs/metodos/mrcd-especificacion.md`` §11 y decisión P6 del
    dueño): en la
plataforma de referencia (macOS arm64) se exige igualdad **bit a bit**; fuera de ella, las
tolerancias
numéricas declaradas por clase. Se fijan aquí, antes de comparar, y nunca se relajan a posteriori.
"""

from __future__ import annotations

import gzip
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

FloatArray = npt.NDArray[np.float64]

FIXTURES = Path(__file__).parent / "golden" / "fixtures"
PRIMITIVAS = FIXTURES / "primitivas"

REFERENCE_PLATFORM = platform.system() == "Darwin" and platform.machine() == "arm64"
"""Plataforma del oráculo (aarch64-apple-darwin20, Accelerate, ``long double == double``)."""

EPS = float(np.finfo(np.float64).eps)

# Tolerancias fuera de la plataforma de referencia (especificación §11; manifest de primitivas).
TOL_OFF_PLATFORM: dict[str, tuple[float, float]] = {
    "E": (0.0, 0.0),  # exacto en cualquier plataforma
    "L": (1e-15, 0.0),  # libm: rtol 1e-15
    "scfac": (1e-14, 0.0),  # .MCDcons vía scipy
    "B": (1e-12, 1e-14),  # BLAS/LAPACK: rtol 1e-12, atol 1e-14·max|ref|
}

TOL_SCFAC_ALWAYS = 1e-14
"""``.MCDcons`` vía scipy (decisión P3): rtol 1e-14 también en la plataforma de referencia (§3.6,
S5)."""


def read_csv_gz(path: Path) -> FloatArray:
    """Lee un ``.csv.gz`` de R con ``float()`` exacto.

    Args:
        path: Ruta del archivo.

    Returns:
        Matriz ``float64`` (filas del CSV).
    """
    with gzip.open(path, "rt", encoding="ascii") as fh:
        rows = [[float(tok) for tok in line.split(",")] for line in fh.read().splitlines() if line]
    return np.array(rows, dtype=np.float64)


@dataclass(frozen=True)
class Case:
    """Caso de un ``indice.json``.

    Attributes:
        func: Familia (carpeta).
        id: Identificador del caso.
        description: Descripción.
        inputs: Entradas por nombre, con la ``forma`` declarada.
        outputs: Salidas por nombre, con la ``forma`` declarada.
        extra: Metadatos adicionales (``extra``/``parametros``).
    """

    func: str
    id: str
    description: str
    inputs: dict[str, FloatArray]
    outputs: dict[str, FloatArray]
    extra: dict[str, Any]


def _load_entry(folder: Path, meta: dict[str, Any]) -> FloatArray:
    arr = read_csv_gz(folder / str(meta["archivo"]))
    shape = tuple(int(v) for v in meta["forma"])
    return arr.reshape(shape)


def primitive_cases(func: str) -> list[Case]:
    """Carga todos los casos de una familia de primitivas.

    Args:
        func: Nombre de la carpeta bajo ``primitivas/``.

    Returns:
        Lista de casos (vacía si la familia no existe).
    """
    folder = PRIMITIVAS / func
    index = folder / "indice.json"
    if not index.exists():
        return []
    data = json.loads(index.read_text(encoding="utf-8"))
    cases = []
    for c in data["casos"]:
        cases.append(
            Case(
                func=func,
                id=str(c["id"]),
                description=str(c.get("descripcion", "")),
                inputs={k: _load_entry(folder, v) for k, v in c["entradas"].items()},
                outputs={k: _load_entry(folder, v) for k, v in c["salidas"].items()},
                extra=dict(c.get("extra") or c.get("parametros") or {}),
            )
        )
    return cases


def case_params(func: str) -> list[Any]:
    """Parámetros de ``pytest.mark.parametrize`` para una familia, o un *skip* explícito.

    Args:
        func: Familia de primitivas.

    Returns:
        Lista de ``pytest.param`` con ``id`` del caso.
    """
    cases = primitive_cases(func)
    if not cases:
        return [
            pytest.param(
                None,
                marks=pytest.mark.skip(
                    reason=f"fixture primitivas/{func} no disponible; regenerar con tools/r/"
                ),
                id=f"{func}-sin-fixture",
            )
        ]
    return [pytest.param(c, id=f"{func}-{c.id}") for c in cases]


def assert_r_equal(actual: object, expected: object, klass: str, what: str = "") -> None:
    """Compara con la regla de fidelidad: bit a bit en la referencia, tolerancia declarada fuera.

    En la plataforma de referencia exige igualdad exacta de valores, de ``NaN`` y del signo de los
    ceros. Fuera de ella aplica ``TOL_OFF_PLATFORM[klass]`` (``atol`` relativo a ``max|ref|``).

    Args:
        actual: Valor del port.
        expected: Valor de R.
        klass: Clase de tolerancia (``E``, ``L``, ``scfac``, ``B``).
        what: Etiqueta para el mensaje.
    """
    a = np.asarray(actual, dtype=np.float64)
    e = np.asarray(expected, dtype=np.float64)
    assert a.shape == e.shape, f"{what}: forma {a.shape} != {e.shape}"
    nan_a = np.isnan(a)
    nan_e = np.isnan(e)
    assert np.array_equal(nan_a, nan_e), f"{what}: NaN en posiciones distintas"
    if REFERENCE_PLATFORM:
        ok = (a == e) | nan_a
        ok &= (np.signbit(a) == np.signbit(e)) | nan_a
        with np.errstate(invalid="ignore"):
            diff = np.where(ok, 0.0, np.abs(a - e))
        assert ok.all(), (
            f"{what}: no es bit a bit ({int((~ok).sum())} elementos, max|Δ|={np.nanmax(diff):.3g})"
        )
        return
    rtol, atol_rel = TOL_OFF_PLATFORM[klass]
    finite = np.isfinite(e)
    scale = float(np.max(np.abs(e[finite]))) if finite.any() else 0.0
    np.testing.assert_allclose(a, e, rtol=rtol, atol=atol_rel * scale, equal_nan=True, err_msg=what)
