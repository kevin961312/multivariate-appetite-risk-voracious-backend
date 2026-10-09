"""Codecs reales de los registros con modelo o informe (M1, vuelta 3.2).

Los repositorios en memoria guardan ``ModelRecord``, ``ModelVersion`` y ``RecalibrationRecord``
codificados como datos (lo que guardaría Postgres); la ida y vuelta es exacta en bits.
"""

import dataclasses
import json
from datetime import UTC, datetime

import numpy as np
import pytest

from support.bits import canonical
from support.composition_cases import active_case, recalibration_cases
from voracious.application.errors import UnknownChartError
from voracious.application.records import (
    BaseRowRef,
    BaseRowSource,
    ErrorInfo,
    Exclusion,
    ExclusionReason,
    JobStatus,
    LifecyclePolicy,
    ModelRecord,
    ModelVersion,
    RecalibrationRecord,
    VersionStatus,
)
from voracious.domain.charts.t2mrcd import T2MRCDChart, T2MRCDModel, T2MRCDRecalibrationReport
from voracious.domain.common import InvalidInputError, RecalibrationDecision, SerialTaskMapper
from voracious.infrastructure.memory import (
    InMemoryModelRepository,
    InMemoryModelVersionRepository,
    InMemoryRecalibrationRepository,
    KeyedStore,
    ModelRecordCodec,
    ModelVersionCodec,
    RecalibrationRecordCodec,
)

CHARTS = {"t2mrcd": T2MRCDChart()}
T0 = datetime(2026, 3, 1, 12, 30, 15, 123456, tzinfo=UTC)


@pytest.fixture(scope="module")
def fitted() -> tuple[np.ndarray, T2MRCDModel, T2MRCDModel, T2MRCDRecalibrationReport]:
    case = active_case()
    chart = CHARTS["t2mrcd"]
    v0 = chart.fit_phase1(case.x, case.params, mapper=SerialTaskMapper())
    recal = recalibration_cases()["extend"]
    outcome = chart.recalibrate(
        v0,
        case.x[v0.base_mask],
        recal.x_new,
        assignable_cause=recal.assignable_cause,
        force_replace=False,
        params=recal.params,
        mapper=SerialTaskMapper(),
    )
    assert outcome.model is not None
    return case.x, v0, outcome.model, outcome.report


def _stored_is_data(stored: object) -> None:
    json.dumps(stored, allow_nan=False)


def test_model_record_round_trip(fitted: tuple) -> None:
    x, v0, _, _ = fitted
    codec = ModelRecordCodec(CHARTS)
    record = ModelRecord(
        "t",
        "t2mrcd",
        "m",
        JobStatus.SUCCEEDED,
        {"bootstrap": {"seed": 7, "n_replicates": 5}},
        x,
        T0,
        started_at=T0,
        finished_at=T0,
        model=v0,
        lifecycle_policy=LifecyclePolicy(None, 5),
    )
    stored = codec.encode(record)
    _stored_is_data(stored)
    assert canonical(codec.decode(json.loads(json.dumps(stored)))) == canonical(record)
    failed = dataclasses.replace(
        record, status=JobStatus.FAILED, model=None, error=ErrorInfo("X", "y", {"a": [1]})
    )
    assert canonical(codec.decode(codec.encode(failed))) == canonical(failed)


def test_model_version_round_trip(fitted: tuple) -> None:
    _, _, v1, report = fitted
    codec = ModelVersionCodec(CHARTS)
    version = ModelVersion(
        "t",
        "t2mrcd",
        "m",
        1,
        VersionStatus.ACTIVE,
        v1,
        np.zeros((v1.n_base, 3)),
        "sha256:abc",
        (BaseRowRef(BaseRowSource.TRAINING, "0"), BaseRowRef(BaseRowSource.OBSERVATION, "o1")),
        (
            Exclusion(BaseRowRef(BaseRowSource.OBSERVATION, "o2"), ExclusionReason.ALREADY_IN_BASE),
            Exclusion(
                BaseRowRef(BaseRowSource.OBSERVATION, "o3"),
                ExclusionReason.ASSIGNABLE_CAUSE,
                annotation_id="a1",
            ),
        ),
        RecalibrationDecision.EXTEND,
        "no_change_detected",
        T0,
        report=report,
        recalibration_id="r",
        previous_number=0,
        effective_from=T0,
        approved_at=T0,
        decided_by="ana",
    )
    stored = codec.encode(version)
    _stored_is_data(stored)
    decoded = codec.decode(json.loads(json.dumps(stored)))
    assert canonical(decoded) == canonical(version)
    assert decoded.created_at.tzinfo is not None


