"""Comparación de bases de una recalibración por pasos (``/comparisons``, vuelta 3.4).

``RequestComparison`` valida de forma síncrona y encola (carril ``calibration``);
``RunComparisonJob`` llama a la carta (``compare``: pruebas formales de S y μ y cambio relativo
informativo) con la base de la versión base y las filas nuevas conservadas tras la exclusión
humana (el dataset del ajuste ``NEW_ROWS``), y decide ``extend`` o ``replace``. Con ``extend`` crea
el dataset ``recalibration_extension`` (base vigente + nuevas conservadas, en ese orden), raíz de
la operación ``EXTENSION``.

**P3 (decisión del dueño):** mientras las pruebas formales no tengan cita, pedir una comparación
responde ``RECALIBRATION_DECISION_PENDING`` (422). Con reemplazo forzado (o un evento estructural
sin resolver) la comparación no se hace: se salta a ``/versions``.
"""

from dataclasses import dataclass, replace

import numpy as np

from voracious.application.charts import ChartRegistry, resolve_chart
from voracious.application.errors import (
    ApplicationError,
    ComparisonNotFoundError,
    RecalibrationDecisionPendingError,
    RecalibrationMismatchError,
)
from voracious.application.lifecycle import base_content_hash, frozen_base
from voracious.application.ports import (
    Clock,
    ComparisonRepository,
    DatasetStorage,
    FitRepository,
    IdGenerator,
    JobKind,
    JobQueue,
    JobRequest,
    LimitsRepository,
    ModelVersionRepository,
    RecalibrationRepository,
)
from voracious.application.recalibration_steps import (
    RecalibrationSteps,
    RecalibrationStepsRegistry,
    resolve_recalibration_steps,
)
from voracious.application.records import (
    ComparisonRecord,
    DatasetRecord,
    DatasetSource,
    ErrorInfo,
    JobStatus,
)
from voracious.application.use_cases.common import INTERNAL_ERROR, get_version
from voracious.application.use_cases.recalibration_chain import get_recalibration, open_session
from voracious.application.use_cases.steps import (
    check_same_fit,
    dataset_chain,
    get_dataset,
    notify_pipeline,
    ready_fit,
    ready_limits,
)
from voracious.domain.common import (
    DomainError,
    FloatMatrix,
    InvalidInputError,
    RecalibrationDecision,
    TaskMapper,
)

__all__ = ["GetComparison", "RequestComparison", "RunComparisonJob", "get_comparison"]


def get_comparison(
    comparisons: ComparisonRepository,
    tenant_id: str,
    chart_id: str,
    model_id: str,
    comparison_id: str,
) -> ComparisonRecord:
    """Busca una comparación o lanza ``ComparisonNotFoundError``.

    Args:
        comparisons: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo.
        comparison_id: Comparación.

    Returns:
        La comparación.

    Raises:
        ComparisonNotFoundError: Si no existe para esa clave.
    """
    record = comparisons.get(tenant_id, chart_id, model_id, comparison_id)
    if record is None:
        raise ComparisonNotFoundError(
            f"la comparación '{comparison_id}' no existe",
            details={"model_id": model_id, "comparison_id": comparison_id},
        )
    return record


