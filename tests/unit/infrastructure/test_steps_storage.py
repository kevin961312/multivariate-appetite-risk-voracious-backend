"""Repositorios de los pasos de Fase I, ``LocalDatasetStorage`` y codecs de ajuste y límites."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from support.bits import canonical
from support.solo_test import fast_params, small_data
from voracious.application.errors import UnknownChartError
from voracious.application.lifecycle import base_content_hash
from voracious.application.ports import DuplicateKeyError, RecordNotFoundError
from voracious.application.records import (
    DatasetRecord,
    DatasetSource,
    DepurationRecord,
    ErrorInfo,
    FitRecord,
    JobStatus,
    LifecyclePolicy,
    LimitsRecord,
    ModelProvenance,
    ModelRecord,
    PipelineKind,
    PipelineRecord,
    PipelineStep,
)
from voracious.domain.charts.t2mrcd import T2MRCDChart
from voracious.domain.common import SerialTaskMapper, StageKind, StageLineage
from voracious.infrastructure.charts import T2MRCDPhase1Steps
from voracious.infrastructure.memory import (
    FitRecordCodec,
    InMemoryDatasetStorage,
    InMemoryDepurationRepository,
    InMemoryFitRepository,
    InMemoryLimitsRepository,
    InMemoryModelRepository,
    InMemoryPipelineRepository,
    LimitsRecordCodec,
    ModelRecordCodec,
)
from voracious.infrastructure.storage import DatasetIntegrityError, LocalDatasetStorage

T = datetime(2026, 1, 1, tzinfo=UTC)
STEPS = {"t2mrcd": T2MRCDPhase1Steps(T2MRCDChart())}


def _dataset(tenant: str = "t", rid: str = "d", **kw: object) -> DatasetRecord:
    data = small_data(5, 2)
    record = DatasetRecord(tenant, rid, data, base_content_hash(data), DatasetSource.UPLOAD, T)
    return replace(record, **kw)


def _fit(tenant: str = "t", rid: str = "f") -> FitRecord:
    return FitRecord(tenant, "c", rid, "d", JobStatus.QUEUED, {}, T)


def _limits(tenant: str = "t", rid: str = "l") -> LimitsRecord:
    return LimitsRecord(tenant, "c", rid, "f", JobStatus.QUEUED, {}, 1, "phase1", 0, (0, 0), T)


def _depuration(tenant: str = "t", rid: str = "x") -> DepurationRecord:
    return DepurationRecord(tenant, "c", rid, "f", JobStatus.QUEUED, (), 0, T)


def _pipeline(tenant: str = "t", rid: str = "p") -> PipelineRecord:
    return PipelineRecord(
        tenant, "c", rid, PipelineKind.PHASE1, JobStatus.QUEUED, "d", {}, (), LifecyclePolicy(), T
    )


JOB_REPOS = [
    (InMemoryFitRepository, _fit),
    (InMemoryLimitsRepository, _limits),
    (InMemoryDepurationRepository, _depuration),
    (InMemoryPipelineRepository, _pipeline),
]


@pytest.mark.parametrize(("repo_type", "make"), JOB_REPOS)
def test_job_repositories_contract(repo_type: type, make: object) -> None:
    repo = repo_type()
    record = make()
    rid = {
        FitRecord: "f",
        LimitsRecord: "l",
        DepurationRecord: "x",
        PipelineRecord: "p",
    }[type(record)]
    repo.add(record)
    with pytest.raises(DuplicateKeyError):
        repo.add(record)
    assert repo.get("t", "c", rid) is record
    assert repo.get("otro", "c", rid) is None
    assert repo.get("t", "otra", rid) is None
    with pytest.raises(RecordNotFoundError):
        repo.update(make("otro"))
    running = repo.claim("t", "c", rid, T)
    assert running is not None
    assert running.status is JobStatus.RUNNING
    assert running.started_at == T
    assert repo.claim("t", "c", rid, T) is None
    assert repo.claim("t", "c", "nada", T) is None
    repo.update(replace(running, status=JobStatus.SUCCEEDED))
    assert repo.get("t", "c", rid).status is JobStatus.SUCCEEDED


def test_pipeline_append_step_is_compare_and_swap() -> None:
    repo = InMemoryPipelineRepository()
    repo.add(_pipeline())
    step = PipelineStep("fit", "f1")
    assert repo.append_step("t", "c", "p", 0, step) is None  # aún queued
    repo.claim("t", "c", "p", T)
    first = repo.append_step("t", "c", "p", 0, step)
    assert first is not None
    assert first.steps == (step,)
    assert repo.append_step("t", "c", "p", 0, PipelineStep("fit", "f2")) is None
    assert repo.append_step("t", "c", "nada", 0, step) is None
    assert repo.get("t", "c", "p").steps == (step,)


def test_in_memory_dataset_storage() -> None:
    storage = InMemoryDatasetStorage()
    record = _dataset()
    storage.add(record)
    with pytest.raises(DuplicateKeyError):
        storage.add(record)
    assert storage.get("t", "d") is record
    assert storage.get("otro", "d") is None


def test_local_dataset_storage_round_trip_in_bits(tmp_path: Path) -> None:
    storage = LocalDatasetStorage(tmp_path / "base")
    root = _dataset()
    derived = _dataset(
        rid="d2",
        source=DatasetSource.DEPURATION_OUTPUT,
        parent_id="d",
        rows=np.array([0, 2, 4], dtype=np.int64),
        lineage_round=1,
        origin_ref="dep-1",
    )
    for record in (root, derived):
        storage.add(record)
        loaded = storage.get("t", record.dataset_id)
        assert loaded is not None
        assert canonical(loaded) == canonical(record)
        assert not loaded.data.flags.writeable
    with pytest.raises(DuplicateKeyError):
        storage.add(root)
    assert storage.get("otro", "d") is None
    assert storage.get("t", "nada") is None
    assert storage.get("t", "../d") is None
    assert storage.get("../t", "d") is None
    assert LocalDatasetStorage(tmp_path / "base").get("t", "d2") is not None  # persiste


def test_local_dataset_storage_rejects_tampering_and_bad_records(tmp_path: Path) -> None:
    storage = LocalDatasetStorage(tmp_path)
    storage.add(_dataset())
    meta = tmp_path / "t" / "d.json"
    doc = json.loads(meta.read_text())
    doc["content_hash"] = "sha256:otra"
    meta.write_text(json.dumps(doc))
    with pytest.raises(DatasetIntegrityError, match="huella"):
        storage.get("t", "d")
    np.save(tmp_path / "t" / "d.npy", np.zeros(3), allow_pickle=False)
    with pytest.raises(DatasetIntegrityError, match="float64"):
        storage.get("t", "d")
    with pytest.raises(ValueError, match="huella"):
        storage.add(replace(_dataset(rid="e"), content_hash="sha256:mal"))
    with pytest.raises(ValueError, match="identificador"):
        storage.add(_dataset(rid="a/b"))


@pytest.fixture(scope="module")
def fitted() -> tuple[object, object, np.ndarray]:
    adapter = STEPS["t2mrcd"]
    x = small_data(40, 4, seed=3)
    params = adapter.encode_params(fast_params())
    fit = adapter.fit(x, adapter.fit_params_of(params))
    calibration = adapter.calibrate(
        x, fit, params, lineage=StageLineage(StageKind.PHASE1), mapper=SerialTaskMapper()
    )
    return fit, calibration.limits, calibration.clean


def test_fit_and_limits_codecs_round_trip_in_bits(
    fitted: tuple[object, object, np.ndarray],
) -> None:
    fit, limits, clean = fitted
    fit_record = replace(
        _fit(),
        chart_id="t2mrcd",
        status=JobStatus.SUCCEEDED,
        params={"alpha": 0.75},
        started_at=T,
        finished_at=T,
        result=fit,
        pipeline_id="p",
    )
    limits_record = replace(
        _limits(),
        chart_id="t2mrcd",
        status=JobStatus.SUCCEEDED,
        result=limits,
        clean_rows=clean,
        recalibration_id="r",
        error=ErrorInfo("X", "y", {"a": [1]}),
    )
    fits = InMemoryFitRepository(FitRecordCodec(STEPS))
    limits_repo = InMemoryLimitsRepository(LimitsRecordCodec(STEPS))
    fits.add(fit_record)
    limits_repo.add(limits_record)
    assert canonical(fits.get("t", "t2mrcd", "f")) == canonical(fit_record)
    assert canonical(limits_repo.get("t", "t2mrcd", "l")) == canonical(limits_record)
    stored = fits._steps.store.rows[("t", "t2mrcd", "f")]
    json.dumps(stored)  # solo datos
    queued = replace(_fit(rid="g"), chart_id="t2mrcd")
    fits.add(queued)
    assert fits.get("t", "t2mrcd", "g").result is None
    with pytest.raises(UnknownChartError):
        fits.add(_fit(rid="h"))  # carta "c" sin pasos


def test_model_record_codec_keeps_provenance() -> None:
    record = ModelRecord(
        "t",
        "t2mrcd",
        "m",
        JobStatus.QUEUED,
        {},
        small_data(4, 2),
        T,
        provenance=ModelProvenance("d", "f", "l", ("x1", "x2")),
        pipeline_id="p",
    )
    repo = InMemoryModelRepository(ModelRecordCodec({"t2mrcd": T2MRCDChart()}))
    repo.add(record)
    assert canonical(repo.get("t", "t2mrcd", "m")) == canonical(record)
    plain = replace(record, model_id="n", provenance=None, pipeline_id=None)
    repo.add(plain)
    assert canonical(repo.get("t", "t2mrcd", "n")) == canonical(plain)
