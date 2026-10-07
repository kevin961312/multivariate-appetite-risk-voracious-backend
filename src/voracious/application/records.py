"""Registros persistentes de modelos (Fase I) y monitoreos (Fase II), comunes a todas las cartas.

Los registros son inmutables; cada transición de estado crea uno nuevo con
``dataclasses.replace`` y se guarda con ``update``. El contenido propio de cada carta
(parámetros, modelo, resultado) se guarda como ``object``: solo la carta lo interpreta.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from voracious.domain.common import FloatMatrix

__all__ = ["ErrorInfo", "JobStatus", "ModelRecord", "MonitoringRecord"]


class JobStatus(StrEnum):
    """Estado de un trabajo asíncrono (ADR 0003, ADR 0005)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class ErrorInfo:
    """Error de un trabajo ``failed``, sin trazas.

    Attributes:
        code: Código estable (p. ej. ``T2MRCD_DECISION_PENDING``).
        message: Mensaje legible.
        details: Datos adicionales serializables.
    """

    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class ModelRecord:
    """Modelo de Fase I de un tenant.

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta (``t2mrcd``…).
        model_id: Identificador del modelo.
        status: Estado del trabajo.
        params: Parámetros de la carta.
        training_data: Histórico ``n x p`` con el que se ajusta.
        created_at: Instante de creación (UTC).
        started_at: Instante en que pasó a ``running`` (UTC).
        finished_at: Instante en que terminó (UTC).
        model: Modelo de la carta si ``succeeded``.
        error: Error si ``failed``.
    """

    tenant_id: str
    chart_id: str
    model_id: str
    status: JobStatus
    params: object
    training_data: FloatMatrix
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    model: object | None = None
    error: ErrorInfo | None = None


@dataclass(frozen=True, eq=False)
class MonitoringRecord:
    """Monitoreo de Fase II contra un modelo.

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        model_id: Modelo contra el que se puntúa.
        monitoring_id: Identificador del monitoreo.
        status: Estado del trabajo.
        observations: Observaciones nuevas ``m x p``.
        created_at: Instante de creación (UTC).
        started_at: Instante en que pasó a ``running`` (UTC).
        finished_at: Instante en que terminó (UTC).
        result: Resultado de la carta si ``succeeded``.
        error: Error si ``failed``.
    """

    tenant_id: str
    chart_id: str
    model_id: str
    monitoring_id: str
    status: JobStatus
    observations: FloatMatrix
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: object | None = None
    error: ErrorInfo | None = None