@dataclass(frozen=True)
class RequestComparison:
    """Valida y encola la comparación de bases de una recalibración.

    Attributes:
        charts: Cartas registradas.
        recalibration_steps: Pasos de la recalibración por carta.
        recalibrations: Repositorio de recalibraciones.
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        comparisons: Repositorio de comparaciones.
        queue: Cola.
        ids: Identificadores.
        clock: Reloj.
    """

    charts: ChartRegistry
    recalibration_steps: RecalibrationStepsRegistry
    recalibrations: RecalibrationRepository
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    comparisons: ComparisonRepository
    queue: JobQueue
    ids: IdGenerator
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
        pipeline_id: str | None = None,
    ) -> str:
        """Encola la comparación.

        Orden: recalibración en curso; sin reemplazo forzado; sin decisiones pendientes (P3);
        ajuste y límites ``succeeded`` de las filas nuevas de esa recalibración (operación
        ``new_rows``).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.
            fit_id: Ajuste de las filas nuevas conservadas (``μ₁``, ``S₁``).
            limits_id: Límites de ese ajuste.
            comparison_id: Identificador ya reservado (tubería).
            pipeline_id: Tubería que la pide.

        Returns:
            El ``comparison_id``.

        Raises:
            UnknownChartError: Si la carta no existe.
            RecalibrationNotFoundError: Si la recalibración no existe para ese modelo.
            RecalibrationNotInProgressError: Si ya no admite pasos.
            InvalidInputError: Si la recalibración es un reemplazo forzado.
            RecalibrationDecisionPendingError: Si las pruebas formales siguen pendientes.
            FitNotFoundError: Si el ajuste no existe.
            FitNotReadyError: Si no está ``succeeded``.
            LimitsNotFoundError: Si los límites no existen.
            LimitsNotReadyError: Si no están ``succeeded``.
            LimitsFitMismatchError: Si los límites son de otro ajuste.
            RecalibrationMismatchError: Si no son de las filas nuevas de esa recalibración.
        """
        chart = resolve_chart(self.charts, chart_id)
        resolve_recalibration_steps(self.recalibration_steps, chart_id)
        session = open_session(
            get_recalibration(self.recalibrations, tenant_id, chart_id, model_id, recalibration_id)
        )
        if session.force_replace:
            raise InvalidInputError(
                "un reemplazo forzado no compara bases: se pide la versión directamente",
                details={
                    "recalibration_id": recalibration_id,
                    "reason": "forced_replace_skips_comparison",
                },
            )
        pending = chart.pending_recalibration_decisions(
            chart.decode_recalibration_params(session.params)
        )
        if pending:
            raise RecalibrationDecisionPendingError(
                "la comparación tiene decisiones estadísticas pendientes",
                details={"pending": list(pending)},
            )
        fit = ready_fit(self.fits, tenant_id, chart_id, fit_id)
        limits = ready_limits(self.limits, tenant_id, chart_id, limits_id)
        check_same_fit(limits, fit_id)
        root = dataset_chain(self.datasets, get_dataset(self.datasets, tenant_id, fit.dataset_id))[
            0
        ]
        if (
            root.source is not DatasetSource.RECALIBRATION_CANDIDATES
            or root.origin_ref != recalibration_id
            or limits.recalibration_id != recalibration_id
        ):
            raise RecalibrationMismatchError(
                "el ajuste no es de las filas nuevas de esa recalibración",
                details={
                    "fit_id": fit_id,
                    "limits_id": limits_id,
                    "recalibration_id": recalibration_id,
                },
            )
        record = ComparisonRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            model_id=model_id,
            comparison_id=comparison_id if comparison_id is not None else self.ids.new_id(),
            recalibration_id=recalibration_id,
            fit_id=fit_id,
            limits_id=limits_id,
            status=JobStatus.QUEUED,
            created_at=self.clock.now(),
            pipeline_id=pipeline_id,
        )
        self.comparisons.add(record)
        self.queue.enqueue(
            JobRequest(JobKind.COMPARISON, tenant_id, chart_id, record.comparison_id, model_id)
        )
        return record.comparison_id


@dataclass(frozen=True)
class GetComparison:
    """Consulta una comparación.

    Attributes:
        charts: Cartas registradas.
        comparisons: Repositorio.
    """

    charts: ChartRegistry
    comparisons: ComparisonRepository

    def execute(
        self, tenant_id: str, chart_id: str, model_id: str, comparison_id: str
    ) -> ComparisonRecord:
        """Devuelve la comparación.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            comparison_id: Comparación.

        Returns:
            El registro.

        Raises:
            UnknownChartError: Si la carta no existe.
            ComparisonNotFoundError: Si no existe.
        """
        resolve_chart(self.charts, chart_id)
        return get_comparison(self.comparisons, tenant_id, chart_id, model_id, comparison_id)


