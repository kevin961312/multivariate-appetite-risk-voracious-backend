"""Versiones del modelo y estado de la carta (ADR 0008).

``ListVersions``, ``GetVersion``, ``ApproveVersion``, ``RejectVersion`` y ``GetChartStatus``. Las
versiones son inmutables; aprobar o rechazar solo cambia su estado con comparar-y-cambiar (CAS),
de modo que dos decisiones concurrentes sobre la misma propuesta no pueden ganar las dos.
"""

from dataclasses import dataclass
from datetime import datetime

from voracious.application.charts import ChartRegistry, resolve_chart
from voracious.application.errors import (
    EffectiveFromNotAfterScoredError,
    VersionNotProposedError,
)
from voracious.application.lifecycle import (
    ChartStatusView,
    derive_chart_state,
    pending_proposal,
    revalidation_due,
    revalidation_due_at,
    unresolved_structural_event,
    utc,
)
from voracious.application.ports import (
    Clock,
    ModelRepository,
    ModelVersionRepository,
    ObservationRepository,
    StructuralEventRepository,
    VersionDecision,
    VersionStatusChange,
)
from voracious.application.records import ModelVersion, VersionStatus
from voracious.application.use_cases.common import (
    get_model,
    get_version,
    ready_model,
    require_active_version,
)

__all__ = ["ApproveVersion", "GetChartStatus", "GetVersion", "ListVersions", "RejectVersion"]


def _require_proposed(version: ModelVersion) -> None:
    """Comprueba que la versión sea una propuesta sin resolver.

    Args:
        version: Versión.

    Raises:
        VersionNotProposedError: Si no está ``proposed``.
    """
    if version.status is not VersionStatus.PROPOSED:
        raise VersionNotProposedError(
            f"la versión {version.number} no es una propuesta",
            details={"version": version.number, "status": str(version.status)},
        )


@dataclass(frozen=True)
class ListVersions:
    """Lista las versiones de un modelo.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        versions: Repositorio de versiones.
    """

    charts: ChartRegistry
    models: ModelRepository
    versions: ModelVersionRepository

    def execute(self, tenant_id: str, chart_id: str, model_id: str) -> list[ModelVersion]:
        """Devuelve las versiones ordenadas por número.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            Las versiones.

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si el modelo no existe para ese tenant y esa carta.
        """
        resolve_chart(self.charts, chart_id)
        get_model(self.models, tenant_id, chart_id, model_id)
        return self.versions.list(tenant_id, chart_id, model_id)


@dataclass(frozen=True)
class GetVersion:
    """Consulta una versión de un modelo.

    Attributes:
        charts: Cartas registradas.
        versions: Repositorio de versiones.
    """

    charts: ChartRegistry
    versions: ModelVersionRepository

    def execute(self, tenant_id: str, chart_id: str, model_id: str, number: int) -> ModelVersion:
        """Devuelve la versión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            number: Número de versión.

        Returns:
            La versión.

        Raises:
            UnknownChartError: Si la carta no existe.
            VersionNotFoundError: Si no existe para esa clave.
        """
        resolve_chart(self.charts, chart_id)
        return get_version(self.versions, tenant_id, chart_id, model_id, number)


