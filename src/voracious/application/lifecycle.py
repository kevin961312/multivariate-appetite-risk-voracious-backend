"""Reglas puras del ciclo de vida de una carta (ADR 0008), sin puertos ni efectos.

Los casos de uso leen versiones, eventos y observaciones de los repositorios y deciden con estas
funciones: qué versión rige en una fecha, si la carta requiere nueva base, si venció la
revalidación periódica y en qué estado está. Todas las fechas son UTC con zona horaria.
"""

import calendar
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np

from voracious.application.records import (
    ExclusionReason,
    LifecyclePolicy,
    ModelVersion,
    StructuralEvent,
    VersionStatus,
)
from voracious.domain.common import (
    FloatMatrix,
    InvalidInputError,
    RecalibrationDecision,
    RowDisposition,
)

__all__ = [
    "ChartStatus",
    "ChartStatusView",
    "active_version",
    "add_months",
    "base_content_hash",
    "derive_chart_state",
    "exclusion_reason",
    "pending_proposal",
    "revalidation_due",
    "revalidation_due_at",
    "unresolved_structural_event",
    "utc",
    "version_for",
]

_APPROVED = frozenset({VersionStatus.ACTIVE, VersionStatus.SUPERSEDED})
"""Estados de las versiones que rigen (o rigieron) alguna fecha."""


class ChartStatus(StrEnum):
    """Estado de la carta, por precedencia (``docs/arquitectura.md``, ADR 0008)."""

    REQUIRES_NEW_BASE = "requires_new_base"
    """Hay un evento estructural sin una versión aprobada que lo resuelva (Q7)."""

    PROPOSAL_PENDING = "proposal_pending"
    """Hay una propuesta sin aprobar ni rechazar."""

    REVALIDATION_DUE = "revalidation_due"
    """Venció la revalidación periódica."""

    STARTUP = "startup"
    """Vigila la versión 0 (límite de Fase I provisional, Q2)."""

    ACTIVE = "active"
    """Vigila una versión recalibrada (límite de Fase II)."""


@dataclass(frozen=True)
class ChartStatusView:
    """Estado de la carta con sus avisos.

    Attributes:
        status: Estado por precedencia.
        active_version: Número de la versión vigente.
        proposed_version: Número de la propuesta pendiente, si la hay.
        unresolved_event_id: Evento estructural sin resolver, si lo hay.
        revalidation_due: ``True`` si venció la revalidación (aviso independiente del estado).
        revalidation_due_at: Fecha en que vence (o venció) la revalidación por meses.
        observations_since_active: Observaciones puntuadas con la versión vigente.
        notices: Avisos activos (``requires_new_base``, ``proposal_pending``,
            ``revalidation_due``), en orden de precedencia.
    """

    status: ChartStatus
    active_version: int
    proposed_version: int | None
    unresolved_event_id: str | None
    revalidation_due: bool
    revalidation_due_at: datetime | None
    observations_since_active: int
    notices: tuple[str, ...]


def utc(value: datetime, field_name: str) -> datetime:
    """Normaliza una fecha con zona horaria a UTC.

    Args:
        value: Fecha.
        field_name: Campo, para el mensaje de error.

    Returns:
        La misma fecha en UTC.

    Raises:
        InvalidInputError: Si no es ``datetime`` o no tiene zona horaria.
    """
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidInputError(
            f"'{field_name}' debe ser una fecha con zona horaria", details={"field": field_name}
        )
    return value.astimezone(UTC)


def add_months(value: datetime, months: int) -> datetime:
    """Suma meses de calendario; si el día no existe en el mes destino, toma el último.

    Args:
        value: Fecha de partida.
        months: Meses a sumar (``>= 0``).

    Returns:
        La fecha resultante, con la misma hora y zona.
    """
    index = value.month - 1 + months
    year, month = value.year + index // 12, index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def frozen_base(data: FloatMatrix) -> FloatMatrix:
    """Copia de solo lectura de una base, para que ``base_hash`` siga valiendo para su contenido.

    Args:
        data: Base ``n x p``.

    Returns:
        Copia ``float64`` con ``writeable=False``.
    """
    arr = np.array(data, dtype=np.float64, copy=True)
    arr.setflags(write=False)
    return arr


def base_content_hash(data: FloatMatrix) -> str:
    """Huella SHA-256 del contenido de una base: forma y bytes ``float64`` little-endian.

    Identifica la base exacta de una versión (la comprobación por T² con tolerancia de la carta
    no prueba identidad). Independiente de la disposición en memoria del arreglo.

    Args:
        data: Base ``n x p``.

    Returns:
        ``"sha256:<hex>"``.
    """
    arr = np.ascontiguousarray(data, dtype="<f8")
    digest = hashlib.sha256()
    digest.update(("x".join(str(d) for d in arr.shape) + ";").encode("ascii"))
    digest.update(arr.tobytes(order="C"))
    return f"sha256:{digest.hexdigest()}"


