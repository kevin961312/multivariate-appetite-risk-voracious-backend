"""Fábricas de registros mínimos para la suite de contrato de los repositorios.

Los registros son de la carta ``c``, una carta de prueba (``StubChart``) que solo sabe codificar
su modelo (``StubModel``), su informe, su ajuste, sus límites y su comparación: lo justo para que
los codecs reales (los de Postgres) funcionen sin ajustar nada.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np

from voracious.application.records import (
    BaseRowRef,
    BaseRowSource,
    ComparisonRecord,
    DatasetRecord,
    DatasetSource,
    ErrorInfo,
    ExclusionRecord,
    FitRecord,
    JobStatus,
    LifecyclePolicy,
    LimitsRecord,
    ModelRecord,
    ModelVersion,
    MonitoringRecord,
    ObservationRecord,
    PipelineKind,
    PipelineRecord,
    RecalibrationMode,
    RecalibrationRecord,
    SignalAnnotation,
    StructuralEvent,
    VersionStatus,
)
from voracious.domain.common import RecalibrationDecision

T = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class StubModel:
    """Modelo, informe, ajuste o límites de la carta de prueba: un real exacto en bits."""

    value: float = 1.0


class StubChart:
    """Carta ``c`` de prueba: codifica sus objetos como ``float.hex``."""

    @staticmethod
    def _encode(obj: object) -> dict[str, object]:
        assert isinstance(obj, StubModel)
        return {"value": obj.value.hex()}

    @staticmethod
    def _decode(data: Mapping[str, object]) -> StubModel:
        return StubModel(float.fromhex(str(data["value"])))

    encode_model = encode_report = encode_fit = encode_limits = encode_comparison = _encode
    decode_model = decode_report = decode_fit = decode_limits = decode_comparison = _decode


STUB = StubChart()
CHARTS = {"c": STUB}
"""Registro con la carta de prueba (sirve de cartas, pasos de Fase I y de recalibración)."""


def model(tenant: str = "t", rid: str = "m", status: JobStatus = JobStatus.QUEUED) -> ModelRecord:
    return ModelRecord(tenant, "c", rid, status, {}, np.zeros((3, 2)), T)


def monitoring(
    tenant: str = "t", rid: str = "x", status: JobStatus = JobStatus.QUEUED
) -> MonitoringRecord:
    return MonitoringRecord(tenant, "c", "m", rid, status, np.zeros((1, 2)), (T,), T)


def recalibration(
    tenant: str = "t",
    rid: str = "r",
    status: JobStatus = JobStatus.QUEUED,
    mode: RecalibrationMode = RecalibrationMode.PIPELINE,
) -> RecalibrationRecord:
    return RecalibrationRecord(
        tenant, "c", "m", rid, status, T, T, {}, False, 0, None, T, mode=mode
    )


def version(
    tenant: str = "t", number: int = 0, status: VersionStatus = VersionStatus.ACTIVE
) -> ModelVersion:
    return ModelVersion(
        tenant,
        "c",
        "m",
        number,
        status,
        StubModel(),
        np.zeros((2, 2)),
        "sha256:0",
        (
            BaseRowRef(BaseRowSource.TRAINING, "0", T),
            BaseRowRef(BaseRowSource.OBSERVATION, "o", None),
        ),
        (),
        RecalibrationDecision.INITIAL,
        "initial_fit",
        T,
    )


def observation(tenant: str = "t", rid: str = "o", hours: int = 0) -> ObservationRecord:
    when = T + timedelta(hours=hours)
    return ObservationRecord(
        tenant, "c", "m", rid, "x", None, when, np.zeros(2), 1.0, 2.0, "k", 0, False, when
    )


def annotation(tenant: str = "t", rid: str = "a", obs: str = "o") -> SignalAnnotation:
    return SignalAnnotation(tenant, "c", "m", rid, obs, True, None, None, None, T)


def event(tenant: str = "t", rid: str = "e") -> StructuralEvent:
    return StructuralEvent(tenant, "c", "m", rid, T, "cambio", None, T)


def fit(tenant: str = "t", rid: str = "f", status: JobStatus = JobStatus.QUEUED) -> FitRecord:
    return FitRecord(tenant, "c", rid, "d", status, {"alpha": 0.75}, T)


def limits(tenant: str = "t", rid: str = "l", status: JobStatus = JobStatus.QUEUED) -> LimitsRecord:
    return LimitsRecord(tenant, "c", rid, "f", status, {}, 7, "phase1", (0, 1), T)


def exclusion(
    tenant: str = "t", rid: str = "e", status: JobStatus = JobStatus.QUEUED
) -> ExclusionRecord:
    return ExclusionRecord(tenant, "c", rid, "d", status, (), T)


def pipeline(
    tenant: str = "t", rid: str = "p", status: JobStatus = JobStatus.QUEUED
) -> PipelineRecord:
    return PipelineRecord(
        tenant, "c", rid, PipelineKind.PHASE1, status, "d", {}, (), LifecyclePolicy(), T
    )


def comparison(
    tenant: str = "t", rid: str = "x", status: JobStatus = JobStatus.QUEUED
) -> ComparisonRecord:
    return ComparisonRecord(tenant, "c", "m", rid, "r", "f", "l", status, T)


def dataset(tenant: str = "t", rid: str = "d", dated: bool = True) -> DatasetRecord:
    from voracious.application.lifecycle import base_content_hash, frozen_base

    data = frozen_base(np.arange(6, dtype=np.float64).reshape(3, 2))
    return DatasetRecord(
        tenant,
        rid,
        data,
        base_content_hash(data),
        DatasetSource.UPLOAD,
        T,
        variables=("a", "b") if dated else None,
        observed_at=tuple(T + timedelta(days=i) for i in range(3)) if dated else None,
    )


FAILED = ErrorInfo("X", "y", {"k": [1, 2.5]})
