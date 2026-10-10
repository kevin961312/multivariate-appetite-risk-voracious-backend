"""Raíz de composición: construye y cablea las dependencias del proceso.

Único lugar que conoce todas las capas: elige los adaptadores según ``config``, registra las
cartas y construye los casos de uso y la cola con un manejador por tipo de trabajo. Un valor de
configuración sin adaptador hace fallar el arranque (nunca se ignora en silencio).
"""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import structlog

from voracious.application.charts import AnyChart, ChartRegistry
from voracious.application.phase1_steps import Phase1Steps, Phase1StepsRegistry
from voracious.application.ports import (
    ComparisonRepository,
    DatasetStorage,
    ExclusionRepository,
    FitRepository,
    JobKind,
    JobLane,
    JobRequest,
    LimitsRepository,
    ModelRepository,
    ModelVersionRepository,
    MonitoringRepository,
    ObservationRepository,
    PipelineRepository,
    RecalibrationRepository,
    SignalAnnotationRepository,
    StructuralEventRepository,
)
from voracious.application.recalibration_steps import (
    RecalibrationSteps,
    RecalibrationStepsRegistry,
)
from voracious.application.use_cases import (
    AnnotateSignal,
    ApproveVersion,
    CancelRecalibration,
    GetChartStatus,
    GetComparison,
    GetDataset,
    GetExclusion,
    GetFit,
    GetLimits,
    GetModel,
    GetMonitoring,
    GetPipeline,
    GetRecalibration,
    GetVersion,
    ListObservations,
    ListStructuralEvents,
    ListVersions,
    MonitorObservations,
    RecalibrationChain,
    RecoverInterruptedJobs,
    RegisterStructuralEvent,
    RejectVersion,
    RequestComparison,
    RequestExclusion,
    RequestFit,
    RequestLimits,
    RequestModel,
    RequestPhase1Pipeline,
    RequestRecalibration,
    RequestVersionProposal,
    RunComparisonJob,
    RunExclusionJob,
    RunFitJob,
    RunLimitsJob,
    RunModelAssemblyJob,
    RunMonitoringJob,
    RunPhase1Pipeline,
    RunPipelineJob,
    RunRecalibrationJob,
    RunVersionProposalJob,
    UploadDataset,
)
from voracious.config import Settings
from voracious.domain.charts.t2mrcd import CHART_ID as T2MRCD_CHART_ID
from voracious.domain.charts.t2mrcd import T2MRCDChart
from voracious.domain.common import SerialTaskMapper, TaskMapper
from voracious.infrastructure.charts import T2MRCDPhase1Steps, T2MRCDRecalibrationSteps
from voracious.infrastructure.clock import SystemClock
from voracious.infrastructure.ids import UuidIdGenerator
from voracious.infrastructure.jobs import InlineJobQueue, JobHandler
from voracious.infrastructure.logging import configure_logging
from voracious.infrastructure.memory import (
    ComparisonRecordCodec,
    ExclusionRecordCodec,
    FitRecordCodec,
    InMemoryComparisonRepository,
    InMemoryDatasetStorage,
    InMemoryExclusionRepository,
    InMemoryFitRepository,
    InMemoryLimitsRepository,
    InMemoryModelRepository,
    InMemoryModelVersionRepository,
    InMemoryMonitoringRepository,
    InMemoryObservationRepository,
    InMemoryPipelineRepository,
    InMemoryRecalibrationRepository,
    InMemorySignalAnnotationRepository,
    InMemoryStructuralEventRepository,
    LimitsRecordCodec,
    ModelRecordCodec,
    ModelVersionCodec,
    MonitoringRecordCodec,
    ObservationRecordCodec,
    PipelineRecordCodec,
    RecalibrationRecordCodec,
    SignalAnnotationCodec,
    StructuralEventCodec,
)
from voracious.infrastructure.parallel import ProcessPoolTaskMapper
from voracious.infrastructure.postgres import (
    PostgresComparisonRepository,
    PostgresDatasetStorage,
    PostgresExclusionRepository,
    PostgresFitRepository,
    PostgresLimitsRepository,
    PostgresModelRepository,
    PostgresModelVersionRepository,
    PostgresMonitoringRepository,
    PostgresObservationRepository,
    PostgresPipelineRepository,
    PostgresRecalibrationRepository,
    PostgresSignalAnnotationRepository,
    PostgresStructuralEventRepository,
    create_pool,
    database_ready,
    migrate,
)
from voracious.infrastructure.storage import LocalDatasetStorage, LocalMatrixStore

