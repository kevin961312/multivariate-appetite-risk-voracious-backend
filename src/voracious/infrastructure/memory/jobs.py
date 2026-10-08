"""Repositorios en memoria de los trabajos: modelos, monitoreos, recalibraciones, comparaciones.

Cada uno implementa ``claim`` (``queued → running`` atómico) para que una entrega duplicada de
la cola no ejecute dos veces el mismo trabajo.
"""

from dataclasses import replace
from datetime import datetime

from voracious.application.ports import DuplicateKeyError, RecordNotFoundError
from voracious.application.records import (
    ComparisonRecord,
    JobStatus,
    ModelRecord,
    MonitoringRecord,
    ProposalRequest,
    RecalibrationMode,
    RecalibrationRecord,
)
from voracious.infrastructure.memory.codec import PassthroughCodec, RecordCodec
from voracious.infrastructure.memory.store import KeyedStore

__all__ = [
    "InMemoryComparisonRepository",
    "InMemoryModelRepository",
    "InMemoryMonitoringRepository",
    "InMemoryRecalibrationRepository",
]

ModelKey = tuple[str, str, str]
ChildKey = tuple[str, str, str, str]

_IN_PROGRESS = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})


class InMemoryModelRepository:
    """``ModelRepository`` en memoria con clave (tenant, carta, modelo)."""

    def __init__(self, codec: RecordCodec[ModelRecord] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec de los registros; ``None`` guarda el registro tal cual (tests).
        """
        self._store: KeyedStore[ModelKey, ModelRecord] = KeyedStore(
            codec if codec is not None else PassthroughCodec(ModelRecord)
        )

    @staticmethod
    def _key(record: ModelRecord) -> ModelKey:
        return (record.tenant_id, record.chart_id, record.model_id)

    def add(self, record: ModelRecord) -> None:
        """Guarda un modelo nuevo.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        key = self._key(record)
        with self._store.lock:
            if self._store.contains(key):
                raise DuplicateKeyError(str(key))
            self._store.put(key, record)

    def get(self, tenant_id: str, chart_id: str, model_id: str) -> ModelRecord | None:
        """Busca un modelo.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            El registro o ``None``.
        """
        return self._store.get((tenant_id, chart_id, model_id))

    def update(self, record: ModelRecord) -> None:
        """Reemplaza un modelo existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        key = self._key(record)
        with self._store.lock:
            if not self._store.contains(key):
                raise RecordNotFoundError(str(key))
            self._store.put(key, record)

    def claim(
        self, tenant_id: str, chart_id: str, model_id: str, started_at: datetime
    ) -> ModelRecord | None:
        """Pasa el modelo de ``queued`` a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None`` si no existe o no estaba ``queued``.
        """
        key = (tenant_id, chart_id, model_id)
        with self._store.lock:
            current = self._store.get(key)
            if current is None or current.status is not JobStatus.QUEUED:
                return None
            running = replace(current, status=JobStatus.RUNNING, started_at=started_at)
            self._store.put(key, running)
            return running


class InMemoryMonitoringRepository:
    """``MonitoringRepository`` en memoria con clave (tenant, carta, modelo, monitoreo)."""

    def __init__(self, codec: RecordCodec[MonitoringRecord] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec de los registros; ``None`` guarda el registro tal cual (tests).
        """
        self._store: KeyedStore[ChildKey, MonitoringRecord] = KeyedStore(
            codec if codec is not None else PassthroughCodec(MonitoringRecord)
        )

    @staticmethod
    def _key(record: MonitoringRecord) -> ChildKey:
        return (record.tenant_id, record.chart_id, record.model_id, record.monitoring_id)

    def add(self, record: MonitoringRecord) -> None:
        """Guarda un monitoreo nuevo.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        key = self._key(record)
        with self._store.lock:
            if self._store.contains(key):
                raise DuplicateKeyError(str(key))
            self._store.put(key, record)

    def get(
        self, tenant_id: str, chart_id: str, model_id: str, monitoring_id: str
    ) -> MonitoringRecord | None:
        """Busca un monitoreo.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            monitoring_id: Monitoreo.

        Returns:
            El registro o ``None``.
        """
        return self._store.get((tenant_id, chart_id, model_id, monitoring_id))

    def update(self, record: MonitoringRecord) -> None:
        """Reemplaza un monitoreo existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        key = self._key(record)
        with self._store.lock:
            if not self._store.contains(key):
                raise RecordNotFoundError(str(key))
            self._store.put(key, record)

    def claim(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        monitoring_id: str,
        started_at: datetime,
    ) -> MonitoringRecord | None:
        """Pasa el monitoreo de ``queued`` a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            monitoring_id: Monitoreo.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None`` si no existe o no estaba ``queued``.
        """
        key = (tenant_id, chart_id, model_id, monitoring_id)
        with self._store.lock:
            current = self._store.get(key)
            if current is None or current.status is not JobStatus.QUEUED:
                return None
            running = replace(current, status=JobStatus.RUNNING, started_at=started_at)
            self._store.put(key, running)
            return running


class InMemoryRecalibrationRepository:
    """``RecalibrationRepository`` en memoria con clave (tenant, carta, modelo, recalibración)."""

    def __init__(self, codec: RecordCodec[RecalibrationRecord] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec de los registros; ``None`` guarda el registro tal cual (tests).
        """
        self._store: KeyedStore[ChildKey, RecalibrationRecord] = KeyedStore(
            codec if codec is not None else PassthroughCodec(RecalibrationRecord)
        )

    @staticmethod
    def _key(record: RecalibrationRecord) -> ChildKey:
        return (record.tenant_id, record.chart_id, record.model_id, record.recalibration_id)

    def add(self, record: RecalibrationRecord) -> None:
        """Guarda una recalibración nueva.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        key = self._key(record)
        with self._store.lock:
            if self._store.contains(key):
                raise DuplicateKeyError(str(key))
            self._store.put(key, record)

    def add_if_none_in_progress(self, record: RecalibrationRecord) -> bool:
        """Guarda la recalibración si el modelo no tiene otra ``queued`` o ``running``.

        Args:
            record: Registro.

        Returns:
            ``True`` si se guardó.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        with self._store.lock:
            busy = self.list(record.tenant_id, record.chart_id, record.model_id)
            if any(r.status in _IN_PROGRESS for r in busy):
                return False
            self.add(record)
            return True

    def get(
        self, tenant_id: str, chart_id: str, model_id: str, recalibration_id: str
    ) -> RecalibrationRecord | None:
        """Busca una recalibración.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.

        Returns:
            El registro o ``None``.
        """
        return self._store.get((tenant_id, chart_id, model_id, recalibration_id))

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[RecalibrationRecord]:
        """Recalibraciones del modelo en orden de creación.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            Los registros.
        """
        prefix = (tenant_id, chart_id, model_id)
        return self._store.select(lambda k: k[:3] == prefix)

    def update(self, record: RecalibrationRecord) -> None:
        """Reemplaza una recalibración existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        key = self._key(record)
        with self._store.lock:
            if not self._store.contains(key):
                raise RecordNotFoundError(str(key))
            self._store.put(key, record)

    def claim(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        recalibration_id: str,
        started_at: datetime,
    ) -> RecalibrationRecord | None:
        """Pasa la recalibración de ``queued`` a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None`` si no existe o no estaba ``queued``.
        """
        key = (tenant_id, chart_id, model_id, recalibration_id)
        with self._store.lock:
            current = self._store.get(key)
            if current is None or current.status is not JobStatus.QUEUED:
                return None
            running = replace(current, status=JobStatus.RUNNING, started_at=started_at)
            self._store.put(key, running)
            return running

    def find(
        self, tenant_id: str, chart_id: str, recalibration_id: str
    ) -> RecalibrationRecord | None:
        """Busca una recalibración solo por su id.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            recalibration_id: Recalibración.

        Returns:
            El registro o ``None``.
        """
        rows = self._store.select(
            lambda k: k[0] == tenant_id and k[1] == chart_id and k[3] == recalibration_id
        )
        return rows[0] if rows else None

    def request_proposal(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        recalibration_id: str,
        proposal: ProposalRequest,
    ) -> RecalibrationRecord | None:
        """Guarda la petición de propuesta si sigue ``running`` y sin otra (atómico).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.
            proposal: Petición.

        Returns:
            El registro con la petición o ``None``.
        """
        key = (tenant_id, chart_id, model_id, recalibration_id)
        with self._store.lock:
            current = self._store.get(key)
            if (
                current is None
                or current.status is not JobStatus.RUNNING
                or current.proposal is not None
            ):
                return None
            updated = replace(current, proposal=proposal)
            self._store.put(key, updated)
            return updated

    def cancel(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        recalibration_id: str,
        finished_at: datetime,
    ) -> RecalibrationRecord | None:
        """Cancela una sesión paso a paso ``running`` sin propuesta pedida (atómico).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.
            finished_at: Instante de la cancelación.

        Returns:
            El registro ``cancelled`` o ``None``.
        """
        key = (tenant_id, chart_id, model_id, recalibration_id)
        with self._store.lock:
            current = self._store.get(key)
            if (
                current is None
                or current.mode is not RecalibrationMode.STEPWISE
                or current.status is not JobStatus.RUNNING
                or current.proposal is not None
            ):
                return None
            cancelled = replace(current, status=JobStatus.CANCELLED, finished_at=finished_at)
            self._store.put(key, cancelled)
            return cancelled

    def claim_proposal(
        self, tenant_id: str, chart_id: str, model_id: str, recalibration_id: str
    ) -> RecalibrationRecord | None:
        """Pasa la petición de propuesta de ``queued`` a ``running`` (atómico).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.

        Returns:
            El registro con la petición en ``running`` o ``None``.
        """
        key = (tenant_id, chart_id, model_id, recalibration_id)
        with self._store.lock:
            current = self._store.get(key)
            if (
                current is None
                or current.proposal is None
                or current.proposal.status is not JobStatus.QUEUED
            ):
                return None
            updated = replace(current, proposal=replace(current.proposal, status=JobStatus.RUNNING))
            self._store.put(key, updated)
            return updated


class InMemoryComparisonRepository:
    """``ComparisonRepository`` en memoria con clave (tenant, carta, modelo, comparación)."""

    def __init__(self, codec: RecordCodec[ComparisonRecord] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec de los registros; ``None`` guarda el registro tal cual (tests).
        """
        self._store: KeyedStore[ChildKey, ComparisonRecord] = KeyedStore(
            codec if codec is not None else PassthroughCodec(ComparisonRecord)
        )

    @staticmethod
    def _key(record: ComparisonRecord) -> ChildKey:
        return (record.tenant_id, record.chart_id, record.model_id, record.comparison_id)

    def add(self, record: ComparisonRecord) -> None:
        """Guarda una comparación nueva.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        key = self._key(record)
        with self._store.lock:
            if self._store.contains(key):
                raise DuplicateKeyError(str(key))
            self._store.put(key, record)

    def get(
        self, tenant_id: str, chart_id: str, model_id: str, comparison_id: str
    ) -> ComparisonRecord | None:
        """Busca una comparación.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            comparison_id: Comparación.

        Returns:
            El registro o ``None``.
        """
        return self._store.get((tenant_id, chart_id, model_id, comparison_id))

    def update(self, record: ComparisonRecord) -> None:
        """Reemplaza una comparación existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        key = self._key(record)
        with self._store.lock:
            if not self._store.contains(key):
                raise RecordNotFoundError(str(key))
            self._store.put(key, record)

    def claim(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        comparison_id: str,
        started_at: datetime,
    ) -> ComparisonRecord | None:
        """Pasa la comparación de ``queued`` a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            comparison_id: Comparación.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None`` si no existe o no estaba ``queued``.
        """
        key = (tenant_id, chart_id, model_id, comparison_id)
        with self._store.lock:
            current = self._store.get(key)
            if current is None or current.status is not JobStatus.QUEUED:
                return None
            running = replace(current, status=JobStatus.RUNNING, started_at=started_at)
            self._store.put(key, running)
            return running
