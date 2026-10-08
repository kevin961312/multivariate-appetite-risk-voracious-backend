"""Pasos encadenables de la Fase I (vuelta 3.3 del Paso 3): cada uno su recurso y su trabajo.

``UploadDataset`` (síncrono) → ``RequestFit``/``RunFitJob`` (carril ``estimation``) →
``RequestLimits``/``RunLimitsJob`` (``calibration``) → ``RequestDepuration``/``RunDepurationJob``
(``calibration``) → ``RequestModel``/``RunModelAssemblyJob`` (``light``). El paso siguiente
**referencia** al anterior por su id: no se reenvían datos ni se recalcula nada.

Linaje y semilla: la ronda de una calibración no la elige el cliente. Se deduce del linaje del
dataset ajustado: su raíz decide la operación (``upload`` → ``PHASE1``) y su ``lineage_round`` (las
depuraciones automáticas que quitaron filas en su ascendencia) el número de ronda; la carta lo
traduce a su hueco de semilla (``stage_spawn_key``). Con los mismos parámetros, encadenar los pasos
da el mismo modelo, en bits, que ``fit_phase1`` (``tests/integration/test_phase1_chain.py``).

Depuración (Q3): la exclusión humana ``{dataset_id, assignable_cause}`` referencia el dataset,
sin ajuste ni límites, y solo al principio (sin rondas automáticas en la ascendencia): como en
``fit_phase1``, las filas con causa asignable se quitan antes de ajustar nada. La ronda
automática ``{fit_id, limits_id}`` evalúa un ajuste con sus límites. Si quita filas crea el
dataset derivado ``parent[kept]`` (mismo orden, ``float64`` contiguo) y el paso siguiente es otro
ajuste; si es final, el modelo.

Parámetros por cadena: sobre un dataset derivado de una ronda automática, ``/limits`` hereda los
parámetros de los límites que lo produjeron (si el cliente los manda, deben coincidir: si no,
``LIMITS_PARAMS_MISMATCH``). Así todas las rondas usan los mismos, como ``fit_phase1``.

Cada ``Run…Job`` es idempotente (``claim``) y, si el recurso lo pidió una tubería, la avisa al
terminar (bien o mal) encolando su trabajo ``pipeline``.

Recalibración por pasos (vuelta 3.4): los mismos pasos sirven para depurar las filas nuevas. Si la
raíz del dataset es ``recalibration_candidates``, los límites heredan los parámetros de la versión
base (``recalibration_id``, linaje ``NEW_ROWS``), la exclusión humana sale de las anotaciones (no
del cliente) y la depuración usa ``min_rows = min_observations``: por debajo se agota y la
recalibración termina ``insufficient``. Sobre ``recalibration_extension`` (linaje ``EXTENSION``)
solo hay ajuste y límites. Lo propio de la recalibración llega por ``RecalibrationLinks``.
"""

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

import numpy as np
import numpy.typing as npt

from voracious.application.errors import (
    ApplicationError,
    DatasetNotFoundError,
    DepurationNotFinalError,
    DepurationNotFoundError,
    FitNotFoundError,
    FitNotReadyError,
    LimitsFitMismatchError,
    LimitsNotFoundError,
    LimitsNotReadyError,
    LimitsParamsMismatchError,
    RecalibrationMismatchError,
)
from voracious.application.lifecycle import base_content_hash, frozen_base
from voracious.application.phase1_steps import (
    Calibration,
    Phase1Steps,
    Phase1StepsRegistry,
    resolve_steps,
)
from voracious.application.ports import (
    Clock,
    DatasetStorage,
    DepurationRepository,
    FitRepository,
    IdGenerator,
    JobKind,
    JobQueue,
    JobRequest,
    LimitsRepository,
    ModelRepository,
    ModelVersionRepository,
)
from voracious.application.records import (
    AssignableCause,
    DatasetRecord,
    DatasetSource,
    DepurationRecord,
    ErrorInfo,
    FitRecord,
    IndexVector,
    JobStatus,
    LifecyclePolicy,
    LimitsRecord,
    ModelProvenance,
    ModelRecord,
    NextStep,
    RecalibrationRecord,
)
from voracious.application.use_cases.common import INTERNAL_ERROR, get_model
from voracious.application.use_cases.training import initial_version
from voracious.domain.common import (
    BoolVector,
    DomainError,
    FloatMatrix,
    InvalidInputError,
    RowDisposition,
    StageKind,
    StageLineage,
    TaskMapper,
    as_matrix,
)

__all__ = [
    "DatasetLineage",
    "GetDataset",
    "GetDepuration",
    "GetFit",
    "GetLimits",
    "RecalibrationLinks",
    "RequestDepuration",
    "RequestFit",
    "RequestLimits",
    "RequestModel",
    "RunDepurationJob",
    "RunFitJob",
    "RunLimitsJob",
    "RunModelAssemblyJob",
    "UploadDataset",
    "dataset_chain",
    "get_dataset",
    "get_depuration",
    "get_fit",
    "get_limits",
    "human_mask",
    "notify_pipeline",
    "parse_csv",
    "ready_fit",
    "ready_limits",
    "recalibration_session",
    "root_indices",
    "stage_lineage",
]

MAX_REPORTED_CELLS = 20
"""Máximo de celdas inválidas que se informan en ``details`` (no es un parámetro estadístico)."""

_ROOT_KINDS: dict[DatasetSource, StageKind] = {
    DatasetSource.UPLOAD: StageKind.PHASE1,
    DatasetSource.RECALIBRATION_CANDIDATES: StageKind.NEW_ROWS,
    DatasetSource.RECALIBRATION_EXTENSION: StageKind.EXTENSION,
}
"""Operación del linaje según el origen del dataset raíz."""

_RECALIBRATION_ROOTS = frozenset(
    {DatasetSource.RECALIBRATION_CANDIDATES, DatasetSource.RECALIBRATION_EXTENSION}
)
"""Orígenes de un dataset raíz que pertenece a una recalibración."""


class RecalibrationLinks(Protocol):
    """Lo que los pasos de la Fase I necesitan de una recalibración por pasos (vuelta 3.4).

    Lo implementa ``use_cases.recalibration_chain.RecalibrationChain``.
    """

    def session_for(
        self, tenant_id: str, chart_id: str, root: DatasetRecord
    ) -> RecalibrationRecord:
        """Recalibración en curso dueña de un dataset raíz de recalibración.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            root: Dataset raíz (``origin_ref`` es la recalibración).

        Returns:
            La recalibración ``running``.

        Raises:
            RecalibrationNotFoundError: Si no existe.
            RecalibrationNotInProgressError: Si ya no admite pasos.
        """
        ...

    def human_causes(self, session: RecalibrationRecord) -> tuple[AssignableCause, ...]:
        """Exclusión humana de las candidatas: anotaciones con causa asignable confirmada.

        Args:
            session: Recalibración.

        Returns:
            Filas del dataset de candidatas con su causa y su anotación, en orden.
        """
        ...

    def bounds(self, session: RecalibrationRecord) -> tuple[int, int]:
        """Rondas máximas y mínimo de filas de la depuración de las filas nuevas.

        Args:
            session: Recalibración.

        Returns:
            ``(max_rounds, min_rows)``.
        """
        ...

    def close_insufficient(
        self,
        session: RecalibrationRecord,
        chain: Sequence[DatasetRecord],
        final: DepurationRecord,
    ) -> None:
        """Cierra la recalibración ``insufficient`` porque la depuración se agotó.

        Args:
            session: Recalibración.
            chain: Ascendencia del dataset depurado.
            final: Depuración agotada (con su resultado).
        """
        ...


# --- búsquedas -----------------------------------------------------------------------------------


def get_dataset(datasets: DatasetStorage, tenant_id: str, dataset_id: str) -> DatasetRecord:
    """Busca un dataset o lanza ``DatasetNotFoundError``.

    Args:
        datasets: Almacenamiento.
        tenant_id: Tenant.
        dataset_id: Dataset.

    Returns:
        El dataset.

    Raises:
        DatasetNotFoundError: Si no existe para ese tenant.
    """
    record = datasets.get(tenant_id, dataset_id)
    if record is None:
        raise DatasetNotFoundError(
            f"el dataset '{dataset_id}' no existe", details={"dataset_id": dataset_id}
        )
    return record


