"""Recalibración a petición: solicitar, ejecutar y consultar (``RequestRecalibration``…).

ADR 0008, punto 4. La petición se valida de forma síncrona y se encola; el trabajo llama a
``ControlChart.recalibrate`` con la base de la versión vigente, las observaciones del rango y la
exclusión humana (anotaciones con causa asignable confirmada), y crea una **versión propuesta**
inmutable con su informe. Solo rige al aprobarse (``ApproveVersion``).

Tras un evento estructural sin resolver, el recálculo es un **reemplazo forzado** y solo admite
observaciones posteriores al evento (D5). Como máximo hay una propuesta pendiente y una
recalibración en curso por carta (D6); las observaciones que ya forman parte de la base vigente
no vuelven a pasar como nuevas (``already_in_base``).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np

from voracious.application.charts import (
    AnyChart,
    ChartRegistry,
    as_recalibration_params,
    as_recalibration_report,
    as_versioned_model,
    resolve_chart,
)
from voracious.application.errors import (
    ApplicationError,
    ProposalPendingError,
    RangeBeforeStructuralEventError,
    RecalibrationDecisionPendingError,
    RecalibrationInProgressError,
    RecalibrationInsufficientObservationsError,
    RecalibrationNotFoundError,
)
from voracious.application.lifecycle import (
    base_content_hash,
    exclusion_reason,
    frozen_base,
    pending_proposal,
    unresolved_structural_event,
    utc,
)
from voracious.application.ports import (
    Clock,
    IdGenerator,
    JobKind,
    JobQueue,
    JobRequest,
    ModelRepository,
    ModelVersionRepository,
    ObservationRepository,
    RecalibrationRepository,
    SignalAnnotationRepository,
    StructuralEventRepository,
)
from voracious.application.records import (
    BaseRowRef,
    BaseRowSource,
    ErrorInfo,
    Exclusion,
    ExclusionReason,
    JobStatus,
    ModelVersion,
    ObservationRecord,
    RecalibrationRecord,
    VersionStatus,
)
from voracious.application.use_cases.common import (
    INTERNAL_ERROR,
    get_version,
    ready_model,
    require_active_version,
)
from voracious.application.use_cases.observations import STRUCTURAL_EVENT_NOTE
from voracious.domain.common import (
    DomainError,
    FloatMatrix,
    InvalidInputError,
    RecalibrationDecision,
    RowDisposition,
    TaskMapper,
)

__all__ = ["GetRecalibration", "RequestRecalibration", "RunRecalibrationJob"]

_IN_PROGRESS = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})


def _candidates(
    observations: ObservationRepository,
    record_key: tuple[str, str, str],
    range_from: datetime,
    range_to: datetime,
    active: ModelVersion,
) -> tuple[list[ObservationRecord], list[ObservationRecord]]:
    """Observaciones del rango separadas en candidatas y ya presentes en la base vigente.

    Args:
        observations: Registro de observaciones.
        record_key: ``(tenant_id, chart_id, model_id)``.
        range_from: Inicio del rango (inclusivo).
        range_to: Fin del rango (inclusivo).
        active: Versión vigente (la base).

    Returns:
        ``(candidatas, ya_en_la_base)``, ordenadas por fecha.
    """
    tenant_id, chart_id, model_id = record_key
    in_base = {r.ref for r in active.base_refs if r.source is BaseRowSource.OBSERVATION}
    rows = observations.list(
        tenant_id, chart_id, model_id, observed_from=range_from, observed_to=range_to
    )
    fresh = [r for r in rows if r.observation_id not in in_base]
    already = [r for r in rows if r.observation_id in in_base]
    return fresh, already


@dataclass(frozen=True)
class RequestRecalibration:
    """Valida una petición de recalibración, crea el registro ``queued`` y lo encola.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        versions: Repositorio de versiones.
        observations: Registro de observaciones.
        events: Eventos estructurales.
        recalibrations: Repositorio de recalibraciones.
        queue: Cola de trabajos.
        ids: Generador de identificadores.
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    versions: ModelVersionRepository
    observations: ObservationRepository
    events: StructuralEventRepository
    recalibrations: RecalibrationRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        *,
        range_from: datetime,
        range_to: datetime,
        params: object,
        force_replace: bool = False,
        actor: str | None = None,
    ) -> str:
        """Encola la recalibración tras validarla de forma síncrona.

        Orden: modelo listo; sin propuesta pendiente ni recalibración en curso; rango válido;
        con un evento estructural sin resolver, rango posterior al evento y reemplazo forzado;
        al menos ``min_observations`` candidatas; sin decisiones pendientes de la carta salvo
        reemplazo forzado. Los parámetros se guardan codificados (M1).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            range_from: Inicio del rango de fechas (con zona horaria, inclusivo).
            range_to: Fin del rango (con zona horaria, inclusivo).
            params: Parámetros de recalibración de la carta.
            force_replace: Reemplazo forzado (decisión humana).
            actor: Quién la pide.

        Returns:
            El ``recalibration_id``.

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si el modelo no existe para ese tenant y esa carta.
            ModelNotReadyError: Si el modelo no está listo.
            ProposalPendingError: Si hay una propuesta sin resolver.
            RecalibrationInProgressError: Si hay una recalibración en curso.
            InvalidInputError: Rango inválido o parámetros no codificables.
            RangeBeforeStructuralEventError: Rango con datos anteriores al evento sin resolver.
            RecalibrationInsufficientObservationsError: Menos candidatas que el mínimo.
            RecalibrationDecisionPendingError: Decisiones de la carta pendientes sin forzar.
        """
        chart = resolve_chart(self.charts, chart_id)
        ready_model(self.models, tenant_id, chart_id, model_id)
        versions = self.versions.list(tenant_id, chart_id, model_id)
        active = require_active_version(versions, model_id)
        proposal = pending_proposal(versions)
        if proposal is not None:
            raise ProposalPendingError(
                "ya hay una propuesta sin resolver", details={"version": proposal.number}
            )
        running = [
            r
            for r in self.recalibrations.list(tenant_id, chart_id, model_id)
            if r.status in _IN_PROGRESS
        ]
        if running:
            raise RecalibrationInProgressError(
                "ya hay una recalibración en curso",
                details={"recalibration_id": running[0].recalibration_id},
            )
        start, end = utc(range_from, "range_from"), utc(range_to, "range_to")
        if start > end:
            raise InvalidInputError(
                "'range_from' debe ser anterior o igual a 'range_to'",
                details={"field": "range_from"},
            )
        event = unresolved_structural_event(
            self.events.list(tenant_id, chart_id, model_id), versions
        )
        if event is not None:
            if start <= event.occurred_at:
                raise RangeBeforeStructuralEventError(
                    "el rango incluye datos anteriores al último evento estructural",
                    details={
                        "event_id": event.event_id,
                        "occurred_at": event.occurred_at.isoformat(),
                        "range_from": start.isoformat(),
                    },
                )
            force_replace = True
        encoded = chart.encode_recalibration_params(params)
        view = as_recalibration_params(params)
        fresh, _ = _candidates(
            self.observations, (tenant_id, chart_id, model_id), start, end, active
        )
        if len(fresh) < view.min_observations:
            raise RecalibrationInsufficientObservationsError(
                "no hay suficientes observaciones candidatas en el rango",
                details={"available": len(fresh), "required": view.min_observations},
            )
        pending = chart.pending_recalibration_decisions(params)
        if pending and not force_replace:
            raise RecalibrationDecisionPendingError(
                "la recalibración tiene decisiones estadísticas pendientes",
                details={"pending": list(pending)},
            )
        record = RecalibrationRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            model_id=model_id,
            recalibration_id=self.ids.new_id(),
            status=JobStatus.QUEUED,
            range_from=start,
            range_to=end,
            params=encoded,
            force_replace=force_replace,
            base_version_number=active.number,
            structural_event_id=None if event is None else event.event_id,
            created_at=self.clock.now(),
            actor=actor,
        )
        self.recalibrations.add(record)
        self.queue.enqueue(
            JobRequest(
                kind=JobKind.RECALIBRATE,
                tenant_id=tenant_id,
                chart_id=chart_id,
                model_id=model_id,
                recalibration_id=record.recalibration_id,
            )
        )
        return record.recalibration_id


