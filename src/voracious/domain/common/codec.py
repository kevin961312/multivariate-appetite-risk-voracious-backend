"""Codificación de arreglos y lectura estricta de datos codificados (mejora M1, sin estadística).

Los modelos, ajustes e informes de cada carta y estimador se persisten como **datos** (números,
textos, booleanos, ``None``, listas y diccionarios). Un arreglo se guarda como
``{"dtype": "<f8", "shape": [n, p], "b64": "..."}``: el ``dtype`` exacto (``numpy``
``dtype.str``), la forma y sus bytes en base64, de modo que la ida y vuelta conserva cada bit
(también ``-0.0``, ``nan`` e infinitos). Se admiten reales, enteros con y sin signo y booleanos.

Las funciones ``read_*`` validan lo leído: un diccionario con un campo desconocido o sin un campo
obligatorio es un error (``InvalidInputError``), nunca se ignora en silencio.
"""

import base64
import binascii
from collections.abc import Mapping
from typing import Final

import numpy as np
import numpy.typing as npt

from voracious.domain.common.errors import InvalidInputError

__all__ = [
    "decode_array",
    "decode_bool_array",
    "decode_float_array",
    "decode_int_array",
    "encode_array",
    "read_bool",
    "read_float",
    "read_int",
    "read_mapping",
    "read_optional_bool",
    "read_optional_float",
    "read_str",
]

_ARRAY_FIELDS: Final = frozenset({"dtype", "shape", "b64"})
_ARRAY_KINDS: Final = frozenset({"b", "i", "u", "f"})
"""Tipos de arreglo admitidos: booleanos, enteros con y sin signo y reales."""


def _error(field: str, message: str) -> InvalidInputError:
    """Error de decodificación de un campo.

    Args:
        field: Campo.
        message: Mensaje.

    Returns:
        El error (``details["reason"] == "invalid_encoding"``).
    """
    return InvalidInputError(
        f"'{field}': {message}", details={"field": field, "reason": "invalid_encoding"}
    )


def read_mapping(
    data: object, field: str, fields: frozenset[str], *, optional: frozenset[str] = frozenset()
) -> Mapping[str, object]:
    """Comprueba que ``data`` sea un diccionario con exactamente los campos esperados.

    Args:
        data: Valor leído.
        field: Nombre del campo, para los mensajes.
        fields: Campos admitidos.
        optional: Campos de ``fields`` que pueden faltar.

    Returns:
        El diccionario.

    Raises:
        InvalidInputError: Si no es un diccionario de claves de texto, tiene campos desconocidos
            (``details["reason"] == "unknown_fields"``) o le falta uno obligatorio
            (``"missing_fields"``).
    """
    if not isinstance(data, Mapping) or not all(isinstance(k, str) for k in data):
        raise _error(field, "debe ser un diccionario")
    unknown = sorted(str(k) for k in data if k not in fields)
    if unknown:
        raise InvalidInputError(
            f"'{field}' tiene campos desconocidos: {unknown}",
            details={"field": field, "reason": "unknown_fields", "unknown": unknown},
        )
    missing = sorted(fields - optional - set(data))
    if missing:
        raise InvalidInputError(
            f"a '{field}' le faltan campos: {missing}",
            details={"field": field, "reason": "missing_fields", "missing": missing},
        )
    return data


def read_int(value: object, field: str) -> int:
    """Entero estricto (sin ``bool`` ni ``float``).

    Args:
        value: Valor leído.
        field: Campo.

    Returns:
        El entero.

    Raises:
        InvalidInputError: Si no es entero.
    """
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise _error(field, "debe ser entero")
    return int(value)


