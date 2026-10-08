"""Schemas HTTP de los datasets (``/v1/datasets``), comunes a todas las cartas."""

from collections.abc import Collection
from datetime import datetime
from typing import Literal

from voracious.api.schemas.common import Matrix, RequestModel, ResponseModel
from voracious.application.records import DatasetRecord
from voracious.application.use_cases import DatasetLineage

__all__ = [
    "DatasetCreated",
    "DatasetInclude",
    "DatasetResponse",
    "DatasetUploadIn",
    "LineageEntryOut",
]

DatasetInclude = Literal["data", "rows"]
"""Partes grandes opcionales de ``GET /v1/datasets/{id}``."""


class DatasetUploadIn(RequestModel):
    """Subida JSON de un dataset.

    Attributes:
        data: Matriz ``n x p`` finita, por filas.
    """

    data: Matrix


class DatasetCreated(ResponseModel):
    """Respuesta ``201`` de una subida."""

    dataset_id: str
    n: int
    p: int
    content_hash: str

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
            dataset_id=record.dataset_id, n=int(n), p=int(p), content_hash=record.content_hash
        )


class LineageEntryOut(ResponseModel):
    """Un dataset de la ascendencia."""

    dataset_id: str
    source: str
    n: int
    lineage_round: int
    origin_ref: str | None


class DatasetResponse(ResponseModel):
    """Un dataset con su linaje (``data`` y ``rows`` solo con ``include``)."""

    dataset_id: str
    n: int
    p: int
    content_hash: str
    source: str
    created_at: datetime
    parent_id: str | None
    lineage_round: int
    origin_ref: str | None
    lineage: list[LineageEntryOut]
    data: list[list[float]] | None = None
    rows: list[int] | None = None

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
            lineage_round=record.lineage_round,
            origin_ref=record.origin_ref,
            lineage=[
                LineageEntryOut(
                    dataset_id=d.dataset_id,
                    source=d.source.value,
                    n=int(d.data.shape[0]),
                    lineage_round=d.lineage_round,
                    origin_ref=d.origin_ref,
                )
                for d in view.chain
            ],
            data=[[float(v) for v in row] for row in record.data] if "data" in include else None,
            rows=None
            if "rows" not in include or record.rows is None
            else [int(i) for i in record.rows],
        )
