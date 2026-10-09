"""Repositorios en memoria de los pasos de Fase I: datasets, exclusiones, ajustes y límites.

Los registros de trabajo tienen clave (tenant, carta, id) y ``claim`` (``queued → running``
atómico); las tuberías además ``append_step`` (comparar-y-cambiar sobre el número de pasos). Los
datasets tienen clave (tenant, dataset): no pertenecen a ninguna carta.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Protocol

from voracious.application.ports import DuplicateKeyError, RecordNotFoundError
from voracious.application.records import (
    DatasetRecord,
    ExclusionRecord,
    FitRecord,
    JobStatus,
    LimitsRecord,
    PipelineRecord,
    PipelineStep,
)
from voracious.infrastructure.memory.codec import PassthroughCodec, RecordCodec
from voracious.infrastructure.memory.store import KeyedStore

__all__ = [
    "InMemoryDatasetStorage",
    "InMemoryExclusionRepository",
    "InMemoryFitRepository",
    "InMemoryLimitsRepository",
    "InMemoryPipelineRepository",
]

StepKey = tuple[str, str, str]


class _StepRecord(Protocol):
    """Lo que el almacén genérico lee de un registro de trabajo."""

    @property
    def tenant_id(self) -> str:
        """Tenant."""
        ...

    @property
    def chart_id(self) -> str:
        """Carta."""
        ...

    @property
    def status(self) -> JobStatus:
        """Estado."""
        ...


class _StepStore[R: _StepRecord]:
    """Almacén de registros de trabajo con clave (tenant, carta, id) y ``claim``."""

    def __init__(
        self,
        codec: RecordCodec[R],
        id_of: Callable[[R], str],
        start: Callable[[R, datetime], R],
    ) -> None:
        """Construye el almacén vacío.

        Args:
            codec: Codec de los registros.
            id_of: Identificador de un registro.
            start: Copia del registro en ``running`` con su instante de inicio.
        """
        self.store: KeyedStore[StepKey, R] = KeyedStore(codec)
        self._id_of = id_of
        self._start = start

    def key(self, record: R) -> StepKey:
        """Clave de un registro.

        Args:
            record: Registro.

        Returns:
            (tenant, carta, id).
        """
        return (record.tenant_id, record.chart_id, self._id_of(record))

    def add(self, record: R) -> None:
        """Guarda un registro nuevo.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        key = self.key(record)
        with self.store.lock:
            if self.store.contains(key):
                raise DuplicateKeyError(str(key))
            self.store.put(key, record)

    def get(self, key: StepKey) -> R | None:
        """Busca un registro.

        Args:
            key: Clave.

        Returns:
            El registro o ``None``.
        """
        return self.store.get(key)

    def update(self, record: R) -> None:
        """Reemplaza un registro existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        key = self.key(record)
        with self.store.lock:
            if not self.store.contains(key):
                raise RecordNotFoundError(str(key))
            self.store.put(key, record)

    def claim(self, key: StepKey, started_at: datetime) -> R | None:
        """Pasa un registro de ``queued`` a ``running`` de forma atómica.

        Args:
            key: Clave.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None`` si no existe o no estaba ``queued``.
        """
        with self.store.lock:
            current = self.store.get(key)
            if current is None or current.status is not JobStatus.QUEUED:
                return None
            running = self._start(current, started_at)
            self.store.put(key, running)
            return running


class InMemoryDatasetStorage:
    """``DatasetStorage`` en memoria con clave (tenant, dataset)."""

    def __init__(self, codec: RecordCodec[DatasetRecord] | None = None) -> None:
        """Construye el almacenamiento vacío.

        Args:
            codec: Codec de los registros; ``None`` guarda el registro tal cual (es inmutable y su
                matriz es de solo lectura).
        """
        self._store: KeyedStore[tuple[str, str], DatasetRecord] = KeyedStore(
            codec if codec is not None else PassthroughCodec(DatasetRecord)
        )

    def add(self, record: DatasetRecord) -> None:
        """Guarda un dataset nuevo.

        Args:
            record: Dataset.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        key = (record.tenant_id, record.dataset_id)
        with self._store.lock:
            if self._store.contains(key):
                raise DuplicateKeyError(str(key))
            self._store.put(key, record)

    def get(self, tenant_id: str, dataset_id: str) -> DatasetRecord | None:
        """Busca un dataset.

        Args:
            tenant_id: Tenant.
            dataset_id: Dataset.

        Returns:
            El dataset o ``None``.
        """
        return self._store.get((tenant_id, dataset_id))