__all__ = ["ConfigurationError", "Container", "UseCases", "build_container", "run_migrations"]

_log = structlog.get_logger(__name__)


_ADAPTERS: Mapping[str, frozenset[str]] = {
    "job_backend": frozenset({"inline"}),
    "repository": frozenset({"memory", "postgres"}),
    "storage": frozenset({"memory", "local"}),
}
"""Valores de configuración con adaptador construido (el resto hace fallar el arranque)."""

_PENDING_ADAPTERS: Mapping[tuple[str, str], str] = {}


class ConfigurationError(ValueError):
    """Un valor de configuración no tiene adaptador; el proceso no arranca."""


@dataclass(frozen=True)
class UseCases:
    """Casos de uso que llama la API.

    Attributes:
        upload_dataset: Subida de un dataset (JSON o CSV).
        get_dataset: Consulta de un dataset con su linaje.
        request_fit: Ajuste del estimador (``/fits``).
        get_fit: Consulta de un ajuste.
        request_limits: Límites sobre un ajuste (``/limits``).
        get_limits: Consulta de unos límites.
        request_exclusion: Exclusión humana (``/exclusions``).
        get_exclusion: Consulta de una exclusión.
        request_model: Ensamblado de un modelo a partir de referencias (``/models``).
        request_pipeline: Fase I completa por pasos (``/pipelines/phase1``).
        get_pipeline: Consulta de una tubería.
        get_model: Consulta de un modelo.
        monitor: Puntuación de observaciones (``scores``).
        get_monitoring: Consulta de una puntuación.
        list_observations: Observaciones registradas.
        annotate: Anotación de una señal.
        register_event: Registro de un evento estructural.
        list_events: Eventos estructurales.
        list_versions: Versiones.
        get_version: Una versión.
        approve: Aprobación de una propuesta.
        reject: Rechazo de una propuesta.
        status: Estado de la carta.
        request_recalibration: Recalibración (paso a paso o tubería).
        get_recalibration: Consulta de una recalibración.
        cancel_recalibration: Cancelación de una sesión paso a paso.
        request_comparison: Comparación de bases de una recalibración (``…/comparisons``).
        get_comparison: Consulta de una comparación.
        request_version_proposal: Propuesta de versión de una recalibración (``…/versions``).
    """

    upload_dataset: UploadDataset
    get_dataset: GetDataset
    request_fit: RequestFit
    get_fit: GetFit
    request_limits: RequestLimits
    get_limits: GetLimits
    request_exclusion: RequestExclusion
    get_exclusion: GetExclusion
    request_model: RequestModel
    request_pipeline: RequestPhase1Pipeline
    get_pipeline: GetPipeline
    get_model: GetModel
    monitor: MonitorObservations
    get_monitoring: GetMonitoring
    list_observations: ListObservations
    annotate: AnnotateSignal
    register_event: RegisterStructuralEvent
    list_events: ListStructuralEvents
    list_versions: ListVersions
    get_version: GetVersion
    approve: ApproveVersion
    reject: RejectVersion
    status: GetChartStatus
    request_recalibration: RequestRecalibration
    get_recalibration: GetRecalibration
    cancel_recalibration: CancelRecalibration
    request_comparison: RequestComparison
    get_comparison: GetComparison
    request_version_proposal: RequestVersionProposal