def _get_recalibration(
    recalibrations: RecalibrationRepository,
    tenant_id: str,
    chart_id: str,
    model_id: str,
    recalibration_id: str,
) -> RecalibrationRecord:
    """Busca una recalibración o lanza ``RecalibrationNotFoundError``.

    Args:
        recalibrations: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo.
        recalibration_id: Recalibración.

    Returns:
        El registro.

    Raises:
        RecalibrationNotFoundError: Si no existe para esa clave.
    """
    record = recalibrations.get(tenant_id, chart_id, model_id, recalibration_id)
    if record is None:
        raise RecalibrationNotFoundError(
            f"la recalibración '{recalibration_id}' no existe",
            details={"model_id": model_id, "recalibration_id": recalibration_id},
        )
    return record


@dataclass(frozen=True)
class GetRecalibration:
    """Consulta una recalibración del tenant.

    Attributes:
        charts: Cartas registradas.
        recalibrations: Repositorio de recalibraciones.
    """

    charts: ChartRegistry
    recalibrations: RecalibrationRepository

    def execute(
        self, tenant_id: str, chart_id: str, model_id: str, recalibration_id: str
    ) -> RecalibrationRecord:
        """Devuelve la recalibración.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.

        Returns:
            El registro.

        Raises:
            UnknownChartError: Si la carta no existe.
            RecalibrationNotFoundError: Si no existe para esa clave.
        """
        resolve_chart(self.charts, chart_id)
        return _get_recalibration(
            self.recalibrations, tenant_id, chart_id, model_id, recalibration_id
        )


