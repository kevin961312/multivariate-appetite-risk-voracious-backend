"""Codec del modelo y del informe de T²MRCD (M1): ida y vuelta exacta en bits."""

import json

import numpy as np
import pytest

from support.bits import canonical
from support.composition_cases import active_case, recalibration_cases
from voracious.domain.charts.t2mrcd import (
    MODEL_FORMAT_VERSION,
    REPORT_FORMAT_VERSION,
    T2MRCDChart,
    T2MRCDModel,
    T2MRCDRecalibrationReport,
)
from voracious.domain.common import InvalidInputError, RecalibrationOutcome, SerialTaskMapper

CHART = T2MRCDChart()
MAPPER = SerialTaskMapper()


def _json(data: dict[str, object]) -> dict[str, object]:
    """Ida y vuelta por JSON: lo codificado son solo datos."""
    out: dict[str, object] = json.loads(json.dumps(data, allow_nan=False))
    return out


@pytest.fixture(scope="module")
def outcomes() -> tuple[T2MRCDModel, np.ndarray, dict[str, RecalibrationOutcome]]:
    case = active_case()
    model = CHART.fit_phase1(case.x, case.params, mapper=MAPPER)
    base = case.x[model.base_mask]
    out = {
        name: CHART.recalibrate(
            model,
            base,
            c.x_new,
            assignable_cause=c.assignable_cause,
            force_replace=c.force_replace,
            params=c.params,
            mapper=MAPPER,
        )
        for name, c in recalibration_cases().items()
    }
    return model, base, out


def _models(
    outcomes: tuple[T2MRCDModel, np.ndarray, dict[str, RecalibrationOutcome]],
) -> dict[str, T2MRCDModel]:
    v0, _, recal = outcomes
    models = {"v0": v0}
    for name in ("extend", "replace"):
        model = recal[name].model
        assert model is not None
        models[name] = model
    return models


@pytest.mark.parametrize("name", ["v0", "extend", "replace"])
def test_model_round_trip_is_exact_in_bits(
    name: str, outcomes: tuple[T2MRCDModel, np.ndarray, dict[str, RecalibrationOutcome]]
) -> None:
    model = _models(outcomes)[name]
    decoded = CHART.decode_model(_json(CHART.encode_model(model)))
    assert canonical(decoded) == canonical(model)
    assert decoded.params == model.params
    assert decoded.operative_limit == model.operative_limit


@pytest.mark.parametrize("name", ["v0", "extend"])
def test_phase2_with_the_decoded_model_is_identical(
    name: str, outcomes: tuple[T2MRCDModel, np.ndarray, dict[str, RecalibrationOutcome]]
) -> None:
    model = _models(outcomes)[name]
    decoded = CHART.decode_model(_json(CHART.encode_model(model)))
    x_new = np.random.default_rng(9).normal(size=(30, 3))
    x_new[3] += 8.0
    assert canonical(CHART.score_phase2(decoded, x_new)) == canonical(
        CHART.score_phase2(model, x_new)
    )


@pytest.mark.parametrize("name", ["extend", "replace", "insufficient", "forced"])
def test_report_round_trip_is_exact(
    name: str, outcomes: tuple[T2MRCDModel, np.ndarray, dict[str, RecalibrationOutcome]]
) -> None:
    report = outcomes[2][name].report
    decoded = CHART.decode_report(_json(CHART.encode_report(report)))
    assert isinstance(decoded, T2MRCDRecalibrationReport)
    assert canonical(decoded) == canonical(report)


def test_unknown_missing_and_versioned_fields_are_errors(
    outcomes: tuple[T2MRCDModel, np.ndarray, dict[str, RecalibrationOutcome]],
) -> None:
    encoded = CHART.encode_model(outcomes[0])
    with pytest.raises(InvalidInputError) as info:
        CHART.decode_model({**encoded, "unexpected": 1})
    assert info.value.details["reason"] == "unknown_fields"
    limits = dict(encoded["limits"])
    limits["extra"] = 0
    with pytest.raises(InvalidInputError) as info:
        CHART.decode_model({**encoded, "limits": limits})
    assert info.value.details["field"] == "model.limits"
    with pytest.raises(InvalidInputError) as info:
        CHART.decode_model({**encoded, "format_version": MODEL_FORMAT_VERSION + 1})
    assert info.value.details["reason"] == "unknown_format_version"
    missing = dict(encoded)
    del missing["historical_t2"]
    with pytest.raises(InvalidInputError) as info:
        CHART.decode_model(missing)
    assert info.value.details["reason"] == "missing_fields"
    with pytest.raises(InvalidInputError, match="LimitRegime"):
        CHART.decode_model({**encoded, "limit_regime": "nope"})
    with pytest.raises(InvalidInputError, match="lista"):
        CHART.decode_model({**encoded, "row_disposition": "kept"})
    with pytest.raises(InvalidInputError, match="diccionario"):
        CHART.decode_model({**encoded, "params": []})
    report = CHART.encode_report(outcomes[2]["extend"].report)
    with pytest.raises(InvalidInputError) as info:
        CHART.decode_report({**report, "extra": None})
    assert info.value.details["reason"] == "unknown_fields"


def test_format_1_with_depuration_fields_is_rejected_by_its_version(
    outcomes: tuple[T2MRCDModel, np.ndarray, dict[str, RecalibrationOutcome]],
) -> None:
    """Registros anteriores a quitar la depuración automática (dueño, 2026-10-09)."""
    assert MODEL_FORMAT_VERSION == REPORT_FORMAT_VERSION == 2
    legacy_model = {
        **CHART.encode_model(outcomes[0]),
        "format_version": 1,
        "depuration_rounds": 0,
        "depuration_converged": True,
        "final_depuration_skipped": False,
    }
    with pytest.raises(InvalidInputError) as info:
        CHART.decode_model(legacy_model)
    assert info.value.details["reason"] == "unknown_format_version"
    legacy_report = {
        **CHART.encode_report(outcomes[2]["extend"].report),
        "format_version": 1,
        "n_excluded_automatic": 0,
        "depuration_rounds": 0,
        "depuration_converged": True,
    }
    with pytest.raises(InvalidInputError) as info:
        CHART.decode_report(legacy_report)
    assert info.value.details["reason"] == "unknown_format_version"


def test_encode_report_checks_its_type() -> None:
    with pytest.raises(TypeError, match="T2MRCDRecalibrationReport"):
        CHART.encode_report(object())