@dataclass(frozen=True)
class Container:
    """Dependencias ya construidas que comparten la API y los workers.

    Attributes:
        settings: Configuración del proceso.
        charts: Cartas registradas por ``chart_id``.
        use_cases: Casos de uso de la API.
        handlers: Manejador de cada tipo de trabajo (los ``Run…Job``).
        queue: Cola de trabajos.
        recovery: Recuperación de los trabajos interrumpidos (se ejecuta en ``startup``).
        readiness: Comprobación de cada dependencia externa para ``/ready`` (``database`` con
            Postgres, ``storage`` con almacenamiento local).
        closers: Lo que se cierra al apagar (el pool de Postgres).
    """

    settings: Settings
    charts: ChartRegistry
    use_cases: UseCases
    handlers: Mapping[JobKind, JobHandler]
    queue: InlineJobQueue
    recovery: RecoverInterruptedJobs
    readiness: Mapping[str, Callable[[], bool]] = field(default_factory=dict)
    closers: tuple[Callable[[], None], ...] = ()

    def startup(self) -> Mapping[str, int]:
        """Arranque: cierra ``failed / JOB_INTERRUPTED`` lo que un reinicio dejó en curso.

        Lo llama el ``lifespan`` de la API antes de aceptar tráfico.

        Returns:
            Cuántos registros se cerraron de cada tipo.
        """
        counts = self.recovery.execute()
        if any(counts.values()):
            _log.warning("interrupted_jobs_failed", **counts)
        return counts

    def check_readiness(self) -> dict[str, bool]:
        """Comprueba cada dependencia externa.

        Returns:
            ``nombre → disponible``.
        """
        return {name: check() for name, check in self.readiness.items()}

    def handle(self, job: JobRequest) -> None:
        """Ejecuta un trabajo con su manejador (punto de entrada de los workers).

        Args:
            job: Petición.

        Raises:
            ValueError: Si no hay manejador para ``job.kind``.
        """
        handler = self.handlers.get(job.kind)
        if handler is None:
            msg = f"no hay manejador para los trabajos '{job.kind}'"
            raise ValueError(msg)
        handler(job)

    def shutdown(self, *, wait: bool = True) -> None:
        """Apaga la cola de trabajos (lo llama el ``lifespan`` de la API).

        Args:
            wait: Esperar a los trabajos en curso.
        """
        self.queue.shutdown(wait=wait)
        for close in self.closers:
            close()


def _build_charts(settings: Settings) -> dict[str, AnyChart]:
    """Registro de cartas de producción.

    ``settings.mrcd_threads`` llega a la carta, que lo pasa a cada ajuste MRCD (base, réplicas y
    pruebas de cambio). Solo cambia el rendimiento, no ningún bit.

    Args:
        settings: Configuración.

    Returns:
        ``chart_id → carta``.
    """
    return {T2MRCD_CHART_ID: T2MRCDChart(mrcd_threads=settings.mrcd_threads)}


def _build_steps(charts: ChartRegistry) -> dict[str, Phase1Steps]:
    """Pasos encadenables de Fase I de las cartas que los exponen (hoy, T²MRCD).

    Args:
        charts: Registro de cartas.

    Returns:
        ``chart_id → pasos``.
    """
    steps: dict[str, Phase1Steps] = {}
    for chart_id, chart in charts.items():
        if isinstance(chart, T2MRCDChart):
            steps[chart_id] = T2MRCDPhase1Steps(chart)
    return steps


def _build_recalibration_steps(charts: ChartRegistry) -> dict[str, RecalibrationSteps]:
    """Pasos encadenables de la recalibración de las cartas que los exponen (hoy, T²MRCD).

    Args:
        charts: Registro de cartas.

    Returns:
        ``chart_id → pasos``.
    """
    steps: dict[str, RecalibrationSteps] = {}
    for chart_id, chart in charts.items():
        if isinstance(chart, T2MRCDChart):
            steps[chart_id] = T2MRCDRecalibrationSteps(chart)
    return steps


