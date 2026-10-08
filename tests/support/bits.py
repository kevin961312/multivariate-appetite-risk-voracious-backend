"""Forma canónica «en bits» de modelos, informes y ajustes para compararlos sin tolerancia.

``canonical`` recorre dataclasses, tuplas, listas, diccionarios, enumeraciones y arreglos y los
convierte en estructuras de Python comparables con ``==``: cada arreglo pasa a
``(dtype, shape, bytes)`` y cada ``float`` a su representación hexadecimal (``-0.0`` y ``nan``
incluidos), así que dos valores canónicos son iguales solo si coinciden bit a bit. Las estrategias
(objetos invocables de los parámetros) se representan por su tipo y su ``name`` si lo tienen.
"""

import dataclasses
from collections.abc import Mapping
from datetime import datetime
from enum import Enum

import numpy as np


def canonical(value: object) -> object:
    """Forma canónica comparable bit a bit de ``value``."""
    if isinstance(value, np.ndarray):
        return ("ndarray", value.dtype.str, value.shape, value.tobytes())
    if isinstance(value, datetime):
        return ("datetime", value.isoformat(), value.utcoffset())
    if isinstance(value, Enum):
        return (type(value).__name__, value.value)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, None | str | int):
        return value
    if isinstance(value, float | np.floating):
        return ("float", float(value).hex())
    if isinstance(value, np.integer | np.bool_):
        return ("npscalar", type(value).__name__, value.item())
    if isinstance(value, np.random.SeedSequence):
        return ("seedseq", value.entropy, value.spawn_key)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {f.name: canonical(getattr(value, f.name)) for f in dataclasses.fields(value)}
        return (type(value).__name__, tuple(sorted(fields.items())))
    if isinstance(value, Mapping):
        return ("mapping", tuple(sorted((str(k), canonical(v)) for k, v in value.items())))
    if isinstance(value, tuple | list):
        return (type(value).__name__, tuple(canonical(v) for v in value))
    if callable(value):
        return ("callable", type(value).__name__, getattr(value, "name", None))
    msg = f"tipo sin forma canónica: {type(value).__name__}"
    raise TypeError(msg)
