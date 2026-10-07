"""Dobles en memoria de los puertos de aplicación (solo para tests)."""

from datetime import UTC, datetime, timedelta

from voracious.application.ports import JobRequest
from voracious.application.records import ModelRecord, MonitoringRecord


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