@dataclass(frozen=True)
class ApproveVersion:
    """Aprueba una propuesta: pasa a ``active`` y la vigente a ``superseded`` (CAS).

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        versions: Repositorio de versiones.
        observations: Registro de observaciones (para la no retroactividad).
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    versions: ModelVersionRepository
    observations: ObservationRepository
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        number: int,
        *,
        effective_from: datetime | None = None,
        note: str | None = None,
        actor: str | None = None,
    ) -> ModelVersion:
        """Aprueba la propuesta ``number``.

        ``effective_from`` (por defecto, ahora) debe ser posterior a la última observación ya
        puntuada (Q6) y a la entrada en vigor de la versión vigente.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            number: Versión propuesta.
            effective_from: Desde cuándo rige (con zona horaria); ``None`` = ahora.
            note: Nota de la aprobación.
            actor: Quién aprueba.

        Returns:
            La versión aprobada.

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si el modelo no existe para ese tenant y esa carta.
            VersionNotFoundError: Si la versión no existe.
            VersionNotProposedError: Si no es una propuesta o otra decisión concurrente ganó.
            EffectiveFromNotAfterScoredError: Si ``effective_from`` es retroactivo.
            InvalidInputError: Si ``effective_from`` no tiene zona horaria.
        """
        resolve_chart(self.charts, chart_id)
        get_model(self.models, tenant_id, chart_id, model_id)
        version = get_version(self.versions, tenant_id, chart_id, model_id, number)
        _require_proposed(version)
        now = self.clock.now()
        start = now if effective_from is None else utc(effective_from, "effective_from")
        last_scored = self.observations.max_observed_at(tenant_id, chart_id, model_id)
        if last_scored is not None and start <= last_scored:
            raise EffectiveFromNotAfterScoredError(
                "'effective_from' debe ser posterior a la última observación puntuada",
                details={
                    "effective_from": start.isoformat(),
                    "last_scored": last_scored.isoformat(),
                },
            )
        active = require_active_version(self.versions.list(tenant_id, chart_id, model_id), model_id)
        if active.effective_from is not None and start <= active.effective_from:
            raise EffectiveFromNotAfterScoredError(
                "'effective_from' debe ser posterior a la entrada en vigor de la versión vigente",
                details={
                    "effective_from": start.isoformat(),
                    "active_effective_from": active.effective_from.isoformat(),
                    "reason": "not_after_active",
                },
            )
        decision = VersionDecision(
            decided_at=now, decided_by=actor, note=note, effective_from=start
        )
        applied = self.versions.apply_status_changes(
            [
                VersionStatusChange(
                    tenant_id,
                    chart_id,
                    model_id,
                    number,
                    VersionStatus.PROPOSED,
                    VersionStatus.ACTIVE,
                    decision,
                ),
                VersionStatusChange(
                    tenant_id,
                    chart_id,
                    model_id,
                    active.number,
                    VersionStatus.ACTIVE,
                    VersionStatus.SUPERSEDED,
                ),
            ]
        )
        if not applied:
            raise VersionNotProposedError(
                f"la versión {number} cambió de estado durante la aprobación",
                details={"version": number, "reason": "concurrent_change"},
            )
        return get_version(self.versions, tenant_id, chart_id, model_id, number)


@dataclass(frozen=True)
class RejectVersion:
    """Rechaza una propuesta (CAS ``proposed → rejected``).

    Attributes:
        charts: Cartas registradas.
        versions: Repositorio de versiones.
        clock: Reloj.
    """

    charts: ChartRegistry
    versions: ModelVersionRepository
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        number: int,
        *,
        note: str | None = None,
        actor: str | None = None,
    ) -> ModelVersion:
        """Rechaza la propuesta ``number``.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            number: Versión propuesta.
            note: Motivo.
            actor: Quién rechaza.

        Returns:
            La versión rechazada.

        Raises:
            UnknownChartError: Si la carta no existe.
            VersionNotFoundError: Si la versión no existe.
            VersionNotProposedError: Si no es una propuesta o otra decisión concurrente ganó.
        """
        resolve_chart(self.charts, chart_id)
        version = get_version(self.versions, tenant_id, chart_id, model_id, number)
        _require_proposed(version)
        decision = VersionDecision(decided_at=self.clock.now(), decided_by=actor, note=note)
        change = VersionStatusChange(
            tenant_id,
            chart_id,
            model_id,
            number,
            VersionStatus.PROPOSED,
            VersionStatus.REJECTED,
            decision,
        )
        if not self.versions.apply_status_changes([change]):
            raise VersionNotProposedError(
                f"la versión {number} cambió de estado durante el rechazo",
                details={"version": number, "reason": "concurrent_change"},
            )
        return get_version(self.versions, tenant_id, chart_id, model_id, number)


@dataclass(frozen=True)
class GetChartStatus:
    """Estado de la carta y sus avisos, evaluados al consultar (D10).

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        versions: Repositorio de versiones.
        observations: Registro de observaciones.
        events: Eventos estructurales.
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    versions: ModelVersionRepository
    observations: ObservationRepository
    events: StructuralEventRepository
    clock: Clock

    def execute(self, tenant_id: str, chart_id: str, model_id: str) -> ChartStatusView:
        """Calcula el estado por precedencia y los avisos.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            El estado de la carta.

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si el modelo no existe para ese tenant y esa carta.
            ModelNotReadyError: Si el modelo no está ``succeeded`` o no tiene versión vigente.
        """
        resolve_chart(self.charts, chart_id)
        model = ready_model(self.models, tenant_id, chart_id, model_id)
        versions = self.versions.list(tenant_id, chart_id, model_id)
        active = require_active_version(versions, model_id)
        proposal = pending_proposal(versions)
        event = unresolved_structural_event(
            self.events.list(tenant_id, chart_id, model_id), versions
        )
        n_scored = self.observations.count_scored_with(tenant_id, chart_id, model_id, active.number)
        policy = model.lifecycle_policy
        due = revalidation_due(policy, active, self.clock.now(), n_scored)
        flags = (
            ("requires_new_base", event is not None),
            ("proposal_pending", proposal is not None),
            ("revalidation_due", due),
        )
        return ChartStatusView(
            status=derive_chart_state(
                requires_new_base=event is not None,
                proposal_pending=proposal is not None,
                revalidation_is_due=due,
                active=active,
            ),
            active_version=active.number,
            proposed_version=None if proposal is None else proposal.number,
            unresolved_event_id=None if event is None else event.event_id,
            revalidation_due=due,
            revalidation_due_at=revalidation_due_at(policy, active),
            observations_since_active=n_scored,
            notices=tuple(name for name, on in flags if on),
        )
