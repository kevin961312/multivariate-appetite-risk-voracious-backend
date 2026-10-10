"""Pasos encadenables de la Fase I (vuelta 3.3 del Paso 3): cada uno su recurso y su trabajo.

``UploadDataset`` (síncrono) → (opcional) ``RequestExclusion``/``RunExclusionJob`` (carril
``light``) → ``RequestFit``/``RunFitJob`` (``estimation``) → ``RequestLimits``/``RunLimitsJob``
(``calibration``) → ``RequestModel``/``RunModelAssemblyJob`` (``light``). El paso siguiente
**referencia** al anterior por su id: no se reenvían datos ni se recalcula nada.

Sin depuración automática iterativa (decisión del dueño, 2026-10-09): la única exclusión de filas
es la humana, ``{dataset_id, assignable_cause}``, que referencia el dataset raíz, sin ajuste ni
límites, y crea el dataset derivado ``parent[kept]`` (mismo orden, ``float64`` contiguo). Como en
``fit_phase1``, las filas con causa asignable se quitan antes de ajustar nada.

Operación y semilla: la operación de una calibración no la elige el cliente. Se deduce del origen
del dataset raíz (``upload`` → ``PHASE1``, ``recalibration_candidates`` → ``NEW_ROWS``,
``recalibration_extension`` → ``EXTENSION``); la carta la traduce a su hueco de semilla
(``stage_spawn_key``). Con los mismos parámetros, encadenar los pasos da el mismo modelo, en bits,
que ``fit_phase1`` (``tests/integration/test_phase1_chain.py``).

Cada ``Run…Job`` es idempotente (``claim``) y, si el recurso lo pidió una tubería, la avisa al
terminar (bien o mal) encolando su trabajo ``pipeline``.

Recalibración por pasos (vuelta 3.4): los mismos pasos sirven para las filas nuevas. Si la raíz del
dataset es ``recalibration_candidates``, los límites heredan los parámetros de la versión base
(``recalibration_id``, operación ``NEW_ROWS``) y la exclusión humana sale de las anotaciones (no
del cliente); si deja menos de ``min_observations`` filas, la recalibración termina
``insufficient``. Sobre ``recalibration_extension`` (operación ``EXTENSION``) solo hay ajuste y
límites. Lo propio de la recalibración llega por ``RecalibrationLinks``.
"""

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

import numpy as np
import numpy.typing as npt

from voracious.application.errors import (
    ApplicationError,
    DatasetNotFoundError,
    ExclusionNotFoundError,
    FitNotFoundError,
    FitNotReadyError,
    LimitsFitMismatchError,
    LimitsNotFoundError,
    LimitsNotReadyError,
    RecalibrationMismatchError,
)
from voracious.application.lifecycle import base_content_hash, frozen_base, utc
from voracious.application.phase1_steps import (
    Calibration,
    Phase1Steps,
    Phase1StepsRegistry,
    resolve_steps,
)
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
)
from voracious.application.records import (
    AssignableCause,
    DatasetRecord,
    DatasetSource,
    ErrorInfo,
    ExclusionRecord,
    FitRecord,
    IndexVector,
    JobStatus,
    LifecyclePolicy,
    LimitsRecord,
    ModelProvenance,
    ModelRecord,
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
    TaskMapper,
    as_matrix,
)

__all__ = [
    "DEFAULT_DATE_COLUMN",
    "CsvTable",
    "DatasetLineage",
    "GetDataset",
    "GetExclusion",
    "GetFit",
    "GetLimits",
    "RecalibrationLinks",
    "RequestExclusion",
    "RequestFit",
    "RequestLimits",
    "RequestModel",
    "RunExclusionJob",
    "RunFitJob",
    "RunLimitsJob",
    "RunModelAssemblyJob",
    "UploadDataset",
    "check_same_fit",
    "dataset_chain",
    "get_dataset",
    "get_exclusion",
    "get_fit",
    "get_limits",
    "human_mask",
    "notify_pipeline",
    "parse_csv",
    "parse_csv_table",
    "ready_fit",
    "ready_limits",
    "recalibration_session",
    "root_indices",
    "stage_kind",
    "validated_variables",
]

