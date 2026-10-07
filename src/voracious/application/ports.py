"""Puertos de la capa de aplicación (``docs/arquitectura.md``, tabla de puertos).

Todo ``get`` exige ``tenant_id``: un recurso de otro tenant es indistinguible de uno inexistente
(devuelve ``None``).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from voracious.application.records import ModelRecord, MonitoringRecord

__all__ = [
    "Clock",
    "IdGenerator",
    "JobKind",
    "JobQueue",
    "JobRequest",
    "ModelRepository",
    "MonitoringRepository",
]


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


class JobKind(StrEnum):
    """Tipo de trabajo asíncrono."""

    TRAIN = "train"
    MONITOR = "monitor"


@dataclass(frozen=True)
class JobRequest:
    """Petición de trabajo serializable (solo identificadores; los datos están en el repositorio).

    Attributes:
        kind: ``train`` (Fase I) o ``monitor`` (Fase II).
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo (el que se entrena o contra el que se monitorea).
        monitoring_id: Monitoreo, solo si ``kind == "monitor"``.
    """

    kind: JobKind
    tenant_id: str
    chart_id: str
    model_id: str
    monitoring_id: str | None = None

    def __post_init__(self) -> None:
        """Comprueba la coherencia entre ``kind`` y ``monitoring_id``.

        Raises:
            ValueError: Si un ``monitor`` no trae ``monitoring_id`` o un ``train`` lo trae.
        """
        if (self.kind is JobKind.MONITOR) != (self.monitoring_id is not None):
            msg = "monitoring_id es obligatorio en 'monitor' y no se admite en 'train'"
            raise ValueError(msg)

    @property
    def resource_id(self) -> str:
        """Recurso que el trabajo actualiza: el monitoreo o, en ``train``, el modelo."""
        return self.monitoring_id if self.monitoring_id is not None else self.model_id


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
