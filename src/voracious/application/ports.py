"""Puertos de la capa de aplicación (``docs/arquitectura.md``, tabla de puertos).

Todo ``get`` y todo ``list`` exigen ``tenant_id``: un recurso de otro tenant es indistinguible de
uno inexistente (devuelve ``None`` o no aparece).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

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

__all__ = [
    "Clock",
    "DuplicateKeyError",
    "IdGenerator",
    "JobKind",
    "JobQueue",
    "JobRequest",
    "ModelRepository",
    "ModelVersionRepository",
    "MonitoringRepository",
    "ObservationRepository",
    "RecalibrationRepository",
    "SignalAnnotationRepository",
    "StructuralEventRepository",
    "VersionDecision",
    "VersionStatusChange",
]


class DuplicateKeyError(Exception):
    """Un ``add`` encontró ya un registro con la misma clave (los registros solo se añaden)."""


class ModelRepository(Protocol):
    """Persistencia de modelos de Fase I."""

    def add(self, record: ModelRecord) -> None:
        """Guarda un modelo nuevo.

        Args:
            record: Registro a guardar.
        """
        ...

    def get(self, tenant_id: str, chart_id: str, model_id: str) -> ModelRecord | None:
        """Busca un modelo del tenant y la carta dados.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Identificador del modelo.

        Returns:
            El registro, o ``None`` si no existe para ese tenant y esa carta.
        """
        ...

    def update(self, record: ModelRecord) -> None:
        """Reemplaza un modelo existente (misma clave tenant/carta/id).

        Args:
            record: Registro nuevo.
        """
        ...


class MonitoringRepository(Protocol):
    """Persistencia de monitoreos de Fase II."""

    def add(self, record: MonitoringRecord) -> None:
        """Guarda un monitoreo nuevo.

        Args:
            record: Registro a guardar.
        """
        ...

    def get(
        self, tenant_id: str, chart_id: str, model_id: str, monitoring_id: str
    ) -> MonitoringRecord | None:
        """Busca un monitoreo del tenant, la carta y el modelo dados.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            monitoring_id: Identificador del monitoreo.

        Returns:
            El registro, o ``None`` si no existe para esa clave.
        """
        ...

    def update(self, record: MonitoringRecord) -> None:
        """Reemplaza un monitoreo existente.

        Args:
            record: Registro nuevo.
        """
        ...


@dataclass(frozen=True)
class VersionDecision:
    """Datos de la decisión humana que acompañan a un cambio de estado de una versión.

    Attributes:
        decided_at: Instante de la decisión (UTC); va a ``approved_at`` o ``rejected_at``.
        decided_by: Quién decidió (``None`` si fue automático, p. ej. un evento estructural).
        note: Nota de la decisión.
        effective_from: Desde cuándo rige (solo al aprobar).
    """

    decided_at: datetime
    decided_by: str | None
    note: str | None
    effective_from: datetime | None = None


@dataclass(frozen=True)
class VersionStatusChange:
    """Cambio de estado de una versión con el estado esperado (comparar-y-cambiar).

    Attributes:
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo.
        number: Versión.
        expected: Estado que debe tener ahora.
        new: Estado nuevo.
        decision: Datos de la decisión que se guardan con el cambio; ``None`` deja los de la
            versión como estaban (p. ej. ``active → superseded``).
    """

    tenant_id: str
    chart_id: str
    model_id: str
    number: int
    expected: VersionStatus
    new: VersionStatus
    decision: VersionDecision | None = None


class ModelVersionRepository(Protocol):
    """Versiones inmutables del modelo de una carta (append-only, ADR 0008).

    El contenido de una versión no se modifica por ningún método; solo su estado y los datos de
    la decisión, y solo con ``apply_status_changes``.
    """

    def add(self, version: ModelVersion) -> None:
        """Añade una versión nueva.

        Args:
            version: Versión a guardar.

        Raises:
            DuplicateKeyError: Si ya existe una versión con la misma clave
                (tenant, carta, modelo, número).
        """
        ...

    def get(self, tenant_id: str, chart_id: str, model_id: str, number: int) -> ModelVersion | None:
        """Busca una versión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            number: Número de versión.

        Returns:
            La versión, o ``None`` si no existe para esa clave.
        """
        ...

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[ModelVersion]:
        """Versiones del modelo ordenadas por número.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            Las versiones (vacía si no hay ninguna para esa clave).
        """
        ...

    def apply_status_changes(self, changes: Sequence[VersionStatusChange]) -> bool:
        """Aplica varios cambios de estado de forma atómica (comparar-y-cambiar).

        Si alguna versión no existe o no está en su estado ``expected``, no se aplica ninguno.

        Args:
            changes: Cambios a aplicar.

        Returns:
            ``True`` si se aplicaron todos; ``False`` si no se aplicó ninguno.
        """
        ...


class ObservationRepository(Protocol):
    """Observaciones de Fase II puntuadas (registro append-only)."""

    def add_many(self, records: Sequence[ObservationRecord]) -> None:
        """Añade observaciones nuevas.

        Args:
            records: Observaciones a guardar.

        Raises:
            DuplicateKeyError: Si alguna ya existe (no se guarda ninguna).
        """
        ...

    def get(
        self, tenant_id: str, chart_id: str, model_id: str, observation_id: str
    ) -> ObservationRecord | None:
        """Busca una observación.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observation_id: Observación.

        Returns:
            La observación, o ``None`` si no existe para esa clave.
        """
        ...

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
        """Observaciones del modelo en un rango de fechas (ambos extremos inclusivos).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observed_from: Inicio del rango, o ``None`` sin límite.
            observed_to: Fin del rango, o ``None`` sin límite.
            signals_only: Solo las que señalaron.

        Returns:
            Las observaciones ordenadas por ``observed_at`` y, a igualdad, por orden de registro.
        """
        ...

    def max_observed_at(self, tenant_id: str, chart_id: str, model_id: str) -> datetime | None:
        """Fecha de la última observación puntuada del modelo.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            La mayor ``observed_at``, o ``None`` si no hay observaciones.
        """
        ...

    def count_scored_with(
        self, tenant_id: str, chart_id: str, model_id: str, version_number: int
    ) -> int:
        """Número de observaciones puntuadas con una versión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            version_number: Versión.

        Returns:
            El recuento.
        """
        ...


class SignalAnnotationRepository(Protocol):
    """Anotaciones de señales (append-only; vale la más reciente)."""

    def add(self, annotation: SignalAnnotation) -> None:
        """Añade una anotación.

        Args:
            annotation: Anotación a guardar.

        Raises:
            DuplicateKeyError: Si ya existe una con el mismo identificador.
        """
        ...

    def latest_for(
        self, tenant_id: str, chart_id: str, model_id: str, observation_ids: Sequence[str]
    ) -> dict[str, SignalAnnotation]:
        """Anotación más reciente de cada observación pedida que tenga alguna.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observation_ids: Observaciones.

        Returns:
            ``observation_id → anotación`` (solo las que tienen alguna).
        """
        ...

    def history(
        self, tenant_id: str, chart_id: str, model_id: str, observation_id: str
    ) -> list[SignalAnnotation]:
        """Todas las anotaciones de una observación, de la más antigua a la más reciente.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observation_id: Observación.

        Returns:
            Las anotaciones.
        """
        ...


class StructuralEventRepository(Protocol):
    """Eventos estructurales (append-only)."""

    def add(self, event: StructuralEvent) -> None:
        """Añade un evento.

        Args:
            event: Evento a guardar.

        Raises:
            DuplicateKeyError: Si ya existe uno con el mismo identificador.
        """
        ...

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[StructuralEvent]:
        """Eventos del modelo ordenados por ``occurred_at`` y, a igualdad, por registro.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            Los eventos.
        """
        ...


class RecalibrationRepository(Protocol):
    """Trabajos de recalibración."""

    def add(self, record: RecalibrationRecord) -> None:
        """Guarda una recalibración nueva.

        Args:
            record: Registro a guardar.

        Raises:
            DuplicateKeyError: Si ya existe una con la misma clave.
        """
        ...

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
            El registro, o ``None`` si no existe para esa clave.
        """
        ...

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[RecalibrationRecord]:
        """Recalibraciones del modelo, en orden de creación.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            Los registros.
        """
        ...

    def update(self, record: RecalibrationRecord) -> None:
        """Reemplaza una recalibración existente.

        Args:
            record: Registro nuevo.
        """
        ...


