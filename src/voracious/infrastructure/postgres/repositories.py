"""Repositorios Postgres de los registros de trabajo y del ciclo de vida (Paso 4.2).

Implementan los mismos puertos que los de memoria con la misma semántica (la suite de contrato
``tests/unit/infrastructure/test_repository_contract.py`` corre contra ambos). La atomicidad la da
la base:

- ``claim``: ``UPDATE … SET status = 'running' WHERE … AND status = 'queued' RETURNING``.
- ``add_if_none_in_progress`` y ``add_proposal_if_none`` (D6): índices únicos parciales
  (``recalibrations_one_in_progress``, ``model_versions_one_proposal``) con
  ``INSERT … ON CONFLICT … DO NOTHING``.
- Cambios de estado de versiones, pasos de tubería y propuestas de recalibración: comparar-y-
  cambiar con ``SELECT … FOR UPDATE`` en una transacción.
- Observaciones, anotaciones y eventos son append-only: nunca se actualizan.
"""

import builtins
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from typing import LiteralString

from psycopg import sql
from psycopg.errors import UniqueViolation
from psycopg_pool import ConnectionPool

from voracious.application.ports import DuplicateKeyError, VersionStatusChange
from voracious.application.records import (
    ComparisonRecord,
    ExclusionRecord,
    FitRecord,
    JobStatus,
    LimitsRecord,
    ModelRecord,
    ModelVersion,
    MonitoringRecord,
    ObservationRecord,
    PipelineRecord,
    PipelineStep,
    ProposalRequest,
    RecalibrationMode,
    RecalibrationRecord,
    SignalAnnotation,
    StructuralEvent,
    VersionStatus,
)
from voracious.infrastructure.memory.codec import RecordCodec
from voracious.infrastructure.memory.versions import decided
from voracious.infrastructure.postgres.store import (
    PAYLOAD_FORMAT_VERSION,
    Conn,
    Table,
    dump_payload,
    ensure_tenant,
)

__all__ = [
    "PostgresComparisonRepository",
    "PostgresExclusionRepository",
    "PostgresFitRepository",
    "PostgresLimitsRepository",
    "PostgresModelRepository",
    "PostgresModelVersionRepository",
    "PostgresMonitoringRepository",
    "PostgresObservationRepository",
    "PostgresPipelineRepository",
    "PostgresRecalibrationRepository",
    "PostgresSignalAnnotationRepository",
    "PostgresStructuralEventRepository",
]

Pool = ConnectionPool[Conn]

_STEP_KEYS: tuple[LiteralString, ...] = ("tenant_id", "chart_id")
_PROPOSED = VersionStatus.PROPOSED.value


def _start[
    R: (
        FitRecord,
        LimitsRecord,
        ExclusionRecord,
        PipelineRecord,
        ModelRecord,
        MonitoringRecord,
        RecalibrationRecord,
        ComparisonRecord,
    )
](started_at: datetime) -> Callable[[R], R]:
    """Función que pasa un registro de trabajo a ``running`` con su instante de inicio.

    Args:
        started_at: Instante de inicio (UTC).

    Returns:
        La función.
    """

    def start(record: R) -> R:
        return replace(record, status=JobStatus.RUNNING, started_at=started_at)

    return start


# --- pasos de la Fase I ----------------------------------------------------------------------