def get_fit(fits: FitRepository, tenant_id: str, chart_id: str, fit_id: str) -> FitRecord:
    """Busca un ajuste o lanza ``FitNotFoundError``.

    Args:
        fits: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        fit_id: Ajuste.

    Returns:
        El ajuste.

    Raises:
        FitNotFoundError: Si no existe para esa clave.
    """
    record = fits.get(tenant_id, chart_id, fit_id)
    if record is None:
        raise FitNotFoundError(f"el ajuste '{fit_id}' no existe", details={"fit_id": fit_id})
    return record


def ready_fit(fits: FitRepository, tenant_id: str, chart_id: str, fit_id: str) -> FitRecord:
    """Ajuste ``succeeded`` o error.

    Args:
        fits: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        fit_id: Ajuste.

    Returns:
        El ajuste.

    Raises:
        FitNotFoundError: Si no existe.
        FitNotReadyError: Si no está ``succeeded``.
    """
    record = get_fit(fits, tenant_id, chart_id, fit_id)
    if record.status is not JobStatus.SUCCEEDED:
        raise FitNotReadyError(
            f"el ajuste '{fit_id}' no está listo",
            details={"fit_id": fit_id, "status": str(record.status)},
        )
    return record


def get_limits(
    limits: LimitsRepository, tenant_id: str, chart_id: str, limits_id: str
) -> LimitsRecord:
    """Busca unos límites o lanza ``LimitsNotFoundError``.

    Args:
        limits: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        limits_id: Límites.

    Returns:
        Los límites.

    Raises:
        LimitsNotFoundError: Si no existen para esa clave.
    """
    record = limits.get(tenant_id, chart_id, limits_id)
    if record is None:
        raise LimitsNotFoundError(
            f"los límites '{limits_id}' no existen", details={"limits_id": limits_id}
        )
    return record


def ready_limits(
    limits: LimitsRepository, tenant_id: str, chart_id: str, limits_id: str
) -> LimitsRecord:
    """Límites ``succeeded`` o error.

    Args:
        limits: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        limits_id: Límites.

    Returns:
        Los límites.

    Raises:
        LimitsNotFoundError: Si no existen.
        LimitsNotReadyError: Si no están ``succeeded``.
    """
    record = get_limits(limits, tenant_id, chart_id, limits_id)
    if record.status is not JobStatus.SUCCEEDED:
        raise LimitsNotReadyError(
            f"los límites '{limits_id}' no están listos",
            details={"limits_id": limits_id, "status": str(record.status)},
        )
    return record


def get_depuration(
    depurations: DepurationRepository, tenant_id: str, chart_id: str, depuration_id: str
) -> DepurationRecord:
    """Busca una depuración o lanza ``DepurationNotFoundError``.

    Args:
        depurations: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        depuration_id: Depuración.

    Returns:
        La depuración.

    Raises:
        DepurationNotFoundError: Si no existe para esa clave.
    """
    record = depurations.get(tenant_id, chart_id, depuration_id)
    if record is None:
        raise DepurationNotFoundError(
            f"la depuración '{depuration_id}' no existe",
            details={"depuration_id": depuration_id},
        )
    return record


# --- linaje --------------------------------------------------------------------------------------


def dataset_chain(datasets: DatasetStorage, record: DatasetRecord) -> list[DatasetRecord]:
    """Ascendencia de un dataset, de la raíz a él mismo.

    Args:
        datasets: Almacenamiento.
        record: Dataset.

    Returns:
        Los datasets desde la raíz.

    Raises:
        DatasetNotFoundError: Si falta un antecesor (error de integridad).
    """
    chain = [record]
    while chain[0].parent_id is not None:
        chain.insert(0, get_dataset(datasets, record.tenant_id, chain[0].parent_id))
    return chain


def stage_lineage(chain: Sequence[DatasetRecord]) -> StageLineage:
    """Linaje de la calibración sobre el último dataset de ``chain``.

    Args:
        chain: Ascendencia desde la raíz (``dataset_chain``).

    Returns:
        Operación (por el origen de la raíz) y ronda (``lineage_round`` del dataset).

    Raises:
        InvalidInputError: Si la raíz no es un dataset raíz o el linaje no es válido.
    """
    kind = _ROOT_KINDS.get(chain[0].source)
    if kind is None:
        raise InvalidInputError(
            "el dataset raíz no tiene un origen de raíz",
            details={"dataset_id": chain[0].dataset_id, "source": str(chain[0].source)},
        )
    return StageLineage(kind, chain[-1].lineage_round)


def _require_links(links: "RecalibrationLinks | None") -> RecalibrationLinks:
    """Los enlaces con la recalibración, o error si el caso de uso se construyó sin ellos.

    Args:
        links: Enlaces.

    Returns:
        Los enlaces.

    Raises:
        RecalibrationMismatchError: Si no hay (la recalibración por pasos no está cableada).
    """
    if links is None:
        raise RecalibrationMismatchError(
            "este paso no admite datasets de recalibración", details={"reason": "not_wired"}
        )
    return links


def recalibration_session(
    links: "RecalibrationLinks | None",
    tenant_id: str,
    chart_id: str,
    chain: Sequence[DatasetRecord],
) -> RecalibrationRecord | None:
    """Recalibración en curso a la que pertenece la ascendencia, o ``None`` si es de Fase I.

    Args:
        links: Enlaces con la recalibración.
        tenant_id: Tenant.
        chart_id: Carta.
        chain: Ascendencia desde la raíz.

    Returns:
        La recalibración, o ``None`` si la raíz es un dataset subido.
    """
    if chain[0].source not in _RECALIBRATION_ROOTS:
        return None
    return _require_links(links).session_for(tenant_id, chart_id, chain[0])


def root_indices(chain: Sequence[DatasetRecord]) -> list[IndexVector]:
    """Índices en la raíz de las filas de cada dataset de la ascendencia.

    Args:
        chain: Ascendencia desde la raíz.

    Returns:
        Un vector por dataset, en el mismo orden.
    """
    out: list[IndexVector] = [np.arange(chain[0].data.shape[0], dtype=np.int64)]
    for record in chain[1:]:
        rows = record.rows if record.rows is not None else np.zeros(0, dtype=np.int64)
        out.append(out[-1][rows])
    return out


# --- comunes -------------------------------------------------------------------------------------


def notify_pipeline(
    queue: JobQueue, tenant_id: str, chart_id: str, pipeline_id: str | None
) -> None:
    """Avisa a la tubería que pidió un recurso de que el recurso terminó.

    Args:
        queue: Cola.
        tenant_id: Tenant.
        chart_id: Carta.
        pipeline_id: Tubería, o ``None`` (no avisa).
    """
    if pipeline_id is not None:
        queue.enqueue(JobRequest(JobKind.PIPELINE, tenant_id, chart_id, pipeline_id))


def _error_of(exc: DomainError | ApplicationError) -> ErrorInfo:
    """Error de un trabajo a partir de una excepción con código.

    Args:
        exc: Excepción.

    Returns:
        El error.
    """
    return ErrorInfo(code=exc.code, message=exc.message, details=exc.details)


def _check_same_fit(limits: LimitsRecord, fit_id: str) -> None:
    """Exige que los límites se calibraran sobre el ajuste indicado.

    Args:
        limits: Límites.
        fit_id: Ajuste.

    Raises:
        LimitsFitMismatchError: Si son de otro ajuste.
    """
    if limits.fit_id != fit_id:
        raise LimitsFitMismatchError(
            f"los límites '{limits.limits_id}' no se calibraron sobre el ajuste '{fit_id}'",
            details={
                "limits_id": limits.limits_id,
                "fit_id": fit_id,
                "limits_fit_id": limits.fit_id,
            },
        )


def _check_kind(job: JobRequest, kind: JobKind, name: str) -> None:
    """Exige el tipo de trabajo de un ``Run…Job``.

    Args:
        job: Petición.
        kind: Tipo exigido.
        name: Caso de uso, para el mensaje.

    Raises:
        ValueError: Si no coincide.
    """
    if job.kind is not kind:
        msg = f"{name} solo ejecuta trabajos '{kind}', no '{job.kind}'"
        raise ValueError(msg)