class InMemoryFitRepository:
    """``FitRepository`` en memoria."""

    def __init__(self, codec: RecordCodec[FitRecord] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec (``FitRecordCodec`` en producción); ``None`` guarda tal cual (tests).
        """
        self._steps: _StepStore[FitRecord] = _StepStore(
            codec if codec is not None else PassthroughCodec(FitRecord),
            lambda r: r.fit_id,
            lambda r, t: replace(r, status=JobStatus.RUNNING, started_at=t),
        )

    def add(self, record: FitRecord) -> None:
        """Guarda un ajuste nuevo.

        Args:
            record: Registro.
        """
        self._steps.add(record)

    def get(self, tenant_id: str, chart_id: str, fit_id: str) -> FitRecord | None:
        """Busca un ajuste.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste.

        Returns:
            El registro o ``None``.
        """
        return self._steps.get((tenant_id, chart_id, fit_id))

    def update(self, record: FitRecord) -> None:
        """Reemplaza un ajuste existente.

        Args:
            record: Registro nuevo.
        """
        self._steps.update(record)

    def claim(
        self, tenant_id: str, chart_id: str, fit_id: str, started_at: datetime
    ) -> FitRecord | None:
        """Pasa el ajuste a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._steps.claim((tenant_id, chart_id, fit_id), started_at)


class InMemoryLimitsRepository:
    """``LimitsRepository`` en memoria."""

    def __init__(self, codec: RecordCodec[LimitsRecord] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec (``LimitsRecordCodec`` en producción); ``None`` guarda tal cual.
        """
        self._steps: _StepStore[LimitsRecord] = _StepStore(
            codec if codec is not None else PassthroughCodec(LimitsRecord),
            lambda r: r.limits_id,
            lambda r, t: replace(r, status=JobStatus.RUNNING, started_at=t),
        )

    def add(self, record: LimitsRecord) -> None:
        """Guarda una calibración nueva.

        Args:
            record: Registro.
        """
        self._steps.add(record)

    def get(self, tenant_id: str, chart_id: str, limits_id: str) -> LimitsRecord | None:
        """Busca una calibración.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            limits_id: Calibración.

        Returns:
            El registro o ``None``.
        """
        return self._steps.get((tenant_id, chart_id, limits_id))

    def update(self, record: LimitsRecord) -> None:
        """Reemplaza una calibración existente.

        Args:
            record: Registro nuevo.
        """
        self._steps.update(record)

    def claim(
        self, tenant_id: str, chart_id: str, limits_id: str, started_at: datetime
    ) -> LimitsRecord | None:
        """Pasa la calibración a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            limits_id: Calibración.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._steps.claim((tenant_id, chart_id, limits_id), started_at)


class InMemoryExclusionRepository:
    """``ExclusionRepository`` en memoria (registros sin objetos de carta: tal cual)."""

    def __init__(self, codec: RecordCodec[ExclusionRecord] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec; ``None`` guarda el registro inmutable tal cual.
        """
        self._steps: _StepStore[ExclusionRecord] = _StepStore(
            codec if codec is not None else PassthroughCodec(ExclusionRecord),
            lambda r: r.exclusion_id,
            lambda r, t: replace(r, status=JobStatus.RUNNING, started_at=t),
        )

    def add(self, record: ExclusionRecord) -> None:
        """Guarda una exclusión nueva.

        Args:
            record: Registro.
        """
        self._steps.add(record)

    def get(self, tenant_id: str, chart_id: str, exclusion_id: str) -> ExclusionRecord | None:
        """Busca una exclusión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            exclusion_id: Exclusión.

        Returns:
            El registro o ``None``.
        """
        return self._steps.get((tenant_id, chart_id, exclusion_id))

    def update(self, record: ExclusionRecord) -> None:
        """Reemplaza una exclusión existente.

        Args:
            record: Registro nuevo.
        """
        self._steps.update(record)

    def claim(
        self, tenant_id: str, chart_id: str, exclusion_id: str, started_at: datetime
    ) -> ExclusionRecord | None:
        """Pasa la exclusión a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            exclusion_id: Exclusión.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._steps.claim((tenant_id, chart_id, exclusion_id), started_at)


class InMemoryPipelineRepository:
    """``PipelineRepository`` en memoria (registros sin objetos de carta: tal cual)."""

    def __init__(self, codec: RecordCodec[PipelineRecord] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec; ``None`` guarda el registro inmutable tal cual.
        """
        self._steps: _StepStore[PipelineRecord] = _StepStore(
            codec if codec is not None else PassthroughCodec(PipelineRecord),
            lambda r: r.pipeline_id,
            lambda r, t: replace(r, status=JobStatus.RUNNING, started_at=t),
        )

    def add(self, record: PipelineRecord) -> None:
        """Guarda una tubería nueva.

        Args:
            record: Registro.
        """
        self._steps.add(record)

    def get(self, tenant_id: str, chart_id: str, pipeline_id: str) -> PipelineRecord | None:
        """Busca una tubería.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            pipeline_id: Tubería.

        Returns:
            El registro o ``None``.
        """
        return self._steps.get((tenant_id, chart_id, pipeline_id))

    def update(self, record: PipelineRecord) -> None:
        """Reemplaza una tubería existente.

        Args:
            record: Registro nuevo.
        """
        self._steps.update(record)

    def claim(
        self, tenant_id: str, chart_id: str, pipeline_id: str, started_at: datetime
    ) -> PipelineRecord | None:
        """Pasa la tubería a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            pipeline_id: Tubería.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._steps.claim((tenant_id, chart_id, pipeline_id), started_at)

    def append_step(
        self,
        tenant_id: str,
        chart_id: str,
        pipeline_id: str,
        expected_steps: int,
        step: PipelineStep,
    ) -> PipelineRecord | None:
        """Añade un paso si la tubería sigue ``running`` con ``expected_steps`` pasos.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            pipeline_id: Tubería.
            expected_steps: Pasos que debe tener ahora.
            step: Paso nuevo.

        Returns:
            El registro con el paso añadido o ``None`` si no se cumplía la condición.
        """
        key = (tenant_id, chart_id, pipeline_id)
        with self._steps.store.lock:
            current = self._steps.get(key)
            if (
                current is None
                or current.status is not JobStatus.RUNNING
                or len(current.steps) != expected_steps
            ):
                return None
            updated = replace(current, steps=(*current.steps, step))
            self._steps.store.put(key, updated)
            return updated