@dataclass(frozen=True)
class _Repositories:
    """Repositorios y almacenamiento de un adaptador, con sus comprobaciones y cierres."""

    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    exclusions: ExclusionRepository
    pipelines: PipelineRepository
    models: ModelRepository
    monitorings: MonitoringRepository
    versions: ModelVersionRepository
    observations: ObservationRepository
    annotations: SignalAnnotationRepository
    events: StructuralEventRepository
    recalibrations: RecalibrationRepository
    comparisons: ComparisonRepository
    readiness: Mapping[str, Callable[[], bool]]
    closers: tuple[Callable[[], None], ...] = ()


def _storage_dir(settings: Settings) -> LocalMatrixStore | None:
    """Almacén local de matrices si ``storage=local``.

    Args:
        settings: Configuración.

    Returns:
        El almacén, o ``None`` con ``storage=memory``.

    Raises:
        ConfigurationError: Si ``storage=local`` sin ``VORACIOUS_STORAGE_DIR``.
    """
    if settings.storage != "local":
        return None
    if settings.storage_dir is None:
        msg = "VORACIOUS_STORAGE=local exige VORACIOUS_STORAGE_DIR"
        raise ConfigurationError(msg)
    return LocalMatrixStore(settings.storage_dir)


def _build_storage(settings: Settings) -> DatasetStorage:
    """Almacenamiento de datasets según ``storage`` (repositorios en memoria).

    Args:
        settings: Configuración.

    Returns:
        El almacenamiento.

    Raises:
        ConfigurationError: Si ``storage=local`` sin ``VORACIOUS_STORAGE_DIR``.
    """
    if settings.storage == "local":
        if settings.storage_dir is None:
            msg = "VORACIOUS_STORAGE=local exige VORACIOUS_STORAGE_DIR"
            raise ConfigurationError(msg)
        return LocalDatasetStorage(settings.storage_dir)
    return InMemoryDatasetStorage()


def _memory_repositories(
    settings: Settings,
    registry: ChartRegistry,
    steps: Phase1StepsRegistry,
    rsteps: RecalibrationStepsRegistry,
) -> _Repositories:
    """Repositorios en memoria (``repository=memory``), con los mismos codecs que Postgres.

    Args:
        settings: Configuración.
        registry: Cartas.
        steps: Pasos de Fase I.
        rsteps: Pasos de la recalibración.

    Returns:
        Los repositorios.
    """
    datasets = _build_storage(settings)
    readiness: dict[str, Callable[[], bool]] = {}
    if isinstance(datasets, LocalDatasetStorage):
        readiness["storage"] = datasets.matrices.writable
    return _Repositories(
        datasets=datasets,
        fits=InMemoryFitRepository(FitRecordCodec(steps)),
        limits=InMemoryLimitsRepository(LimitsRecordCodec(steps)),
        exclusions=InMemoryExclusionRepository(ExclusionRecordCodec()),
        pipelines=InMemoryPipelineRepository(PipelineRecordCodec()),
        models=InMemoryModelRepository(ModelRecordCodec(registry)),
        monitorings=InMemoryMonitoringRepository(MonitoringRecordCodec()),
        versions=InMemoryModelVersionRepository(ModelVersionCodec(registry)),
        observations=InMemoryObservationRepository(ObservationRecordCodec()),
        annotations=InMemorySignalAnnotationRepository(SignalAnnotationCodec()),
        events=InMemoryStructuralEventRepository(StructuralEventCodec()),
        recalibrations=InMemoryRecalibrationRepository(RecalibrationRecordCodec(registry)),
        comparisons=InMemoryComparisonRepository(ComparisonRecordCodec(rsteps)),
        readiness=readiness,
    )


def _database_url(settings: Settings) -> str:
    """Cadena de conexión revelada solo para abrir la conexión (nunca se registra).

    Args:
        settings: Configuración.

    Returns:
        La cadena.

    Raises:
        ConfigurationError: Si falta ``VORACIOUS_DATABASE_URL``.
    """
    if settings.database_url is None or not settings.database_url.get_secret_value():
        msg = "VORACIOUS_REPOSITORY=postgres exige VORACIOUS_DATABASE_URL"
        raise ConfigurationError(msg)
    return settings.database_url.get_secret_value()