def _validated_upload(data: npt.ArrayLike) -> FloatMatrix:
    """Matriz de un dataset subido: ``n x p`` no vacía y finita, ``float64`` contigua.

    Args:
        data: Datos.

    Returns:
        La matriz de solo lectura.

    Raises:
        InvalidInputError: Si no es una matriz numérica no vacía y finita.
    """
    arr = as_matrix(data, name="data")
    n, p = arr.shape
    if n == 0 or p == 0:
        raise InvalidInputError(
            "'data' no puede estar vacía", details={"input": "data", "shape": [n, p]}
        )
    bad = np.flatnonzero(~np.isfinite(arr).all(axis=1))
    if bad.size:
        raise InvalidInputError(
            "'data' contiene valores no finitos (NaN o infinito)",
            details={"input": "data", "rows": [int(i) for i in bad[:MAX_REPORTED_CELLS]]},
        )
    return frozen_base(np.ascontiguousarray(arr))


def parse_csv(text: str) -> list[list[float]]:
    """Lee una matriz numérica de un CSV (coma como separador; cabecera opcional).

    Si alguna celda de la primera fila no es un número, la fila se toma como cabecera y se
    descarta. Las líneas vacías se ignoran.

    Args:
        text: Contenido del CSV.

    Returns:
        Las filas como listas de ``float``.

    Raises:
        InvalidInputError: Si una celda no es numérica (fuera de la cabecera) o no hay filas.
    """
    rows = [row for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row)]
    if rows and not all(_is_number(c) for c in rows[0]):
        rows = rows[1:]
    bad: list[dict[str, object]] = []
    out: list[list[float]] = []
    for i, row in enumerate(rows):
        values: list[float] = []
        for j, cell in enumerate(row):
            if _is_number(cell):
                values.append(float(cell))
            else:
                bad.append({"row": i, "column": j})
        out.append(values)
    if bad:
        raise InvalidInputError(
            "el CSV tiene celdas no numéricas",
            details={"input": "csv", "cells": bad[:MAX_REPORTED_CELLS], "n_bad": len(bad)},
        )
    if not out:
        raise InvalidInputError("el CSV no tiene filas", details={"input": "csv"})
    return out


def _is_number(cell: str) -> bool:
    """Indica si una celda se lee como número real.

    Args:
        cell: Celda.

    Returns:
        ``True`` si ``float(cell)`` funciona.
    """
    try:
        float(cell)
    except ValueError:
        return False
    return True


# --- datasets ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UploadDataset:
    """Guarda un dataset subido por el cliente (raíz de una Fase I).

    Attributes:
        datasets: Almacenamiento.
        ids: Identificadores.
        clock: Reloj.
    """

    datasets: DatasetStorage
    ids: IdGenerator
    clock: Clock

    def execute(self, tenant_id: str, data: npt.ArrayLike) -> DatasetRecord:
        """Valida y guarda la matriz.

        Args:
            tenant_id: Tenant.
            data: Matriz ``n x p``.

        Returns:
            El dataset guardado.

        Raises:
            InvalidInputError: Si no es una matriz numérica no vacía y finita.
        """
        arr = _validated_upload(data)
        record = DatasetRecord(
            tenant_id=tenant_id,
            dataset_id=self.ids.new_id(),
            data=arr,
            content_hash=base_content_hash(arr),
            source=DatasetSource.UPLOAD,
            created_at=self.clock.now(),
        )
        self.datasets.add(record)
        return record

    def execute_csv(self, tenant_id: str, text: str) -> DatasetRecord:
        """Lee un CSV (``parse_csv``) y lo guarda como ``execute``.

        Args:
            tenant_id: Tenant.
            text: Contenido del CSV.

        Returns:
            El dataset guardado.

        Raises:
            InvalidInputError: Si el CSV no es una matriz numérica finita.
        """
        return self.execute(tenant_id, parse_csv(text))


@dataclass(frozen=True)
class DatasetLineage:
    """Un dataset con su ascendencia.

    Attributes:
        dataset: El dataset.
        chain: Ascendencia desde la raíz (incluye ``dataset`` al final).
    """

    dataset: DatasetRecord
    chain: tuple[DatasetRecord, ...]


@dataclass(frozen=True)
class GetDataset:
    """Consulta un dataset con su linaje.

    Attributes:
        datasets: Almacenamiento.
    """

    datasets: DatasetStorage

    def execute(self, tenant_id: str, dataset_id: str) -> DatasetLineage:
        """Devuelve el dataset y su ascendencia.

        Args:
            tenant_id: Tenant.
            dataset_id: Dataset.

        Returns:
            El dataset con su linaje.

        Raises:
            DatasetNotFoundError: Si no existe para ese tenant.
        """
        record = get_dataset(self.datasets, tenant_id, dataset_id)
        return DatasetLineage(record, tuple(dataset_chain(self.datasets, record)))