def read_float(value: object, field: str) -> float:
    """Real (se admiten enteros, no ``bool``).

    Args:
        value: Valor leído.
        field: Campo.

    Returns:
        El valor como ``float``.

    Raises:
        InvalidInputError: Si no es numérico.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        raise _error(field, "debe ser numérico")
    return float(value)


def read_optional_float(value: object, field: str) -> float | None:
    """Como ``read_float``, pero ``None`` se conserva.

    Args:
        value: Valor leído.
        field: Campo.

    Returns:
        El valor o ``None``.
    """
    return None if value is None else read_float(value, field)


def read_bool(value: object, field: str) -> bool:
    """Booleano estricto.

    Args:
        value: Valor leído.
        field: Campo.

    Returns:
        El booleano.

    Raises:
        InvalidInputError: Si no es booleano.
    """
    if not isinstance(value, bool):
        raise _error(field, "debe ser booleano")
    return value


def read_optional_bool(value: object, field: str) -> bool | None:
    """Como ``read_bool``, pero ``None`` se conserva.

    Args:
        value: Valor leído.
        field: Campo.

    Returns:
        El booleano o ``None``.
    """
    return None if value is None else read_bool(value, field)


def read_str(value: object, field: str) -> str:
    """Texto estricto.

    Args:
        value: Valor leído.
        field: Campo.

    Returns:
        El texto.

    Raises:
        InvalidInputError: Si no es texto.
    """
    if not isinstance(value, str):
        raise _error(field, "debe ser texto")
    return value


def encode_array(array: npt.NDArray[np.generic]) -> dict[str, object]:
    """Codifica un arreglo con su ``dtype``, su forma y sus bytes exactos.

    Args:
        array: Arreglo real, entero o booleano.

    Returns:
        ``{"dtype": ..., "shape": [...], "b64": ...}``.

    Raises:
        InvalidInputError: Si el tipo del arreglo no se admite (p. ej. ``object``).
    """
    arr = np.asarray(array)
    if arr.dtype.kind not in _ARRAY_KINDS:
        raise _error("array", f"tipo de arreglo no admitido: {arr.dtype.str}")
    return {
        "dtype": arr.dtype.str,
        "shape": [int(d) for d in arr.shape],
        "b64": base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode("ascii"),
    }


def decode_array(data: object, field: str) -> npt.NDArray[np.generic]:
    """Decodifica un arreglo (inversa de ``encode_array``) en una copia propia y escribible.

    Args:
        data: Arreglo codificado.
        field: Campo, para los mensajes.

    Returns:
        El arreglo, idéntico en bits al codificado.

    Raises:
        InvalidInputError: Si los datos no son un arreglo codificado válido.
    """
    raw = read_mapping(data, field, _ARRAY_FIELDS)
    dtype_name, shape_raw, b64 = raw["dtype"], raw["shape"], raw["b64"]
    if not isinstance(dtype_name, str) or not isinstance(b64, str):
        raise _error(field, "'dtype' y 'b64' deben ser texto")
    try:
        dtype = np.dtype(dtype_name)
    except TypeError as exc:
        raise _error(field, f"dtype desconocido: {dtype_name!r}") from exc
    if dtype.kind not in _ARRAY_KINDS or dtype.str != dtype_name:
        raise _error(field, f"dtype no admitido: {dtype_name!r}")
    if not isinstance(shape_raw, list | tuple):
        raise _error(field, "'shape' debe ser una lista de enteros")
    shape = tuple(read_int(d, f"{field}.shape") for d in shape_raw)
    if any(d < 0 for d in shape):
        raise _error(field, "'shape' no admite dimensiones negativas")
    try:
        payload = base64.b64decode(b64, validate=True)
    except binascii.Error as exc:
        raise _error(field, "'b64' no es base64 válido") from exc
    if len(payload) != dtype.itemsize * int(np.prod(shape, dtype=np.int64)):
        raise _error(field, "el número de bytes no coincide con 'dtype' y 'shape'")
    return np.frombuffer(payload, dtype=dtype).reshape(shape).copy()


def _exact[T: np.generic](data: object, field: str, scalar: type[T]) -> npt.NDArray[T]:
    """Decodifica un arreglo y exige un ``dtype`` concreto (nativo).

    Args:
        data: Arreglo codificado.
        field: Campo, para los mensajes.
        scalar: Tipo escalar exigido (``np.float64``, ``np.int64`` o ``np.bool_``).

    Returns:
        El arreglo con ese tipo (sin conversión: el ``dtype`` ya coincide).

    Raises:
        InvalidInputError: Si no es un arreglo codificado válido o su ``dtype`` es otro.
    """
    arr = decode_array(data, field)
    if arr.dtype != np.dtype(scalar):
        raise _error(field, f"se esperaba dtype {np.dtype(scalar).str}, no {arr.dtype.str}")
    return arr.astype(scalar, copy=False)


def decode_float_array(data: object, field: str) -> npt.NDArray[np.float64]:
    """Decodifica un arreglo ``float64``.

    Args:
        data: Arreglo codificado.
        field: Campo, para los mensajes.

    Returns:
        El arreglo.
    """
    return _exact(data, field, np.float64)


def decode_int_array(data: object, field: str) -> npt.NDArray[np.int64]:
    """Decodifica un arreglo ``int64``.

    Args:
        data: Arreglo codificado.
        field: Campo, para los mensajes.

    Returns:
        El arreglo.
    """
    return _exact(data, field, np.int64)


def decode_bool_array(data: object, field: str) -> npt.NDArray[np.bool_]:
    """Decodifica un arreglo booleano.

    Args:
        data: Arreglo codificado.
        field: Campo, para los mensajes.

    Returns:
        El arreglo.
    """
    return _exact(data, field, np.bool_)
