"""Schemas HTTP de los datasets (``/v1/datasets``), comunes a todas las cartas."""

from collections.abc import Collection
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from voracious.api.schemas.common import Matrix, RequestModel, ResponseModel, UtcDatetime
from voracious.application.records import DatasetRecord
from voracious.application.use_cases import DatasetLineage

__all__ = [
    "DatasetCreated",
    "DatasetInclude",
    "DatasetResponse",
    "DatasetUploadIn",
    "LineageEntryOut",
]

DatasetInclude = Literal["data", "rows", "observed_at"]
"""Partes grandes opcionales de ``GET /v1/datasets/{id}``."""


VariableName = Annotated[str, Field(min_length=1, max_length=200)]
"""Nombre de una variable."""


class DatasetUploadIn(RequestModel):
    """Subida JSON de un dataset.

    Attributes:
        data: Matriz ``n x p`` finita, por filas.
        variables: Nombre de cada columna (``p``, distintos), opcional.
        observed_at: Fecha de cada fila con zona horaria (``n``), opcional. Solo trazabilidad.
    """

    data: Matrix
    variables: list[VariableName] | None = Field(default=None, min_length=1)
    observed_at: list[UtcDatetime] | None = Field(default=None, min_length=1)


class DatasetCreated(ResponseModel):
    """Respuesta ``201`` de una subida."""

    dataset_id: str
    n: int
    p: int
    content_hash: str
    variables: list[str] | None
    has_observed_at: bool

    @classmethod
    def of(cls, record: DatasetRecord) -> "DatasetCreated":
        """Convierte el dataset guardado.

        Args:
            record: Dataset.

        Returns:
            La respuesta.
        """
        n, p = record.data.shape
        return cls(
            dataset_id=record.dataset_id,
            n=int(n),
            p=int(p),
            content_hash=record.content_hash,
            variables=None if record.variables is None else list(record.variables),
            has_observed_at=record.observed_at is not None,
        )


class LineageEntryOut(ResponseModel):
    """Un dataset de la ascendencia."""

    dataset_id: str
    source: str
    n: int
    origin_ref: str | None


class DatasetResponse(ResponseModel):
    """Un dataset con su linaje (``data``, ``rows`` y ``observed_at`` solo con ``include``)."""

    dataset_id: str
    n: int
    p: int
    content_hash: str
    source: str
    created_at: datetime
    parent_id: str | None
    origin_ref: str | None
    lineage: list[LineageEntryOut]
    variables: list[str] | None
    has_observed_at: bool
    data: list[list[float]] | None = None
    rows: list[int] | None = None
    observed_at: list[datetime] | None = None

    @classmethod
    def of(cls, view: DatasetLineage, include: Collection[str]) -> "DatasetResponse":
        """Convierte el dataset y su ascendencia.

        Args:
            view: Dataset con linaje.
            include: Partes opcionales pedidas.

        Returns:
            La respuesta.
        """
        record = view.dataset
        n, p = record.data.shape
        return cls(
            dataset_id=record.dataset_id,
            n=int(n),
            p=int(p),
            content_hash=record.content_hash,
            source=record.source.value,
            created_at=record.created_at,
            parent_id=record.parent_id,
            origin_ref=record.origin_ref,
            lineage=[
                LineageEntryOut(
                    dataset_id=d.dataset_id,
                    source=d.source.value,
                    n=int(d.data.shape[0]),
                    origin_ref=d.origin_ref,
                )
                for d in view.chain
            ],
            variables=None if record.variables is None else list(record.variables),
            has_observed_at=record.observed_at is not None,
            data=[[float(v) for v in row] for row in record.data] if "data" in include else None,
            rows=None
            if "rows" not in include or record.rows is None
            else [int(i) for i in record.rows],
            observed_at=None
            if "observed_at" not in include or record.observed_at is None
            else list(record.observed_at),
        )