def _postgres_repositories(
    settings: Settings,
    registry: ChartRegistry,
    steps: Phase1StepsRegistry,
    rsteps: RecalibrationStepsRegistry,
) -> _Repositories:
    """Repositorios en Postgres (``repository=postgres``); la matriz de los datasets, en disco.

    Args:
        settings: Configuración.
        registry: Cartas.
        steps: Pasos de Fase I.
        rsteps: Pasos de la recalibración.

    Returns:
        Los repositorios.

    Raises:
        ConfigurationError: Sin ``VORACIOUS_DATABASE_URL`` o sin ``storage=local`` con su
            directorio (la matriz de los datasets no vive en Postgres).
    """
    url = _database_url(settings)
    matrices = _storage_dir(settings)
    if matrices is None:
        msg = "VORACIOUS_REPOSITORY=postgres exige VORACIOUS_STORAGE=local (matrices en disco)"
        raise ConfigurationError(msg)
    pool = create_pool(url, settings.database_pool_size)
    return _Repositories(
        datasets=PostgresDatasetStorage(pool, matrices),
        fits=PostgresFitRepository(pool, FitRecordCodec(steps)),
        limits=PostgresLimitsRepository(pool, LimitsRecordCodec(steps)),
        exclusions=PostgresExclusionRepository(pool, ExclusionRecordCodec()),
        pipelines=PostgresPipelineRepository(pool, PipelineRecordCodec()),
        models=PostgresModelRepository(pool, ModelRecordCodec(registry)),
        monitorings=PostgresMonitoringRepository(pool, MonitoringRecordCodec()),
        versions=PostgresModelVersionRepository(pool, ModelVersionCodec(registry)),
        observations=PostgresObservationRepository(pool, ObservationRecordCodec()),
        annotations=PostgresSignalAnnotationRepository(pool, SignalAnnotationCodec()),
        events=PostgresStructuralEventRepository(pool, StructuralEventCodec()),
        recalibrations=PostgresRecalibrationRepository(pool, RecalibrationRecordCodec(registry)),
        comparisons=PostgresComparisonRepository(pool, ComparisonRecordCodec(rsteps)),
        readiness={"database": lambda: database_ready(pool), "storage": matrices.writable},
        closers=(pool.close,),
    )


def run_migrations(settings: Settings | None = None) -> list[str]:
    """Aplica las migraciones pendientes de Postgres (``python -m voracious.cli migrate``).

    Args:
        settings: Configuración; ``None`` la lee del entorno.

    Returns:
        Las versiones aplicadas ahora.

    Raises:
        ConfigurationError: Si ``repository`` no es ``postgres`` o falta la URL.
    """
    resolved = settings if settings is not None else Settings()
    configure_logging(resolved.log_level)
    if resolved.repository != "postgres":
        msg = "las migraciones exigen VORACIOUS_REPOSITORY=postgres"
        raise ConfigurationError(msg)
    applied = migrate(_database_url(resolved))
    _log.info("migrations_applied", versions=applied)
    return applied


def _build_mapper(settings: Settings) -> TaskMapper:
    """Reparto de réplicas: en serie o en procesos según ``replicate_processes``.

    Args:
        settings: Configuración.

    Returns:
        El mapper.
    """
    if settings.replicate_processes is None:
        return SerialTaskMapper()
    return ProcessPoolTaskMapper(settings.replicate_processes, settings.mrcd_threads)


def oversubscribed(settings: Settings, cpu_count: int | None) -> bool:
    """Indica si procesos por hilos de ``pymrcd`` superan los núcleos.

    Con ``mrcd_threads`` vacío ``pymrcd`` usa todos los núcleos en cada proceso.

    Args:
        settings: Configuración.
        cpu_count: Núcleos visibles (``None`` si no se conocen: no se avisa).

    Returns:
        ``True`` si hay sobresuscripción.
    """
    if cpu_count is None or settings.replicate_processes is None:
        return False
    threads = settings.mrcd_threads if settings.mrcd_threads is not None else cpu_count
    return settings.replicate_processes * threads > cpu_count