def _justification(record: RecalibrationRecord, decision: RecalibrationDecision) -> str:
    """Por qué se tomó la decisión de la versión propuesta.

    Args:
        record: Recalibración.
        decision: Decisión de la carta.

    Returns:
        ``structural_event``, ``forced_replace``, ``change_detected`` o ``no_change_detected``.
    """
    if record.structural_event_id is not None:
        return "structural_event"
    if record.force_replace:
        return "forced_replace"
    if decision is RecalibrationDecision.REPLACE:
        return "change_detected"
    return "no_change_detected"


@dataclass(frozen=True)
class _NewBase:
    """Base de la versión propuesta y sus exclusiones."""

    data: FloatMatrix
    refs: tuple[BaseRowRef, ...]
    exclusions: tuple[Exclusion, ...]


def _new_base(
    active: ModelVersion,
    decision: RecalibrationDecision,
    new_rows: Sequence[ObservationRecord],
    dispositions: Sequence[RowDisposition],
    annotation_ids: dict[str, str],
    already: Sequence[ObservationRecord],
) -> _NewBase:
    """Construye la base de la nueva versión a partir del destino de cada fila nueva.

    ``EXTEND`` = base vigente + nuevas conservadas; ``REPLACE`` = solo las nuevas conservadas
    (vocabulario común, ``RecalibrationDecision``).

    Args:
        active: Versión vigente.
        decision: ``EXTEND`` o ``REPLACE``.
        new_rows: Observaciones pasadas como nuevas, en orden.
        dispositions: Destino de cada fila nueva.
        annotation_ids: ``observation_id → annotation_id`` de las excluidas por una persona.
        already: Observaciones del rango que ya estaban en la base vigente.

    Returns:
        La base nueva.

    Raises:
        TypeError: Si la decisión no es ``EXTEND`` ni ``REPLACE``.
    """
    kept = [i for i, d in enumerate(dispositions) if d is RowDisposition.KEPT]
    kept_refs = tuple(
        BaseRowRef(BaseRowSource.OBSERVATION, new_rows[i].observation_id) for i in kept
    )
    kept_data = np.array([new_rows[i].values for i in kept], dtype=np.float64).reshape(
        len(kept), active.base_data.shape[1]
    )
    if decision is RecalibrationDecision.EXTEND:
        data = np.vstack([active.base_data, kept_data])
        refs = active.base_refs + kept_refs
    elif decision is RecalibrationDecision.REPLACE:
        data, refs = kept_data, kept_refs
    else:
        msg = f"decisión de recalibración inesperada con modelo: {decision}"
        raise TypeError(msg)
    exclusions = [
        Exclusion(
            ref=BaseRowRef(BaseRowSource.OBSERVATION, r.observation_id),
            reason=ExclusionReason.ALREADY_IN_BASE,
        )
        for r in already
    ]
    for row, disposition in zip(new_rows, dispositions, strict=True):
        reason = exclusion_reason(disposition)
        if reason is None:
            continue
        exclusions.append(
            Exclusion(
                ref=BaseRowRef(BaseRowSource.OBSERVATION, row.observation_id),
                reason=reason,
                annotation_id=annotation_ids.get(row.observation_id)
                if reason is ExclusionReason.ASSIGNABLE_CAUSE
                else None,
            )
        )
    return _NewBase(np.ascontiguousarray(data), refs, tuple(exclusions))


