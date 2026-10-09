"""Propuesta de versión de una recalibración por pasos (``POST …/versions``, vuelta 3.4).

``RequestVersionProposal`` valida de forma síncrona que los pasos pedidos sean los que exige la
decisión y encola (carril ``light``); ``RunVersionProposalJob`` ensambla el modelo con ellos, arma
el informe y crea la versión **propuesta** inmutable (solo rige al aprobarse).

- **EXTEND** (sin cambio detectado): ajuste y límites del dataset ``recalibration_extension``
  (linaje ``EXTENSION``, hueco ``(0, 0)``).
- **REPLACE** (cambio detectado o reemplazo forzado): ajuste y límites de las filas nuevas
  conservadas tras la exclusión humana (operación ``NEW_ROWS``, hueco ``(1, 0)``), reutilizados
  como hace ``ControlChart.recalibrate``.

Base nueva, justificación, ``base_hash``, ``base_refs``, exclusiones y la regla del evento
estructural son las de la recalibración en una sola llamada (ADR 0008).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from voracious.application.charts import as_versioned_model
from voracious.application.errors import (
    ApplicationError,
    ComparisonNotReadyError,
    ProposalPendingError,
    RecalibrationNotInProgressError,
    VersionInputsMismatchError,
)
from voracious.application.lifecycle import (
    base_content_hash,
    exclusion_reason,
    frozen_base,
    pending_proposal,
    unresolved_structural_event,
)
from voracious.application.phase1_steps import Calibration
from voracious.application.ports import (
    Clock,
    ComparisonRepository,
    DatasetStorage,
    ExclusionRepository,
    FitRepository,
    JobKind,
    JobQueue,
    JobRequest,
    LimitsRepository,
    ModelRepository,
    ModelVersionRepository,
    RecalibrationRepository,
    StructuralEventRepository,
)
from voracious.application.recalibration_steps import (
    RecalibrationSteps,
    RecalibrationStepsRegistry,
    resolve_recalibration_steps,
)
from voracious.application.records import (
    BaseRowRef,
    BaseRowSource,
    ComparisonRecord,
    DatasetRecord,
    DatasetSource,
    ErrorInfo,
    Exclusion,
    ExclusionReason,
    JobStatus,
    LimitsRecord,
    ModelVersion,
    ProposalRequest,
    RecalibrationRecord,
    VersionStatus,
)
from voracious.application.use_cases.common import (
    INTERNAL_ERROR,
    get_version,
    ready_model,
)
from voracious.application.use_cases.comparisons import get_comparison
from voracious.application.use_cases.observations import STRUCTURAL_EVENT_NOTE
from voracious.application.use_cases.recalibration_chain import (
    CandidateOutcome,
    candidate_outcome,
    get_recalibration,
    open_session,
)
from voracious.application.use_cases.steps import (
    dataset_chain,
    get_dataset,
    notify_pipeline,
    ready_fit,
    ready_limits,
)
from voracious.domain.common import (
    DomainError,
    FloatMatrix,
    RecalibrationDecision,
    RowDisposition,
)

__all__ = ["RequestVersionProposal", "RunVersionProposalJob", "justification", "new_base"]


def _mismatch(reason: str, **details: object) -> VersionInputsMismatchError:
    """Error ``VERSION_INPUTS_MISMATCH`` con su motivo.

    Args:
        reason: Motivo (``details.reason``).
        **details: Datos adicionales.

    Returns:
        El error.
    """
    return VersionInputsMismatchError(
        "los pasos pedidos no son los que exige la decisión de la recalibración",
        details={"reason": reason, **details},
    )


def _calibration(limits: LimitsRecord) -> Calibration:
    """Calibración guardada en unos límites.

    Args:
        limits: Límites ``succeeded``.

    Returns:
        La calibración.
    """
    clean = limits.clean_rows if limits.clean_rows is not None else np.zeros(0, np.bool_)
    return Calibration(limits=limits.result, clean=clean)


def justification(record: RecalibrationRecord, decision: RecalibrationDecision) -> str:
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
class NewBase:
    """Base de la versión propuesta y sus exclusiones."""

    data: FloatMatrix
    refs: tuple[BaseRowRef, ...]
    exclusions: tuple[Exclusion, ...]


def new_base(
    active: ModelVersion,
    decision: RecalibrationDecision,
    data: FloatMatrix,
    session: RecalibrationRecord,
    outcome: CandidateOutcome,
) -> NewBase:
    """Base de la versión nueva: ``data`` (la del modelo) con el origen de cada fila.

    ``EXTEND`` = base vigente + candidatas conservadas; ``REPLACE`` = solo las conservadas
    (vocabulario común, ``RecalibrationDecision``). Las exclusiones: primero las del rango que ya
    estaban en la base, después cada candidata excluida, en orden.

    Args:
        active: Versión base.
        decision: ``EXTEND`` o ``REPLACE``.
        data: Base con la que se ajustó el modelo nuevo.
        session: Recalibración (candidatas y ya presentes).
        outcome: Destino de las candidatas.

    Returns:
        La base nueva.

    Raises:
        TypeError: Si la decisión no es ``EXTEND`` ni ``REPLACE`` o las filas no cuadran con
            ``data`` (error de integración).
    """
    kept_refs = tuple(
        BaseRowRef(BaseRowSource.OBSERVATION, session.candidate_ids[i])
        for i, d in enumerate(outcome.dispositions)
        if d is RowDisposition.KEPT
    )
    if decision is RecalibrationDecision.EXTEND:
        refs = active.base_refs + kept_refs
    elif decision is RecalibrationDecision.REPLACE:
        refs = kept_refs
    else:
        msg = f"decisión de recalibración inesperada con modelo: {decision}"
        raise TypeError(msg)
    if len(refs) != data.shape[0]:
        msg = "la base del modelo nuevo no coincide con la reconstruida"
        raise TypeError(msg)
    exclusions = [
        Exclusion(
            ref=BaseRowRef(BaseRowSource.OBSERVATION, oid), reason=ExclusionReason.ALREADY_IN_BASE
        )
        for oid in session.already_in_base_ids
    ]
    for row, disposition in enumerate(outcome.dispositions):
        reason = exclusion_reason(disposition)
        if reason is None:
            continue
        exclusions.append(
            Exclusion(
                ref=BaseRowRef(BaseRowSource.OBSERVATION, session.candidate_ids[row]),
                reason=reason,
                annotation_id=outcome.annotation_ids.get(row)
                if reason is ExclusionReason.ASSIGNABLE_CAUSE
                else None,
            )
        )
    return NewBase(data, refs, tuple(exclusions))


@dataclass(frozen=True)
class RequestVersionProposal:
    """Valida y encola la propuesta de versión de una recalibración.

    Attributes:
        recalibration_steps: Pasos de la recalibración por carta.
        recalibrations: Repositorio de recalibraciones.
        versions: Repositorio de versiones.
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        comparisons: Repositorio de comparaciones.
        queue: Cola.
        clock: Reloj.
    """

    recalibration_steps: RecalibrationStepsRegistry
    recalibrations: RecalibrationRepository
    versions: ModelVersionRepository
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    comparisons: ComparisonRepository
    queue: JobQueue
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        recalibration_id: str,
        *,
        fit_id: str,
        limits_id: str,
        comparison_id: str | None = None,
    ) -> str:
        """Encola la propuesta; el trabajo es la recalibración (``GET …/recalibrations/{id}``).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración en curso.
            fit_id: Ajuste final.
            limits_id: Límites de ese ajuste.
            comparison_id: Comparación (obligatoria sin reemplazo forzado; prohibida con él).

        Returns:
            El ``recalibration_id``.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            RecalibrationNotFoundError: Si la recalibración no existe para ese modelo.
            RecalibrationNotInProgressError: Si ya no admite pasos o ya pidió su propuesta.
            ProposalPendingError: Si ya hay una propuesta sin resolver.
            FitNotFoundError: Si el ajuste no existe.
            FitNotReadyError: Si no está ``succeeded``.
            LimitsNotFoundError: Si los límites no existen.
            LimitsNotReadyError: Si no están ``succeeded``.
            LimitsFitMismatchError: Si los límites son de otro ajuste.
            ComparisonNotFoundError: Si la comparación no existe.
            ComparisonNotReadyError: Si no está ``succeeded``.
            VersionInputsMismatchError: Si los pasos no son los que exige la decisión.
        """
        resolve_recalibration_steps(self.recalibration_steps, chart_id)
        session = open_session(
            get_recalibration(self.recalibrations, tenant_id, chart_id, model_id, recalibration_id)
        )
        proposal = pending_proposal(self.versions.list(tenant_id, chart_id, model_id))
        if proposal is not None:
            raise ProposalPendingError(
                "ya hay una propuesta sin resolver", details={"version": proposal.number}
            )
        fit = ready_fit(self.fits, tenant_id, chart_id, fit_id)
        limits = ready_limits(self.limits, tenant_id, chart_id, limits_id)
        if limits.fit_id != fit_id:
            raise _mismatch("limits_of_another_fit", fit_id=fit_id, limits_id=limits_id)
        if limits.recalibration_id != recalibration_id:
            raise _mismatch("limits_not_of_recalibration", limits_id=limits_id)
        chain = dataset_chain(self.datasets, get_dataset(self.datasets, tenant_id, fit.dataset_id))
        if chain[0].origin_ref != recalibration_id:
            raise _mismatch("fit_not_of_recalibration", fit_id=fit_id)
        if session.force_replace:
            _check_forced(chain, fit_id, comparison_id)
        else:
            self._check_compared(session, chain, fit_id, limits_id, comparison_id)
        request = ProposalRequest(
            fit_id=fit_id,
            limits_id=limits_id,
            comparison_id=comparison_id,
            status=JobStatus.QUEUED,
            requested_at=self.clock.now(),
        )
        if (
            self.recalibrations.request_proposal(
                tenant_id, chart_id, model_id, recalibration_id, request
            )
            is None
        ):
            raise RecalibrationNotInProgressError(
                "la recalibración ya pidió su propuesta",
                details={"recalibration_id": recalibration_id, "reason": "concurrent_request"},
            )
        self.queue.enqueue(
            JobRequest(JobKind.VERSION_PROPOSAL, tenant_id, chart_id, recalibration_id, model_id)
        )
        return recalibration_id

    def _check_compared(
        self,
        session: RecalibrationRecord,
        chain: Sequence[DatasetRecord],
        fit_id: str,
        limits_id: str,
        comparison_id: str | None,
    ) -> None:
        """Con comparación: EXTEND usa el dataset de extensión; REPLACE, el ajuste comparado.

        Args:
            session: Recalibración.
            chain: Ascendencia del dataset del ajuste.
            fit_id: Ajuste.
            limits_id: Límites.
            comparison_id: Comparación (obligatoria).

        Raises:
            VersionInputsMismatchError: Si falta la comparación o los pasos no son los de su
                decisión.
            ComparisonNotFoundError: Si la comparación no existe.
            ComparisonNotReadyError: Si no está ``succeeded``.
        """
        if comparison_id is None:
            raise _mismatch("comparison_required")
        comparison = get_comparison(
            self.comparisons, session.tenant_id, session.chart_id, session.model_id, comparison_id
        )
        if comparison.status is not JobStatus.SUCCEEDED:
            raise ComparisonNotReadyError(
                f"la comparación '{comparison_id}' no está lista",
                details={"comparison_id": comparison_id, "status": str(comparison.status)},
            )
        if comparison.recalibration_id != session.recalibration_id:
            raise _mismatch("comparison_not_of_recalibration", comparison_id=comparison_id)
        if comparison.decision is RecalibrationDecision.EXTEND:
            if len(chain) != 1 or chain[0].dataset_id != comparison.extension_dataset_id:
                raise _mismatch(
                    "extend_uses_extension_dataset",
                    extension_dataset_id=comparison.extension_dataset_id,
                )
        elif (fit_id, limits_id) != (comparison.fit_id, comparison.limits_id):
            raise _mismatch(
                "replace_uses_compared_fit",
                fit_id=comparison.fit_id,
                limits_id=comparison.limits_id,
            )


def _check_forced(chain: Sequence[DatasetRecord], fit_id: str, comparison_id: str | None) -> None:
    """Reemplazo forzado: sin comparación y con el ajuste de las filas nuevas.

    Args:
        chain: Ascendencia del dataset del ajuste.
        fit_id: Ajuste.
        comparison_id: Debe ser ``None``.

    Raises:
        VersionInputsMismatchError: Si hay comparación o el ajuste no es de las filas nuevas.
    """
    if comparison_id is not None:
        raise _mismatch("forced_replace_has_no_comparison", comparison_id=comparison_id)
    if chain[0].source is not DatasetSource.RECALIBRATION_CANDIDATES:
        raise _mismatch("replace_uses_new_rows", fit_id=fit_id)


@dataclass(frozen=True)
class _Inputs:
    """Lo que la propuesta lee de los pasos encadenados."""

    decision: RecalibrationDecision
    comparison: object | None
    outcome: CandidateOutcome


@dataclass(frozen=True)
class RunVersionProposalJob:
    """Ensambla el modelo, el informe y la versión propuesta (carril ``light``).

    Attributes:
        recalibration_steps: Pasos de la recalibración por carta.
        models: Repositorio de modelos.
        versions: Repositorio de versiones (recibe la propuesta).
        events: Eventos estructurales.
        recalibrations: Repositorio de recalibraciones (el trabajo es la recalibración).
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        exclusions: Repositorio de exclusiones (destino de las candidatas).
        comparisons: Repositorio de comparaciones.
        queue: Cola (aviso a la tubería).
        clock: Reloj.
    """

    recalibration_steps: RecalibrationStepsRegistry
    models: ModelRepository
    versions: ModelVersionRepository
    events: StructuralEventRepository
    recalibrations: RecalibrationRepository
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    exclusions: ExclusionRepository
    comparisons: ComparisonRepository
    queue: JobQueue
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo; idempotente (``claim_proposal``).

        La propuesta se guarda con ``add_proposal_if_none``: si ya hay otra sin resolver, la
        recalibración termina ``failed / PROPOSAL_PENDING`` (D6). Si mientras se calculaba se
        registró un evento estructural nuevo, la versión se guarda ya ``rejected`` con la nota
        ``structural_event``. Un error con código deja la recalibración ``failed`` con él;
        cualquier otro, ``failed / INTERNAL_ERROR`` y se relanza.

        Args:
            job: Petición ``version_proposal`` (el recurso es la recalibración).

        Raises:
            ValueError: Si ``job`` no es de tipo ``version_proposal``.
            UnknownChartError: Si la carta no expone pasos.
            RecalibrationNotFoundError: Si la recalibración no existe.
        """
        if job.kind is not JobKind.VERSION_PROPOSAL or job.model_id is None:
            msg = f"RunVersionProposalJob solo ejecuta 'version_proposal', no '{job.kind}'"
            raise ValueError(msg)
        recalibration = resolve_recalibration_steps(self.recalibration_steps, job.scope)
        key = (job.tenant_id, job.scope, job.model_id)
        get_recalibration(self.recalibrations, *key, job.resource_id)
        claimed = self.recalibrations.claim_proposal(*key, job.resource_id)
        if claimed is None:
            return
        try:
            done = self._run(recalibration, claimed)
        except (DomainError, ApplicationError) as exc:
            self._close(claimed, error=ErrorInfo(exc.code, exc.message, exc.details))
            return
        except Exception:
            self._close(claimed, error=ErrorInfo(INTERNAL_ERROR, "error interno en la propuesta"))
            raise
        self._close(done)

    def _inputs(
        self,
        recalibration: RecalibrationSteps,
        session: RecalibrationRecord,
        proposal: ProposalRequest,
        dataset: DatasetRecord,
    ) -> _Inputs:
        """Decisión, comparación y destino de las candidatas.

        Args:
            recalibration: Pasos de la recalibración.
            session: Recalibración.
            proposal: Petición.
            dataset: Dataset del ajuste de la versión.

        Returns:
            Las entradas de la propuesta.
        """
        tenant, chart = session.tenant_id, session.chart_id
        if proposal.comparison_id is None:
            decision = recalibration.decide(
                None,
                n_kept=int(dataset.data.shape[0]),
                recalibration_params=session.params,
                force_replace=True,
            )
            outcome = candidate_outcome(
                self.exclusions, chart, dataset_chain(self.datasets, dataset)
            )
            return _Inputs(decision, None, outcome)
        comparison: ComparisonRecord = get_comparison(
            self.comparisons, tenant, chart, session.model_id, proposal.comparison_id
        )
        new_fit = ready_fit(self.fits, tenant, chart, comparison.fit_id)
        chain = dataset_chain(self.datasets, get_dataset(self.datasets, tenant, new_fit.dataset_id))
        if comparison.decision is None:
            msg = "la comparación terminada no tiene decisión"
            raise TypeError(msg)
        return _Inputs(
            comparison.decision,
            comparison.result,
            candidate_outcome(self.exclusions, chart, chain),
        )

    def _run(
        self, recalibration: RecalibrationSteps, session: RecalibrationRecord
    ) -> RecalibrationRecord:
        """Ensambla y guarda la versión propuesta.

        Args:
            recalibration: Pasos de la recalibración.
            session: Recalibración con la propuesta en ``running``.

        Returns:
            La recalibración con la decisión, el informe y la versión propuesta.
        """
        proposal = session.proposal
        if proposal is None:
            msg = "la recalibración no tiene propuesta pedida"
            raise TypeError(msg)
        key = (session.tenant_id, session.chart_id, session.model_id)
        ready_model(self.models, *key)
        active = get_version(self.versions, *key, session.base_version_number)
        fit = ready_fit(self.fits, session.tenant_id, session.chart_id, proposal.fit_id)
        limits = ready_limits(self.limits, session.tenant_id, session.chart_id, proposal.limits_id)
        dataset = get_dataset(self.datasets, session.tenant_id, fit.dataset_id)
        inputs = self._inputs(recalibration, session, proposal, dataset)
        model = recalibration.assemble_model(
            dataset.data, limits.params, fit.result, _calibration(limits)
        )
        report = recalibration.report(
            active.model,
            decision=inputs.decision,
            forced=session.force_replace,
            n_base=int(active.base_data.shape[0]),
            new_dispositions=inputs.outcome.dispositions,
            recalibration_params=session.params,
            comparison=inputs.comparison,
            model=model,
        )
        base = new_base(active, inputs.decision, dataset.data, session, inputs.outcome)
        if as_versioned_model(model).base_mask.shape != (base.data.shape[0],):
            msg = "la base del modelo nuevo no coincide con la reconstruida"
            raise TypeError(msg)
        number = 1 + max(v.number for v in self.versions.list(*key))
        now = self.clock.now()
        event = unresolved_structural_event(self.events.list(*key), self.versions.list(*key))
        superseded_by_event = event is not None and event.event_id != session.structural_event_id
        version = ModelVersion(
            tenant_id=session.tenant_id,
            chart_id=session.chart_id,
            model_id=session.model_id,
            number=number,
            status=VersionStatus.REJECTED if superseded_by_event else VersionStatus.PROPOSED,
            model=model,
            base_data=frozen_base(base.data),
            base_hash=base_content_hash(base.data),
            base_refs=base.refs,
            exclusions=base.exclusions,
            decision=inputs.decision,
            justification=justification(session, inputs.decision),
            created_at=now,
            report=report,
            recalibration_id=session.recalibration_id,
            structural_event_id=session.structural_event_id,
            previous_number=active.number,
            rejected_at=now if superseded_by_event else None,
            decision_note=STRUCTURAL_EVENT_NOTE if superseded_by_event else None,
        )
        if superseded_by_event:
            self.versions.add(version)
        elif not self.versions.add_proposal_if_none(version):
            pending = pending_proposal(self.versions.list(*key))
            raise ProposalPendingError(
                "ya hay una propuesta sin resolver",
                details={"version": None if pending is None else pending.number},
            )
        return replace(session, outcome=inputs.decision, report=report, proposed_version=number)

    def _close(self, record: RecalibrationRecord, *, error: ErrorInfo | None = None) -> None:
        """Cierra la recalibración (y su propuesta) y avisa a su tubería.

        Args:
            record: Recalibración (con la versión si terminó bien).
            error: Error si falló.
        """
        status = JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED
        proposal = record.proposal
        self.recalibrations.update(
            replace(
                record,
                status=status,
                finished_at=self.clock.now(),
                error=error,
                proposal=None if proposal is None else replace(proposal, status=status),
            )
        )
        notify_pipeline(self.queue, record.tenant_id, record.chart_id, record.pipeline_id)