# --- ajuste --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestFit:
    """Valida y encola el ajuste del estimador de una carta sobre un dataset (``/fits``).

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        queue: Cola.
        ids: Identificadores.
        clock: Reloj.
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock

    def execute(self, tenant_id: str, chart_id: str, dataset_id: str, fit_params: object) -> str:
        """Encola el ajuste.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            dataset_id: Dataset.
            fit_params: Parámetros del estimador (cada carta los suyos), o ``None``
                para los de la carta.

        Returns:
            El ``fit_id``.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            DatasetNotFoundError: Si el dataset no existe.
            InvalidInputError: Si la carta no admite el dataset (validación síncrona).
        """
        steps = resolve_steps(self.steps, chart_id)
        return self.create(
            tenant_id, chart_id, dataset_id, steps.encode_fit_params(fit_params), steps=steps
        )

    def create(
        self,
        tenant_id: str,
        chart_id: str,
        dataset_id: str,
        fit_params: dict[str, object],
        *,
        steps: Phase1Steps | None = None,
        fit_id: str | None = None,
        pipeline_id: str | None = None,
    ) -> str:
        """Crea el ajuste con parámetros ya codificados (lo usa también la tubería).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            dataset_id: Dataset.
            fit_params: Parámetros del estimador codificados.
            steps: Pasos de la carta (``None``: se resuelven).
            fit_id: Identificador ya reservado (``None``: uno nuevo).
            pipeline_id: Tubería que lo pide.

        Returns:
            El ``fit_id``.
        """
        resolved = steps if steps is not None else resolve_steps(self.steps, chart_id)
        dataset = get_dataset(self.datasets, tenant_id, dataset_id)
        resolved.validate_input(dataset.data)
        record = FitRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            fit_id=fit_id if fit_id is not None else self.ids.new_id(),
            dataset_id=dataset_id,
            status=JobStatus.QUEUED,
            params=fit_params,
            created_at=self.clock.now(),
            pipeline_id=pipeline_id,
        )
        self.fits.add(record)
        self.queue.enqueue(JobRequest(JobKind.MRCD_FIT, tenant_id, chart_id, record.fit_id))
        return record.fit_id


@dataclass(frozen=True)
class GetFit:
    """Consulta un ajuste.

    Attributes:
        steps: Pasos de Fase I por carta.
        fits: Repositorio.
    """

    steps: Phase1StepsRegistry
    fits: FitRepository

    def execute(self, tenant_id: str, chart_id: str, fit_id: str) -> FitRecord:
        """Devuelve el ajuste.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste.

        Returns:
            El registro.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            FitNotFoundError: Si no existe.
        """
        resolve_steps(self.steps, chart_id)
        return get_fit(self.fits, tenant_id, chart_id, fit_id)


@dataclass(frozen=True)
class RunFitJob:
    """Ejecuta un ajuste encolado: ``running`` → ``succeeded | failed`` (carril ``estimation``).

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        queue: Cola (aviso a la tubería).
        clock: Reloj.
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    queue: JobQueue
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo; idempotente (si el ajuste ya no está ``queued``, no hace nada).

        Un ``DomainError`` o ``ApplicationError`` deja el ajuste ``failed`` con su código;
        cualquier otra excepción, ``failed / INTERNAL_ERROR`` y se relanza.

        Args:
            job: Petición ``mrcd_fit``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``mrcd_fit``.
            UnknownChartError: Si la carta no expone pasos.
            FitNotFoundError: Si el ajuste no existe.
        """
        _check_kind(job, JobKind.MRCD_FIT, "RunFitJob")
        steps = resolve_steps(self.steps, job.scope)
        get_fit(self.fits, job.tenant_id, job.scope, job.resource_id)
        record = self.fits.claim(job.tenant_id, job.scope, job.resource_id, self.clock.now())
        if record is None:
            return
        try:
            dataset = get_dataset(self.datasets, job.tenant_id, record.dataset_id)
            fit = steps.fit(dataset.data, record.params)
        except (DomainError, ApplicationError) as exc:
            self._close(record, error=_error_of(exc))
            return
        except Exception:
            self._close(record, error=ErrorInfo(INTERNAL_ERROR, "error interno en el ajuste"))
            raise
        self._close(record, result=fit)

    def _close(
        self, record: FitRecord, *, result: object = None, error: ErrorInfo | None = None
    ) -> None:
        """Cierra el ajuste y avisa a su tubería.

        Args:
            record: Registro en ``running``.
            result: Ajuste si terminó bien.
            error: Error si falló.
        """
        status = JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED
        self.fits.update(
            replace(record, status=status, finished_at=self.clock.now(), result=result, error=error)
        )
        notify_pipeline(self.queue, record.tenant_id, record.chart_id, record.pipeline_id)


# --- límites -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestLimits:
    """Valida y encola la calibración de límites sobre un ajuste (``/limits``).

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        depurations: Repositorio de depuraciones (parámetros heredados de la cadena).
        queue: Cola.
        ids: Identificadores.
        clock: Reloj.
        recalibration: Enlaces con la recalibración por pasos (``None``: solo Fase I).
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    depurations: DepurationRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock
    recalibration: RecalibrationLinks | None = None

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        fit_id: str,
        params: object | None,
        *,
        recalibration_id: str | None = None,
    ) -> str:
        """Encola la calibración.

        Como mucho una de las dos: ``params`` (Fase I) o ``recalibration_id`` (filas nuevas o
        base ampliada de esa recalibración: hereda los parámetros de la versión base). En la Fase
        I, ``params`` es obligatorio sobre un dataset sin ronda automática previa y opcional sobre
        uno derivado de una depuración automática (se heredan; si se mandan, deben coincidir).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste ``succeeded``.
            params: Parámetros de la carta (cada carta los suyos), o ``None``.
            recalibration_id: Recalibración, o ``None``.

        Returns:
            El ``limits_id``.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            InvalidInputError: Si llegan las dos formas, faltan los parámetros o falta la
                exclusión humana de las candidatas.
            FitNotFoundError: Si el ajuste no existe.
            FitNotReadyError: Si no está ``succeeded``.
            RecalibrationMismatchError: Si el dataset no es de esa recalibración (o de ninguna).
            LimitsParamsMismatchError: Si ``params`` difiere de los heredados de la cadena.
            DomainError: Si hay decisiones pendientes (``T2MRCD_DECISION_PENDING``) o los
                parámetros de su estimador no son los que usará la carta
                (``T2MRCD_FIT_PARAMS_MISMATCH`` en T²MRCD).
        """
        steps = resolve_steps(self.steps, chart_id)
        if params is not None and recalibration_id is not None:
            raise InvalidInputError(
                "unos límites llevan 'params' (Fase I) o 'recalibration_id', no los dos",
                details={"field": "params", "reason": "one_of_params_or_recalibration"},
            )
        encoded = None if params is None else steps.encode_params(params)
        return self.create(
            tenant_id, chart_id, fit_id, encoded, steps=steps, recalibration_id=recalibration_id
        )

    def create(
        self,
        tenant_id: str,
        chart_id: str,
        fit_id: str,
        params: dict[str, object] | None,
        *,
        steps: Phase1Steps | None = None,
        recalibration_id: str | None = None,
        limits_id: str | None = None,
        pipeline_id: str | None = None,
    ) -> str:
        """Crea la calibración con parámetros ya codificados (lo usa también la tubería).

        El linaje (y con él el hueco de semilla) se deduce del dataset del ajuste. En un
        dataset de recalibración los parámetros son los heredados de la sesión (``params`` se
        ignora) y, sobre las candidatas sin depurar, se exige antes la exclusión humana si hay
        anotaciones con causa asignable. En la Fase I, sobre un dataset derivado de una
        depuración automática, los parámetros son los de los límites que lo produjeron: todas
        las rondas de la cadena usan los mismos, como ``fit_phase1``. Las decisiones pendientes
        de la carta se comprueban aquí, antes de encolar.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste.
            params: Parámetros de la carta codificados (``None`` en una recalibración o para
                heredarlos de la cadena).
            steps: Pasos de la carta (``None``: se resuelven).
            recalibration_id: Recalibración a la que pertenece el dataset, si es de una.
            limits_id: Identificador ya reservado.
            pipeline_id: Tubería que la pide.

        Returns:
            El ``limits_id``.

        Raises:
            RecalibrationMismatchError: Si ``recalibration_id`` no es el del dataset.
            InvalidInputError: Si falta la exclusión humana de las candidatas o faltan los
                parámetros.
            LimitsParamsMismatchError: Si ``params`` difiere de los heredados de la cadena.
            DomainError: Si hay decisiones pendientes o el ajuste no casa con los parámetros.
        """
        resolved = steps if steps is not None else resolve_steps(self.steps, chart_id)
        fit = ready_fit(self.fits, tenant_id, chart_id, fit_id)
        dataset = get_dataset(self.datasets, tenant_id, fit.dataset_id)
        chain = dataset_chain(self.datasets, dataset)
        root = chain[0]
        expected = root.origin_ref if root.source in _RECALIBRATION_ROOTS else None
        if recalibration_id != expected:
            raise RecalibrationMismatchError(
                "el ajuste no es de esa recalibración",
                details={
                    "fit_id": fit_id,
                    "dataset_id": root.dataset_id,
                    "recalibration_id": recalibration_id,
                    "dataset_recalibration_id": expected,
                },
            )
        session = recalibration_session(self.recalibration, tenant_id, chart_id, chain)
        if session is not None:
            links = _require_links(self.recalibration)
            if (
                root.source is DatasetSource.RECALIBRATION_CANDIDATES
                and len(chain) == 1
                and links.human_causes(session)
            ):
                raise InvalidInputError(
                    "hay candidatas con causa asignable: primero la exclusión humana",
                    details={"fit_id": fit_id, "reason": "human_exclusion_required"},
                )
            params = dict(session.inherited_params)
        else:
            params = self._chain_params(tenant_id, chart_id, fit_id, chain, params)
        resolved.check_params(params)
        resolved.check_fit_params(fit.params, params)
        lineage = stage_lineage(chain)
        record = LimitsRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            limits_id=limits_id if limits_id is not None else self.ids.new_id(),
            fit_id=fit_id,
            status=JobStatus.QUEUED,
            params=params,
            seed=resolved.seed(params),
            stage_kind=lineage.kind.value,
            round=lineage.round,
            spawn_key=resolved.stage_spawn_key(lineage),
            created_at=self.clock.now(),
            recalibration_id=recalibration_id,
            pipeline_id=pipeline_id,
        )
        self.limits.add(record)
        self.queue.enqueue(JobRequest(JobKind.LIMITS, tenant_id, chart_id, record.limits_id))
        return record.limits_id

    def _chain_params(
        self,
        tenant_id: str,
        chart_id: str,
        fit_id: str,
        chain: Sequence[DatasetRecord],
        params: dict[str, object] | None,
    ) -> dict[str, object]:
        """Parámetros de una calibración de Fase I: los heredados de la cadena o los del cliente.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste (para los mensajes).
            chain: Ascendencia del dataset del ajuste.
            params: Parámetros del cliente codificados, o ``None``.

        Returns:
            Los parámetros de la calibración.

        Raises:
            InvalidInputError: Si faltan y no hay de dónde heredarlos.
            LimitsParamsMismatchError: Si difieren de los heredados.
        """
        source = self._source_limits(tenant_id, chart_id, chain)
        if source is None:
            if params is None:
                raise InvalidInputError(
                    "faltan los parámetros de la carta: el dataset no viene de una ronda "
                    "automática de la que heredarlos",
                    details={"field": "params", "reason": "params_required"},
                )
            return params
        inherited = dict(source.params)
        if params is None:
            return inherited
        if params != inherited:
            raise LimitsParamsMismatchError(
                "los parámetros no son los de la cadena de Fase I del dataset",
                details={
                    "fit_id": fit_id,
                    "source_limits_id": source.limits_id,
                    "fields": _differing_fields(params, inherited),
                },
            )
        return params

    def _source_limits(
        self, tenant_id: str, chart_id: str, chain: Sequence[DatasetRecord]
    ) -> LimitsRecord | None:
        """Límites de la última ronda automática de la ascendencia (``None`` si no hubo).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            chain: Ascendencia desde la raíz.

        Returns:
            Los límites que produjeron el último dataset derivado de una ronda automática.
        """
        for derived in reversed(chain[1:]):
            if derived.origin_ref is None:
                continue
            depuration = get_depuration(self.depurations, tenant_id, chart_id, derived.origin_ref)
            if depuration.limits_id is not None:
                return get_limits(self.limits, tenant_id, chart_id, depuration.limits_id)
        return None


