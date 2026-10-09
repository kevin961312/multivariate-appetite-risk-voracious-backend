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
import math
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

FIXTURES = Path(__file__).parent / "golden" / "fixtures"
PRIMITIVAS = FIXTURES / "primitivas"

REFERENCE_PLATFORM = platform.system() == "Darwin" and platform.machine() == "arm64"
"""Plataforma del oráculo (aarch64-apple-darwin20, Accelerate, ``long double == double``)."""

EPS = float(np.finfo(np.float64).eps)

# Tolerancias fuera de la plataforma de referencia (especificación §11; manifest de primitivas).
TOL_OFF_PLATFORM: dict[str, tuple[float, float]] = {
    "E": (0.0, 0.0),  # exacto en cualquier plataforma
    "L": (1e-15, 0.0),  # libm: rtol 1e-15
    "scfac": (1e-14, 0.0),  # .MCDcons (nmath portado; fuera de la referencia, §11)
    "B": (1e-12, 1e-14),  # BLAS/LAPACK: rtol 1e-12, atol 1e-14·max|ref|
}


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


class Inter:
    """Intermedios de ``.detmrcd`` de un caso golden, con *skip* explícito si falta alguno.

    Los intermedios pesados de los casos grandes no se versionan (``golden/fixtures/README.md``):
    si faltan, el test se salta con el motivo «intermedio no versionado; regenerar con tools/r/».
    """

    def __init__(self, case: str) -> None:
        self.case = case
        self.root = FIXTURES / case
        self.folder = self.root / "intermedios"
        self.index: dict[str, Any] = json.loads(
            (self.folder / "indice.json").read_text(encoding="utf-8")
        )
        self.manifest: dict[str, Any] = json.loads((self.root / "manifest.json").read_text("utf-8"))

    def has(self, name: str) -> bool:
        """``True`` si el intermedio está exportado y presente en disco."""
        meta = self.index.get(name)
        return meta is not None and (self.folder / str(meta["archivo"])).exists()

    def get(self, name: str) -> FloatArray:
        """Lee un intermedio con su forma declarada (o salta el test con el motivo)."""
        meta = self.index.get(name)
        if meta is None:
            pytest.skip(f"{self.case}: intermedio {name} no exportado para este caso")
        path: Path = self.folder / str(meta["archivo"])
        if not path.exists():
            pytest.skip(f"{self.case}: intermedio {name} no versionado; regenerar con tools/r/")
        return read_csv_gz(path).reshape(tuple(int(v) for v in meta["forma"]))

    def scalar(self, name: str) -> float:
        """Intermedio escalar."""
        return float(self.get(name).item())

    def ints(self, name: str) -> IntArray:
        """Intermedio entero como vector ``int64`` (base de R)."""
        return np.asarray(self.get(name).ravel(), dtype=np.int64)

    def output(self, name: str) -> FloatArray:
        """Salida final del caso (``<caso>/<name>.csv.gz``)."""
        return read_csv_gz(self.root / f"{name}.csv.gz")

    def input_x(self) -> FloatArray:
        """Datos de entrada ``x`` (ruta del manifiesto)."""
        return read_csv_gz(self.root / str(self.manifest["entrada"]["archivo"]))

    @property
    def equicorrelation(self) -> bool:
        """``True`` si el caso usa ``target = "equicorrelation"``."""
        return str(self.manifest.get("variante_target")) == "equicorrelation"

    @property
    def target(self) -> str:
        """``target`` del caso."""
        return "equicorrelation" if self.equicorrelation else "identity"

    def r6_input(self) -> FloatArray:
        """Entrada de ``r6pack`` (``mW`` con equicorrelación, ``mU`` con identidad)."""
        return self.get("eq_mW") if self.equicorrelation else self.get("std_mU")

    def mx(self) -> FloatArray:
        """``mX`` (``p x n``) estandarizada y rotada (``detmrcd.R:422``, ``:433``)."""
        return np.array(self.r6_input().T, dtype=np.float64)


INTER_CASES = sorted(
    p.parent.parent.name for p in FIXTURES.glob("*/intermedios/indice.json") if p.is_file()
)
"""Casos golden con intermedios exportados."""


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


class DivergenciaR1(UserWarning):
    """Divergencia documentada de un subconjunto R1 (especificación §6), con su medida.

    Nivel iii (desde cero): subconjunto R1 del régimen distinto de R. Nivel i (tests por etapa de
    ``initset`` fuera de la referencia, enmienda D1 del 2026-10-09): segundo canal de R1.
    """


def required_sets(n: int, p: int) -> frozenset[int]:
    """Subconjuntos iniciales (base 1) exigidos iguales a R desde cero (§6 punto 3b).

    Args:
        n: Observaciones.
        p: Variables.

    Returns:
        Conjunto de índices exigidos.
    """
    if p >= n:
        return frozenset({6})
    if p >= math.ceil(n / 2):
        return frozenset({1, 2, 3, 4, 6})
    return frozenset({1, 2, 3, 4, 5, 6})


def null_space_evidence(lam: FloatArray, p: int) -> bool:
    """Prueba estructural de espacio nulo de §6 («Segundo canal de R1»), condición 2 de D1.

    ``min(lambda) / max(lambda) <= 10·p·eps`` sobre el ``lambda`` de R (``is.k.lambda``). Con
    ``max(lambda) <= 0`` (sin escala) no hay prueba y devuelve ``False`` (se exige todo).

    Args:
        lam: ``lambda`` de R del conjunto ``k`` (``detmrcd.R:70``).
        p: Variables.

    Returns:
        ``True`` si hay prueba numérica del espacio nulo.
    """
    lam_max = float(np.max(lam))
    if not lam_max > 0:
        return False
    return float(np.min(lam)) / lam_max <= 10 * p * EPS


def r1_second_channel(
    k: int, n: int, p: int, lam: FloatArray, *, reference: bool = REFERENCE_PLATFORM
) -> bool:
    """Regla D1 (enmienda 2026-10-09, §6 «Segundo canal de R1» y §11.1).

    Las etapas de ``initset`` posteriores a ``is_lambda`` (``is_colmed``, ``is_estloc``,
    ``is_centeredx``, ``is_dist``) y el orden ``is_ord`` se registran como ``DivergenciaR1`` en
    lugar de fallar si y solo si: fuera de la plataforma de referencia, ``k`` no es exigido
    (``required_sets(n, p)``) **y** hay prueba de espacio nulo (``null_space_evidence``).

    Args:
        k: Conjunto inicial (base 1).
        n: Observaciones.
        p: Variables.
        lam: ``lambda`` de R del conjunto ``k``.
        reference: ``True`` en la plataforma de referencia (allí nunca aplica).

    Returns:
        ``True`` si rige el registro en lugar del fallo.
    """
    if reference:
        return False
    return k not in required_sets(n, p) and null_space_evidence(lam, p)