class PostgresFitRepository:
    """``FitRepository`` en la tabla ``fits``."""

    def __init__(self, pool: Pool, codec: RecordCodec[FitRecord]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de los ajustes.
        """
        self._t: Table[FitRecord] = Table(
            pool,
            "fits",
            (*_STEP_KEYS, "fit_id"),
            codec,
            lambda r: (r.tenant_id, r.chart_id, r.fit_id),
            lambda r: {
                "status": r.status.value,
                "dataset_id": r.dataset_id,
                "pipeline_id": r.pipeline_id,
                "created_at": r.created_at,
            },
        )

    def add(self, record: FitRecord) -> None:
        """Guarda un ajuste nuevo.

        Args:
            record: Registro.
        """
        self._t.add(record)

    def get(self, tenant_id: str, chart_id: str, fit_id: str) -> FitRecord | None:
        """Busca un ajuste.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste.

        Returns:
            El registro o ``None``.
        """
        return self._t.get((tenant_id, chart_id, fit_id))

    def update(self, record: FitRecord) -> None:
        """Reemplaza un ajuste existente.

        Args:
            record: Registro nuevo.
        """
        self._t.update(record)

    def claim(
        self, tenant_id: str, chart_id: str, fit_id: str, started_at: datetime
    ) -> FitRecord | None:
        """Pasa el ajuste a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._t.claim(
            (tenant_id, chart_id, fit_id),
            _start(started_at),
        )

    def list_unfinished(self) -> list[FitRecord]:
        """Ajustes ``queued`` o ``running`` de todos los tenants.

        Returns:
            Los registros.
        """
        return self._t.unfinished()


class PostgresLimitsRepository:
    """``LimitsRepository`` en la tabla ``limits``."""

    def __init__(self, pool: Pool, codec: RecordCodec[LimitsRecord]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de los límites.
        """
        self._t: Table[LimitsRecord] = Table(
            pool,
            "limits",
            (*_STEP_KEYS, "limits_id"),
            codec,
            lambda r: (r.tenant_id, r.chart_id, r.limits_id),
            lambda r: {
                "status": r.status.value,
                "fit_id": r.fit_id,
                "recalibration_id": r.recalibration_id,
                "pipeline_id": r.pipeline_id,
                "created_at": r.created_at,
            },
        )

    def add(self, record: LimitsRecord) -> None:
        """Guarda una calibración nueva.

        Args:
            record: Registro.
        """
        self._t.add(record)

    def get(self, tenant_id: str, chart_id: str, limits_id: str) -> LimitsRecord | None:
        """Busca una calibración.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            limits_id: Calibración.

        Returns:
            El registro o ``None``.
        """
        return self._t.get((tenant_id, chart_id, limits_id))

    def update(self, record: LimitsRecord) -> None:
        """Reemplaza una calibración existente.

        Args:
            record: Registro nuevo.
        """
        self._t.update(record)

    def claim(
        self, tenant_id: str, chart_id: str, limits_id: str, started_at: datetime
    ) -> LimitsRecord | None:
        """Pasa la calibración a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            limits_id: Calibración.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._t.claim(
            (tenant_id, chart_id, limits_id),
            _start(started_at),
        )

    def list_unfinished(self) -> list[LimitsRecord]:
        """Calibraciones ``queued`` o ``running`` de todos los tenants.

        Returns:
            Los registros.
        """
        return self._t.unfinished()


class PostgresExclusionRepository:
    """``ExclusionRepository`` en la tabla ``exclusions``."""

    def __init__(self, pool: Pool, codec: RecordCodec[ExclusionRecord]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de las exclusiones.
        """
        self._t: Table[ExclusionRecord] = Table(
            pool,
            "exclusions",
            (*_STEP_KEYS, "exclusion_id"),
            codec,
            lambda r: (r.tenant_id, r.chart_id, r.exclusion_id),
            lambda r: {
                "status": r.status.value,
                "dataset_id": r.dataset_id,
                "pipeline_id": r.pipeline_id,
                "created_at": r.created_at,
            },
        )

    def add(self, record: ExclusionRecord) -> None:
        """Guarda una exclusión nueva.

        Args:
            record: Registro.
        """
        self._t.add(record)

    def get(self, tenant_id: str, chart_id: str, exclusion_id: str) -> ExclusionRecord | None:
        """Busca una exclusión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            exclusion_id: Exclusión.

        Returns:
            El registro o ``None``.
        """
        return self._t.get((tenant_id, chart_id, exclusion_id))

    def update(self, record: ExclusionRecord) -> None:
        """Reemplaza una exclusión existente.

        Args:
            record: Registro nuevo.
        """
        self._t.update(record)

    def claim(
        self, tenant_id: str, chart_id: str, exclusion_id: str, started_at: datetime
    ) -> ExclusionRecord | None:
        """Pasa la exclusión a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            exclusion_id: Exclusión.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._t.claim(
            (tenant_id, chart_id, exclusion_id),
            _start(started_at),
        )

    def list_unfinished(self) -> list[ExclusionRecord]:
        """Exclusiones ``queued`` o ``running`` de todos los tenants.

        Returns:
            Los registros.
        """
        return self._t.unfinished()


class PostgresPipelineRepository:
    """``PipelineRepository`` en la tabla ``pipelines``."""

    def __init__(self, pool: Pool, codec: RecordCodec[PipelineRecord]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de las tuberías.
        """
        self._t: Table[PipelineRecord] = Table(
            pool,
            "pipelines",
            (*_STEP_KEYS, "pipeline_id"),
            codec,
            lambda r: (r.tenant_id, r.chart_id, r.pipeline_id),
            lambda r: {
                "status": r.status.value,
                "kind": r.kind.value,
                "dataset_id": r.dataset_id,
                "n_steps": len(r.steps),
                "model_id": r.model_id,
                "recalibration_id": r.recalibration_id,
                "created_at": r.created_at,
            },
        )

    def add(self, record: PipelineRecord) -> None:
        """Guarda una tubería nueva.

        Args:
            record: Registro.
        """
        self._t.add(record)

    def get(self, tenant_id: str, chart_id: str, pipeline_id: str) -> PipelineRecord | None:
        """Busca una tubería.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            pipeline_id: Tubería.

        Returns:
            El registro o ``None``.
        """
        return self._t.get((tenant_id, chart_id, pipeline_id))

    def update(self, record: PipelineRecord) -> None:
        """Reemplaza una tubería existente.

        Args:
            record: Registro nuevo.
        """
        self._t.update(record)

    def claim(
        self, tenant_id: str, chart_id: str, pipeline_id: str, started_at: datetime
    ) -> PipelineRecord | None:
        """Pasa la tubería a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            pipeline_id: Tubería.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._t.claim(
            (tenant_id, chart_id, pipeline_id),
            _start(started_at),
        )

    def append_step(
        self,
        tenant_id: str,
        chart_id: str,
        pipeline_id: str,
        expected_steps: int,
        step: PipelineStep,
    ) -> PipelineRecord | None:
        """Añade un paso si la tubería sigue ``running`` con ``expected_steps`` pasos (atómico).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            pipeline_id: Tubería.
            expected_steps: Pasos que debe tener ahora.
            step: Paso nuevo.

        Returns:
            El registro con el paso añadido o ``None`` si no se cumplía la condición.
        """
        return self._t.transition(
            (tenant_id, chart_id, pipeline_id),
            sql.SQL("status = 'running' AND n_steps = %s"),
            (expected_steps,),
            lambda r: replace(r, steps=(*r.steps, step)),
        )

    def list_unfinished(self) -> list[PipelineRecord]:
        """Tuberías ``queued`` o ``running`` de todos los tenants.

        Returns:
            Los registros.
        """
        return self._t.unfinished()


# --- modelos, puntuaciones, recalibraciones y comparaciones -----------------------------------


class PostgresModelRepository:
    """``ModelRepository`` en la tabla ``models``."""

    def __init__(self, pool: Pool, codec: RecordCodec[ModelRecord]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de los modelos.
        """
        self._t: Table[ModelRecord] = Table(
            pool,
            "models",
            (*_STEP_KEYS, "model_id"),
            codec,
            lambda r: (r.tenant_id, r.chart_id, r.model_id),
            lambda r: {
                "status": r.status.value,
                "root_dataset_id": None if r.provenance is None else r.provenance.root_dataset_id,
                "pipeline_id": r.pipeline_id,
                "created_at": r.created_at,
            },
        )

    def add(self, record: ModelRecord) -> None:
        """Guarda un modelo nuevo.

        Args:
            record: Registro.
        """
        self._t.add(record)

    def get(self, tenant_id: str, chart_id: str, model_id: str) -> ModelRecord | None:
        """Busca un modelo.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            El registro o ``None``.
        """
        return self._t.get((tenant_id, chart_id, model_id))

    def update(self, record: ModelRecord) -> None:
        """Reemplaza un modelo existente.

        Args:
            record: Registro nuevo.
        """
        self._t.update(record)

    def claim(
        self, tenant_id: str, chart_id: str, model_id: str, started_at: datetime
    ) -> ModelRecord | None:
        """Pasa el modelo a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._t.claim(
            (tenant_id, chart_id, model_id),
            _start(started_at),
        )

    def list_unfinished(self) -> list[ModelRecord]:
        """Modelos ``queued`` o ``running`` de todos los tenants.

        Returns:
            Los registros.
        """
        return self._t.unfinished()


_CHILD_KEYS: tuple[LiteralString, ...] = ("tenant_id", "chart_id", "model_id")


class PostgresMonitoringRepository:
    """``MonitoringRepository`` en la tabla ``scores``."""

    def __init__(self, pool: Pool, codec: RecordCodec[MonitoringRecord]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de las puntuaciones.
        """
        self._t: Table[MonitoringRecord] = Table(
            pool,
            "scores",
            (*_CHILD_KEYS, "score_id"),
            codec,
            lambda r: (r.tenant_id, r.chart_id, r.model_id, r.monitoring_id),
            lambda r: {
                "status": r.status.value,
                "batch_label": r.batch_label,
                "created_at": r.created_at,
            },
        )

    def add(self, record: MonitoringRecord) -> None:
        """Guarda una puntuación nueva.

        Args:
            record: Registro.
        """
        self._t.add(record)

    def get(
        self, tenant_id: str, chart_id: str, model_id: str, monitoring_id: str
    ) -> MonitoringRecord | None:
        """Busca una puntuación.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            monitoring_id: Puntuación.

        Returns:
            El registro o ``None``.
        """
        return self._t.get((tenant_id, chart_id, model_id, monitoring_id))

    def update(self, record: MonitoringRecord) -> None:
        """Reemplaza una puntuación existente.

        Args:
            record: Registro nuevo.
        """
        self._t.update(record)

    def claim(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        monitoring_id: str,
        started_at: datetime,
    ) -> MonitoringRecord | None:
        """Pasa la puntuación a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            monitoring_id: Puntuación.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._t.claim(
            (tenant_id, chart_id, model_id, monitoring_id),
            _start(started_at),
        )

    def list_unfinished(self) -> list[MonitoringRecord]:
        """Puntuaciones ``queued`` o ``running`` de todos los tenants.

        Returns:
            Los registros.
        """
        return self._t.unfinished()


class PostgresComparisonRepository:
    """``ComparisonRepository`` en la tabla ``comparisons``."""

    def __init__(self, pool: Pool, codec: RecordCodec[ComparisonRecord]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de las comparaciones.
        """
        self._t: Table[ComparisonRecord] = Table(
            pool,
            "comparisons",
            (*_CHILD_KEYS, "comparison_id"),
            codec,
            lambda r: (r.tenant_id, r.chart_id, r.model_id, r.comparison_id),
            lambda r: {
                "status": r.status.value,
                "recalibration_id": r.recalibration_id,
                "created_at": r.created_at,
            },
        )

    def add(self, record: ComparisonRecord) -> None:
        """Guarda una comparación nueva.

        Args:
            record: Registro.
        """
        self._t.add(record)

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
            El registro o ``None``.
        """
        return self._t.get((tenant_id, chart_id, model_id, comparison_id))

    def update(self, record: ComparisonRecord) -> None:
        """Reemplaza una comparación existente.

        Args:
            record: Registro nuevo.
        """
        self._t.update(record)

    def claim(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        comparison_id: str,
        started_at: datetime,
    ) -> ComparisonRecord | None:
        """Pasa la comparación a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            comparison_id: Comparación.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._t.claim(
            (tenant_id, chart_id, model_id, comparison_id),
            _start(started_at),
        )

    def list_unfinished(self) -> list[ComparisonRecord]:
        """Comparaciones ``queued`` o ``running`` de todos los tenants.

        Returns:
            Los registros.
        """
        return self._t.unfinished()


class PostgresRecalibrationRepository:
    """``RecalibrationRepository`` en la tabla ``recalibrations``."""

    def __init__(self, pool: Pool, codec: RecordCodec[RecalibrationRecord]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de las recalibraciones.
        """
        self._pool = pool
        self._t: Table[RecalibrationRecord] = Table(
            pool,
            "recalibrations",
            (*_CHILD_KEYS, "recalibration_id"),
            codec,
            lambda r: (r.tenant_id, r.chart_id, r.model_id, r.recalibration_id),
            lambda r: {
                "status": r.status.value,
                "mode": r.mode.value,
                "proposal_status": None if r.proposal is None else r.proposal.status.value,
                "created_at": r.created_at,
            },
        )

    def add(self, record: RecalibrationRecord) -> None:
        """Guarda una recalibración nueva.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si ya existe la clave (o ya hay otra en curso para el modelo y
                esta también lo está: lo impide el índice único parcial).
        """
        self._t.add(record)

    def add_if_none_in_progress(self, record: RecalibrationRecord) -> bool:
        """Guarda la recalibración si el modelo no tiene otra ``queued`` o ``running`` (D6).

        Una recalibración ya terminada no ocupa el índice único parcial: la que se guarda en
        curso choca con la que esté en curso (``ON CONFLICT … DO NOTHING`` → ``False``) y una
        clave repetida es ``DuplicateKeyError``.

        Args:
            record: Registro.

        Returns:
            ``True`` si se guardó.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        if record.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            with self._pool.connection() as conn:
                busy = conn.execute(
                    sql.SQL(
                        "SELECT 1 FROM recalibrations WHERE {} AND status IN ('queued', 'running')"
                    ).format(self._t.where_key(_CHILD_KEYS)),
                    (record.tenant_id, record.chart_id, record.model_id),
                ).fetchone()
                if busy is not None:
                    return False
                self._t.insert(conn, record)
                return True
        query = sql.SQL(
            "INSERT INTO recalibrations (tenant_id, chart_id, model_id, recalibration_id,"
            " status, mode, proposal_status, created_at, format_version, payload)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (tenant_id, chart_id, model_id)"
            " WHERE status IN ('queued', 'running') DO NOTHING RETURNING 1"
        )
        params = [
            record.tenant_id,
            record.chart_id,
            record.model_id,
            record.recalibration_id,
            record.status.value,
            record.mode.value,
            None if record.proposal is None else record.proposal.status.value,
            record.created_at,
            PAYLOAD_FORMAT_VERSION,
            dump_payload(self._t.codec.encode(record)),
        ]
        with self._pool.connection() as conn:
            ensure_tenant(conn, record.tenant_id)
            try:
                return conn.execute(query, params).fetchone() is not None
            except UniqueViolation as exc:
                raise DuplicateKeyError(f"recalibrations: {record.recalibration_id}") from exc

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
            El registro o ``None``.
        """
        return self._t.get((tenant_id, chart_id, model_id, recalibration_id))

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[RecalibrationRecord]:
        """Recalibraciones del modelo en orden de creación.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            Los registros.
        """
        return self._t.select(self._t.where_key(_CHILD_KEYS), (tenant_id, chart_id, model_id))

    def update(self, record: RecalibrationRecord) -> None:
        """Reemplaza una recalibración existente.

        Args:
            record: Registro nuevo.
        """
        self._t.update(record)

    def claim(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        recalibration_id: str,
        started_at: datetime,
    ) -> RecalibrationRecord | None:
        """Pasa la recalibración a ``running`` de forma atómica.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.
            started_at: Instante de inicio.

        Returns:
            El registro en ``running`` o ``None``.
        """
        return self._t.claim(
            (tenant_id, chart_id, model_id, recalibration_id),
            _start(started_at),
        )

    def find(
        self, tenant_id: str, chart_id: str, recalibration_id: str
    ) -> RecalibrationRecord | None:
        """Busca una recalibración solo por su id.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            recalibration_id: Recalibración.

        Returns:
            El registro o ``None``.
        """
        rows = self._t.select(
            self._t.where_key(("tenant_id", "chart_id", "recalibration_id")),
            (tenant_id, chart_id, recalibration_id),
        )
        return rows[0] if rows else None

    def request_proposal(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        recalibration_id: str,
        proposal: ProposalRequest,
    ) -> RecalibrationRecord | None:
        """Guarda la petición de propuesta si sigue ``running`` y sin otra (atómico).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.
            proposal: Petición.

        Returns:
            El registro con la petición o ``None``.
        """
        return self._t.transition(
            (tenant_id, chart_id, model_id, recalibration_id),
            sql.SQL("status = 'running' AND proposal_status IS NULL"),
            (),
            lambda r: replace(r, proposal=proposal),
        )

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
            finished_at: Instante de la cancelación.

        Returns:
            El registro ``cancelled`` o ``None``.
        """
        return self._t.transition(
            (tenant_id, chart_id, model_id, recalibration_id),
            sql.SQL("mode = %s AND status = 'running' AND proposal_status IS NULL"),
            (RecalibrationMode.STEPWISE.value,),
            lambda r: replace(r, status=JobStatus.CANCELLED, finished_at=finished_at),
        )

    def claim_proposal(
        self, tenant_id: str, chart_id: str, model_id: str, recalibration_id: str
    ) -> RecalibrationRecord | None:
        """Pasa la petición de propuesta de ``queued`` a ``running`` (atómico).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.

        Returns:
            El registro con la petición en ``running`` o ``None``.
        """

        def start(record: RecalibrationRecord) -> RecalibrationRecord:
            current = record.proposal
            if current is None:  # pragma: no cover - la condición SQL lo excluye
                return record
            return replace(record, proposal=replace(current, status=JobStatus.RUNNING))

        return self._t.transition(
            (tenant_id, chart_id, model_id, recalibration_id),
            sql.SQL("proposal_status = 'queued'"),
            (),
            start,
        )

    def list_unfinished(self) -> builtins.list[RecalibrationRecord]:
        """Recalibraciones ``queued`` o ``running`` de todos los tenants.

        Returns:
            Los registros (también las sesiones paso a paso abiertas: decide el caso de uso).
        """
        return self._t.unfinished()


# --- versiones -------------------------------------------------------------------------------


class PostgresModelVersionRepository:
    """``ModelVersionRepository`` en ``model_versions`` + ``version_base_rows`` (append-only)."""

    def __init__(self, pool: Pool, codec: RecordCodec[ModelVersion]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de las versiones.
        """
        self._pool = pool
        self._t: Table[ModelVersion] = Table(
            pool,
            "model_versions",
            (*_CHILD_KEYS, "number"),
            codec,
            lambda v: (v.tenant_id, v.chart_id, v.model_id, v.number),
            lambda v: {
                "status": v.status.value,
                "effective_from": v.effective_from,
                "recalibration_id": v.recalibration_id,
                "created_at": v.created_at,
            },
        )

    @staticmethod
    def _base_rows(conn: Conn, version: ModelVersion) -> None:
        """Escribe el origen y la fecha de cada fila de la base (``COPY``).

        Args:
            conn: Conexión de la transacción del alta.
            version: Versión.
        """
        key = (version.tenant_id, version.chart_id, version.model_id, version.number)
        with (
            conn.cursor() as cur,
            cur.copy(
                "COPY version_base_rows (tenant_id, chart_id, model_id, number, row_index,"
                " source, ref, observed_at) FROM STDIN"
            ) as copy,
        ):
            for i, ref in enumerate(version.base_refs):
                copy.write_row((*key, i, ref.source.value, ref.ref, ref.observed_at))

    def add(self, version: ModelVersion) -> None:
        """Añade una versión.

        Args:
            version: Versión.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        with self._pool.connection() as conn:
            self._t.insert(conn, version)
            self._base_rows(conn, version)

    def add_proposal_if_none(self, version: ModelVersion) -> bool:
        """Añade una propuesta si el modelo no tiene otra sin resolver (atómico, D6).

        Args:
            version: Versión ``proposed``.

        Returns:
            ``True`` si se añadió.

        Raises:
            ValueError: Si la versión no está ``proposed``.
            DuplicateKeyError: Si ya existe la clave.
        """
        if version.status is not VersionStatus.PROPOSED:
            msg = "add_proposal_if_none solo admite versiones 'proposed'"
            raise ValueError(msg)
        query = sql.SQL(
            "INSERT INTO model_versions (tenant_id, chart_id, model_id, number, status,"
            " effective_from, recalibration_id, created_at, format_version, payload)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (tenant_id, chart_id, model_id) WHERE status = 'proposed'"
            " DO NOTHING RETURNING 1"
        )
        params = [
            version.tenant_id,
            version.chart_id,
            version.model_id,
            version.number,
            _PROPOSED,
            version.effective_from,
            version.recalibration_id,
            version.created_at,
            PAYLOAD_FORMAT_VERSION,
            dump_payload(self._t.codec.encode(version)),
        ]
        with self._pool.connection() as conn:
            ensure_tenant(conn, version.tenant_id)
            try:
                inserted = conn.execute(query, params).fetchone() is not None
            except UniqueViolation as exc:
                raise DuplicateKeyError(f"model_versions: {version.number}") from exc
            if inserted:
                self._base_rows(conn, version)
            return inserted

    def get(self, tenant_id: str, chart_id: str, model_id: str, number: int) -> ModelVersion | None:
        """Busca una versión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            number: Número.

        Returns:
            La versión o ``None``.
        """
        return self._t.get((tenant_id, chart_id, model_id, number))

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[ModelVersion]:
        """Versiones del modelo ordenadas por número.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            Las versiones.
        """
        return self._t.select(
            self._t.where_key(_CHILD_KEYS), (tenant_id, chart_id, model_id), sql.SQL("number")
        )

    def apply_status_changes(self, changes: Sequence[VersionStatusChange]) -> bool:
        """Aplica todos los cambios o ninguno (``SELECT … FOR UPDATE`` en una transacción).

        Las filas se bloquean en orden de clave (sin interbloqueos entre dos aprobaciones).

        Args:
            changes: Cambios.

        Returns:
            ``True`` si se aplicaron todos.
        """
        ordered = sorted(changes, key=lambda c: (c.tenant_id, c.chart_id, c.model_id, c.number))
        query = sql.SQL(
            "SELECT payload, format_version FROM model_versions WHERE {} FOR UPDATE"
        ).format(self._t.where_key())
        with self._pool.connection() as conn:
            current: builtins.list[ModelVersion] = []
            for change in ordered:
                key = (change.tenant_id, change.chart_id, change.model_id, change.number)
                row = conn.execute(query, key).fetchone()
                if row is None:
                    return False
                version = self._t.decode(row)
                if version.status is not change.expected:
                    return False
                current.append(version)
            for version, change in zip(current, ordered, strict=True):
                self._t.write(conn, decided(version, change))
            return True


# --- registros append-only -------------------------------------------------------------------


class PostgresObservationRepository:
    """``ObservationRepository`` en la tabla ``observations`` (append-only)."""

    def __init__(self, pool: Pool, codec: RecordCodec[ObservationRecord]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de las observaciones.
        """
        self._pool = pool
        self._t: Table[ObservationRecord] = Table(
            pool,
            "observations",
            (*_CHILD_KEYS, "observation_id"),
            codec,
            lambda r: (r.tenant_id, r.chart_id, r.model_id, r.observation_id),
            lambda r: {
                "score_id": r.monitoring_id,
                "batch_label": r.batch_label,
                "observed_at": r.observed_at,
                "observed_values": [float(v) for v in r.values],
                "t2": float(r.t2),
                "limit_used": float(r.limit),
                "limit_kind": r.limit_kind,
                "version_number": r.version_number,
                "signal": bool(r.signal),
                "recorded_at": r.recorded_at,
            },
        )

    def add_many(self, records: Sequence[ObservationRecord]) -> None:
        """Añade observaciones (todas o ninguna, en una transacción).

        Args:
            records: Observaciones.

        Raises:
            DuplicateKeyError: Si alguna clave se repite o ya existe.
        """
        with self._pool.connection() as conn:
            for record in records:
                self._t.insert(conn, record)

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
            La observación o ``None``.
        """
        return self._t.get((tenant_id, chart_id, model_id, observation_id))

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
        """Observaciones del rango (inclusivo), por fecha y orden de registro.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observed_from: Inicio o ``None``.
            observed_to: Fin o ``None``.
            signals_only: Solo señales.

        Returns:
            Las observaciones.
        """
        where = sql.SQL(
            "{} AND (%s::timestamptz IS NULL OR observed_at >= %s::timestamptz)"
            " AND (%s::timestamptz IS NULL OR observed_at <= %s::timestamptz)"
            " AND (NOT %s OR signal)"
        ).format(self._t.where_key(_CHILD_KEYS))
        params = (
            tenant_id,
            chart_id,
            model_id,
            observed_from,
            observed_from,
            observed_to,
            observed_to,
            signals_only,
        )
        return self._t.select(where, params, sql.SQL("observed_at, seq"))

    def max_observed_at(self, tenant_id: str, chart_id: str, model_id: str) -> datetime | None:
        """Fecha de la última observación del modelo (la guardada en su payload).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            La mayor fecha o ``None``.
        """
        rows = self._t.select(
            sql.SQL(
                "{} AND observed_at = (SELECT max(observed_at) FROM observations WHERE {})"
            ).format(self._t.where_key(_CHILD_KEYS), self._t.where_key(_CHILD_KEYS)),
            (tenant_id, chart_id, model_id, tenant_id, chart_id, model_id),
        )
        return rows[0].observed_at if rows else None

    def count_scored_with(
        self, tenant_id: str, chart_id: str, model_id: str, version_number: int
    ) -> int:
        """Observaciones puntuadas con una versión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            version_number: Versión.

        Returns:
            El recuento.
        """
        query = sql.SQL(
            "SELECT count(*) FROM observations WHERE {} AND version_number = %s"
        ).format(self._t.where_key(_CHILD_KEYS))
        with self._pool.connection() as conn:
            row = conn.execute(query, (tenant_id, chart_id, model_id, version_number)).fetchone()
        return 0 if row is None else int(str(row[0]))


class PostgresSignalAnnotationRepository:
    """``SignalAnnotationRepository`` en ``signal_annotations`` (append-only; vale la última)."""

    def __init__(self, pool: Pool, codec: RecordCodec[SignalAnnotation]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de las anotaciones.
        """
        self._t: Table[SignalAnnotation] = Table(
            pool,
            "signal_annotations",
            (*_CHILD_KEYS, "annotation_id"),
            codec,
            lambda a: (a.tenant_id, a.chart_id, a.model_id, a.annotation_id),
            lambda a: {
                "observation_id": a.observation_id,
                "assignable_cause": a.assignable_cause,
                "created_at": a.created_at,
            },
        )

    def add(self, annotation: SignalAnnotation) -> None:
        """Añade una anotación.

        Args:
            annotation: Anotación.
        """
        self._t.add(annotation)

    def history(
        self, tenant_id: str, chart_id: str, model_id: str, observation_id: str
    ) -> list[SignalAnnotation]:
        """Anotaciones de una observación, de la más antigua a la más reciente.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observation_id: Observación.

        Returns:
            Las anotaciones.
        """
        return self._t.select(
            self._t.where_key((*_CHILD_KEYS, "observation_id")),
            (tenant_id, chart_id, model_id, observation_id),
        )

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
            ``observation_id → anotación``.
        """
        if not observation_ids:
            return {}
        rows = self._t.select(
            sql.SQL(
                "seq IN (SELECT DISTINCT ON (observation_id) seq FROM signal_annotations"
                " WHERE {} AND observation_id = ANY(%s) ORDER BY observation_id, seq DESC)"
            ).format(self._t.where_key(_CHILD_KEYS)),
            (tenant_id, chart_id, model_id, list(observation_ids)),
        )
        return {a.observation_id: a for a in rows}


class PostgresStructuralEventRepository:
    """``StructuralEventRepository`` en ``structural_events`` (append-only)."""

    def __init__(self, pool: Pool, codec: RecordCodec[StructuralEvent]) -> None:
        """Construye el repositorio.

        Args:
            pool: Pool de conexiones.
            codec: Codec de los eventos.
        """
        self._t: Table[StructuralEvent] = Table(
            pool,
            "structural_events",
            (*_CHILD_KEYS, "event_id"),
            codec,
            lambda e: (e.tenant_id, e.chart_id, e.model_id, e.event_id),
            lambda e: {"occurred_at": e.occurred_at, "registered_at": e.registered_at},
        )

    def add(self, event: StructuralEvent) -> None:
        """Añade un evento.

        Args:
            event: Evento.
        """
        self._t.add(event)

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[StructuralEvent]:
        """Eventos del modelo por ``occurred_at`` y, a igualdad, por registro.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            Los eventos.
        """
        return self._t.select(
            self._t.where_key(_CHILD_KEYS),
            (tenant_id, chart_id, model_id),
            sql.SQL("occurred_at, registered_at, seq"),
        )