def exclusion_reason(disposition: RowDisposition) -> ExclusionReason | None:
    """Motivo de exclusión que corresponde al destino de una fila según la carta.

    Args:
        disposition: Destino de la fila.

    Returns:
        El motivo, o ``None`` si la fila se conservó.
    """
    return {
        RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE: ExclusionReason.ASSIGNABLE_CAUSE,
        RowDisposition.ALREADY_IN_BASE: ExclusionReason.ALREADY_IN_BASE,
    }.get(disposition)


def active_version(versions: Sequence[ModelVersion]) -> ModelVersion | None:
    """La versión vigente (estado ``active``).

    Args:
        versions: Versiones del modelo.

    Returns:
        La vigente, o ``None`` si no hay ninguna.
    """
    return next((v for v in versions if v.status is VersionStatus.ACTIVE), None)


def pending_proposal(versions: Sequence[ModelVersion]) -> ModelVersion | None:
    """La propuesta sin resolver (estado ``proposed``).

    Args:
        versions: Versiones del modelo.

    Returns:
        La propuesta, o ``None`` si no hay ninguna.
    """
    return next((v for v in versions if v.status is VersionStatus.PROPOSED), None)


def version_for(observed_at: datetime, versions: Sequence[ModelVersion]) -> ModelVersion | None:
    """Versión que rige en una fecha: la aprobada con el mayor ``effective_from <= observed_at``.

    ``effective_from = None`` rige desde el origen. Las versiones aprobadas y luego sustituidas
    siguen rigiendo sus fechas (no retroactividad, Q6).

    Args:
        observed_at: Fecha de la observación (UTC).
        versions: Versiones del modelo.

    Returns:
        La versión, o ``None`` si la fecha es anterior a todas.
    """
    best: ModelVersion | None = None
    for version in versions:
        if version.status not in _APPROVED:
            continue
        start = version.effective_from
        if start is not None and start > observed_at:
            continue
        if best is None or (
            start is not None and (best.effective_from is None or start >= best.effective_from)
        ):
            best = version
    return best


def unresolved_structural_event(
    events: Sequence[StructuralEvent], versions: Sequence[ModelVersion]
) -> StructuralEvent | None:
    """Último evento estructural sin una versión aprobada que lo resuelva (D5).

    Solo cuenta el último evento (por ``occurred_at`` y, a igualdad, por registro): una base
    nueva con datos posteriores a él también deja atrás a los anteriores.

    Args:
        events: Eventos del modelo.
        versions: Versiones del modelo.

    Returns:
        El evento sin resolver, o ``None``.
    """
    if not events:
        return None
    latest = max(events, key=lambda e: (e.occurred_at, e.registered_at))
    resolved = any(
        v.structural_event_id == latest.event_id and v.status in _APPROVED for v in versions
    )
    return None if resolved else latest


def revalidation_due_at(policy: LifecyclePolicy, active: ModelVersion) -> datetime | None:
    """Fecha en que vence la revalidación por meses de la versión vigente.

    Se cuenta desde su aprobación (``approved_at``; en la versión 0, el fin de la Fase I).

    Args:
        policy: Política de la carta.
        active: Versión vigente.

    Returns:
        La fecha, o ``None`` si el criterio por meses está desactivado o no hay aprobación.
    """
    if policy.revalidate_every_months is None or active.approved_at is None:
        return None
    return add_months(active.approved_at, policy.revalidate_every_months)


def revalidation_due(
    policy: LifecyclePolicy, active: ModelVersion, now: datetime, n_scored: int
) -> bool:
    """Indica si venció la revalidación periódica (por meses o por observaciones).

    Args:
        policy: Política de la carta.
        active: Versión vigente.
        now: Instante actual (UTC, de ``Clock``).
        n_scored: Observaciones puntuadas con la versión vigente.

    Returns:
        ``True`` si se cumple alguno de los criterios activos.
    """
    due_at = revalidation_due_at(policy, active)
    by_time = due_at is not None and now >= due_at
    every = policy.revalidate_every_observations
    by_count = every is not None and n_scored >= every
    return by_time or by_count


def derive_chart_state(
    *,
    requires_new_base: bool,
    proposal_pending: bool,
    revalidation_is_due: bool,
    active: ModelVersion,
) -> ChartStatus:
    """Estado de la carta por precedencia.

    ``requires_new_base > proposal_pending > revalidation_due > startup/active``.

    Args:
        requires_new_base: Hay un evento estructural sin resolver.
        proposal_pending: Hay una propuesta sin resolver.
        revalidation_is_due: Venció la revalidación.
        active: Versión vigente.

    Returns:
        El estado.
    """
    if requires_new_base:
        return ChartStatus.REQUIRES_NEW_BASE
    if proposal_pending:
        return ChartStatus.PROPOSAL_PENDING
    if revalidation_is_due:
        return ChartStatus.REVALIDATION_DUE
    if active.decision is RecalibrationDecision.INITIAL:
        return ChartStatus.STARTUP
    return ChartStatus.ACTIVE