class JobKind(StrEnum):
    """Tipo de trabajo asíncrono."""

    TRAIN = "train"
    MONITOR = "monitor"
    RECALIBRATE = "recalibrate"


@dataclass(frozen=True)
class JobRequest:
    """Petición de trabajo serializable (solo identificadores; los datos están en el repositorio).

    Attributes:
        kind: ``train`` (Fase I), ``monitor`` (Fase II) o ``recalibrate``.
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo (el que se entrena, contra el que se monitorea o que se recalibra).
        monitoring_id: Monitoreo, solo si ``kind == "monitor"``.
        recalibration_id: Recalibración, solo si ``kind == "recalibrate"``.
    """

    kind: JobKind
    tenant_id: str
    chart_id: str
    model_id: str
    monitoring_id: str | None = None
    recalibration_id: str | None = None

    def __post_init__(self) -> None:
        """Comprueba la coherencia entre ``kind`` y los identificadores opcionales.

        Raises:
            ValueError: Si ``monitoring_id`` no está exactamente en ``monitor`` o
                ``recalibration_id`` no está exactamente en ``recalibrate``.
        """
        if (self.kind is JobKind.MONITOR) != (self.monitoring_id is not None):
            msg = "monitoring_id es obligatorio en 'monitor' y no se admite en otro tipo"
            raise ValueError(msg)
        if (self.kind is JobKind.RECALIBRATE) != (self.recalibration_id is not None):
            msg = "recalibration_id es obligatorio en 'recalibrate' y no se admite en otro tipo"
            raise ValueError(msg)

    @property
    def resource_id(self) -> str:
        """Recurso que el trabajo actualiza: el monitoreo, la recalibración o el modelo."""
        if self.monitoring_id is not None:
            return self.monitoring_id
        if self.recalibration_id is not None:
            return self.recalibration_id
        return self.model_id


class JobQueue(Protocol):
    """Cola de trabajos (``InlineJobQueue`` hoy, ``CeleryJobQueue`` después)."""

    def enqueue(self, job: JobRequest) -> None:
        """Encola un trabajo.

        Args:
            job: Petición serializable.
        """
        ...


class IdGenerator(Protocol):
    """Generador de identificadores de recursos."""

    def new_id(self) -> str:
        """Devuelve un identificador nuevo y único."""
        ...


class Clock(Protocol):
    """Reloj del sistema (inyectable en tests)."""

    def now(self) -> datetime:
        """Instante actual con zona horaria UTC."""
        ...
