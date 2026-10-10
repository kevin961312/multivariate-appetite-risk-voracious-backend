"""Puertos de la capa de aplicación (``docs/arquitectura.md``, tabla de puertos).

Todo ``get`` y todo ``list`` exigen ``tenant_id``: un recurso de otro tenant es indistinguible de
uno inexistente (devuelve ``None`` o no aparece).
"""

import builtins
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from voracious.application.records import (
    ComparisonRecord,
    DatasetRecord,
    ExclusionRecord,
    FitRecord,
    LimitsRecord,
    ModelRecord,
    ModelVersion,
    MonitoringRecord,
    ObservationRecord,
    PipelineRecord,
    PipelineStep,
    ProposalRequest,
    RecalibrationRecord,
    SignalAnnotation,
    StructuralEvent,
    VersionStatus,
)

__all__ = [
    "Clock",
    "ComparisonRepository",
    "DatasetStorage",
    "DuplicateKeyError",
    "ExclusionRepository",
    "FitRepository",
    "IdGenerator",
    "JobKind",
    "JobLane",
    "JobQueue",
    "JobRequest",
    "LimitsRepository",
    "ModelRepository",
    "ModelVersionRepository",
    "MonitoringRepository",
    "ObservationRepository",
    "PipelineRepository",
    "RecalibrationRepository",
    "RecordNotFoundError",
    "SignalAnnotationRepository",
    "StructuralEventRepository",
    "VersionDecision",
    "VersionStatusChange",
    "lane_of",
]


class DuplicateKeyError(Exception):
    """Un ``add`` encontró ya un registro con la misma clave (los registros solo se añaden)."""


class RecordNotFoundError(Exception):
    """Un ``update`` no encontró el registro que debía reemplazar (error de integración)."""


class DatasetStorage(Protocol):
    """Datasets inmutables ``n x p`` (``memory`` hoy; ``local`` en disco; S3 después).

    La clave es (tenant, dataset); un dataset no pertenece a ninguna carta.
    """

    def add(self, record: DatasetRecord) -> None:
        """Guarda un dataset nuevo.

        Args:
            record: Dataset.

        Raises:
            DuplicateKeyError: Si ya existe uno con la misma clave.
        """
        ...

    def get(self, tenant_id: str, dataset_id: str) -> DatasetRecord | None:
        """Busca un dataset del tenant.

        Args:
            tenant_id: Tenant.
            dataset_id: Dataset.

        Returns:
            El dataset, o ``None`` si no existe para ese tenant.
        """
        ...


class FitRepository(Protocol):
    """Ajustes del estimador de una carta (``/fits``)."""

    def add(self, record: FitRecord) -> None:
        """Guarda un ajuste nuevo.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        ...

    def get(self, tenant_id: str, chart_id: str, fit_id: str) -> FitRecord | None:
        """Busca un ajuste.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste.

        Returns:
            El registro, o ``None`` si no existe para esa clave.
        """
        ...

    def update(self, record: FitRecord) -> None:
        """Reemplaza un ajuste existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        ...

    def claim(
        self, tenant_id: str, chart_id: str, fit_id: str, started_at: datetime
    ) -> FitRecord | None:
        """Pasa el ajuste de ``queued`` a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste.
            started_at: Instante de inicio (UTC).

        Returns:
            El registro en ``running``, o ``None`` si no existe o no estaba ``queued``.
        """
        ...

    def list_unfinished(self) -> list[FitRecord]:
        """Ajustes ``queued`` o ``running`` de todos los tenants.

        Solo lo usa ``RecoverInterruptedJobs``: con la cola en el proceso, lo que estaba en curso
        al reiniciar no lo va a terminar nadie.

        Returns:
            Los registros, en orden de creación.
        """
        ...


class LimitsRepository(Protocol):
    """Calibraciones de límites (``/limits``)."""

    def add(self, record: LimitsRecord) -> None:
        """Guarda una calibración nueva.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        ...

    def get(self, tenant_id: str, chart_id: str, limits_id: str) -> LimitsRecord | None:
        """Busca una calibración.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            limits_id: Calibración.

        Returns:
            El registro, o ``None`` si no existe para esa clave.
        """
        ...

    def update(self, record: LimitsRecord) -> None:
        """Reemplaza una calibración existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        ...

    def claim(
        self, tenant_id: str, chart_id: str, limits_id: str, started_at: datetime
    ) -> LimitsRecord | None:
        """Pasa la calibración de ``queued`` a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            limits_id: Calibración.
            started_at: Instante de inicio (UTC).

        Returns:
            El registro en ``running``, o ``None`` si no existe o no estaba ``queued``.
        """
        ...

    def list_unfinished(self) -> list[LimitsRecord]:
        """Calibraciones ``queued`` o ``running`` de todos los tenants.

        Solo lo usa ``RecoverInterruptedJobs``: con la cola en el proceso, lo que estaba en curso
        al reiniciar no lo va a terminar nadie.

        Returns:
            Los registros, en orden de creación.
        """
        ...


class ExclusionRepository(Protocol):
    """Exclusiones humanas (``/exclusions``)."""

    def add(self, record: ExclusionRecord) -> None:
        """Guarda una exclusión nueva.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        ...

    def get(self, tenant_id: str, chart_id: str, exclusion_id: str) -> ExclusionRecord | None:
        """Busca una exclusión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            exclusion_id: Exclusión.

        Returns:
            El registro, o ``None`` si no existe para esa clave.
        """
        ...

    def update(self, record: ExclusionRecord) -> None:
        """Reemplaza una exclusión existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        ...

    def claim(
        self, tenant_id: str, chart_id: str, exclusion_id: str, started_at: datetime
    ) -> ExclusionRecord | None:
        """Pasa la exclusión de ``queued`` a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            exclusion_id: Exclusión.
            started_at: Instante de inicio (UTC).

        Returns:
            El registro en ``running``, o ``None`` si no existe o no estaba ``queued``.
        """
        ...

    def list_unfinished(self) -> list[ExclusionRecord]:
        """Exclusiones ``queued`` o ``running`` de todos los tenants.

        Solo lo usa ``RecoverInterruptedJobs``: con la cola en el proceso, lo que estaba en curso
        al reiniciar no lo va a terminar nadie.

        Returns:
            Los registros, en orden de creación.
        """
        ...


class PipelineRepository(Protocol):
    """Tuberías (``/pipelines``)."""

    def add(self, record: PipelineRecord) -> None:
        """Guarda una tubería nueva.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        ...

    def get(self, tenant_id: str, chart_id: str, pipeline_id: str) -> PipelineRecord | None:
        """Busca una tubería.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            pipeline_id: Tubería.

        Returns:
            El registro, o ``None`` si no existe para esa clave.
        """
        ...

    def update(self, record: PipelineRecord) -> None:
        """Reemplaza una tubería existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        ...

    def claim(
        self, tenant_id: str, chart_id: str, pipeline_id: str, started_at: datetime
    ) -> PipelineRecord | None:
        """Pasa la tubería de ``queued`` a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            pipeline_id: Tubería.
            started_at: Instante de inicio (UTC).

        Returns:
            El registro en ``running``, o ``None`` si no existe o no estaba ``queued``.
        """
        ...

    def append_step(
        self,
        tenant_id: str,
        chart_id: str,
        pipeline_id: str,
        expected_steps: int,
        step: PipelineStep,
    ) -> PipelineRecord | None:
        """Añade un paso si la tubería sigue ``running`` con ``expected_steps`` pasos (atómico).

        Dos avances concurrentes de la misma tubería: solo uno añade el paso siguiente.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            pipeline_id: Tubería.
            expected_steps: Número de pasos que debe tener ahora.
            step: Paso nuevo.

        Returns:
            El registro con el paso añadido, o ``None`` si no se cumplía la condición.
        """
        ...

    def list_unfinished(self) -> list[PipelineRecord]:
        """Tuberías ``queued`` o ``running`` de todos los tenants.

        Solo lo usa ``RecoverInterruptedJobs``: con la cola en el proceso, lo que estaba en curso
        al reiniciar no lo va a terminar nadie.

        Returns:
            Los registros, en orden de creación.
        """
        ...


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

        Raises:
            RecordNotFoundError: Si no existe un modelo con esa clave.
        """
        ...

    def claim(
        self, tenant_id: str, chart_id: str, model_id: str, started_at: datetime
    ) -> ModelRecord | None:
        """Pasa el modelo de ``queued`` a ``running`` de forma atómica (comparar-y-cambiar).

        Dos llamadas concurrentes sobre el mismo modelo: solo una lo obtiene.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            started_at: Instante de inicio (UTC); va a ``started_at``.

        Returns:
            El registro ya en ``running``, o ``None`` si no existe o no estaba ``queued``.
        """
        ...

    def list_unfinished(self) -> list[ModelRecord]:
        """Modelos ``queued`` o ``running`` de todos los tenants.

        Solo lo usa ``RecoverInterruptedJobs``: con la cola en el proceso, lo que estaba en curso
        al reiniciar no lo va a terminar nadie.

        Returns:
            Los registros, en orden de creación.
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

        Raises:
            RecordNotFoundError: Si no existe un monitoreo con esa clave.
        """
        ...

    def claim(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        monitoring_id: str,
        started_at: datetime,
    ) -> MonitoringRecord | None:
        """Pasa el monitoreo de ``queued`` a ``running`` de forma atómica (comparar-y-cambiar).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            monitoring_id: Monitoreo.
            started_at: Instante de inicio (UTC).

        Returns:
            El registro ya en ``running``, o ``None`` si no existe o no estaba ``queued``.
        """
        ...

    def list_unfinished(self) -> list[MonitoringRecord]:
        """Monitoreos ``queued`` o ``running`` de todos los tenants.

        Solo lo usa ``RecoverInterruptedJobs``: con la cola en el proceso, lo que estaba en curso
        al reiniciar no lo va a terminar nadie.

        Returns:
            Los registros, en orden de creación.
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

    def add_proposal_if_none(self, version: ModelVersion) -> bool:
        """Añade una versión ``proposed`` solo si el modelo no tiene otra propuesta (atómico, D6).

        Args:
            version: Versión en estado ``proposed``.

        Returns:
            ``True`` si se añadió; ``False`` si ya había una propuesta sin resolver.

        Raises:
            ValueError: Si ``version`` no está ``proposed``.
            DuplicateKeyError: Si ya existe una versión con la misma clave.
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

    def add_if_none_in_progress(self, record: RecalibrationRecord) -> bool:
        """Guarda la recalibración solo si el modelo no tiene otra en curso (atómico, D6).

        «En curso» es ``queued`` o ``running``.

        Args:
            record: Registro a guardar.

        Returns:
            ``True`` si se guardó; ``False`` si ya había una en curso para el modelo.

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

        Raises:
            RecordNotFoundError: Si no existe una recalibración con esa clave.
        """
        ...

    def claim(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        recalibration_id: str,
        started_at: datetime,
    ) -> RecalibrationRecord | None:
        """Pasa la recalibración de ``queued`` a ``running`` de forma atómica (comparar-y-cambiar).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.
            started_at: Instante de inicio (UTC).

        Returns:
            El registro ya en ``running``, o ``None`` si no existe o no estaba ``queued``.
        """
        ...

    def find(
        self, tenant_id: str, chart_id: str, recalibration_id: str
    ) -> RecalibrationRecord | None:
        """Busca una recalibración solo por su id (los pasos sueltos no conocen el modelo).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            recalibration_id: Recalibración.

        Returns:
            El registro, o ``None`` si no existe para ese tenant y esa carta.
        """
        ...

    def request_proposal(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        recalibration_id: str,
        proposal: ProposalRequest,
    ) -> RecalibrationRecord | None:
        """Guarda la petición de propuesta si la recalibración sigue ``running`` sin otra (atómico).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.
            proposal: Petición (``queued``).

        Returns:
            El registro con la petición, o ``None`` si no estaba ``running`` o ya tenía una.
        """
        ...

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
            finished_at: Instante de la cancelación (UTC).

        Returns:
            El registro ``cancelled``, o ``None`` si no cumplía la condición.
        """
        ...

    def claim_proposal(
        self, tenant_id: str, chart_id: str, model_id: str, recalibration_id: str
    ) -> RecalibrationRecord | None:
        """Pasa la petición de propuesta de ``queued`` a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.

        Returns:
            El registro con la petición en ``running``, o ``None`` si no había una ``queued``.
        """
        ...

    def list_unfinished(self) -> builtins.list[RecalibrationRecord]:
        """Recalibraciones ``queued`` o ``running`` de todos los tenants.

        Solo lo usa ``RecoverInterruptedJobs``: con la cola en el proceso, lo que estaba en curso
        al reiniciar no lo va a terminar nadie.

        Returns:
            Los registros, en orden de creación.
        """
        ...


class ComparisonRepository(Protocol):
    """Comparaciones de bases (``/comparisons``), hijas de un modelo."""

    def add(self, record: ComparisonRecord) -> None:
        """Guarda una comparación nueva.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        ...

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
            El registro, o ``None`` si no existe para esa clave.
        """
        ...

    def update(self, record: ComparisonRecord) -> None:
        """Reemplaza una comparación existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        ...

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
            started_at: Instante de inicio (UTC).

        Returns:
            El registro en ``running``, o ``None`` si no existe o no estaba ``queued``.
        """
        ...

    def list_unfinished(self) -> list[ComparisonRecord]:
        """Comparaciones ``queued`` o ``running`` de todos los tenants.

        Solo lo usa ``RecoverInterruptedJobs``: con la cola en el proceso, lo que estaba en curso
        al reiniciar no lo va a terminar nadie.

        Returns:
            Los registros, en orden de creación.
        """
        ...


class JobKind(StrEnum):
    """Tipo de trabajo asíncrono (Paso 3: un trabajo por paso de cómputo encadenable).

    La recalibración en modo tubería es una tubería más (``PIPELINE``) que encadena los pasos
    (vuelta 3.4); por eso ya no hay un tipo propio de recalibración.
    """

    MRCD_FIT = "mrcd_fit"
    """Ajuste MRCD suelto (``/fits``)."""

    LIMITS = "limits"
    """Calibración de límites bootstrap sobre un ajuste."""

    EXCLUSION = "exclusion"
    """Exclusión humana de las filas con causa asignable (sin ajuste)."""

    MODEL_ASSEMBLY = "model_assembly"
    """Ensamblado de un modelo a partir de referencias (el recurso es el modelo)."""

    SCORE = "score"
    """Puntuación de observaciones de Fase II contra un modelo."""

    COMPARISON = "comparison"
    """Comparación de bases (cambio en S y μ); el recurso es la comparación."""

    VERSION_PROPOSAL = "version_proposal"
    """Propuesta de una versión nueva de un modelo; el recurso es la recalibración."""

    PIPELINE = "pipeline"
    """Orquestación de varios pasos encadenados (Fase I o recalibración)."""


class JobLane(StrEnum):
    """Carril de la cola: trabajos de coste parecido comparten un grupo de trabajadores.

    Separar carriles evita que un trabajo largo (una calibración bootstrap de minutos) bloquee a
    uno corto (puntuar un lote).
    """

    ESTIMATION = "estimation"
    """Ajustes del estimador."""

    CALIBRATION = "calibration"
    """Calibraciones con réplicas y comparaciones (lo más costoso)."""

    LIGHT = "light"
    """Trabajos cortos: excluir filas, puntuar, ensamblar, proponer versión."""

    ORCHESTRATION = "orchestration"
    """Tuberías que encadenan otros pasos."""


_LANES: dict[JobKind, JobLane] = {
    JobKind.MRCD_FIT: JobLane.ESTIMATION,
    JobKind.LIMITS: JobLane.CALIBRATION,
    JobKind.COMPARISON: JobLane.CALIBRATION,
    JobKind.EXCLUSION: JobLane.LIGHT,
    JobKind.MODEL_ASSEMBLY: JobLane.LIGHT,
    JobKind.SCORE: JobLane.LIGHT,
    JobKind.VERSION_PROPOSAL: JobLane.LIGHT,
    JobKind.PIPELINE: JobLane.ORCHESTRATION,
}


def lane_of(kind: JobKind) -> JobLane:
    """Carril de la cola de un tipo de trabajo.

    Args:
        kind: Tipo de trabajo.

    Returns:
        Su carril.
    """
    return _LANES[kind]


_MODEL_REQUIRED = frozenset({JobKind.SCORE, JobKind.VERSION_PROPOSAL, JobKind.COMPARISON})
"""Trabajos sobre un recurso hijo de un modelo: ``model_id`` es obligatorio."""


@dataclass(frozen=True)
class JobRequest:
    """Petición de trabajo serializable (solo identificadores; los datos están en el repositorio).

    Attributes:
        kind: Tipo de trabajo.
        tenant_id: Tenant.
        scope: Espacio del recurso: la carta (``t2mrcd``…) a la que pertenece.
        resource_id: Recurso que el trabajo actualiza (el ajuste en ``mrcd_fit``, los límites en
            ``limits``, la exclusión en ``exclusion``, el modelo en ``model_assembly``, la
            puntuación en ``score``, la tubería en ``pipeline``, la comparación en
            ``comparison`` y la recalibración en ``version_proposal``).
        model_id: Modelo del que cuelga el recurso: obligatorio en ``score``,
            ``comparison`` y ``version_proposal``; ``None`` en el resto (o el recurso es el
            modelo, o no cuelga de ninguno).
    """

    kind: JobKind
    tenant_id: str
    scope: str
    resource_id: str
    model_id: str | None = None

    def __post_init__(self) -> None:
        """Comprueba los identificadores y su coherencia con ``kind``.

        Raises:
            ValueError: Si un identificador está vacío o ``model_id`` no cumple la regla de su
                tipo.
        """
        for name in ("tenant_id", "scope", "resource_id"):
            if not getattr(self, name):
                msg = f"'{name}' no puede estar vacío"
                raise ValueError(msg)
        if self.kind in _MODEL_REQUIRED and not self.model_id:
            msg = f"model_id es obligatorio en '{self.kind}'"
            raise ValueError(msg)
        if self.kind not in _MODEL_REQUIRED and self.model_id is not None:
            msg = f"model_id no se admite en '{self.kind}'"
            raise ValueError(msg)


class JobQueue(Protocol):
    """Cola de trabajos (``InlineJobQueue`` hoy, ``CeleryJobQueue`` después)."""

    def enqueue(self, job: JobRequest) -> None:
        """Encola un trabajo y vuelve enseguida, sin esperar a que se ejecute.

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
