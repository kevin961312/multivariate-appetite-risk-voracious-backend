"""Dobles en memoria de los puertos de aplicación (solo para tests)."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from voracious.application.ports import DuplicateKeyError, JobRequest, VersionStatusChange
from voracious.application.records import (
    ModelRecord,
    ModelVersion,
    MonitoringRecord,
    ObservationRecord,
    RecalibrationRecord,
    SignalAnnotation,
    StructuralEvent,
    VersionStatus,
)

ModelKey = tuple[str, str, str]


class InMemoryModelRepository:
    """``ModelRepository`` en memoria con clave (tenant, carta, modelo)."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str], ModelRecord] = {}
        self.history: list[ModelRecord] = []

    def add(self, record: ModelRecord) -> None:
        key = (record.tenant_id, record.chart_id, record.model_id)
        assert key not in self.records
        self.records[key] = record
        self.history.append(record)

    def get(self, tenant_id: str, chart_id: str, model_id: str) -> ModelRecord | None:
        return self.records.get((tenant_id, chart_id, model_id))

    def update(self, record: ModelRecord) -> None:
        key = (record.tenant_id, record.chart_id, record.model_id)
        assert key in self.records
        self.records[key] = record
        self.history.append(record)


class InMemoryMonitoringRepository:
    """``MonitoringRepository`` en memoria con clave (tenant, carta, modelo, monitoreo)."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str, str], MonitoringRecord] = {}
        self.history: list[MonitoringRecord] = []

    def add(self, record: MonitoringRecord) -> None:
        key = (record.tenant_id, record.chart_id, record.model_id, record.monitoring_id)
        assert key not in self.records
        self.records[key] = record
        self.history.append(record)

    def get(
        self, tenant_id: str, chart_id: str, model_id: str, monitoring_id: str
    ) -> MonitoringRecord | None:
        return self.records.get((tenant_id, chart_id, model_id, monitoring_id))

    def update(self, record: MonitoringRecord) -> None:
        key = (record.tenant_id, record.chart_id, record.model_id, record.monitoring_id)
        assert key in self.records
        self.records[key] = record
        self.history.append(record)


class RecordingJobQueue:
    """``JobQueue`` que solo guarda las peticiones (los tests las ejecutan a mano)."""

    def __init__(self) -> None:
        self.jobs: list[JobRequest] = []

    def enqueue(self, job: JobRequest) -> None:
        self.jobs.append(job)


class SequentialIds:
    """``IdGenerator`` determinista: ``id-1``, ``id-2``…"""

    def __init__(self) -> None:
        self.count = 0

    def new_id(self) -> str:
        self.count += 1
        return f"id-{self.count}"


class TickingClock:
    """``Clock`` que avanza un segundo en cada llamada, en UTC."""

    def __init__(self) -> None:
        self.current = datetime(2026, 10, 7, tzinfo=UTC)

    def now(self) -> datetime:
        self.current += timedelta(seconds=1)
        return self.current


class InMemoryModelVersionRepository:
    """``ModelVersionRepository`` append-only con comparar-y-cambiar de estado real."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str, int], ModelVersion] = {}

    def add(self, version: ModelVersion) -> None:
        key = (version.tenant_id, version.chart_id, version.model_id, version.number)
        if key in self.records:
            raise DuplicateKeyError(str(key))
        self.records[key] = version

    def get(self, tenant_id: str, chart_id: str, model_id: str, number: int) -> ModelVersion | None:
        return self.records.get((tenant_id, chart_id, model_id, number))

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[ModelVersion]:
        return sorted(
            (v for k, v in self.records.items() if k[:3] == (tenant_id, chart_id, model_id)),
            key=lambda v: v.number,
        )

    def apply_status_changes(self, changes: Sequence[VersionStatusChange]) -> bool:
        keys = [(c.tenant_id, c.chart_id, c.model_id, c.number) for c in changes]
        for key, change in zip(keys, changes, strict=True):
            current = self.records.get(key)
            if current is None or current.status is not change.expected:
                return False
        for key, change in zip(keys, changes, strict=True):
            version = replace(self.records[key], status=change.new)
            decision = change.decision
            if decision is not None:
                approved = change.new is VersionStatus.ACTIVE
                version = replace(
                    version,
                    effective_from=decision.effective_from if approved else version.effective_from,
                    approved_at=decision.decided_at if approved else version.approved_at,
                    rejected_at=decision.decided_at
                    if change.new is VersionStatus.REJECTED
                    else version.rejected_at,
                    decided_by=decision.decided_by,
                    decision_note=decision.note,
                )
            self.records[key] = version
        return True


