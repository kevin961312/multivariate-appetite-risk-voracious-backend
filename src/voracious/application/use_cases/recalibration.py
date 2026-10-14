"""Recalibración a petición: pedirla (paso a paso o todo junto), consultarla y orquestarla.

ADR 0008, punto 4, y vuelta 3.4 del Paso 3. La petición se valida de forma síncrona y abre la
**sesión**: fija las observaciones candidatas del rango (en orden; las que ya están en la base
vigente quedan aparte, ``already_in_base``), los parámetros de la carta heredados de la versión
base con la semilla de la recalibración (Q8) y crea el dataset ``recalibration_candidates``.

- ``stepwise``: la recalibración queda ``running`` y el cliente encadena por id ``/exclusions``
  (si hay anotaciones con causa asignable), ``…/extension`` (salvo reemplazo), ``/fits``,
  ``/limits`` (con ``recalibration_id``) y ``…/versions``.
- ``pipeline``: ``RunRecalibrationJob`` encadena **los mismos casos de uso** (orquestación pura,
  como ``RunPhase1Pipeline``), así que paso a paso, tubería y ``ControlChart.recalibrate`` dan el
  mismo modelo e informe en bits (``tests/integration/test_recalibration_chain.py``).

Sin comparación de bases (decisión del dueño, 2026-10-14): la recalibración amplía la base vigente
por defecto (``EXTEND``) y la reemplaza (``REPLACE``) solo con ``force_replace`` o tras un evento
estructural sin resolver, que además solo admite observaciones posteriores al evento (D5). Como
máximo hay una propuesta pendiente y una recalibración en curso por carta (D6).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np

from voracious.application.charts import (
    AnyChart,
    ChartRegistry,
    as_recalibration_params,
    resolve_chart,
)
from voracious.application.errors import (
    ApplicationError,
    ProposalPendingError,
    RangeBeforeStructuralEventError,
    RecalibrationInProgressError,
    RecalibrationInsufficientObservationsError,
    RecalibrationNotInProgressError,
    VariablesMismatchError,
)
from voracious.application.lifecycle import (
    base_content_hash,
    frozen_base,
    pending_proposal,
    unresolved_structural_event,
    utc,
)
from voracious.application.phase1_steps import Phase1Steps, Phase1StepsRegistry, resolve_steps
from voracious.application.ports import (
    Clock,
    DatasetStorage,
    ExclusionRepository,
    FitRepository,
    IdGenerator,
    JobKind,
    JobQueue,
    JobRequest,
    LimitsRepository,
    ModelRepository,
    ModelVersionRepository,
    ObservationRepository,
    PipelineRepository,
    RecalibrationRepository,
    StructuralEventRepository,
)
from voracious.application.recalibration_steps import (
    RecalibrationStepsRegistry,
    resolve_recalibration_steps,
)
from voracious.application.records import (
    BaseRowSource,
    DatasetRecord,
    DatasetSource,
    ErrorInfo,
    JobStatus,
    LifecyclePolicy,
    ModelVersion,
    ObservationRecord,
    PipelineKind,
    PipelineRecord,
    PipelineStep,
    RecalibrationMode,
    RecalibrationRecord,
)
from voracious.application.use_cases.common import (
    INTERNAL_ERROR,
    ready_model,
    require_active_version,
)
from voracious.application.use_cases.extension import RequestRecalibrationExtension
from voracious.application.use_cases.pipelines import get_pipeline
from voracious.application.use_cases.proposals import RequestVersionProposal
from voracious.application.use_cases.recalibration_chain import (
    RecalibrationChain,
    get_recalibration,
)
from voracious.application.use_cases.steps import (
    RequestExclusion,
    RequestFit,
    RequestLimits,
    get_exclusion,
    get_fit,
    get_limits,
    notify_pipeline,
)
from voracious.domain.common import DomainError, InvalidInputError

__all__ = [
    "STEP_EXTENSION",
    "STEP_VERSION",
    "CancelRecalibration",
    "GetRecalibration",
    "RequestRecalibration",
    "RunRecalibrationJob",
]

_IN_PROGRESS = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})

STEP_EXCLUSION = "exclusion"
STEP_FIT = "fit"
STEP_LIMITS = "limits"
STEP_EXTENSION = "extension"
STEP_VERSION = "version"


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
    """Valida una petición de recalibración y abre su sesión (paso a paso o tubería).

    Attributes:
        charts: Cartas registradas.
        recalibration_steps: Pasos de la recalibración por carta.
        models: Repositorio de modelos.
        versions: Repositorio de versiones.
        observations: Registro de observaciones.
        events: Eventos estructurales.
        recalibrations: Repositorio de recalibraciones.
        datasets: Almacenamiento (recibe el dataset de candidatas).
        pipelines: Repositorio de tuberías (modo ``pipeline``).
        queue: Cola de trabajos.
        ids: Generador de identificadores.
        clock: Reloj.
    """

    charts: ChartRegistry
    recalibration_steps: RecalibrationStepsRegistry
    models: ModelRepository
    versions: ModelVersionRepository
    observations: ObservationRepository
    events: StructuralEventRepository
    recalibrations: RecalibrationRepository
    datasets: DatasetStorage
    pipelines: PipelineRepository
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
        mode: RecalibrationMode = RecalibrationMode.PIPELINE,
    ) -> str:
        """Abre la recalibración tras validarla de forma síncrona.

        La comprobación «sin recalibración en curso» se repite de forma atómica al guardar
        (``add_if_none_in_progress``): de dos peticiones concurrentes solo una se acepta (D6).

        Orden: modelo listo; sin propuesta pendiente ni recalibración en curso; rango válido;
        con un evento estructural sin resolver, rango posterior al evento y reemplazo forzado;
        al menos ``min_observations`` candidatas. Los parámetros se guardan codificados (M1).

        ``stepwise`` deja la recalibración ``running`` (sesión abierta, sin trabajo encolado);
        ``pipeline`` la deja ``queued`` y encola su tubería.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            range_from: Inicio del rango de fechas (con zona horaria, inclusivo).
            range_to: Fin del rango (con zona horaria, inclusivo).
            params: Parámetros de recalibración de la carta.
            force_replace: Reemplazar la base por las filas nuevas (petición explícita); sin él se
                amplía la base (por defecto), salvo evento estructural sin resolver.
            actor: Quién la pide.
            mode: ``pipeline`` (por defecto) o ``stepwise``.

        Returns:
            El ``recalibration_id`` (en ``stepwise``, el dataset de candidatas está en el
            registro: ``candidates_dataset_id``).

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si el modelo no existe para ese tenant y esa carta.
            ModelNotReadyError: Si el modelo no está listo.
            ProposalPendingError: Si hay una propuesta sin resolver.
            RecalibrationInProgressError: Si hay una recalibración en curso.
            InvalidInputError: Rango inválido o parámetros no codificables.
            RangeBeforeStructuralEventError: Rango con datos anteriores al evento sin resolver.
            RecalibrationInsufficientObservationsError: Menos candidatas que el mínimo.
            VariablesMismatchError: Si alguna candidata no tiene el número de variables de la
                base vigente (los nombres ya se comprobaron al puntuarla).
        """
        chart = resolve_chart(self.charts, chart_id)
        steps = resolve_recalibration_steps(self.recalibration_steps, chart_id)
        model = ready_model(self.models, tenant_id, chart_id, model_id)
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
        fresh, already = _candidates(
            self.observations, (tenant_id, chart_id, model_id), start, end, active
        )
        p = int(active.base_data.shape[1])
        odd = [r.observation_id for r in fresh if r.values.shape != (p,)]
        if odd:
            raise VariablesMismatchError(
                "hay observaciones candidatas con otro número de variables que el modelo",
                details={"input": "recalibration", "columns": p, "observations": odd[:20]},
            )
        if len(fresh) < view.min_observations:
            raise RecalibrationInsufficientObservationsError(
                "no hay suficientes observaciones candidatas en el rango",
                details={"available": len(fresh), "required": view.min_observations},
            )
        mode = RecalibrationMode(mode)
        now = self.clock.now()
        stepwise = mode is RecalibrationMode.STEPWISE
        record = RecalibrationRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            model_id=model_id,
            recalibration_id=self.ids.new_id(),
            status=JobStatus.RUNNING if stepwise else JobStatus.QUEUED,
            range_from=start,
            range_to=end,
            params=encoded,
            force_replace=force_replace,
            base_version_number=active.number,
            structural_event_id=None if event is None else event.event_id,
            created_at=now,
            actor=actor,
            started_at=now if stepwise else None,
            mode=mode,
            inherited_params=steps.inherited_params(active.model, encoded),
            candidate_ids=tuple(r.observation_id for r in fresh),
            already_in_base_ids=tuple(r.observation_id for r in already),
            candidates_dataset_id=self.ids.new_id(),
            pipeline_id=None if stepwise else self.ids.new_id(),
        )
        if not self.recalibrations.add_if_none_in_progress(record):
            # Otra petición concurrente pasó la comprobación de arriba y guardó antes (D6).
            raise RecalibrationInProgressError(
                "ya hay una recalibración en curso", details={"reason": "concurrent_request"}
            )
        self.datasets.add(self._candidates_dataset(record, fresh, p, model.variables))
        if record.pipeline_id is not None:
            self._start_pipeline(record)
        return record.recalibration_id

    def _candidates_dataset(
        self,
        record: RecalibrationRecord,
        fresh: Sequence[ObservationRecord],
        p: int,
        variables: tuple[str, ...] | None,
    ) -> DatasetRecord:
        """Dataset ``recalibration_candidates``: los valores de las candidatas en orden.

        Lleva los nombres de variables del modelo y la fecha de cada candidata (trazabilidad).

        Args:
            record: Recalibración.
            fresh: Candidatas.
            p: Número de variables.
            variables: Nombres de las variables del modelo, o ``None``.

        Returns:
            El dataset (raíz del linaje ``NEW_ROWS``).
        """
        values = np.array([r.values for r in fresh], dtype=np.float64).reshape(len(fresh), p)
        data = frozen_base(np.ascontiguousarray(values))
        return DatasetRecord(
            tenant_id=record.tenant_id,
            dataset_id=record.candidates_dataset_id or "",
            data=data,
            content_hash=base_content_hash(data),
            source=DatasetSource.RECALIBRATION_CANDIDATES,
            created_at=record.created_at,
            origin_ref=record.recalibration_id,
            variables=variables,
            observed_at=tuple(r.observed_at for r in fresh),
        )

    def _start_pipeline(self, record: RecalibrationRecord) -> None:
        """Crea y encola la tubería que orquesta la recalibración (modo ``pipeline``).

        Args:
            record: Recalibración ``queued`` con ``pipeline_id``.
        """
        pipeline = PipelineRecord(
            tenant_id=record.tenant_id,
            chart_id=record.chart_id,
            pipeline_id=record.pipeline_id or "",
            kind=PipelineKind.RECALIBRATION,
            status=JobStatus.QUEUED,
            dataset_id=record.candidates_dataset_id or "",
            params=record.inherited_params,
            assignable_cause=(),
            lifecycle_policy=LifecyclePolicy(),
            created_at=record.created_at,
            model_id=record.model_id,
            recalibration_id=record.recalibration_id,
        )
        self.pipelines.add(pipeline)
        self.queue.enqueue(
            JobRequest(JobKind.PIPELINE, record.tenant_id, record.chart_id, pipeline.pipeline_id)
        )


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
        return get_recalibration(
            self.recalibrations, tenant_id, chart_id, model_id, recalibration_id
        )


@dataclass(frozen=True)
class CancelRecalibration:
    """Cierra una sesión paso a paso abandonada como ``cancelled`` (libera D6).

    Solo una recalibración ``stepwise`` ``running`` sin propuesta pedida; la comprobación se
    repite de forma atómica al guardar (``RecalibrationRepository.cancel``). Los recursos ya
    creados (exclusiones, extensión, ajustes y límites) se conservan; los pasos posteriores
    sobre la sesión responden ``RECALIBRATION_NOT_IN_PROGRESS``.

    Attributes:
        charts: Cartas registradas.
        recalibrations: Repositorio de recalibraciones.
        clock: Reloj.
    """

    charts: ChartRegistry
    recalibrations: RecalibrationRepository
    clock: Clock

    def execute(
        self, tenant_id: str, chart_id: str, model_id: str, recalibration_id: str
    ) -> RecalibrationRecord:
        """Cancela la sesión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.

        Returns:
            El registro ``cancelled``.

        Raises:
            UnknownChartError: Si la carta no existe.
            RecalibrationNotFoundError: Si no existe para esa clave.
            RecalibrationNotInProgressError: Si no es una sesión paso a paso ``running`` sin
                propuesta pedida.
        """
        resolve_chart(self.charts, chart_id)
        record = get_recalibration(
            self.recalibrations, tenant_id, chart_id, model_id, recalibration_id
        )
        cancelled = self.recalibrations.cancel(
            tenant_id, chart_id, model_id, recalibration_id, self.clock.now()
        )
        if cancelled is None:
            raise RecalibrationNotInProgressError(
                f"la recalibración '{recalibration_id}' no se puede cancelar",
                details={
                    "recalibration_id": recalibration_id,
                    "mode": str(record.mode),
                    "status": str(record.status),
                    "proposal_requested": record.proposal is not None,
                },
            )
        return cancelled


@dataclass(frozen=True)
class _Next:
    """Paso siguiente decidido por la tubería de recalibración."""

    kind: str
    target: str
    """Dataset (``exclusion``, ``extension`` y ``fit``) o ajuste (``limits`` y ``version``)."""
    limits_id: str | None = None


@dataclass(frozen=True)
class RunRecalibrationJob:
    """Avanza la tubería de una recalibración (modo ``pipeline``): un paso por aviso.

    Orquestación pura con los mismos casos de uso que la API por pasos. Orden: (si hay
    anotaciones con causa asignable: exclusión humana de las candidatas) → extensión (base
    vigente + nuevas conservadas) → ajuste → límites (``EXTENSION``) → versión; con reemplazo
    (evento estructural o petición explícita), sin extensión: ajuste → límites (``NEW_ROWS``) →
    versión. Sin comparación de bases (decisión del dueño, 2026-10-14) ni depuración automática
    iterativa (2026-10-09). Si la
    exclusión humana deja menos de ``min_observations`` filas, la recalibración ya terminó
    ``insufficient`` y la tubería termina bien. Si un paso falla, la tubería y la recalibración
    fallan con su error.

    Attributes:
        charts: Cartas registradas.
        steps: Pasos de Fase I por carta.
        pipelines: Repositorio de tuberías.
        recalibrations: Repositorio de recalibraciones.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        exclusions: Repositorio de exclusiones.
        datasets: Almacenamiento.
        chain: Enlaces con la recalibración (exclusión humana).
        request_exclusion: Caso de uso de la exclusión humana.
        request_fit: Caso de uso del ajuste.
        request_limits: Caso de uso de los límites.
        request_extension: Caso de uso de la extensión (síncrono).
        request_proposal: Caso de uso de la propuesta de versión.
        queue: Cola (la extensión, síncrona, avisa a la tubería al terminar).
        ids: Identificadores (reserva el id del paso antes de crearlo).
        clock: Reloj.
    """

    charts: ChartRegistry
    steps: Phase1StepsRegistry
    pipelines: PipelineRepository
    recalibrations: RecalibrationRepository
    fits: FitRepository
    limits: LimitsRepository
    exclusions: ExclusionRepository
    datasets: DatasetStorage
    chain: RecalibrationChain
    request_exclusion: RequestExclusion
    request_fit: RequestFit
    request_limits: RequestLimits
    request_extension: RequestRecalibrationExtension
    request_proposal: RequestVersionProposal
    queue: JobQueue
    ids: IdGenerator
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Arranca la tubería (``queued``) o la avanza (``running``); terminada, no hace nada.

        Args:
            job: Petición ``pipeline`` de una tubería ``recalibration``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``pipeline`` o la tubería no es de recalibración.
            UnknownChartError: Si la carta no existe.
            PipelineNotFoundError: Si la tubería no existe.
        """
        if job.kind is not JobKind.PIPELINE:
            msg = f"RunRecalibrationJob solo ejecuta trabajos 'pipeline', no '{job.kind}'"
            raise ValueError(msg)
        chart = resolve_chart(self.charts, job.scope)
        steps = resolve_steps(self.steps, job.scope)
        record = get_pipeline(self.pipelines, job.tenant_id, job.scope, job.resource_id)
        if record.kind is not PipelineKind.RECALIBRATION:
            msg = f"la tubería '{record.pipeline_id}' no es de recalibración"
            raise ValueError(msg)
        if record.status is JobStatus.QUEUED:
            claimed = self.pipelines.claim(
                job.tenant_id, job.scope, job.resource_id, self.clock.now()
            )
            if claimed is None:
                return
            record = claimed
            try:
                self._start(chart, steps, record)
            except (DomainError, ApplicationError) as exc:
                self._fail(record, ErrorInfo(exc.code, exc.message, exc.details))
                return
        if record.status is not JobStatus.RUNNING:
            return
        try:
            self._advance(steps, record)
        except (DomainError, ApplicationError) as exc:
            self._fail(record, ErrorInfo(exc.code, exc.message, exc.details))
        except Exception:
            self._fail(record, ErrorInfo(INTERNAL_ERROR, "error interno en la recalibración"))
            raise

    def _session(self, record: PipelineRecord) -> RecalibrationRecord:
        """Recalibración que orquesta la tubería.

        Args:
            record: Tubería.

        Returns:
            La recalibración.
        """
        return get_recalibration(
            self.recalibrations,
            record.tenant_id,
            record.chart_id,
            record.model_id or "",
            record.recalibration_id or "",
        )

    def _start(self, chart: AnyChart, steps: Phase1Steps, record: PipelineRecord) -> None:
        """Pasa la recalibración a ``running`` y comprueba sus parámetros antes de ajustar.

        Args:
            chart: Carta.
            steps: Pasos de la Fase I.
            record: Tubería recién reclamada.

        Raises:
            InvalidInputError: Si los parámetros guardados no son válidos.
            DomainError: Decisiones pendientes de los parámetros heredados.
        """
        session = self._session(record)
        self.recalibrations.claim(
            session.tenant_id,
            session.chart_id,
            session.model_id,
            session.recalibration_id,
            self.clock.now(),
        )
        chart.decode_recalibration_params(session.params)
        steps.check_params(record.params)

    def _advance(self, steps: Phase1Steps, record: PipelineRecord) -> None:
        """Decide y crea el paso siguiente si el último terminó bien.

        Args:
            steps: Pasos de la Fase I.
            record: Tubería en ``running``.
        """
        if not record.steps:
            # Exclusión humana de las candidatas (anotaciones) antes de ajustar nada.
            session = self._session(record)
            if self.chain.human_causes(session):
                first = _Next(STEP_EXCLUSION, record.dataset_id)
            else:
                first = self._kept_next(session, record.dataset_id)
            self._create(steps, record, first)
            return
        last = record.steps[-1]
        status, error = self._status(record, last)
        if status in _IN_PROGRESS:
            return
        if status is JobStatus.FAILED:
            info = error if error is not None else ErrorInfo(INTERNAL_ERROR, "paso fallido")
            details = {**info.details, "step": last.kind, "step_id": last.resource_id}
            self._fail(record, ErrorInfo(info.code, info.message, details))
            return
        nxt = self._next(record, last)
        if nxt is None:
            self._succeed(record)
            return
        self._create(steps, record, nxt)

    def _status(
        self, record: PipelineRecord, step: PipelineStep
    ) -> tuple[JobStatus, ErrorInfo | None]:
        """Estado y error del recurso de un paso.

        Args:
            record: Tubería.
            step: Paso.

        Returns:
            Estado y error del recurso.
        """
        tenant, chart, rid = record.tenant_id, record.chart_id, step.resource_id
        if step.kind == STEP_FIT:
            fit = get_fit(self.fits, tenant, chart, rid)
            return fit.status, fit.error
        if step.kind == STEP_LIMITS:
            limits = get_limits(self.limits, tenant, chart, rid)
            return limits.status, limits.error
        if step.kind == STEP_EXCLUSION:
            exclusion = get_exclusion(self.exclusions, tenant, chart, rid)
            return exclusion.status, exclusion.error
        session = self._session(record)
        if step.kind == STEP_EXTENSION and session.extension_dataset_id == rid:
            return JobStatus.SUCCEEDED, None
        return session.status, session.error

    @staticmethod
    def _kept_next(session: RecalibrationRecord, kept_dataset_id: str) -> _Next:
        """Paso que sigue a tener las filas nuevas conservadas.

        Args:
            session: Recalibración.
            kept_dataset_id: Filas nuevas conservadas (candidatas o salida de la exclusión).

        Returns:
            El ajuste de esas filas si se reemplaza la base; si no, la extensión.
        """
        if session.force_replace:
            return _Next(STEP_FIT, kept_dataset_id)
        return _Next(STEP_EXTENSION, kept_dataset_id)

    def _next(self, record: PipelineRecord, last: PipelineStep) -> _Next | None:
        """Paso que sigue a uno terminado bien (``None``: la tubería terminó).

        Args:
            record: Tubería.
            last: Último paso, ``succeeded``.

        Returns:
            El paso siguiente o ``None`` (versión pedida, o exclusión humana que dejó menos de
            ``min_observations`` filas: la recalibración ya terminó ``insufficient``).
        """
        tenant, chart = record.tenant_id, record.chart_id
        if last.kind == STEP_EXCLUSION:
            exclusion = get_exclusion(self.exclusions, tenant, chart, last.resource_id)
            if exclusion.output_dataset_id is None:
                return None
            return self._kept_next(self._session(record), exclusion.output_dataset_id)
        if last.kind == STEP_EXTENSION:
            return _Next(STEP_FIT, last.resource_id)
        if last.kind == STEP_FIT:
            return _Next(STEP_LIMITS, last.resource_id)
        if last.kind == STEP_LIMITS:
            limits = get_limits(self.limits, tenant, chart, last.resource_id)
            return _Next(STEP_VERSION, limits.fit_id, limits.limits_id)
        return None

    def _create(self, steps: Phase1Steps, record: PipelineRecord, nxt: _Next) -> None:
        """Reserva el paso (atómico) y crea su recurso con el caso de uso de la API.

        Args:
            steps: Pasos de la Fase I.
            record: Tubería.
            nxt: Paso a crear.
        """
        session = self._session(record)
        rid = session.recalibration_id if nxt.kind == STEP_VERSION else self.ids.new_id()
        appended = self.pipelines.append_step(
            record.tenant_id,
            record.chart_id,
            record.pipeline_id,
            len(record.steps),
            PipelineStep(nxt.kind, rid),
        )
        if appended is None:
            return
        try:
            self._request(steps, record, session, nxt, rid)
        except (DomainError, ApplicationError) as exc:
            details = {**exc.details, "step": nxt.kind, "step_id": rid}
            self._fail(record, ErrorInfo(exc.code, exc.message, details))

    def _request(
        self,
        steps: Phase1Steps,
        record: PipelineRecord,
        session: RecalibrationRecord,
        nxt: _Next,
        rid: str,
    ) -> None:
        """Crea el recurso de un paso ya reservado.

        Args:
            steps: Pasos de la Fase I.
            record: Tubería.
            session: Recalibración.
            nxt: Paso a crear.
            rid: Identificador reservado del recurso.
        """
        tenant, chart, pid = record.tenant_id, record.chart_id, record.pipeline_id
        model_id = session.model_id
        if nxt.kind == STEP_FIT:
            self.request_fit.create(
                tenant,
                chart,
                nxt.target,
                steps.fit_params_of(record.params),
                steps=steps,
                fit_id=rid,
                pipeline_id=pid,
            )
        elif nxt.kind == STEP_LIMITS:
            self.request_limits.create(
                tenant,
                chart,
                nxt.target,
                None,
                steps=steps,
                recalibration_id=session.recalibration_id,
                limits_id=rid,
                pipeline_id=pid,
            )
        elif nxt.kind == STEP_EXCLUSION:
            self.request_exclusion.execute(
                tenant, chart, nxt.target, exclusion_id=rid, pipeline_id=pid
            )
        elif nxt.kind == STEP_EXTENSION:
            # Síncrona: construye el dataset y avisa a la tubería para que siga.
            self.request_extension.execute(
                tenant,
                chart,
                model_id,
                session.recalibration_id,
                dataset_id=nxt.target,
                extension_id=rid,
            )
            notify_pipeline(self.queue, tenant, chart, pid)
        else:
            self.request_proposal.execute(
                tenant,
                chart,
                model_id,
                session.recalibration_id,
                fit_id=nxt.target,
                limits_id=nxt.limits_id or "",
            )

    def _fail(self, record: PipelineRecord, error: ErrorInfo) -> None:
        """Cierra la tubería y la recalibración (si siguen en curso) en ``failed``.

        Args:
            record: Tubería.
            error: Error.
        """
        current = get_pipeline(
            self.pipelines, record.tenant_id, record.chart_id, record.pipeline_id
        )
        if current.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
            return
        now = self.clock.now()
        self.pipelines.update(
            replace(current, status=JobStatus.FAILED, finished_at=now, error=error)
        )
        session = self._session(record)
        if session.status in _IN_PROGRESS:
            self.recalibrations.update(
                replace(session, status=JobStatus.FAILED, finished_at=now, error=error)
            )

    def _succeed(self, record: PipelineRecord) -> None:
        """Cierra la tubería en ``succeeded`` (la recalibración ya la cerró su último paso).

        Args:
            record: Tubería.
        """
        current = get_pipeline(
            self.pipelines, record.tenant_id, record.chart_id, record.pipeline_id
        )
        if current.status is not JobStatus.RUNNING:
            return
        self.pipelines.update(
            replace(current, status=JobStatus.SUCCEEDED, finished_at=self.clock.now())
        )
