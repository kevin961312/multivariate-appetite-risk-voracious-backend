"""Tubería de Fase I (``/pipelines/phase1``): orquestación pura de los pasos encadenables.

No calcula nada: cada paso crea su recurso con el mismo caso de uso que la API por pasos
(``RequestExclusion``, ``RequestFit``, ``RequestLimits``, ``RequestModel``) y, al terminar, el
trabajo del paso encola el de la tubería, que decide el siguiente (continuaciones). Por eso la
tubería, la cadena manual y ``fit_phase1`` dan el mismo modelo en bits.

Orden: (si hay ``assignable_cause``: exclusión humana sobre el dataset raíz, sin ajuste) →
ajuste → límites → modelo con ese ajuste y esos límites. Sin depuración automática iterativa
(decisión del dueño, 2026-10-09). Si un paso falla (también si su recurso no se puede crear), la
tubería falla con su error (``details.step`` y ``details.step_id``). Las decisiones pendientes se
comprueban antes del primer paso.

El avance es atómico (``PipelineRepository.append_step`` con el número de pasos esperado): si dos
avisos llegan a la vez, solo uno crea el paso siguiente.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from voracious.application.errors import ApplicationError, PipelineNotFoundError
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
    PipelineRepository,
)
from voracious.application.records import (
    AssignableCause,
    ErrorInfo,
    JobStatus,
    LifecyclePolicy,
    PipelineKind,
    PipelineRecord,
    PipelineStep,
)
from voracious.application.use_cases.common import INTERNAL_ERROR
from voracious.application.use_cases.steps import (
    RequestExclusion,
    RequestFit,
    RequestLimits,
    RequestModel,
    get_dataset,
    get_exclusion,
    get_fit,
    get_limits,
    human_mask,
)
from voracious.domain.common import DomainError, InvalidInputError

__all__ = [
    "GetPipeline",
    "RequestPhase1Pipeline",
    "RunPhase1Pipeline",
    "get_pipeline",
]

STEP_EXCLUSION = "exclusion"
STEP_FIT = "fit"
STEP_LIMITS = "limits"
STEP_MODEL = "model"


def get_pipeline(
    pipelines: PipelineRepository, tenant_id: str, chart_id: str, pipeline_id: str
) -> PipelineRecord:
    """Busca una tubería o lanza ``PipelineNotFoundError``.

    Args:
        pipelines: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        pipeline_id: Tubería.

    Returns:
        La tubería.

    Raises:
        PipelineNotFoundError: Si no existe para esa clave.
    """
    record = pipelines.get(tenant_id, chart_id, pipeline_id)
    if record is None:
        raise PipelineNotFoundError(
            f"la tubería '{pipeline_id}' no existe", details={"pipeline_id": pipeline_id}
        )
    return record


@dataclass(frozen=True)
class RequestPhase1Pipeline:
    """Valida y encola una Fase I completa por pasos (``POST /pipelines/phase1``).

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento.
        pipelines: Repositorio de tuberías.
        queue: Cola.
        ids: Identificadores.
        clock: Reloj.
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    pipelines: PipelineRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        dataset_id: str,
        params: object,
        assignable_cause: Sequence[AssignableCause] = (),
        lifecycle_policy: LifecyclePolicy | None = None,
    ) -> str:
        """Encola la tubería.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            dataset_id: Dataset raíz (subido).
            params: Parámetros de la carta.
            assignable_cause: Filas del dataset raíz con causa asignable.
            lifecycle_policy: Política del modelo resultante.

        Returns:
            El ``pipeline_id``.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            DatasetNotFoundError: Si el dataset no existe.
            InvalidInputError: Si la carta no admite el dataset o una fila es inválida.
        """
        steps = resolve_steps(self.steps, chart_id)
        dataset = get_dataset(self.datasets, tenant_id, dataset_id)
        steps.validate_input(dataset.data)
        causes = tuple(assignable_cause)
        human = human_mask(causes, dataset.data.shape[0])
        if causes and bool(human.all()):
            raise InvalidInputError(
                "la exclusión humana no puede quitar todas las filas",
                details={"field": "assignable_cause", "n": int(human.size)},
            )
        record = PipelineRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            pipeline_id=self.ids.new_id(),
            kind=PipelineKind.PHASE1,
            status=JobStatus.QUEUED,
            dataset_id=dataset_id,
            params=steps.encode_params(params),
            assignable_cause=causes,
            lifecycle_policy=lifecycle_policy
            if lifecycle_policy is not None
            else LifecyclePolicy(),
            created_at=self.clock.now(),
        )
        self.pipelines.add(record)
        self.queue.enqueue(JobRequest(JobKind.PIPELINE, tenant_id, chart_id, record.pipeline_id))
        return record.pipeline_id