def _differing_fields(
    left: Mapping[str, object], right: Mapping[str, object], prefix: str = ""
) -> list[str]:
    """Campos (con su ruta ``a.b``) en que difieren dos parámetros codificados.

    Args:
        left: Unos parámetros.
        right: Otros.
        prefix: Ruta del diccionario actual.

    Returns:
        Las rutas distintas, ordenadas.
    """
    out: list[str] = []
    for key in sorted(set(left) | set(right)):
        a, b = left.get(key), right.get(key)
        path = f"{prefix}{key}"
        if isinstance(a, Mapping) and isinstance(b, Mapping):
            out.extend(_differing_fields(a, b, f"{path}."))
        elif a != b or (key in left) != (key in right):
            out.append(path)
    return out


@dataclass(frozen=True)
class GetLimits:
    """Consulta unos límites.

    Attributes:
        steps: Pasos de Fase I por carta.
        limits: Repositorio.
    """

    steps: Phase1StepsRegistry
    limits: LimitsRepository

    def execute(self, tenant_id: str, chart_id: str, limits_id: str) -> LimitsRecord:
        """Devuelve los límites.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            limits_id: Límites.

        Returns:
            El registro.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            LimitsNotFoundError: Si no existen.
        """
        resolve_steps(self.steps, chart_id)
        return get_limits(self.limits, tenant_id, chart_id, limits_id)


@dataclass(frozen=True)
class RunLimitsJob:
    """Ejecuta una calibración encolada (carril ``calibration``).

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        mapper: Reparto de las réplicas.
        queue: Cola (aviso a la tubería).
        clock: Reloj.
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    mapper: TaskMapper
    queue: JobQueue
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo; idempotente.

        Args:
            job: Petición ``limits``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``limits``.
            UnknownChartError: Si la carta no expone pasos.
            LimitsNotFoundError: Si los límites no existen.
        """
        _check_kind(job, JobKind.LIMITS, "RunLimitsJob")
        steps = resolve_steps(self.steps, job.scope)
        get_limits(self.limits, job.tenant_id, job.scope, job.resource_id)
        record = self.limits.claim(job.tenant_id, job.scope, job.resource_id, self.clock.now())
        if record is None:
            return
        try:
            fit = ready_fit(self.fits, job.tenant_id, job.scope, record.fit_id)
            dataset = get_dataset(self.datasets, job.tenant_id, fit.dataset_id)
            calibration = steps.calibrate(
                dataset.data,
                fit.result,
                record.params,
                lineage=StageLineage(StageKind(record.stage_kind), record.round),
                mapper=self.mapper,
            )
        except (DomainError, ApplicationError) as exc:
            self._close(record, error=_error_of(exc))
            return
        except Exception:
            self._close(record, error=ErrorInfo(INTERNAL_ERROR, "error interno en los límites"))
            raise
        self._close(record, calibration=calibration)

    def _close(
        self,
        record: LimitsRecord,
        *,
        calibration: Calibration | None = None,
        error: ErrorInfo | None = None,
    ) -> None:
        """Cierra la calibración y avisa a su tubería.

        Args:
            record: Registro en ``running``.
            calibration: Calibración si terminó bien.
            error: Error si falló.
        """
        self.limits.update(
            replace(
                record,
                status=JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED,
                finished_at=self.clock.now(),
                result=None if calibration is None else calibration.limits,
                clean_rows=None if calibration is None else calibration.clean,
                error=error,
            )
        )
        notify_pipeline(self.queue, record.tenant_id, record.chart_id, record.pipeline_id)


# --- depuración ----------------------------------------------------------------------------------


def human_mask(causes: Sequence[AssignableCause], n: int) -> BoolVector:
    """Máscara de exclusión humana sobre ``n`` filas, validada.

    Args:
        causes: Filas con causa asignable.
        n: Filas del dataset.

    Returns:
        La máscara.

    Raises:
        InvalidInputError: Si una fila está fuera de rango o repetida.
    """
    mask = np.zeros(n, dtype=np.bool_)
    for item in causes:
        if isinstance(item.row, bool) or not 0 <= item.row < n:
            raise InvalidInputError(
                f"la fila {item.row} está fuera del dataset (0..{n - 1})",
                details={"field": "assignable_cause.row", "row": item.row, "n": n},
            )
        if mask[item.row]:
            raise InvalidInputError(
                f"la fila {item.row} está repetida",
                details={"field": "assignable_cause.row", "row": item.row},
            )
        mask[item.row] = True
    return mask