def test_recalibration_record_round_trip(fitted: tuple) -> None:
    _, _, _, report = fitted
    codec = RecalibrationRecordCodec(CHARTS)
    record = RecalibrationRecord(
        "t",
        "t2mrcd",
        "m",
        "r",
        JobStatus.SUCCEEDED,
        T0,
        T0,
        {"seed": 11},
        False,
        0,
        None,
        T0,
        actor="ana",
        outcome=RecalibrationDecision.EXTEND,
        report=report,
        proposed_version=1,
    )
    stored = codec.encode(record)
    _stored_is_data(stored)
    assert canonical(codec.decode(json.loads(json.dumps(stored)))) == canonical(record)
    queued = dataclasses.replace(record, status=JobStatus.QUEUED, outcome=None, report=None)
    assert canonical(codec.decode(codec.encode(queued))) == canonical(queued)


def test_repositories_store_encoded_data(fitted: tuple) -> None:
    x, v0, _, _ = fitted
    store: KeyedStore[str, ModelRecord] = KeyedStore(ModelRecordCodec(CHARTS))
    record = ModelRecord("t", "t2mrcd", "m", JobStatus.SUCCEEDED, {}, x, T0, model=v0)
    store.put("k", record)
    assert isinstance(store.rows["k"], dict)
    got = store.get("k")
    assert got is not None
    assert got is not record
    assert canonical(got) == canonical(record)
    repos = (
        InMemoryModelRepository(ModelRecordCodec(CHARTS)),
        InMemoryModelVersionRepository(ModelVersionCodec(CHARTS)),
        InMemoryRecalibrationRepository(RecalibrationRecordCodec(CHARTS)),
    )
    repos[0].add(record)
    assert canonical(repos[0].get("t", "t2mrcd", "m")) == canonical(record)


def test_invalid_stored_data_and_unknown_charts_are_errors(fitted: tuple) -> None:
    x, v0, _, _ = fitted
    codec = ModelRecordCodec(CHARTS)
    record = ModelRecord("t", "t2mrcd", "m", JobStatus.SUCCEEDED, {}, x, T0, model=v0)
    stored = codec.encode(record)
    assert isinstance(stored, dict)
    with pytest.raises(InvalidInputError) as info:
        codec.decode({**stored, "extra": 1})
    assert info.value.details["reason"] == "unknown_fields"
    for field, value in [
        ("status", "nope"),
        ("created_at", "ayer"),
        ("params", []),
        ("model", []),
        ("error", {"code": "X"}),
    ]:
        with pytest.raises(InvalidInputError):
            codec.decode({**stored, field: value})
    with pytest.raises(UnknownChartError):
        codec.encode(dataclasses.replace(record, chart_id="otra"))
    with pytest.raises(InvalidInputError, match="lista"):
        ModelVersionCodec(CHARTS).decode(
            {**_version_stored(v0), "base_refs": "x"}  # no es una lista
        )


def _version_stored(model: T2MRCDModel) -> dict[str, object]:
    version = ModelVersion(
        "t",
        "t2mrcd",
        "m",
        0,
        VersionStatus.ACTIVE,
        model,
        np.zeros((1, 3)),
        "h",
        (),
        (),
        RecalibrationDecision.INITIAL,
        "initial_fit",
        T0,
    )
    stored = ModelVersionCodec(CHARTS).encode(version)
    assert isinstance(stored, dict)
    return stored