def _check_adapters(settings: Settings) -> None:
    """Falla si algún adaptador configurado no existe.

    Args:
        settings: Configuración.

    Raises:
        ConfigurationError: Si ``job_backend``, ``repository`` o ``storage`` no tienen
            adaptador.
    """
    for name, supported in _ADAPTERS.items():
        value = str(getattr(settings, name))
        if value not in supported:
            hint = _PENDING_ADAPTERS.get((name, value), "")
            msg = f"VORACIOUS_{name.upper()}={value!r} no tiene adaptador{hint}"
            raise ConfigurationError(msg)


def build_container(
    settings: Settings | None = None, *, charts: Mapping[str, AnyChart] | None = None
) -> Container:
    """Construye el contenedor y configura el logging.

    Args:
        settings: Configuración a usar; si es ``None`` se lee del entorno ``VORACIOUS_*``.
        charts: Registro de cartas; ``None`` usa el de producción. Los tests inyectan aquí
            cartas con estrategias «SOLO TEST» (que nunca viven en ``src/``).

    Returns:
        El contenedor con todas las dependencias cableadas.

    Raises:
        ConfigurationError: Si un adaptador configurado no existe o le falta configuración.
    """
    resolved = settings if settings is not None else Settings()
    configure_logging(resolved.log_level)
    _check_adapters(resolved)
    if oversubscribed(resolved, os.cpu_count()):
        _log.warning(
            "replicate_oversubscription",
            replicate_processes=resolved.replicate_processes,
            mrcd_threads=resolved.mrcd_threads,
            cpu_count=os.cpu_count(),
        )
    registry: ChartRegistry = dict(charts) if charts is not None else _build_charts(resolved)
    steps: Phase1StepsRegistry = _build_steps(registry)
    rsteps: RecalibrationStepsRegistry = _build_recalibration_steps(registry)
    build = _postgres_repositories if resolved.repository == "postgres" else _memory_repositories
    repos = build(resolved, registry, steps, rsteps)
    datasets, fits, limits = repos.datasets, repos.fits, repos.limits
    exclusions, pipelines, models = repos.exclusions, repos.pipelines, repos.models
    monitorings, versions, observations = repos.monitorings, repos.versions, repos.observations
    annotations, events = repos.annotations, repos.events
    recalibrations, comparisons = repos.recalibrations, repos.comparisons
    ids = UuidIdGenerator()
    clock = SystemClock()
    mapper = _build_mapper(resolved)

    handlers: dict[JobKind, JobHandler] = {}
    queue = InlineJobQueue(
        handlers,
        {
            JobLane.ESTIMATION: resolved.queue_workers_estimation,
            JobLane.CALIBRATION: resolved.queue_workers_calibration,
            JobLane.LIGHT: resolved.queue_workers_light,
            JobLane.ORCHESTRATION: resolved.queue_workers_orchestration,
        },
    )
    chain = RecalibrationChain(rsteps, recalibrations, versions, annotations, clock)
    request_fit = RequestFit(steps, datasets, fits, queue, ids, clock)
    request_limits = RequestLimits(steps, datasets, fits, limits, queue, ids, clock, chain)
    request_exclusion = RequestExclusion(steps, datasets, exclusions, queue, ids, clock, chain)
    request_model = RequestModel(steps, datasets, fits, limits, models, queue, ids, clock)
    request_comparison = RequestComparison(
        registry,
        rsteps,
        recalibrations,
        datasets,
        fits,
        limits,
        comparisons,
        queue,
        ids,
        clock,
    )
    request_proposal = RequestVersionProposal(
        rsteps, recalibrations, versions, datasets, fits, limits, comparisons, queue, clock
    )
    handlers.update(
        {
            JobKind.MRCD_FIT: RunFitJob(steps, datasets, fits, queue, clock).execute,
            JobKind.LIMITS: RunLimitsJob(
                steps, datasets, fits, limits, mapper, queue, clock
            ).execute,
            JobKind.EXCLUSION: RunExclusionJob(
                steps, datasets, exclusions, queue, ids, clock, chain
            ).execute,
            JobKind.MODEL_ASSEMBLY: RunModelAssemblyJob(
                steps, datasets, fits, limits, models, versions, queue, clock
            ).execute,
            JobKind.PIPELINE: RunPipelineJob(
                pipelines,
                RunPhase1Pipeline(
                    steps,
                    pipelines,
                    fits,
                    limits,
                    exclusions,
                    models,
                    request_exclusion,
                    request_fit,
                    request_limits,
                    request_model,
                    ids,
                    clock,
                ),
                RunRecalibrationJob(
                    registry,
                    steps,
                    pipelines,
                    recalibrations,
                    fits,
                    limits,
                    exclusions,
                    comparisons,
                    datasets,
                    chain,
                    request_exclusion,
                    request_fit,
                    request_limits,
                    request_comparison,
                    request_proposal,
                    ids,
                    clock,
                ),
            ).execute,
            JobKind.SCORE: RunMonitoringJob(
                registry, models, versions, monitorings, observations, ids, clock
            ).execute,
            JobKind.COMPARISON: RunComparisonJob(
                rsteps,
                recalibrations,
                versions,
                datasets,
                fits,
                comparisons,
                mapper,
                queue,
                ids,
                clock,
            ).execute,
            JobKind.VERSION_PROPOSAL: RunVersionProposalJob(
                rsteps,
                models,
                versions,
                events,
                recalibrations,
                datasets,
                fits,
                limits,
                exclusions,
                comparisons,
                queue,
                clock,
            ).execute,
        }
    )
    use_cases = UseCases(
        upload_dataset=UploadDataset(datasets, ids, clock),
        get_dataset=GetDataset(datasets),
        request_fit=request_fit,
        get_fit=GetFit(steps, fits),
        request_limits=request_limits,
        get_limits=GetLimits(steps, limits),
        request_exclusion=request_exclusion,
        get_exclusion=GetExclusion(steps, exclusions),
        request_model=request_model,
        request_pipeline=RequestPhase1Pipeline(steps, datasets, pipelines, queue, ids, clock),
        get_pipeline=GetPipeline(steps, pipelines),
        get_model=GetModel(registry, models),
        monitor=MonitorObservations(registry, models, versions, monitorings, queue, ids, clock),
        get_monitoring=GetMonitoring(registry, monitorings),
        list_observations=ListObservations(registry, models, observations, annotations),
        annotate=AnnotateSignal(registry, observations, annotations, ids, clock),
        register_event=RegisterStructuralEvent(registry, models, versions, events, ids, clock),
        list_events=ListStructuralEvents(registry, models, events),
        list_versions=ListVersions(registry, models, versions),
        get_version=GetVersion(registry, versions),
        approve=ApproveVersion(registry, models, versions, observations, clock),
        reject=RejectVersion(registry, versions, clock),
        status=GetChartStatus(registry, models, versions, observations, events, clock),
        request_recalibration=RequestRecalibration(
            registry,
            rsteps,
            models,
            versions,
            observations,
            events,
            recalibrations,
            datasets,
            pipelines,
            queue,
            ids,
            clock,
        ),
        get_recalibration=GetRecalibration(registry, recalibrations),
        cancel_recalibration=CancelRecalibration(registry, recalibrations, clock),
        request_comparison=request_comparison,
        get_comparison=GetComparison(registry, comparisons),
        request_version_proposal=request_proposal,
    )
    return Container(
        settings=resolved,
        charts=registry,
        use_cases=use_cases,
        handlers=handlers,
        queue=queue,
        recovery=RecoverInterruptedJobs(
            fits,
            limits,
            exclusions,
            pipelines,
            models,
            monitorings,
            recalibrations,
            comparisons,
            versions,
            clock,
        ),
        readiness=repos.readiness,
        closers=repos.closers,
    )
