"""Fábricas de registros mínimos para la suite de contrato de los repositorios."""

from datetime import UTC, datetime, timedelta

import numpy as np

from voracious.application.records import (
    JobStatus,
    ModelRecord,
    ModelVersion,
    MonitoringRecord,
    ObservationRecord,
    RecalibrationRecord,
    SignalAnnotation,
    StructuralEvent,
    VersionStatus,
)
from voracious.domain.common import RecalibrationDecision

T = datetime(2026, 1, 1, tzinfo=UTC)


def model(tenant: str = "t", rid: str = "m", status: JobStatus = JobStatus.QUEUED) -> ModelRecord:
    return ModelRecord(tenant, "c", rid, status, {}, np.zeros((3, 2)), T)


def monitoring(
    tenant: str = "t", rid: str = "x", status: JobStatus = JobStatus.QUEUED
) -> MonitoringRecord:
    return MonitoringRecord(tenant, "c", "m", rid, status, np.zeros((1, 2)), (T,), T)


def recalibration(
    tenant: str = "t", rid: str = "r", status: JobStatus = JobStatus.QUEUED
) -> RecalibrationRecord:
    return RecalibrationRecord(tenant, "c", "m", rid, status, T, T, {}, False, 0, None, T)


def version(
    tenant: str = "t", number: int = 0, status: VersionStatus = VersionStatus.ACTIVE
) -> ModelVersion:
    return ModelVersion(
        tenant,
        "c",
        "m",
        number,
        status,
        object(),
        np.zeros((2, 2)),
        "sha256:0",
        (),
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
