"""Dobles de los puertos de aplicación para tests.

Los repositorios en memoria son los de producción (``voracious.infrastructure.memory``); aquí
solo se añade lo que los tests inspeccionan: ``records`` (el almacén, que con el codec identidad
guarda los registros tal cual) e ``history`` (cada registro guardado, en orden). La cola, los
identificadores y los relojes deterministas son solo de test.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from voracious.application.ports import JobRequest
from voracious.application.records import ModelRecord, MonitoringRecord
from voracious.infrastructure.memory import (
    InMemoryComparisonRepository,
    InMemoryDatasetStorage,
    InMemoryExclusionRepository,
    InMemoryFitRepository,
    InMemoryLimitsRepository,
    InMemoryObservationRepository,
    InMemoryPipelineRepository,
    InMemorySignalAnnotationRepository,
    InMemoryStructuralEventRepository,
)
from voracious.infrastructure.memory import (
    InMemoryModelRepository as _ModelRepository,
)
from voracious.infrastructure.memory import (
    InMemoryModelVersionRepository as _VersionRepository,
)
from voracious.infrastructure.memory import (
    InMemoryMonitoringRepository as _MonitoringRepository,
)
from voracious.infrastructure.memory import (
    InMemoryRecalibrationRepository as _RecalibrationRepository,
)

__all__ = [
    "FixedClock",
    "InMemoryComparisonRepository",
    "InMemoryDatasetStorage",
    "InMemoryExclusionRepository",
    "InMemoryFitRepository",
    "InMemoryLimitsRepository",
    "InMemoryModelRepository",
    "InMemoryModelVersionRepository",
    "InMemoryMonitoringRepository",
    "InMemoryObservationRepository",
    "InMemoryPipelineRepository",
    "InMemoryRecalibrationRepository",
    "InMemorySignalAnnotationRepository",
    "InMemoryStructuralEventRepository",
    "RecordingJobQueue",
    "SequentialIds",
    "TickingClock",
]


class InMemoryModelRepository(_ModelRepository):
    """Repositorio de producción con ``records`` e ``history`` para inspección."""

    def __init__(self) -> None:
        super().__init__()
        self.history: list[ModelRecord] = []

    @property
    def records(self) -> dict[Any, Any]:
        return self._store.rows

    def add(self, record: ModelRecord) -> None:
        super().add(record)
        self.history.append(record)

    def update(self, record: ModelRecord) -> None:
        super().update(record)
        self.history.append(record)

    def claim(
        self, tenant_id: str, chart_id: str, model_id: str, started_at: datetime
    ) -> ModelRecord | None:
        out = super().claim(tenant_id, chart_id, model_id, started_at)
        if out is not None:
            self.history.append(out)
        return out


class InMemoryMonitoringRepository(_MonitoringRepository):
    """Repositorio de producción con ``records`` e ``history`` para inspección."""

    def __init__(self) -> None:
        super().__init__()
        self.history: list[MonitoringRecord] = []

    @property
    def records(self) -> dict[Any, Any]:
        return self._store.rows

    def add(self, record: MonitoringRecord) -> None:
        super().add(record)
        self.history.append(record)

    def update(self, record: MonitoringRecord) -> None:
        super().update(record)
        self.history.append(record)

    def claim(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        monitoring_id: str,
        started_at: datetime,
    ) -> MonitoringRecord | None:
        out = super().claim(tenant_id, chart_id, model_id, monitoring_id, started_at)
        if out is not None:
            self.history.append(out)
        return out


class InMemoryModelVersionRepository(_VersionRepository):
    """Repositorio de producción con ``records`` para inspección."""

    @property
    def records(self) -> dict[Any, Any]:
        return self._store.rows


class InMemoryRecalibrationRepository(_RecalibrationRepository):
    """Repositorio de producción con ``records`` para inspección."""

    @property
    def records(self) -> dict[Any, Any]:
        return self._store.rows


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


class FixedClock:
    """``Clock`` controlado por el test (UTC); ``advance`` lo mueve."""

    def __init__(self, start: datetime | None = None) -> None:
        self.current = start if start is not None else datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta
