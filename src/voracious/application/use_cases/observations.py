"""Registro de observaciones, anotaciones de señales y eventos estructurales (ADR 0008).

``ListObservations``, ``AnnotateSignal`` y ``RegisterStructuralEvent``. Las anotaciones y los
eventos solo se añaden (D8); de una observación vale la anotación más reciente.
"""

from dataclasses import dataclass
from datetime import datetime

from voracious.application.charts import ChartRegistry, resolve_chart
from voracious.application.errors import NotASignalError, ObservationNotFoundError
from voracious.application.lifecycle import pending_proposal, utc
from voracious.application.ports import (
    Clock,
    IdGenerator,
    ModelRepository,
    ModelVersionRepository,
    ObservationRepository,
    SignalAnnotationRepository,
    StructuralEventRepository,
    VersionDecision,
    VersionStatusChange,
)
from voracious.application.records import (
    ObservationRecord,
    SignalAnnotation,
    StructuralEvent,
    VersionStatus,
)
from voracious.application.use_cases.common import get_model, ready_model

__all__ = [
    "STRUCTURAL_EVENT_NOTE",
    "AnnotateSignal",
    "AnnotatedObservation",
    "ListObservations",
    "RegisterStructuralEvent",
]

STRUCTURAL_EVENT_NOTE = "structural_event"
"""Nota con la que un evento estructural rechaza la propuesta pendiente (D5)."""


@dataclass(frozen=True)
class AnnotatedObservation:
    """Observación registrada con su anotación vigente.

    Attributes:
        observation: Observación.
        annotation: Anotación más reciente, o ``None``.
    """

    observation: ObservationRecord
    annotation: SignalAnnotation | None


@dataclass(frozen=True)
class ListObservations:
    """Lista las observaciones registradas de un modelo por rango de fechas.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        observations: Registro de observaciones.
        annotations: Anotaciones de señales.
    """

    charts: ChartRegistry
    models: ModelRepository
    observations: ObservationRepository
    annotations: SignalAnnotationRepository

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        *,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
        signals_only: bool = False,
    ) -> list[AnnotatedObservation]:
        """Devuelve las observaciones del rango (inclusivo) con su anotación vigente.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observed_from: Inicio del rango (con zona horaria), o ``None``.
            observed_to: Fin del rango (con zona horaria), o ``None``.
            signals_only: Solo las que señalaron.

        Returns:
            Las observaciones ordenadas por fecha.

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si el modelo no existe para ese tenant y esa carta.
            InvalidInputError: Si una fecha no tiene zona horaria.
        """
        resolve_chart(self.charts, chart_id)
        get_model(self.models, tenant_id, chart_id, model_id)
        records = self.observations.list(
            tenant_id,
            chart_id,
            model_id,
            observed_from=None if observed_from is None else utc(observed_from, "from"),
            observed_to=None if observed_to is None else utc(observed_to, "to"),
            signals_only=signals_only,
        )
        latest = self.annotations.latest_for(
            tenant_id, chart_id, model_id, [r.observation_id for r in records]
        )
        return [AnnotatedObservation(r, latest.get(r.observation_id)) for r in records]


@dataclass(frozen=True)
class AnnotateSignal:
    """Anota una observación con señal (Q12): causa asignable, cuál y acción.

    Attributes:
        charts: Cartas registradas.
        observations: Registro de observaciones.
        annotations: Anotaciones de señales.
        ids: Generador de identificadores.
        clock: Reloj.
    """

    charts: ChartRegistry
    observations: ObservationRepository
    annotations: SignalAnnotationRepository
    ids: IdGenerator
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        observation_id: str,
        *,
        assignable_cause: bool,
        cause: str | None = None,
        action: str | None = None,
        actor: str | None = None,
    ) -> SignalAnnotation:
        """Añade una anotación (la más reciente es la que vale).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observation_id: Observación con señal.
            assignable_cause: Causa asignable confirmada.
            cause: Cuál.
            action: Acción tomada.
            actor: Quién anota.

        Returns:
            La anotación.

        Raises:
            UnknownChartError: Si la carta no existe.
            ObservationNotFoundError: Si la observación no existe o es ajena.
            NotASignalError: Si la observación no señaló.
        """
        resolve_chart(self.charts, chart_id)
        observation = self.observations.get(tenant_id, chart_id, model_id, observation_id)
        if observation is None:
            raise ObservationNotFoundError(
                f"la observación '{observation_id}' no existe",
                details={"model_id": model_id, "observation_id": observation_id},
            )
        if not observation.signal:
            raise NotASignalError(
                "solo se anotan observaciones con señal",
                details={"observation_id": observation_id},
            )
        annotation = SignalAnnotation(
            tenant_id=tenant_id,
            chart_id=chart_id,
            model_id=model_id,
            annotation_id=self.ids.new_id(),
            observation_id=observation_id,
            assignable_cause=assignable_cause,
            cause=cause,
            action=action,
            actor=actor,
            created_at=self.clock.now(),
        )
        self.annotations.add(annotation)
        return annotation


@dataclass(frozen=True)
class RegisterStructuralEvent:
    """Registra un evento estructural: la carta pasa a «requiere nueva base» (Q7, D5).

    Si hay una propuesta pendiente, se rechaza con la nota ``structural_event``: se calculó con
    datos anteriores al evento.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        versions: Repositorio de versiones.
        events: Eventos estructurales.
        ids: Generador de identificadores.
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    versions: ModelVersionRepository
    events: StructuralEventRepository
    ids: IdGenerator
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        *,
        occurred_at: datetime,
        description: str,
        actor: str | None = None,
    ) -> StructuralEvent:
        """Registra el evento y rechaza la propuesta pendiente, si la hay.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            occurred_at: Cuándo ocurrió (con zona horaria).
            description: Descripción.
            actor: Quién lo registra.

        Returns:
            El evento.

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si el modelo no existe para ese tenant y esa carta.
            ModelNotReadyError: Si el modelo no está ``succeeded``.
            InvalidInputError: Si ``occurred_at`` no tiene zona horaria.
        """
        resolve_chart(self.charts, chart_id)
        ready_model(self.models, tenant_id, chart_id, model_id)
        now = self.clock.now()
        event = StructuralEvent(
            tenant_id=tenant_id,
            chart_id=chart_id,
            model_id=model_id,
            event_id=self.ids.new_id(),
            occurred_at=utc(occurred_at, "occurred_at"),
            description=description,
            actor=actor,
            registered_at=now,
        )
        self.events.add(event)
        proposal = pending_proposal(self.versions.list(tenant_id, chart_id, model_id))
        if proposal is not None:
            # Si otra decisión gana el CAS, la propuesta ya no está pendiente: nada que hacer.
            self.versions.apply_status_changes(
                [
                    VersionStatusChange(
                        tenant_id,
                        chart_id,
                        model_id,
                        proposal.number,
                        VersionStatus.PROPOSED,
                        VersionStatus.REJECTED,
                        VersionDecision(
                            decided_at=now, decided_by=actor, note=STRUCTURAL_EVENT_NOTE
                        ),
                    )
                ]
            )
        return event
