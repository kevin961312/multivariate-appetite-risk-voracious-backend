"""Codificación de ``MRCDFit`` como datos: ida y vuelta exacta en bits."""

import json

import numpy as np
import pytest

from support.bits import canonical
from voracious.domain.common import InvalidInputError
from voracious.domain.estimators.mrcd import MRCDParams, decode_fit, encode_fit, fit_mrcd


@pytest.mark.parametrize(("n", "p"), [(40, 4), (12, 20)])
def test_fit_round_trip_is_exact_in_bits(n: int, p: int) -> None:
    x = np.random.default_rng(4).normal(size=(n, p))
    fit = fit_mrcd(x, MRCDParams(alpha=0.75))
    decoded = decode_fit(json.loads(json.dumps(encode_fit(fit))))
    assert canonical(decoded) == canonical(fit)
    assert np.array_equal(decoded.distances(x), fit.distances(x))
    assert decoded.distances(x).tobytes() == fit.mah.tobytes()


def test_unknown_or_missing_fields_are_errors() -> None:
    encoded = encode_fit(fit_mrcd(np.random.default_rng(1).normal(size=(20, 2)), MRCDParams()))
    with pytest.raises(InvalidInputError) as info:
        decode_fit({**encoded, "extra": 1})
    assert info.value.details["reason"] == "unknown_fields"
    del encoded["rho"]
    with pytest.raises(InvalidInputError) as info:
        decode_fit(encoded)
    assert info.value.details["reason"] == "missing_fields"