@dataclass(frozen=True)
class RunRecalibrationJob:
    """Ejecuta una recalibración encolada: ``running`` → ``succeeded | failed``.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
        versions: Repositorio de versiones.
        observations: Registro de observaciones.
        annotations: Anotaciones de señales.
        events: Eventos estructurales.
        recalibrations: Repositorio de recalibraciones.
        mapper: Reparto de tareas para la carta.
        clock: Reloj.
    """

    charts: ChartRegistry
    models: ModelRepository
    versions: ModelVersionRepository
    observations: ObservationRepository
    annotations: SignalAnnotationRepository
    events: StructuralEventRepository
    recalibrations: RecalibrationRepository
    mapper: TaskMapper
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo; idempotente: si la recalibración ya no está ``queued``, no hace nada.

        ``INSUFFICIENT`` deja la recalibración ``succeeded`` sin versión. Si mientras se
        calculaba se registró un evento estructural nuevo, la versión se guarda ya ``rejected``
        con la nota ``structural_event``. Un ``DomainError`` o un error de aplicación la dejan
        ``failed`` con su código; cualquier otra excepción, ``failed / INTERNAL_ERROR`` y se
        relanza.

        Args:
            job: Petición ``recalibrate``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``recalibrate``.
            UnknownChartError: Si la carta no existe.
            RecalibrationNotFoundError: Si la recalibración no existe.
        """
        if job.kind is not JobKind.RECALIBRATE or job.recalibration_id is None:
            msg = f"RunRecalibrationJob solo ejecuta trabajos 'recalibrate', no '{job.kind}'"
            raise ValueError(msg)
        chart = resolve_chart(self.charts, job.chart_id)
        record = _get_recalibration(
            self.recalibrations, job.tenant_id, job.chart_id, job.model_id, job.recalibration_id
        )
        if record.status is not JobStatus.QUEUED:
            return
        record = replace(record, status=JobStatus.RUNNING, started_at=self.clock.now())
        self.recalibrations.update(record)
        try:
            record = self._run(chart, record)
        except (DomainError, ApplicationError) as exc:
            error = ErrorInfo(code=exc.code, message=exc.message, details=exc.details)
            self.recalibrations.update(self._finish(record, error=error))
            return
        except Exception:
            error = ErrorInfo(code=INTERNAL_ERROR, message="error interno en la recalibración")
            self.recalibrations.update(self._finish(record, error=error))
            raise
        self.recalibrations.update(self._finish(record))

    def _run(self, chart: AnyChart, record: RecalibrationRecord) -> RecalibrationRecord:
        """Llama a la carta y guarda la versión propuesta.

        Args:
            chart: Carta.
            record: Recalibración en ``running``.

        Returns:
            El registro con la decisión, el informe y la versión propuesta.
        """
        key = (record.tenant_id, record.chart_id, record.model_id)
        ready_model(self.models, *key)
        active = get_version(self.versions, *key, record.base_version_number)
        new_rows, already = _candidates(
            self.observations, key, record.range_from, record.range_to, active
        )
        latest = self.annotations.latest_for(*key, [r.observation_id for r in new_rows])
        assignable = {obs_id: a.annotation_id for obs_id, a in latest.items() if a.assignable_cause}
        mask = np.array([r.observation_id in assignable for r in new_rows], dtype=np.bool_)
        x_new = np.array([r.values for r in new_rows], dtype=np.float64).reshape(
            len(new_rows), active.base_data.shape[1]
        )
        outcome = chart.recalibrate(
            active.model,
            active.base_data,
            x_new,
            assignable_cause=mask,
            force_replace=record.force_replace,
            params=chart.decode_recalibration_params(record.params),
            mapper=self.mapper,
        )
        record = replace(record, outcome=outcome.decision, report=outcome.report)
        if outcome.decision is RecalibrationDecision.INSUFFICIENT or outcome.model is None:
            return record
        dispositions = as_recalibration_report(outcome.report).row_disposition
        n_base = active.base_data.shape[0]
        if len(dispositions) != n_base + len(new_rows):
            msg = "el informe no tiene un destino por fila de base + nuevas"
            raise TypeError(msg)
        base = _new_base(
            active, outcome.decision, new_rows, dispositions[n_base:], assignable, already
        )
        if as_versioned_model(outcome.model).base_mask.shape != (base.data.shape[0],):
            msg = "la base del modelo nuevo no coincide con la reconstruida"
            raise TypeError(msg)
        number = 1 + max(v.number for v in self.versions.list(*key))
        now = self.clock.now()
        event = unresolved_structural_event(self.events.list(*key), self.versions.list(*key))
        superseded_by_event = event is not None and event.event_id != record.structural_event_id
        self.versions.add(
            ModelVersion(
                tenant_id=record.tenant_id,
                chart_id=record.chart_id,
                model_id=record.model_id,
                number=number,
                status=VersionStatus.REJECTED if superseded_by_event else VersionStatus.PROPOSED,
                model=outcome.model,
                base_data=frozen_base(base.data),
                base_hash=base_content_hash(base.data),
                base_refs=base.refs,
                exclusions=base.exclusions,
                decision=outcome.decision,
                justification=_justification(record, outcome.decision),
                created_at=now,
                report=outcome.report,
                recalibration_id=record.recalibration_id,
                structural_event_id=record.structural_event_id,
                previous_number=active.number,
                rejected_at=now if superseded_by_event else None,
                decision_note=STRUCTURAL_EVENT_NOTE if superseded_by_event else None,
            )
        )
        return replace(record, proposed_version=number)

    def _finish(
        self, record: RecalibrationRecord, *, error: ErrorInfo | None = None
    ) -> RecalibrationRecord:
        """Cierra una recalibración en ``succeeded`` o ``failed`` (con ``error``).

        Args:
            record: Registro en ``running``.
            error: Error, si falló.

        Returns:
            El registro terminado.
        """
        status = JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED
        return replace(record, status=status, finished_at=self.clock.now(), error=error)
