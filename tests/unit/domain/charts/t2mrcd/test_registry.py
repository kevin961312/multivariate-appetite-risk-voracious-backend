"""M1: estrategias de T²MRCD por nombre y parámetros persistidos como datos."""

import json
from dataclasses import replace

import pytest

from support.change_tests import permutation_covariance_test, permutation_mean_test
from support.solo_test import SOLO_TEST_STRATEGIES, fast_params, solo_test_recalibration
from voracious.domain.charts.t2mrcd import (
    BEST_SUBSET_CRITERION_NAME,
    DEFAULT_STRATEGIES,
    T2MRCDBootstrap,
    T2MRCDChart,
    T2MRCDParams,
    T2MRCDRecalibrationParams,
    best_subset_criterion,
    decode_params,
    decode_recalibration_params,
    encode_params,
    encode_recalibration_params,
    pooled_quantile,
)
from voracious.domain.common import InvalidInputError
from voracious.domain.estimators.mrcd import MRCDParams


def test_params_round_trip_by_name_is_plain_data() -> None:
    params = T2MRCDParams(
        bootstrap=T2MRCDBootstrap(n_replicates=7, seed=3, alpha_limit=0.01, aggregation=None),
        mrcd=MRCDParams(alpha=0.8, h=30, rho=0.1, target="equicorrelation", maxcond=40.0),
        max_depuration_rounds=2,
    )
    data = encode_params(params)
    assert json.loads(json.dumps(data)) == data  # solo datos, sin invocables
    boot = data["bootstrap"]
    assert isinstance(boot, dict)
    assert boot["clean_criterion"] == BEST_SUBSET_CRITERION_NAME
    assert boot["aggregation"] is None
    assert boot["phase2_aggregation"] == "pooled_quantile"
    decoded = decode_params(data)
    assert decoded == params
    assert decoded.bootstrap.clean_criterion is best_subset_criterion
    assert decoded.bootstrap.phase2_aggregation is pooled_quantile


def test_recalibration_params_round_trip_with_solo_test_registry() -> None:
    params = solo_test_recalibration(seed=5, threshold_decides=True, min_observations=9)
    data = encode_recalibration_params(params, SOLO_TEST_STRATEGIES)
    assert json.loads(json.dumps(data)) == data
    assert data["covariance_test"] == permutation_covariance_test.name
    assert data["mean_test"] == permutation_mean_test.name
    assert decode_recalibration_params(data, SOLO_TEST_STRATEGIES) == params
    defaults = T2MRCDRecalibrationParams(seed=1)
    assert decode_recalibration_params(encode_recalibration_params(defaults)) == defaults


def test_missing_fields_take_dataclass_defaults() -> None:
    assert decode_params({"bootstrap": {"seed": 4}}) == T2MRCDParams(
        bootstrap=T2MRCDBootstrap(seed=4)
    )
    partial = decode_params({"bootstrap": {"seed": 4}, "mrcd": {"maxcsteps": 50}})
    assert partial.mrcd == MRCDParams(alpha=0.75, maxcsteps=50)
    assert decode_recalibration_params({"seed": 2}) == T2MRCDRecalibrationParams(seed=2)


def test_unknown_strategy_name_is_a_clear_error() -> None:
    with pytest.raises(InvalidInputError) as info:
        decode_params({"bootstrap": {"seed": 1, "aggregation": "mean_of_quantiles"}})
    assert info.value.code == "INVALID_INPUT"
    assert info.value.details == {
        "field": "bootstrap.aggregation",
        "reason": "unknown_strategy",
        "name": "mean_of_quantiles",
        "known": ["pooled_quantile"],
    }
    # Las pruebas SOLO TEST no existen en el registro de producción.
    data = encode_recalibration_params(solo_test_recalibration(), SOLO_TEST_STRATEGIES)
    with pytest.raises(InvalidInputError) as info:
        decode_recalibration_params(data)
    assert info.value.details["reason"] == "unknown_strategy"
    assert info.value.details["known"] == []


def test_unregistered_strategy_cannot_be_persisted() -> None:
    with pytest.raises(InvalidInputError) as info:
        encode_recalibration_params(solo_test_recalibration())
    assert info.value.details["reason"] == "unregistered_strategy"
    assert info.value.details["field"] == "recalibration.covariance_test"


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({}, "bootstrap"),
        ({"bootstrap": {}}, "bootstrap.seed"),
        ({"bootstrap": {"seed": 1.0}}, "bootstrap.seed"),
        ({"bootstrap": {"seed": True}}, "bootstrap.seed"),
        ({"bootstrap": {"seed": 1, "alpha_limit": "x"}}, "bootstrap.alpha_limit"),
        ({"bootstrap": {"seed": 1, "extra": 1}}, "bootstrap"),
        ({"bootstrap": {"seed": 1}, "mrcd": {"target": "other"}}, "mrcd.target"),
        ({"bootstrap": {"seed": 1}, "mrcd": []}, "mrcd"),
        ({"bootstrap": {"seed": 1}, "max_depuration_rounds": 1.5}, "max_depuration_rounds"),
        ({"bootstrap": {"seed": 1, "clean_criterion": 3}}, "bootstrap.clean_criterion"),
    ],
)
def test_invalid_params_data(data: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidInputError) as info:
        decode_params(data)
    assert info.value.details["field"] == field


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({}, "recalibration.seed"),
        ({"seed": 1, "threshold_decides": 1}, "recalibration.threshold_decides"),
        ({"seed": 1, "n_test_resamples": "a"}, "recalibration.n_test_resamples"),
        ({"seed": 1, "unknown": 1}, "recalibration"),
    ],
)
def test_invalid_recalibration_data(data: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidInputError) as info:
        decode_recalibration_params(data)
    assert info.value.details["field"] == field


def test_chart_codec_uses_its_registry() -> None:
    chart = T2MRCDChart(strategies=SOLO_TEST_STRATEGIES)
    params = fast_params()
    assert chart.decode_params(chart.encode_params(params)) == params
    recal = solo_test_recalibration()
    assert chart.decode_recalibration_params(chart.encode_recalibration_params(recal)) == recal
    assert T2MRCDChart() == T2MRCDChart(strategies=replace(DEFAULT_STRATEGIES))