@dataclass(frozen=True)
class RunComparisonJob:
    """Ejecuta una comparación encolada (carril ``calibration``).

    Attributes:
        recalibration_steps: Pasos de la recalibración por carta.
        recalibrations: Repositorio de recalibraciones.
        versions: Repositorio de versiones (la base).
        datasets: Almacenamiento (recibe el dataset de extensión).
        fits: Repositorio de ajustes.
        comparisons: Repositorio de comparaciones.
        mapper: Reparto de los remuestreos.
        queue: Cola (aviso a la tubería).
        ids: Identificadores (dataset de extensión).
        clock: Reloj.
    """

    recalibration_steps: RecalibrationStepsRegistry
    recalibrations: RecalibrationRepository
    versions: ModelVersionRepository
    datasets: DatasetStorage
    fits: FitRepository
    comparisons: ComparisonRepository
    mapper: TaskMapper
    queue: JobQueue
    ids: IdGenerator
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo; idempotente (si ya no está ``queued``, no hace nada).

        Args:
            job: Petición ``comparison``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``comparison``.
            UnknownChartError: Si la carta no expone pasos de recalibración.
            ComparisonNotFoundError: Si la comparación no existe.
        """
        if job.kind is not JobKind.COMPARISON or job.model_id is None:
            msg = f"RunComparisonJob solo ejecuta trabajos 'comparison', no '{job.kind}'"
            raise ValueError(msg)
        steps = resolve_recalibration_steps(self.recalibration_steps, job.scope)
        key = (job.tenant_id, job.scope, job.model_id)
        get_comparison(self.comparisons, *key, job.resource_id)
        record = self.comparisons.claim(*key, job.resource_id, self.clock.now())
        if record is None:
            return
        try:
            done = self._run(steps, record)
        except (DomainError, ApplicationError) as exc:
            self._close(record, error=ErrorInfo(exc.code, exc.message, exc.details))
            return
        except Exception:
            self._close(record, error=ErrorInfo(INTERNAL_ERROR, "error interno en la comparación"))
            raise
        self._close(done)

    def _run(self, steps: RecalibrationSteps, record: ComparisonRecord) -> ComparisonRecord:
        """Compara, decide y, si amplía la base, crea el dataset de extensión.

        Args:
            steps: Pasos de la recalibración.
            record: Comparación en ``running``.

        Returns:
            La comparación con su resultado.
        """
        key = (record.tenant_id, record.chart_id, record.model_id)
        session = get_recalibration(self.recalibrations, *key, record.recalibration_id)
        active = get_version(self.versions, *key, session.base_version_number)
        fit = ready_fit(self.fits, record.tenant_id, record.chart_id, record.fit_id)
        new_kept = get_dataset(self.datasets, record.tenant_id, fit.dataset_id).data
        result = steps.compare(
            active.model, active.base_data, new_kept, fit.result, session.params, mapper=self.mapper
        )
        decision = steps.decide(
            result,
            n_kept=int(new_kept.shape[0]),
            recalibration_params=session.params,
            force_replace=False,
        )
        extension_id = None
        if decision is RecalibrationDecision.EXTEND:
            extension_id = self._extension(record, active.base_data, new_kept)
        return replace(record, result=result, decision=decision, extension_dataset_id=extension_id)

    def _extension(self, record: ComparisonRecord, base: FloatMatrix, new_kept: FloatMatrix) -> str:
        """Crea el dataset ``recalibration_extension`` = ``vstack(base, nuevas conservadas)``.

        Args:
            record: Comparación.
            base: Base de la versión base.
            new_kept: Filas nuevas conservadas.

        Returns:
            El id del dataset.
        """
        data = frozen_base(np.ascontiguousarray(np.vstack([base, new_kept]), dtype=np.float64))
        dataset = DatasetRecord(
            tenant_id=record.tenant_id,
            dataset_id=self.ids.new_id(),
            data=data,
            content_hash=base_content_hash(data),
            source=DatasetSource.RECALIBRATION_EXTENSION,
            created_at=self.clock.now(),
            origin_ref=record.recalibration_id,
        )
        self.datasets.add(dataset)
        return dataset.dataset_id

    def _close(self, record: ComparisonRecord, *, error: ErrorInfo | None = None) -> None:
        """Cierra la comparación y avisa a su tubería.

        Args:
            record: Registro (con el resultado si terminó bien).
            error: Error si falló.
        """
        self.comparisons.update(
            replace(
                record,
                status=JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED,
                finished_at=self.clock.now(),
                error=error,
            )
        )
        notify_pipeline(self.queue, record.tenant_id, record.chart_id, record.pipeline_id)