@dataclass(frozen=True)
class RequestDepuration:
    """Valida y encola una depuración de un ajuste (``/depurations``).

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        depurations: Repositorio de depuraciones.
        queue: Cola.
        ids: Identificadores.
        clock: Reloj.
        recalibration: Enlaces con la recalibración por pasos (``None``: solo Fase I).
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    depurations: DepurationRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock
    recalibration: RecalibrationLinks | None = None

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        *,
        dataset_id: str | None = None,
        fit_id: str | None = None,
        limits_id: str | None = None,
        assignable_cause: Sequence[AssignableCause] = (),
        depuration_id: str | None = None,
        pipeline_id: str | None = None,
    ) -> str:
        """Encola la depuración.

        Dos formas, exactamente una:

        - Exclusión humana ``{dataset_id, assignable_cause}``: referencia el dataset, sin ajuste
          (las filas con causa asignable se quitan antes de ajustar nada, como en
          ``fit_phase1``). Solo al principio: sobre un dataset sin rondas automáticas en su
          ascendencia. Sobre las candidatas de una recalibración la exclusión **no** la manda el
          cliente: ``{dataset_id}`` solo, y se toma de las anotaciones con causa asignable
          confirmada (solo sobre el dataset de candidatas sin depurar).
        - Ronda automática ``{fit_id, limits_id}``: límites ``succeeded`` del mismo ajuste.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            dataset_id: Dataset de la exclusión humana.
            fit_id: Ajuste ``succeeded`` de la ronda automática.
            limits_id: Límites ``succeeded`` del mismo ajuste.
            assignable_cause: Filas del dataset con causa asignable (exclusión humana).
            depuration_id: Identificador ya reservado (tubería).
            pipeline_id: Tubería que la pide.

        Returns:
            El ``depuration_id``.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            DatasetNotFoundError: Si el dataset no existe.
            FitNotFoundError: Si el ajuste no existe.
            FitNotReadyError: Si no está ``succeeded``.
            LimitsNotFoundError: Si los límites no existen.
            LimitsNotReadyError: Si no están ``succeeded``.
            LimitsFitMismatchError: Si los límites son de otro ajuste.
            InvalidInputError: Si no es exactamente una de las dos formas, una fila es inválida,
                la exclusión humana no es al principio o deja el dataset vacío.
            RecalibrationNotInProgressError: Si la recalibración del dataset ya terminó.
        """
        resolve_steps(self.steps, chart_id)
        causes = tuple(assignable_cause)
        if dataset_id is not None and fit_id is None and limits_id is None:
            return self._human(tenant_id, chart_id, dataset_id, causes, depuration_id, pipeline_id)
        if dataset_id is None and fit_id is not None and limits_id is not None and not causes:
            return self._automatic(
                tenant_id, chart_id, fit_id, limits_id, depuration_id, pipeline_id
            )
        raise InvalidInputError(
            "una depuración se pide con {dataset_id, assignable_cause} (exclusión humana) o "
            "con {fit_id, limits_id} (ronda automática)",
            details={"field": "dataset_id", "reason": "one_of_human_or_automatic"},
        )

    def _human(
        self,
        tenant_id: str,
        chart_id: str,
        dataset_id: str,
        causes: tuple[AssignableCause, ...],
        depuration_id: str | None,
        pipeline_id: str | None,
    ) -> str:
        """Valida y encola una exclusión humana (sin ajuste).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            dataset_id: Dataset.
            causes: Filas del cliente con causa asignable.
            depuration_id: Identificador reservado o ``None``.
            pipeline_id: Tubería que la pide.

        Returns:
            El ``depuration_id``.
        """
        dataset = get_dataset(self.datasets, tenant_id, dataset_id)
        chain = dataset_chain(self.datasets, dataset)
        session = recalibration_session(self.recalibration, tenant_id, chart_id, chain)
        if session is not None:
            causes = self._recalibration_causes(session, chain, causes)
            human_mask(causes, dataset.data.shape[0])
        else:
            self._check_human(tenant_id, chart_id, chain, causes)
        return self._add(
            tenant_id, chart_id, dataset, None, None, causes, depuration_id, pipeline_id
        )

    def _automatic(
        self,
        tenant_id: str,
        chart_id: str,
        fit_id: str,
        limits_id: str,
        depuration_id: str | None,
        pipeline_id: str | None,
    ) -> str:
        """Valida y encola una ronda automática.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste.
            limits_id: Límites del mismo ajuste.
            depuration_id: Identificador reservado o ``None``.
            pipeline_id: Tubería que la pide.

        Returns:
            El ``depuration_id``.

        Raises:
            InvalidInputError: Si la recalibración no admite la ronda (base ampliada o falta la
                exclusión humana de las candidatas).
        """
        fit = ready_fit(self.fits, tenant_id, chart_id, fit_id)
        dataset = get_dataset(self.datasets, tenant_id, fit.dataset_id)
        chain = dataset_chain(self.datasets, dataset)
        session = recalibration_session(self.recalibration, tenant_id, chart_id, chain)
        if session is not None:
            reason: str | None = None
            if chain[0].source is DatasetSource.RECALIBRATION_EXTENSION:
                reason = "extension_is_not_depurated"
            elif len(chain) == 1 and _require_links(self.recalibration).human_causes(session):
                reason = "human_exclusion_required"
            if reason is not None:
                raise InvalidInputError(
                    "depuración no admitida en esta recalibración"
                    if reason == "extension_is_not_depurated"
                    else "hay candidatas con causa asignable: primero la exclusión humana",
                    details={"recalibration_id": session.recalibration_id, "reason": reason},
                )
        _check_same_fit(ready_limits(self.limits, tenant_id, chart_id, limits_id), fit_id)
        return self._add(
            tenant_id, chart_id, dataset, fit_id, limits_id, (), depuration_id, pipeline_id
        )

    def _check_human(
        self,
        tenant_id: str,
        chart_id: str,
        chain: Sequence[DatasetRecord],
        causes: tuple[AssignableCause, ...],
    ) -> None:
        """Valida una exclusión humana de Fase I: al principio, con filas y sin vaciar el dataset.

        Como en ``fit_phase1`` (``docs/metodos/t2mrcd.md``), las filas con causa asignable se
        quitan antes de la depuración automática: no se admite sobre un dataset con rondas
        automáticas en su ascendencia.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            chain: Ascendencia del dataset.
            causes: Filas con causa asignable.

        Raises:
            InvalidInputError: Si no hay filas, no es al principio, una fila es inválida o quita
                todas.
        """
        dataset = chain[-1]
        if not causes:
            raise InvalidInputError(
                "una exclusión humana lleva 'assignable_cause'",
                details={"field": "assignable_cause", "reason": "assignable_cause_required"},
            )
        automatic = any(
            get_depuration(self.depurations, tenant_id, chart_id, d.origin_ref).limits_id
            is not None
            for d in chain[1:]
            if d.origin_ref is not None
        )
        if dataset.lineage_round != 0 or automatic:
            raise InvalidInputError(
                "la exclusión humana solo se admite al principio, antes de la depuración "
                "automática",
                details={
                    "dataset_id": dataset.dataset_id,
                    "reason": "human_exclusion_only_at_start",
                },
            )
        human = human_mask(causes, dataset.data.shape[0])
        if bool(human.all()):
            raise InvalidInputError(
                "la exclusión humana no puede quitar todas las filas",
                details={"field": "assignable_cause", "n": int(human.size)},
            )

    def _recalibration_causes(
        self,
        session: RecalibrationRecord,
        chain: Sequence[DatasetRecord],
        causes: tuple[AssignableCause, ...],
    ) -> tuple[AssignableCause, ...]:
        """Exclusión humana de una recalibración (de las anotaciones).

        Args:
            session: Recalibración en curso.
            chain: Ascendencia del dataset.
            causes: Las que mandó el cliente (deben ir vacías).

        Returns:
            Las filas excluidas por una persona.

        Raises:
            InvalidInputError: Si el cliente manda filas, la base ampliada se depura o la
                exclusión humana no es sobre las candidatas sin depurar.
        """
        links = _require_links(self.recalibration)
        reason: str | None = None
        if causes:
            reason = "assignable_cause_from_annotations"
        elif chain[0].source is DatasetSource.RECALIBRATION_EXTENSION:
            reason = "extension_is_not_depurated"
        elif len(chain) != 1:
            reason = "human_exclusion_only_on_candidates"
        if reason is not None:
            raise InvalidInputError(
                "depuración no admitida en esta recalibración",
                details={"recalibration_id": session.recalibration_id, "reason": reason},
            )
        return links.human_causes(session)

    def _add(
        self,
        tenant_id: str,
        chart_id: str,
        dataset: DatasetRecord,
        fit_id: str | None,
        limits_id: str | None,
        causes: tuple[AssignableCause, ...],
        depuration_id: str | None,
        pipeline_id: str | None,
    ) -> str:
        """Guarda la depuración ``queued`` y la encola.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            dataset: Dataset depurado.
            fit_id: Ajuste (ronda automática) o ``None``.
            limits_id: Límites (ronda automática) o ``None``.
            causes: Exclusión humana.
            depuration_id: Identificador reservado o ``None``.
            pipeline_id: Tubería que la pide.

        Returns:
            El ``depuration_id``.
        """
        record = DepurationRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            depuration_id=depuration_id if depuration_id is not None else self.ids.new_id(),
            dataset_id=dataset.dataset_id,
            status=JobStatus.QUEUED,
            assignable_cause=causes,
            round=dataset.lineage_round,
            created_at=self.clock.now(),
            fit_id=fit_id,
            limits_id=limits_id,
            pipeline_id=pipeline_id,
        )
        self.depurations.add(record)
        self.queue.enqueue(
            JobRequest(JobKind.DEPURATION, tenant_id, chart_id, record.depuration_id)
        )
        return record.depuration_id


@dataclass(frozen=True)
class GetDepuration:
    """Consulta una depuración.

    Attributes:
        steps: Pasos de Fase I por carta.
        depurations: Repositorio.
    """

    steps: Phase1StepsRegistry
    depurations: DepurationRepository

    def execute(self, tenant_id: str, chart_id: str, depuration_id: str) -> DepurationRecord:
        """Devuelve la depuración.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            depuration_id: Depuración.

        Returns:
            El registro.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            DepurationNotFoundError: Si no existe.
        """
        resolve_steps(self.steps, chart_id)
        return get_depuration(self.depurations, tenant_id, chart_id, depuration_id)


@dataclass(frozen=True)
class _DepurationResult:
    """Lo que una depuración terminada guarda."""

    disposition: tuple[RowDisposition, ...]
    kept: BoolVector
    automatic_removed: bool
    converged: bool | None
    final: bool
    exhausted: bool


@dataclass(frozen=True)
class RunDepurationJob:
    """Ejecuta una depuración encolada (carril ``calibration``; no ajusta nada).

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento (recibe el dataset derivado).
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        depurations: Repositorio de depuraciones.
        queue: Cola (aviso a la tubería).
        ids: Identificadores (dataset derivado).
        clock: Reloj.
        recalibration: Enlaces con la recalibración por pasos (``None``: solo Fase I).
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    depurations: DepurationRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock
    recalibration: RecalibrationLinks | None = None

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo; idempotente.

        Args:
            job: Petición ``depuration``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``depuration``.
            UnknownChartError: Si la carta no expone pasos.
            DepurationNotFoundError: Si la depuración no existe.
        """
        _check_kind(job, JobKind.DEPURATION, "RunDepurationJob")
        steps = resolve_steps(self.steps, job.scope)
        get_depuration(self.depurations, job.tenant_id, job.scope, job.resource_id)
        record = self.depurations.claim(job.tenant_id, job.scope, job.resource_id, self.clock.now())
        if record is None:
            return
        try:
            dataset = get_dataset(self.datasets, job.tenant_id, record.dataset_id)
            chain = dataset_chain(self.datasets, dataset)
            session = recalibration_session(self.recalibration, job.tenant_id, job.scope, chain)
            result = self._evaluate(steps, record, dataset, session)
            output_id = self._derive(record, dataset, result)
            next_step = (
                None if result.exhausted else NextStep.MODEL if result.final else NextStep.FIT
            )
            done = replace(
                record,
                result=result.disposition,
                converged=result.converged,
                final=result.final,
                exhausted=result.exhausted,
                output_dataset_id=output_id,
                next_step=next_step,
            )
            if session is not None and result.exhausted:
                # Menos filas que ``min_observations``: la recalibración termina INSUFFICIENT.
                _require_links(self.recalibration).close_insufficient(session, chain, done)
        except (DomainError, ApplicationError) as exc:
            self._close(record, error=_error_of(exc))
            return
        except Exception:
            self._close(record, error=ErrorInfo(INTERNAL_ERROR, "error interno en la depuración"))
            raise
        self._close(done)

    def _evaluate(
        self,
        steps: Phase1Steps,
        record: DepurationRecord,
        dataset: DatasetRecord,
        session: RecalibrationRecord | None,
    ) -> _DepurationResult:
        """Exclusión humana (sin ajuste) o ronda automática (con su ajuste y sus límites).

        En una recalibración las rondas máximas y el mínimo de filas son los de sus parámetros
        (``min_observations``): si la exclusión humana o una ronda dejan menos, se agota.

        Args:
            steps: Pasos de la carta.
            record: Depuración.
            dataset: Dataset depurado.
            session: Recalibración a la que pertenece, o ``None`` (Fase I).

        Returns:
            El resultado.
        """
        n = dataset.data.shape[0]
        max_rounds, min_rows = (
            (None, 1) if session is None else _require_links(self.recalibration).bounds(session)
        )
        if record.limits_id is None or record.fit_id is None:
            human = human_mask(record.assignable_cause, n)
            disposition = tuple(
                RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE if h else RowDisposition.KEPT
                for h in human.tolist()
            )
            short = session is not None and int((~human).sum()) < min_rows
            return _DepurationResult(disposition, ~human, False, None, short, short)
        fit = ready_fit(self.fits, record.tenant_id, record.chart_id, record.fit_id)
        limits = ready_limits(self.limits, record.tenant_id, record.chart_id, record.limits_id)
        clean = limits.clean_rows if limits.clean_rows is not None else np.zeros(0, np.bool_)
        outcome = steps.depurate(
            dataset.data,
            fit.result,
            Calibration(limits=limits.result, clean=clean),
            limits.params,
            round_index=record.round,
            max_rounds=max_rounds,
            min_rows=min_rows,
        )
        disposition = tuple(
            RowDisposition.EXCLUDED_AUTOMATIC if a else RowDisposition.KEPT
            for a in outcome.excluded_automatic.tolist()
        )
        removed = bool(outcome.excluded_automatic.any())
        return _DepurationResult(
            disposition, outcome.kept, removed, outcome.converged, outcome.final, outcome.exhausted
        )

    def _derive(
        self, record: DepurationRecord, dataset: DatasetRecord, result: _DepurationResult
    ) -> str | None:
        """Crea el dataset derivado ``parent[kept]`` si la depuración quitó filas.

        Args:
            record: Depuración.
            dataset: Dataset depurado (el padre).
            result: Resultado.

        Returns:
            El id del dataset derivado, o ``None`` si no se crea (final o agotada).
        """
        if result.final or result.exhausted:
            return None
        rows = np.flatnonzero(result.kept).astype(np.int64)
        data = frozen_base(np.ascontiguousarray(dataset.data[rows], dtype=np.float64))
        derived = DatasetRecord(
            tenant_id=record.tenant_id,
            dataset_id=self.ids.new_id(),
            data=data,
            content_hash=base_content_hash(data),
            source=DatasetSource.DEPURATION_OUTPUT,
            created_at=self.clock.now(),
            parent_id=dataset.dataset_id,
            rows=rows,
            lineage_round=dataset.lineage_round + (1 if result.automatic_removed else 0),
            origin_ref=record.depuration_id,
        )
        self.datasets.add(derived)
        return derived.dataset_id

    def _close(self, record: DepurationRecord, *, error: ErrorInfo | None = None) -> None:
        """Cierra la depuración y avisa a su tubería.

        Args:
            record: Registro (con el resultado si terminó bien).
            error: Error si falló.
        """
        self.depurations.update(
            replace(
                record,
                status=JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED,
                finished_at=self.clock.now(),
                error=error,
            )
        )
        notify_pipeline(self.queue, record.tenant_id, record.chart_id, record.pipeline_id)


# --- modelo --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestModel:
    """Valida y encola el ensamblado de un modelo a partir de referencias (``/models``).

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        depurations: Repositorio de depuraciones.
        models: Repositorio de modelos.
        queue: Cola.
        ids: Identificadores.
        clock: Reloj.
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    depurations: DepurationRepository
    models: ModelRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        *,
        depuration_id: str | None = None,
        fit_id: str | None = None,
        limits_id: str | None = None,
        lifecycle_policy: LifecyclePolicy | None = None,
        model_id: str | None = None,
        pipeline_id: str | None = None,
    ) -> str:
        """Encola el ensamblado.

        Formas: ``{depuration_id}`` (la depuración final de la cadena) o ``{fit_id, limits_id}``
        (sin más depuración automática: la ronda se toma como final).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            depuration_id: Depuración final.
            fit_id: Ajuste final.
            limits_id: Límites finales del mismo ajuste.
            lifecycle_policy: Política de revalidación (``None``: la de por defecto).
            model_id: Identificador ya reservado (tubería).
            pipeline_id: Tubería que lo pide.

        Returns:
            El ``model_id``.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            InvalidInputError: Si no es exactamente una de las dos formas.
            DepurationNotFoundError: Si la depuración no existe.
            DepurationNotFinalError: Si no está ``succeeded`` o no es final.
            FitNotFoundError: Si el ajuste no existe.
            FitNotReadyError: Si no está ``succeeded``.
            LimitsNotFoundError: Si los límites no existen.
            LimitsNotReadyError: Si no están ``succeeded``.
            LimitsFitMismatchError: Si los límites son de otro ajuste.
        """
        resolve_steps(self.steps, chart_id)
        refs = fit_id is not None or limits_id is not None
        final_depuration: str | None = None
        if depuration_id is not None and not refs:
            depuration = get_depuration(self.depurations, tenant_id, chart_id, depuration_id)
            if (
                depuration.status is not JobStatus.SUCCEEDED
                or not depuration.final
                or depuration.exhausted
                or depuration.fit_id is None
                or depuration.limits_id is None
            ):
                raise DepurationNotFinalError(
                    f"la depuración '{depuration_id}' no es la final de su cadena",
                    details={
                        "depuration_id": depuration_id,
                        "status": str(depuration.status),
                        "final": depuration.final,
                        "exhausted": depuration.exhausted,
                    },
                )
            fit_ref, limits_ref = depuration.fit_id, depuration.limits_id
            final_depuration = depuration_id
        elif depuration_id is None and fit_id is not None and limits_id is not None:
            fit_ref, limits_ref = fit_id, limits_id
        else:
            raise InvalidInputError(
                "un modelo se pide con {depuration_id} o con {fit_id, limits_id}",
                details={"field": "depuration_id", "reason": "one_of_depuration_or_fit_limits"},
            )
        fit = ready_fit(self.fits, tenant_id, chart_id, fit_ref)
        limits = ready_limits(self.limits, tenant_id, chart_id, limits_ref)
        _check_same_fit(limits, fit_ref)
        chain = dataset_chain(self.datasets, get_dataset(self.datasets, tenant_id, fit.dataset_id))
        if chain[0].source in _RECALIBRATION_ROOTS:
            raise RecalibrationMismatchError(
                "un modelo de Fase I no se ensambla con datos de una recalibración",
                details={"fit_id": fit_ref, "reason": "recalibration_dataset"},
            )
        depurations = tuple(d.origin_ref for d in chain[1:] if d.origin_ref is not None)
        if final_depuration is not None:
            depurations += (final_depuration,)
        record = ModelRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            model_id=model_id if model_id is not None else self.ids.new_id(),
            status=JobStatus.QUEUED,
            params=dict(limits.params),
            training_data=chain[0].data,
            created_at=self.clock.now(),
            lifecycle_policy=lifecycle_policy
            if lifecycle_policy is not None
            else LifecyclePolicy(),
            provenance=ModelProvenance(
                root_dataset_id=chain[0].dataset_id,
                fit_id=fit_ref,
                limits_id=limits_ref,
                depuration_ids=depurations,
            ),
            pipeline_id=pipeline_id,
        )
        self.models.add(record)
        self.queue.enqueue(JobRequest(JobKind.MODEL_ASSEMBLY, tenant_id, chart_id, record.model_id))
        return record.model_id


@dataclass(frozen=True)
class RunModelAssemblyJob:
    """Ensambla un modelo encolado y crea su versión 0 (carril ``light``).

    Recorre el linaje del dataset del ajuste hasta la raíz para obtener las máscaras de la base y
    de las exclusiones humana y automática sobre el histórico raíz.

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        depurations: Repositorio de depuraciones.
        models: Repositorio de modelos.
        versions: Repositorio de versiones (recibe la versión 0).
        queue: Cola (aviso a la tubería).
        clock: Reloj.
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    depurations: DepurationRepository
    models: ModelRepository
    versions: ModelVersionRepository
    queue: JobQueue
    clock: Clock

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo; idempotente.

        Args:
            job: Petición ``model_assembly``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``model_assembly``.
            UnknownChartError: Si la carta no expone pasos.
            ModelNotFoundError: Si el modelo no existe.
        """
        _check_kind(job, JobKind.MODEL_ASSEMBLY, "RunModelAssemblyJob")
        steps = resolve_steps(self.steps, job.scope)
        get_model(self.models, job.tenant_id, job.scope, job.resource_id)
        record = self.models.claim(job.tenant_id, job.scope, job.resource_id, self.clock.now())
        if record is None:
            return
        try:
            model = self._assemble(steps, record)
            finished_at = self.clock.now()
            self.versions.add(initial_version(record, model, finished_at))
        except (DomainError, ApplicationError) as exc:
            self._close(record, error=_error_of(exc))
            return
        except Exception:
            self._close(record, error=ErrorInfo(INTERNAL_ERROR, "error interno en el modelo"))
            raise
        self._close(record, model=model, finished_at=finished_at)

    def _assemble(self, steps: Phase1Steps, record: ModelRecord) -> object:
        """Modelo de la carta a partir de las referencias del registro.

        Args:
            steps: Pasos de la carta.
            record: Modelo en ``running`` (con ``provenance``).

        Returns:
            El modelo de la carta.

        Raises:
            InvalidInputError: Si el modelo no tiene procedencia.
        """
        provenance = record.provenance
        if provenance is None:
            raise InvalidInputError(
                "el modelo no tiene procedencia", details={"model_id": record.model_id}
            )
        tenant, chart = record.tenant_id, record.chart_id
        fit = ready_fit(self.fits, tenant, chart, provenance.fit_id)
        limits = ready_limits(self.limits, tenant, chart, provenance.limits_id)
        chain = dataset_chain(self.datasets, get_dataset(self.datasets, tenant, fit.dataset_id))
        indices = root_indices(chain)
        n_root = chain[0].data.shape[0]
        human = np.zeros(n_root, dtype=np.bool_)
        automatic = np.zeros(n_root, dtype=np.bool_)
        for parent_rows, derived in zip(indices[:-1], chain[1:], strict=True):
            if derived.origin_ref is None:
                continue
            depuration = get_depuration(self.depurations, tenant, chart, derived.origin_ref)
            for i, disposition in enumerate(depuration.result or ()):
                if disposition is RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE:
                    human[parent_rows[i]] = True
                elif disposition is RowDisposition.EXCLUDED_AUTOMATIC:
                    automatic[parent_rows[i]] = True
        kept = np.zeros(n_root, dtype=np.bool_)
        kept[indices[-1]] = True
        clean = limits.clean_rows if limits.clean_rows is not None else np.zeros(0, np.bool_)
        calibration = Calibration(limits=limits.result, clean=clean)
        final = provenance.depuration_ids[-1:] if provenance.depuration_ids else ()
        converged = self._converged(steps, final, chain[-1], fit, calibration, limits)
        return steps.assemble_initial_model(
            chain[0].data,
            limits.params,
            fit.result,
            calibration,
            kept=kept,
            excluded=human,
            automatic=automatic,
            rounds=chain[-1].lineage_round,
            converged=converged,
        )

    def _converged(
        self,
        steps: Phase1Steps,
        final: tuple[str, ...],
        dataset: DatasetRecord,
        fit: FitRecord,
        calibration: Calibration,
        limits: LimitsRecord,
    ) -> bool:
        """Convergencia de la ronda final.

        Si la última depuración de la cadena evaluó este ajuste, su ``converged``; si no (modelo
        pedido con ``{fit_id, limits_id}``), se evalúa la ronda sin quitar filas.

        Args:
            steps: Pasos de la carta.
            final: La última depuración de la procedencia (vacía si no hay).
            dataset: Dataset del ajuste final.
            fit: Ajuste final.
            calibration: Calibración final.
            limits: Límites finales.

        Returns:
            ``True`` si ninguna fila de la base supera el límite.
        """
        if final:
            depuration = get_depuration(self.depurations, fit.tenant_id, fit.chart_id, final[0])
            if depuration.fit_id == fit.fit_id and depuration.converged is not None:
                return depuration.converged
        outcome = steps.depurate(
            dataset.data,
            fit.result,
            calibration,
            limits.params,
            round_index=dataset.lineage_round,
            evaluate_only=True,
        )
        return outcome.converged

    def _close(
        self,
        record: ModelRecord,
        *,
        model: object = None,
        error: ErrorInfo | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        """Cierra el modelo y avisa a su tubería.

        Args:
            record: Registro en ``running``.
            model: Modelo si terminó bien.
            error: Error si falló.
            finished_at: Instante de cierre (``None``: ahora).
        """
        self.models.update(
            replace(
                record,
                status=JobStatus.FAILED if error is not None else JobStatus.SUCCEEDED,
                finished_at=finished_at if finished_at is not None else self.clock.now(),
                model=model,
                error=error,
            )
        )
        notify_pipeline(self.queue, record.tenant_id, record.chart_id, record.pipeline_id)