@dataclass(frozen=True)
class GetPipeline:
    """Consulta una tubería.

    Attributes:
        steps: Pasos de Fase I por carta.
        pipelines: Repositorio.
    """

    steps: Phase1StepsRegistry
    pipelines: PipelineRepository

    def execute(self, tenant_id: str, chart_id: str, pipeline_id: str) -> PipelineRecord:
        """Devuelve la tubería.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            pipeline_id: Tubería.

        Returns:
            El registro.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            PipelineNotFoundError: Si no existe.
        """
        resolve_steps(self.steps, chart_id)
        return get_pipeline(self.pipelines, tenant_id, chart_id, pipeline_id)


@dataclass(frozen=True)
class _Next:
    """Paso siguiente decidido por la tubería."""

    kind: str
    target: str
    """Dataset (``exclusion`` y ``fit``) o ajuste (``limits`` y ``model``)."""
    limits_id: str | None = None


@dataclass(frozen=True)
class RunPhase1Pipeline:
    """Avanza una tubería de Fase I (carril ``orchestration``): un paso por aviso.

    Attributes:
        steps: Pasos de Fase I por carta.
        pipelines: Repositorio de tuberías.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        exclusions: Repositorio de exclusiones.
        models: Repositorio de modelos.
        request_exclusion: Caso de uso de la exclusión humana.
        request_fit: Caso de uso del ajuste.
        request_limits: Caso de uso de los límites.
        request_model: Caso de uso del modelo.
        ids: Identificadores (reserva el id del paso antes de crearlo).
        clock: Reloj.
    """

    steps: Phase1StepsRegistry
    pipelines: PipelineRepository
    fits: FitRepository
    limits: LimitsRepository
    exclusions: ExclusionRepository
    models: ModelRepository
    request_exclusion: RequestExclusion
    request_fit: RequestFit
    request_limits: RequestLimits
    request_model: RequestModel
    ids: IdGenerator
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Arranca la tubería (``queued``) o la avanza (``running``); terminada, no hace nada.

        Args:
            job: Petición ``pipeline``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``pipeline`` o la tubería no es de Fase I.
            UnknownChartError: Si la carta no expone pasos.
            PipelineNotFoundError: Si la tubería no existe.
        """
        if job.kind is not JobKind.PIPELINE:
            msg = f"RunPhase1Pipeline solo ejecuta trabajos 'pipeline', no '{job.kind}'"
            raise ValueError(msg)
        steps = resolve_steps(self.steps, job.scope)
        record = get_pipeline(self.pipelines, job.tenant_id, job.scope, job.resource_id)
        if record.kind is not PipelineKind.PHASE1:
            msg = f"la tubería '{record.pipeline_id}' no es de Fase I"
            raise ValueError(msg)
        if record.status is JobStatus.QUEUED:
            claimed = self.pipelines.claim(
                job.tenant_id, job.scope, job.resource_id, self.clock.now()
            )
            if claimed is None:
                return
            record = claimed
            try:
                steps.check_params(record.params)
            except DomainError as exc:
                self._fail(record, ErrorInfo(exc.code, exc.message, exc.details))
                return
        if record.status is not JobStatus.RUNNING:
            return
        try:
            self._advance(steps, record)
        except (DomainError, ApplicationError) as exc:
            self._fail(record, ErrorInfo(exc.code, exc.message, exc.details))
        except Exception:
            self._fail(record, ErrorInfo(INTERNAL_ERROR, "error interno en la tubería"))
            raise

    def _advance(self, steps: Phase1Steps, record: PipelineRecord) -> None:
        """Decide y crea el paso siguiente si el último terminó bien.

        Args:
            steps: Pasos de la carta.
            record: Tubería en ``running``.
        """
        if not record.steps:
            first = _Next(
                STEP_EXCLUSION if record.assignable_cause else STEP_FIT, record.dataset_id
            )
            self._create(steps, record, first)
            return
        last = record.steps[-1]
        status, error = self._status(record, last)
        if status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return
        if status is JobStatus.FAILED:
            info = error if error is not None else ErrorInfo(INTERNAL_ERROR, "paso fallido")
            details = {**info.details, "step": last.kind, "step_id": last.resource_id}
            self._fail(record, ErrorInfo(info.code, info.message, details))
            return
        nxt = self._next(record, last)
        if nxt is None:
            self._succeed(record, last.resource_id)
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
        model = self.models.get(tenant, chart, rid)
        if model is None:
            return JobStatus.FAILED, ErrorInfo(INTERNAL_ERROR, "el modelo de la tubería no existe")
        return model.status, model.error

    def _next(self, record: PipelineRecord, last: PipelineStep) -> _Next | None:
        """Paso que sigue a uno terminado bien (``None``: la tubería terminó).

        Args:
            record: Tubería.
            last: Último paso, ``succeeded``.

        Returns:
            El paso siguiente o ``None``.

        Raises:
            TypeError: Si la exclusión terminó sin dataset de salida (error de integridad).
        """
        tenant, chart = record.tenant_id, record.chart_id
        if last.kind == STEP_EXCLUSION:
            exclusion = get_exclusion(self.exclusions, tenant, chart, last.resource_id)
            if exclusion.output_dataset_id is None:
                msg = "la exclusión de Fase I terminó sin dataset de salida"
                raise TypeError(msg)
            return _Next(STEP_FIT, exclusion.output_dataset_id)
        if last.kind == STEP_FIT:
            return _Next(STEP_LIMITS, last.resource_id)
        if last.kind == STEP_LIMITS:
            limits = get_limits(self.limits, tenant, chart, last.resource_id)
            return _Next(STEP_MODEL, limits.fit_id, limits_id=limits.limits_id)
        return None

    def _create(self, steps: Phase1Steps, record: PipelineRecord, nxt: _Next) -> None:
        """Reserva el paso (atómico) y crea su recurso con el caso de uso de la API.

        Si el recurso no se puede crear (validación síncrona del paso), la tubería falla con ese
        error y ``details.step``/``details.step_id``, como si el paso hubiera fallado.

        Args:
            steps: Pasos de la carta.
            record: Tubería.
            nxt: Paso a crear.
        """
        rid = self.ids.new_id()
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
            self._request(steps, record, nxt, rid)
        except (DomainError, ApplicationError) as exc:
            details = {**exc.details, "step": nxt.kind, "step_id": rid}
            self._fail(record, ErrorInfo(exc.code, exc.message, details))

    def _request(self, steps: Phase1Steps, record: PipelineRecord, nxt: _Next, rid: str) -> None:
        """Crea el recurso de un paso ya reservado.

        Args:
            steps: Pasos de la carta.
            record: Tubería.
            nxt: Paso a crear.
            rid: Identificador reservado del recurso.
        """
        tenant, chart, pid = record.tenant_id, record.chart_id, record.pipeline_id
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
                dict(record.params),
                steps=steps,
                limits_id=rid,
                pipeline_id=pid,
            )
        elif nxt.kind == STEP_EXCLUSION:
            self.request_exclusion.execute(
                tenant,
                chart,
                nxt.target,
                record.assignable_cause,
                exclusion_id=rid,
                pipeline_id=pid,
            )
        else:
            self.request_model.execute(
                tenant,
                chart,
                fit_id=nxt.target,
                limits_id=nxt.limits_id or "",
                lifecycle_policy=record.lifecycle_policy,
                model_id=rid,
                pipeline_id=pid,
            )

    def _fail(self, record: PipelineRecord, error: ErrorInfo) -> None:
        """Cierra la tubería en ``failed`` (si sigue en curso).

        Args:
            record: Tubería.
            error: Error.
        """
        current = get_pipeline(
            self.pipelines, record.tenant_id, record.chart_id, record.pipeline_id
        )
        if current.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
            return
        self.pipelines.update(
            replace(current, status=JobStatus.FAILED, finished_at=self.clock.now(), error=error)
        )

    def _succeed(self, record: PipelineRecord, model_id: str) -> None:
        """Cierra la tubería en ``succeeded`` con el modelo.

        Args:
            record: Tubería.
            model_id: Modelo resultante.
        """
        current = get_pipeline(
            self.pipelines, record.tenant_id, record.chart_id, record.pipeline_id
        )
        if current.status is not JobStatus.RUNNING:
            return
        self.pipelines.update(
            replace(
                current,
                status=JobStatus.SUCCEEDED,
                finished_at=self.clock.now(),
                model_id=model_id,
            )
        )