MAX_REPORTED_CELLS = 20
"""Máximo de celdas inválidas que se informan en ``details`` (no es un parámetro estadístico)."""

_ROOT_KINDS: dict[DatasetSource, StageKind] = {
    DatasetSource.UPLOAD: StageKind.PHASE1,
    DatasetSource.RECALIBRATION_CANDIDATES: StageKind.NEW_ROWS,
    DatasetSource.RECALIBRATION_EXTENSION: StageKind.EXTENSION,
}
"""Operación de la calibración según el origen del dataset raíz."""

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

    def min_observations(self, session: RecalibrationRecord) -> int:
        """Mínimo de filas nuevas conservadas tras la exclusión humana.

        Args:
            session: Recalibración.

        Returns:
            El mínimo.
        """
        ...

    def close_insufficient(self, session: RecalibrationRecord, exclusion: ExclusionRecord) -> None:
        """Cierra la recalibración ``insufficient``: la exclusión humana dejó menos filas.

        Args:
            session: Recalibración.
            exclusion: Exclusión de las candidatas (con su resultado).
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


def get_exclusion(
    exclusions: ExclusionRepository, tenant_id: str, chart_id: str, exclusion_id: str
) -> ExclusionRecord:
    """Busca una exclusión o lanza ``ExclusionNotFoundError``.

    Args:
        exclusions: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        exclusion_id: Exclusión.

    Returns:
        La exclusión.

    Raises:
        ExclusionNotFoundError: Si no existe para esa clave.
    """
    record = exclusions.get(tenant_id, chart_id, exclusion_id)
    if record is None:
        raise ExclusionNotFoundError(
            f"la exclusión '{exclusion_id}' no existe", details={"exclusion_id": exclusion_id}
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


def stage_kind(chain: Sequence[DatasetRecord]) -> StageKind:
    """Operación de la calibración sobre el último dataset de ``chain``.

    Args:
        chain: Ascendencia desde la raíz (``dataset_chain``).

    Returns:
        La operación, por el origen de la raíz.

    Raises:
        InvalidInputError: Si la raíz no es un dataset raíz.
    """
    kind = _ROOT_KINDS.get(chain[0].source)
    if kind is None:
        raise InvalidInputError(
            "el dataset raíz no tiene un origen de raíz",
            details={"dataset_id": chain[0].dataset_id, "source": str(chain[0].source)},
        )
    return kind


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


def check_same_fit(limits: LimitsRecord, fit_id: str) -> None:
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


DEFAULT_DATE_COLUMN = "observed_at"
"""Columna de fecha por defecto de un CSV con cabecera (``?date_column=`` la cambia)."""


@dataclass(frozen=True)
class CsvTable:
    """Contenido de un CSV subido.

    Attributes:
        rows: Filas numéricas (sin la columna de fecha).
        variables: Nombres de las columnas numéricas si había cabecera; si no, ``None``.
        observed_at: Fecha de cada fila si la cabecera tenía la columna de fecha; si no, ``None``.
    """

    rows: list[list[float]]
    variables: tuple[str, ...] | None
    observed_at: tuple[datetime, ...] | None


def parse_csv(text: str) -> list[list[float]]:
    """Lee una matriz numérica de un CSV (coma como separador; cabecera opcional).

    Equivale a ``parse_csv_table(text).rows`` con la columna de fecha por defecto.

    Args:
        text: Contenido del CSV.

    Returns:
        Las filas como listas de ``float``.
    """
    return parse_csv_table(text).rows


def _csv_date(cell: str) -> datetime | None:
    """Fecha ISO 8601 con zona horaria de una celda, o ``None`` si no lo es.

    Args:
        cell: Celda.

    Returns:
        La fecha, o ``None``.
    """
    try:
        when = datetime.fromisoformat(cell.strip())
    except ValueError:
        return None
    return when if when.utcoffset() is not None else None


def parse_csv_table(text: str, date_column: str = DEFAULT_DATE_COLUMN) -> CsvTable:
    """Lee un CSV (coma como separador): cabecera opcional y columna de fecha opcional.

    Si alguna celda de la primera fila no es un número, la fila es la **cabecera**: sus celdas
    son los nombres de las variables. Si una de ellas es ``date_column``, esa columna es la fecha
    de cada fila (ISO 8601 con zona horaria) y no es una variable. Las líneas vacías se ignoran.

    Args:
        text: Contenido del CSV.
        date_column: Nombre de la columna de fecha en la cabecera.

    Returns:
        Las filas, los nombres (o ``None``) y las fechas (o ``None``).

    Raises:
        InvalidInputError: Si una celda no es numérica (fuera de la cabecera), una fecha no es
            válida o no hay filas.
    """
    rows = [row for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row)]
    header: list[str] | None = None
    if rows and not all(_is_number(c) for c in rows[0]):
        header = [c.strip() for c in rows[0]]
        rows = rows[1:]
    date_at = header.index(date_column) if header is not None and date_column in header else None
    bad: list[dict[str, object]] = []
    out: list[list[float]] = []
    dates: list[datetime] = []
    for i, row in enumerate(rows):
        values: list[float] = []
        for j, cell in enumerate(row):
            if j == date_at:
                when = _csv_date(cell)
                if when is None:
                    bad.append({"row": i, "column": j, "reason": "invalid_date"})
                else:
                    dates.append(when)
            elif _is_number(cell):
                values.append(float(cell))
            else:
                bad.append({"row": i, "column": j})
        out.append(values)
    if bad:
        raise InvalidInputError(
            "el CSV tiene celdas no válidas",
            details={"input": "csv", "cells": bad[:MAX_REPORTED_CELLS], "n_bad": len(bad)},
        )
    if not out:
        raise InvalidInputError("el CSV no tiene filas", details={"input": "csv"})
    variables = None if header is None else tuple(n for j, n in enumerate(header) if j != date_at)
    if date_at is not None and len(dates) != len(out):
        raise InvalidInputError(
            "falta la fecha de alguna fila",
            details={"input": "csv", "column": date_column, "rows": len(out), "dates": len(dates)},
        )
    return CsvTable(out, variables, None if date_at is None else tuple(dates))


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

    def execute(
        self,
        tenant_id: str,
        data: npt.ArrayLike,
        *,
        variables: Sequence[str] | None = None,
        observed_at: Sequence[datetime] | None = None,
    ) -> DatasetRecord:
        """Valida y guarda la matriz con sus nombres de variables y sus fechas (opcionales).

        Args:
            tenant_id: Tenant.
            data: Matriz ``n x p``.
            variables: Nombre de cada columna (``p``, distintos y no vacíos), o ``None``.
            observed_at: Fecha de cada fila con zona horaria (``n``), o ``None``.

        Returns:
            El dataset guardado.

        Raises:
            InvalidInputError: Si no es una matriz numérica no vacía y finita, o los nombres o las
                fechas no cuadran con ella.
        """
        arr = _validated_upload(data)
        n, p = arr.shape
        record = DatasetRecord(
            tenant_id=tenant_id,
            dataset_id=self.ids.new_id(),
            data=arr,
            content_hash=base_content_hash(arr),
            source=DatasetSource.UPLOAD,
            created_at=self.clock.now(),
            variables=None if variables is None else validated_variables(variables, p),
            observed_at=None if observed_at is None else _validated_dates(observed_at, n),
        )
        self.datasets.add(record)
        return record

    def execute_csv(
        self, tenant_id: str, text: str, *, date_column: str = DEFAULT_DATE_COLUMN
    ) -> DatasetRecord:
        """Lee un CSV (``parse_csv_table``) y lo guarda como ``execute``.

        Args:
            tenant_id: Tenant.
            text: Contenido del CSV.
            date_column: Columna de fecha de la cabecera.

        Returns:
            El dataset guardado.

        Raises:
            InvalidInputError: Si el CSV no es una matriz numérica finita o sus fechas no valen.
        """
        table = parse_csv_table(text, date_column)
        return self.execute(
            tenant_id, table.rows, variables=table.variables, observed_at=table.observed_at
        )


def validated_variables(variables: Sequence[str], p: int) -> tuple[str, ...]:
    """Nombres de variables válidos para ``p`` columnas: ``p`` textos distintos y no vacíos.

    Args:
        variables: Nombres.
        p: Número de columnas.

    Returns:
        Los nombres (sin espacios alrededor).

    Raises:
        InvalidInputError: Si no hay uno por columna, alguno está vacío o se repite.
    """
    names = tuple(str(v).strip() for v in variables)
    if len(names) != p:
        raise InvalidInputError(
            "'variables' debe tener un nombre por columna",
            details={"input": "variables", "columns": p, "names": len(names)},
        )
    if any(not name for name in names):
        raise InvalidInputError(
            "'variables' no admite nombres vacíos", details={"input": "variables"}
        )
    if len(set(names)) != len(names):
        repeated = sorted({n for n in names if names.count(n) > 1})
        raise InvalidInputError(
            "'variables' tiene nombres repetidos",
            details={"input": "variables", "repeated": repeated[:MAX_REPORTED_CELLS]},
        )
    return names


def _validated_dates(observed_at: Sequence[datetime], n: int) -> tuple[datetime, ...]:
    """Fechas de las filas: una por fila, con zona horaria, normalizadas a UTC.

    Args:
        observed_at: Fechas.
        n: Número de filas.

    Returns:
        Las fechas en UTC.

    Raises:
        InvalidInputError: Si no hay una por fila o alguna no tiene zona horaria.
    """
    dates = tuple(utc(when, "observed_at") for when in observed_at)
    if len(dates) != n:
        raise InvalidInputError(
            "'observed_at' debe tener una fecha por fila",
            details={"input": "observed_at", "rows": n, "dates": len(dates)},
        )
    return dates


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
        queue: Cola.
        ids: Identificadores.
        clock: Reloj.
        recalibration: Enlaces con la recalibración por pasos (``None``: solo Fase I).
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
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

        Exactamente una de las dos: ``params`` (Fase I) o ``recalibration_id`` (filas nuevas o
        base ampliada de esa recalibración: hereda los parámetros de la versión base).

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

        La operación (y con ella el hueco de semilla) se deduce del dataset del ajuste. En un
        dataset de recalibración los parámetros son los heredados de la sesión (``params`` se
        ignora) y, sobre las candidatas, se exige antes la exclusión humana si hay anotaciones
        con causa asignable. En la Fase I, ``params`` es obligatorio. Las decisiones pendientes
        de la carta se comprueban aquí, antes de encolar.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste.
            params: Parámetros de la carta codificados (``None`` en una recalibración).
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
        elif params is None:
            raise InvalidInputError(
                "faltan los parámetros de la carta",
                details={"field": "params", "reason": "params_required"},
            )
        resolved.check_params(params)
        resolved.check_fit_params(fit.params, params)
        kind = stage_kind(chain)
        record = LimitsRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            limits_id=limits_id if limits_id is not None else self.ids.new_id(),
            fit_id=fit_id,
            status=JobStatus.QUEUED,
            params=params,
            seed=resolved.seed(params),
            stage_kind=kind.value,
            spawn_key=resolved.stage_spawn_key(kind),
            created_at=self.clock.now(),
            recalibration_id=recalibration_id,
            pipeline_id=pipeline_id,
        )
        self.limits.add(record)
        self.queue.enqueue(JobRequest(JobKind.LIMITS, tenant_id, chart_id, record.limits_id))
        return record.limits_id


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
                kind=StageKind(record.stage_kind),
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


# --- exclusión humana ----------------------------------------------------------------------------


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
class RequestExclusion:
    """Valida y encola una exclusión humana de un dataset (``/exclusions``).

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento.
        exclusions: Repositorio de exclusiones.
        queue: Cola.
        ids: Identificadores.
        clock: Reloj.
        recalibration: Enlaces con la recalibración por pasos (``None``: solo Fase I).
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    exclusions: ExclusionRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock
    recalibration: RecalibrationLinks | None = None

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        dataset_id: str,
        assignable_cause: Sequence[AssignableCause] = (),
        *,
        exclusion_id: str | None = None,
        pipeline_id: str | None = None,
    ) -> str:
        """Encola la exclusión humana.

        Referencia el dataset, sin ajuste: las filas con causa asignable se quitan antes de
        ajustar nada, como en ``fit_phase1``. En la Fase I, solo sobre el dataset subido (al
        principio) y con las filas del cliente. Sobre las candidatas de una recalibración las
        filas **no** las manda el cliente: se toman de las anotaciones con causa asignable
        confirmada.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            dataset_id: Dataset.
            assignable_cause: Filas del dataset con causa asignable (vacías al recalibrar).
            exclusion_id: Identificador ya reservado (tubería).
            pipeline_id: Tubería que la pide.

        Returns:
            El ``exclusion_id``.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            DatasetNotFoundError: Si el dataset no existe.
            InvalidInputError: Si faltan las filas, una fila es inválida, la exclusión no es al
                principio o deja el dataset vacío (``details.reason``).
            RecalibrationNotInProgressError: Si la recalibración del dataset ya terminó.
        """
        resolve_steps(self.steps, chart_id)
        causes = tuple(assignable_cause)
        dataset = get_dataset(self.datasets, tenant_id, dataset_id)
        chain = dataset_chain(self.datasets, dataset)
        session = recalibration_session(self.recalibration, tenant_id, chart_id, chain)
        if session is not None:
            causes = self._recalibration_causes(session, chain, causes)
            human_mask(causes, dataset.data.shape[0])
        else:
            self._check_phase1(chain, causes)
        record = ExclusionRecord(
            tenant_id=tenant_id,
            chart_id=chart_id,
            exclusion_id=exclusion_id if exclusion_id is not None else self.ids.new_id(),
            dataset_id=dataset.dataset_id,
            status=JobStatus.QUEUED,
            assignable_cause=causes,
            created_at=self.clock.now(),
            pipeline_id=pipeline_id,
        )
        self.exclusions.add(record)
        self.queue.enqueue(JobRequest(JobKind.EXCLUSION, tenant_id, chart_id, record.exclusion_id))
        return record.exclusion_id

    def _check_phase1(
        self, chain: Sequence[DatasetRecord], causes: tuple[AssignableCause, ...]
    ) -> None:
        """Valida una exclusión humana de Fase I: al principio, con filas y sin vaciar el dataset.

        Args:
            chain: Ascendencia del dataset.
            causes: Filas con causa asignable.

        Raises:
            InvalidInputError: Si no hay filas, no es sobre el dataset subido, una fila es
                inválida o quita todas.
        """
        dataset = chain[-1]
        if not causes:
            raise InvalidInputError(
                "una exclusión humana lleva 'assignable_cause'",
                details={"field": "assignable_cause", "reason": "assignable_cause_required"},
            )
        if len(chain) != 1:
            raise InvalidInputError(
                "la exclusión humana solo se admite al principio, sobre el dataset subido",
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
            InvalidInputError: Si el cliente manda filas o la exclusión no es sobre las
                candidatas.
        """
        links = _require_links(self.recalibration)
        reason: str | None = None
        if causes:
            reason = "assignable_cause_from_annotations"
        elif chain[0].source is not DatasetSource.RECALIBRATION_CANDIDATES or len(chain) != 1:
            reason = "human_exclusion_only_on_candidates"
        if reason is not None:
            raise InvalidInputError(
                "exclusión no admitida en esta recalibración",
                details={"recalibration_id": session.recalibration_id, "reason": reason},
            )
        return links.human_causes(session)


@dataclass(frozen=True)
class GetExclusion:
    """Consulta una exclusión.

    Attributes:
        steps: Pasos de Fase I por carta.
        exclusions: Repositorio.
    """

    steps: Phase1StepsRegistry
    exclusions: ExclusionRepository

    def execute(self, tenant_id: str, chart_id: str, exclusion_id: str) -> ExclusionRecord:
        """Devuelve la exclusión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            exclusion_id: Exclusión.

        Returns:
            El registro.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            ExclusionNotFoundError: Si no existe.
        """
        resolve_steps(self.steps, chart_id)
        return get_exclusion(self.exclusions, tenant_id, chart_id, exclusion_id)


@dataclass(frozen=True)
class RunExclusionJob:
    """Ejecuta una exclusión encolada (carril ``light``; no ajusta nada).

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento (recibe el dataset derivado).
        exclusions: Repositorio de exclusiones.
        queue: Cola (aviso a la tubería).
        ids: Identificadores (dataset derivado).
        clock: Reloj.
        recalibration: Enlaces con la recalibración por pasos (``None``: solo Fase I).
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    exclusions: ExclusionRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock
    recalibration: RecalibrationLinks | None = None

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo; idempotente.

        Crea el dataset derivado ``parent[kept]``. En una recalibración, si quedan menos filas
        que ``min_observations``, no lo crea y cierra la recalibración ``insufficient``.

        Args:
            job: Petición ``exclusion``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``exclusion``.
            UnknownChartError: Si la carta no expone pasos.
            ExclusionNotFoundError: Si la exclusión no existe.
        """
        _check_kind(job, JobKind.EXCLUSION, "RunExclusionJob")
        resolve_steps(self.steps, job.scope)
        get_exclusion(self.exclusions, job.tenant_id, job.scope, job.resource_id)
        record = self.exclusions.claim(job.tenant_id, job.scope, job.resource_id, self.clock.now())
        if record is None:
            return
        try:
            dataset = get_dataset(self.datasets, job.tenant_id, record.dataset_id)
            chain = dataset_chain(self.datasets, dataset)
            session = recalibration_session(self.recalibration, job.tenant_id, job.scope, chain)
            human = human_mask(record.assignable_cause, dataset.data.shape[0])
            disposition = tuple(
                RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE if h else RowDisposition.KEPT
                for h in human.tolist()
            )
            insufficient = session is not None and int((~human).sum()) < _require_links(
                self.recalibration
            ).min_observations(session)
            output_id = None if insufficient else self._derive(record, dataset, ~human)
            done = replace(
                record,
                result=disposition,
                insufficient=insufficient,
                output_dataset_id=output_id,
            )
            if session is not None and insufficient:
                _require_links(self.recalibration).close_insufficient(session, done)
        except (DomainError, ApplicationError) as exc:
            self._close(record, error=_error_of(exc))
            return
        except Exception:
            self._close(record, error=ErrorInfo(INTERNAL_ERROR, "error interno en la exclusión"))
            raise
        self._close(done)

    def _derive(self, record: ExclusionRecord, dataset: DatasetRecord, kept: BoolVector) -> str:
        """Crea el dataset derivado ``parent[kept]``.

        Args:
            record: Exclusión.
            dataset: Dataset de entrada (el padre).
            kept: Filas conservadas.

        Returns:
            El id del dataset derivado.
        """
        rows = np.flatnonzero(kept).astype(np.int64)
        data = frozen_base(np.ascontiguousarray(dataset.data[rows], dtype=np.float64))
        derived = DatasetRecord(
            tenant_id=record.tenant_id,
            dataset_id=self.ids.new_id(),
            data=data,
            content_hash=base_content_hash(data),
            source=DatasetSource.EXCLUSION_OUTPUT,
            created_at=self.clock.now(),
            parent_id=dataset.dataset_id,
            rows=rows,
            origin_ref=record.exclusion_id,
            variables=dataset.variables,
            observed_at=None
            if dataset.observed_at is None
            else tuple(dataset.observed_at[i] for i in rows),
        )
        self.datasets.add(derived)
        return derived.dataset_id

    def _close(self, record: ExclusionRecord, *, error: ErrorInfo | None = None) -> None:
        """Cierra la exclusión y avisa a su tubería.

        Args:
            record: Registro (con el resultado si terminó bien).
            error: Error si falló.
        """
        self.exclusions.update(
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
        models: Repositorio de modelos.
        queue: Cola.
        ids: Identificadores.
        clock: Reloj.
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
    models: ModelRepository
    queue: JobQueue
    ids: IdGenerator
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        *,
        fit_id: str,
        limits_id: str,
        lifecycle_policy: LifecyclePolicy | None = None,
        model_id: str | None = None,
        pipeline_id: str | None = None,
    ) -> str:
        """Encola el ensamblado con ``{fit_id, limits_id}`` (el ajuste y sus límites).

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            fit_id: Ajuste (del dataset subido o de su exclusión humana).
            limits_id: Límites del mismo ajuste.
            lifecycle_policy: Política de revalidación (``None``: la de por defecto).
            model_id: Identificador ya reservado (tubería).
            pipeline_id: Tubería que lo pide.

        Returns:
            El ``model_id``.

        Raises:
            UnknownChartError: Si la carta no expone pasos.
            FitNotFoundError: Si el ajuste no existe.
            FitNotReadyError: Si no está ``succeeded``.
            LimitsNotFoundError: Si los límites no existen.
            LimitsNotReadyError: Si no están ``succeeded``.
            LimitsFitMismatchError: Si los límites son de otro ajuste.
            RecalibrationMismatchError: Si el ajuste es de una recalibración.
        """
        resolve_steps(self.steps, chart_id)
        fit = ready_fit(self.fits, tenant_id, chart_id, fit_id)
        limits = ready_limits(self.limits, tenant_id, chart_id, limits_id)
        check_same_fit(limits, fit_id)
        chain = dataset_chain(self.datasets, get_dataset(self.datasets, tenant_id, fit.dataset_id))
        if chain[0].source in _RECALIBRATION_ROOTS:
            raise RecalibrationMismatchError(
                "un modelo de Fase I no se ensambla con datos de una recalibración",
                details={"fit_id": fit_id, "reason": "recalibration_dataset"},
            )
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
                fit_id=fit_id,
                limits_id=limits_id,
                exclusion_id=chain[-1].origin_ref if len(chain) > 1 else None,
            ),
            pipeline_id=pipeline_id,
            variables=chain[0].variables,
            observed_at=chain[0].observed_at,
        )
        self.models.add(record)
        self.queue.enqueue(JobRequest(JobKind.MODEL_ASSEMBLY, tenant_id, chart_id, record.model_id))
        return record.model_id


@dataclass(frozen=True)
class RunModelAssemblyJob:
    """Ensambla un modelo encolado y crea su versión 0 (carril ``light``).

    Recorre el linaje del dataset del ajuste hasta la raíz: las filas de la raíz que no llegan al
    dataset del ajuste son las de la exclusión humana.

    Attributes:
        steps: Pasos de Fase I por carta.
        datasets: Almacenamiento.
        fits: Repositorio de ajustes.
        limits: Repositorio de límites.
        models: Repositorio de modelos.
        versions: Repositorio de versiones (recibe la versión 0).
        queue: Cola (aviso a la tubería).
        clock: Reloj.
    """

    steps: Phase1StepsRegistry
    datasets: DatasetStorage
    fits: FitRepository
    limits: LimitsRepository
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
        excluded = np.ones(chain[0].data.shape[0], dtype=np.bool_)
        excluded[root_indices(chain)[-1]] = False
        clean = limits.clean_rows if limits.clean_rows is not None else np.zeros(0, np.bool_)
        return steps.assemble_initial_model(
            chain[0].data,
            limits.params,
            fit.result,
            Calibration(limits=limits.result, clean=clean),
            excluded=excluded,
        )

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
