"""Codificación de arreglos como datos y lectura estricta (``domain/common/codec.py``)."""

import json

import numpy as np
import pytest

from support.bits import canonical
from voracious.domain.common import InvalidInputError
from voracious.domain.common.codec import (
    decode_array,
    decode_bool_array,
    decode_float_array,
    decode_int_array,
    encode_array,
    read_bool,
    read_float,
    read_int,
    read_mapping,
    read_optional_bool,
    read_optional_float,
    read_str,
)


@pytest.mark.parametrize(
    "array",
    [
        np.array([[0.1, -0.0], [np.nan, np.inf], [-np.inf, 5e-324]]),
        np.arange(6, dtype=np.int64).reshape(3, 2),
        np.array([True, False, True]),
        np.array([1, 2], dtype=np.uint8),
        np.array([1.5], dtype=np.float32),
        np.zeros((0, 3)),
        np.asfortranarray(np.arange(6.0).reshape(2, 3)),
    ],
)
def test_round_trip_is_exact_in_bits_and_json_serializable(array: np.ndarray) -> None:
    encoded = json.loads(json.dumps(encode_array(array)))
    decoded = decode_array(encoded, "a")
    assert canonical(decoded) == canonical(np.ascontiguousarray(array))
    assert decoded.flags.writeable
    assert encoded["dtype"] == array.dtype.str


def test_typed_decoders_require_their_dtype() -> None:
    assert decode_float_array(encode_array(np.zeros(2)), "f").dtype == np.float64
    assert decode_int_array(encode_array(np.zeros(2, dtype=np.int64)), "i").dtype == np.int64
    assert decode_bool_array(encode_array(np.zeros(2, dtype=np.bool_)), "b").dtype == np.bool_
    with pytest.raises(InvalidInputError, match="se esperaba dtype"):
        decode_float_array(encode_array(np.zeros(2, dtype=np.int64)), "f")


def test_object_arrays_are_rejected() -> None:
    with pytest.raises(InvalidInputError, match="no admitido"):
        encode_array(np.array([object()]))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"dtype": "<f8", "shape": [1]}, "le faltan campos"),
        ({"dtype": "<f8", "shape": [1], "b64": "", "extra": 1}, "desconocidos"),
        ({"dtype": "nope", "shape": [1], "b64": ""}, "dtype desconocido"),
        ({"dtype": "|O", "shape": [1], "b64": ""}, "no admitido"),
        ({"dtype": "<f8", "shape": 1, "b64": ""}, "lista de enteros"),
        ({"dtype": "<f8", "shape": [-1], "b64": ""}, "negativas"),
        ({"dtype": "<f8", "shape": [1], "b64": "***"}, "base64"),
        ({"dtype": "<f8", "shape": [2], "b64": "AAAAAAAAAAA="}, "número de bytes"),
        ({"dtype": 8, "shape": [1], "b64": ""}, "texto"),
        ([1, 2], "diccionario"),
    ],
)
def test_invalid_encodings_are_errors(data: object, message: str) -> None:
    with pytest.raises(InvalidInputError, match=message):
        decode_array(data, "a")


def test_readers_are_strict() -> None:
    assert read_int(np.int64(3), "f") == 3
    assert read_float(2, "f") == 2.0
    assert read_optional_float(None, "f") is None
    assert read_optional_bool(None, "f") is None
    assert read_bool(True, "f") is True
    assert read_str("x", "f") == "x"
    for reader, value in [
        (read_int, True),
        (read_int, 1.0),
        (read_float, False),
        (read_float, "1"),
        (read_bool, 1),
        (read_str, 1),
    ]:
        with pytest.raises(InvalidInputError):
            reader(value, "f")
    assert read_mapping({"a": 1}, "m", frozenset({"a", "b"}), optional=frozenset({"b"})) == {"a": 1}