class InMemoryObservationRepository:
    """``ObservationRepository`` en memoria."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str, str], ObservationRecord] = {}

    def add_many(self, records: Sequence[ObservationRecord]) -> None:
        keys = [(r.tenant_id, r.chart_id, r.model_id, r.observation_id) for r in records]
        if any(k in self.records for k in keys) or len(set(keys)) != len(keys):
            raise DuplicateKeyError("observación repetida")
        self.records.update(zip(keys, records, strict=True))

    def get(
        self, tenant_id: str, chart_id: str, model_id: str, observation_id: str
    ) -> ObservationRecord | None:
        return self.records.get((tenant_id, chart_id, model_id, observation_id))

    def _of(self, key: ModelKey) -> list[ObservationRecord]:
        return [r for k, r in self.records.items() if k[:3] == key]

    def list(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        *,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
        signals_only: bool = False,
    ) -> list[ObservationRecord]:
        rows = [
            r
            for r in self._of((tenant_id, chart_id, model_id))
            if (observed_from is None or r.observed_at >= observed_from)
            and (observed_to is None or r.observed_at <= observed_to)
            and (not signals_only or r.signal)
        ]
        return sorted(rows, key=lambda r: r.observed_at)

    def max_observed_at(self, tenant_id: str, chart_id: str, model_id: str) -> datetime | None:
        rows = self._of((tenant_id, chart_id, model_id))
        return max((r.observed_at for r in rows), default=None)

    def count_scored_with(
        self, tenant_id: str, chart_id: str, model_id: str, version_number: int
    ) -> int:
        rows = self._of((tenant_id, chart_id, model_id))
        return sum(r.version_number == version_number for r in rows)


class InMemorySignalAnnotationRepository:
    """``SignalAnnotationRepository`` append-only en memoria."""

    def __init__(self) -> None:
        self.records: list[SignalAnnotation] = []

    def add(self, annotation: SignalAnnotation) -> None:
        if any(a.annotation_id == annotation.annotation_id for a in self.records):
            raise DuplicateKeyError(annotation.annotation_id)
        self.records.append(annotation)

    def history(
        self, tenant_id: str, chart_id: str, model_id: str, observation_id: str
    ) -> list[SignalAnnotation]:
        key = (tenant_id, chart_id, model_id, observation_id)
        return [
            a
            for a in self.records
            if (a.tenant_id, a.chart_id, a.model_id, a.observation_id) == key
        ]

    def latest_for(
        self, tenant_id: str, chart_id: str, model_id: str, observation_ids: Sequence[str]
    ) -> dict[str, SignalAnnotation]:
        out: dict[str, SignalAnnotation] = {}
        for obs_id in observation_ids:
            history = self.history(tenant_id, chart_id, model_id, obs_id)
            if history:
                out[obs_id] = history[-1]
        return out


class InMemoryStructuralEventRepository:
    """``StructuralEventRepository`` append-only en memoria."""

    def __init__(self) -> None:
        self.records: list[StructuralEvent] = []

    def add(self, event: StructuralEvent) -> None:
        if any(e.event_id == event.event_id for e in self.records):
            raise DuplicateKeyError(event.event_id)
        self.records.append(event)

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[StructuralEvent]:
        rows = [
            e
            for e in self.records
            if (e.tenant_id, e.chart_id, e.model_id) == (tenant_id, chart_id, model_id)
        ]
        return sorted(rows, key=lambda e: (e.occurred_at, e.registered_at))


class InMemoryRecalibrationRepository:
    """``RecalibrationRepository`` en memoria."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str, str], RecalibrationRecord] = {}

    def add(self, record: RecalibrationRecord) -> None:
        key = (record.tenant_id, record.chart_id, record.model_id, record.recalibration_id)
        if key in self.records:
            raise DuplicateKeyError(str(key))
        self.records[key] = record

    def get(
        self, tenant_id: str, chart_id: str, model_id: str, recalibration_id: str
    ) -> RecalibrationRecord | None:
        return self.records.get((tenant_id, chart_id, model_id, recalibration_id))

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[RecalibrationRecord]:
        return [r for k, r in self.records.items() if k[:3] == (tenant_id, chart_id, model_id)]

    def update(self, record: RecalibrationRecord) -> None:
        key = (record.tenant_id, record.chart_id, record.model_id, record.recalibration_id)
        assert key in self.records
        self.records[key] = record


class FixedClock:
    """``Clock`` controlado por el test (UTC); ``advance`` lo mueve."""

    def __init__(self, start: datetime | None = None) -> None:
        self.current = start if start is not None else datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta
