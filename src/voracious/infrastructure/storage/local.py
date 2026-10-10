"""``LocalDatasetStorage``: datasets en disco como ``.npy`` con su huella (mejora M6).

Cada dataset son dos ficheros bajo ``<base>/<tenant>/``: ``<id>.npy`` (la matriz ``float64``,
sin *pickle*) y ``<id>.json`` (linaje, huella ``content_hash``, nombres de variables y fecha de
cada fila). Al leer se recalcula la huella del contenido y, si no coincide, se rechaza
(``DatasetIntegrityError``): un fichero corrompido o alterado nunca entra en un ajuste. Las
escrituras son atómicas (fichero temporal y ``os.replace``) y los identificadores se validan para
que no puedan salir del directorio base.

``LocalMatrixStore`` es solo la parte de la matriz (``.npy`` con su huella). La usa también
``PostgresDatasetStorage`` (Paso 4.2): con ``VORACIOUS_REPOSITORY=postgres`` los metadatos van a
Postgres y la matriz sigue en disco.
"""

import io
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Final

import numpy as np

from voracious.application.lifecycle import base_content_hash, frozen_base
from voracious.application.ports import DuplicateKeyError
from voracious.application.records import DatasetRecord, DatasetSource
from voracious.domain.common import FloatMatrix, InvalidInputError
from voracious.infrastructure.memory.codec import decode_dataset_meta, encode_dataset_meta

__all__ = ["DatasetIntegrityError", "LocalDatasetStorage", "LocalMatrixStore"]

_SAFE_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,128}")
"""Forma admitida de un tenant o un dataset en una ruta (coincidencia completa)."""

_META_VERSION: Final = 3
"""Versión del formato de los metadatos (se comprueba al leer).

La 2 quitó ``lineage_round`` y el origen ``depuration_output`` (sin depuración automática
iterativa, decisión del dueño 2026-10-09). La 3 (Paso 4.2) guarda los metadatos con el mismo codec
que Postgres (``encode_dataset_meta``), con nombres de variables y fecha de cada fila. La 2 se
sigue leyendo (sin nombres ni fechas).
"""

_LEGACY_META_VERSION: Final = 2


class DatasetIntegrityError(RuntimeError):
    """El contenido guardado de un dataset no coincide con su huella."""


def _safe(value: str) -> bool:
    """Indica si un identificador se puede usar como nombre de fichero.

    Args:
        value: Identificador.

    Returns:
        ``True`` si cumple ``[A-Za-z0-9_-]{1,128}``.
    """
    return _SAFE_ID.fullmatch(value) is not None


def _write_atomic(path: Path, payload: bytes) -> None:
    """Escribe un fichero de forma atómica.

    Args:
        path: Destino.
        payload: Contenido.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


class LocalMatrixStore:
    """Matrices ``float64`` en ``<base>/<tenant>/<id>.npy``, comprobadas contra su huella.

    Attributes:
        base_dir: Directorio base (``VORACIOUS_STORAGE_DIR``).
    """

    def __init__(self, base_dir: Path) -> None:
        """Crea el directorio base si no existe.

        Args:
            base_dir: Directorio base.
        """
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def path(self, tenant_id: str, dataset_id: str, suffix: str = ".npy") -> Path:
        """Ruta de un fichero del dataset.

        Args:
            tenant_id: Tenant.
            dataset_id: Dataset.
            suffix: Extensión.

        Returns:
            La ruta.

        Raises:
            ValueError: Si algún identificador no es seguro.
        """
        if not (_safe(tenant_id) and _safe(dataset_id)):
            msg = "identificador de tenant o de dataset no válido para el almacenamiento"
            raise ValueError(msg)
        return self.base_dir / tenant_id / f"{dataset_id}{suffix}"

    def put(self, tenant_id: str, dataset_id: str, data: FloatMatrix, content_hash: str) -> None:
        """Escribe la matriz de un dataset nuevo.

        Args:
            tenant_id: Tenant.
            dataset_id: Dataset.
            data: Matriz.
            content_hash: Huella (``base_content_hash``) que debe corresponder a ``data``.

        Raises:
            DuplicateKeyError: Si ya existe.
            ValueError: Si un identificador no es seguro o la huella no corresponde a los datos.
        """
        npy = self.path(tenant_id, dataset_id)
        if base_content_hash(data) != content_hash:
            msg = "la huella del dataset no corresponde a sus datos"
            raise ValueError(msg)
        with self.lock:
            if npy.exists():
                raise DuplicateKeyError(f"({tenant_id}, {dataset_id})")
            npy.parent.mkdir(parents=True, exist_ok=True)
            buffer = io.BytesIO()
            np.save(buffer, np.ascontiguousarray(data, dtype="<f8"), allow_pickle=False)
            _write_atomic(npy, buffer.getvalue())

    def get(self, tenant_id: str, dataset_id: str, content_hash: str) -> FloatMatrix | None:
        """Lee la matriz de un dataset y comprueba su huella.

        Args:
            tenant_id: Tenant.
            dataset_id: Dataset.
            content_hash: Huella esperada.

        Returns:
            La matriz (de solo lectura) o ``None`` si no existe o el id no es seguro.

        Raises:
            DatasetIntegrityError: Si no es una matriz ``float64`` o no coincide con la huella.
        """
        try:
            npy = self.path(tenant_id, dataset_id)
        except ValueError:
            return None
        if not npy.exists():
            return None
        data = np.load(npy, allow_pickle=False)
        if data.dtype != np.float64 or data.ndim != 2:
            msg = f"el dataset '{dataset_id}' no es una matriz float64"
            raise DatasetIntegrityError(msg)
        if base_content_hash(data) != content_hash:
            msg = f"el contenido del dataset '{dataset_id}' no coincide con su huella"
            raise DatasetIntegrityError(msg)
        return frozen_base(data)

    def writable(self) -> bool:
        """Indica si el directorio base existe y se puede escribir (``/ready``).

        Returns:
            ``True`` si es un directorio escribible.
        """
        return self.base_dir.is_dir() and os.access(self.base_dir, os.W_OK | os.X_OK)


class LocalDatasetStorage:
    """``DatasetStorage`` en disco local.

    Attributes:
        base_dir: Directorio base (``VORACIOUS_STORAGE_DIR``).
        matrices: Almacén de las matrices.
    """

    def __init__(self, base_dir: Path) -> None:
        """Crea el directorio base si no existe.

        Args:
            base_dir: Directorio base.
        """
        self.base_dir = base_dir
        self.matrices = LocalMatrixStore(base_dir)

    def add(self, record: DatasetRecord) -> None:
        """Guarda un dataset nuevo.

        Args:
            record: Dataset.

        Raises:
            DuplicateKeyError: Si ya existe.
            ValueError: Si un identificador no es seguro o la huella no corresponde a los datos.
        """
        meta = self.matrices.path(record.tenant_id, record.dataset_id, ".json")
        doc = {"format_version": _META_VERSION, **encode_dataset_meta(record)}
        if meta.exists():
            raise DuplicateKeyError(f"({record.tenant_id}, {record.dataset_id})")
        self.matrices.put(record.tenant_id, record.dataset_id, record.data, record.content_hash)
        with self.matrices.lock:
            _write_atomic(meta, json.dumps(doc, sort_keys=True).encode("utf-8"))

    def get(self, tenant_id: str, dataset_id: str) -> DatasetRecord | None:
        """Lee un dataset y comprueba su huella.

        Args:
            tenant_id: Tenant.
            dataset_id: Dataset.

        Returns:
            El dataset (matriz de solo lectura) o ``None`` si no existe para ese tenant.

        Raises:
            DatasetIntegrityError: Si los metadatos son de otro formato o el contenido no coincide
                con la huella guardada.
        """
        try:
            meta = self.matrices.path(tenant_id, dataset_id, ".json")
        except ValueError:
            return None
        if not meta.exists():
            return None
        doc = json.loads(meta.read_text(encoding="utf-8"))
        version = doc.pop("format_version", None)
        if version not in (_META_VERSION, _LEGACY_META_VERSION):
            msg = f"los metadatos del dataset '{dataset_id}' tienen un formato desconocido"
            raise DatasetIntegrityError(msg)
        data = self.matrices.get(tenant_id, dataset_id, str(doc["content_hash"]))
        if data is None:
            return None
        if version == _LEGACY_META_VERSION:
            return _legacy(doc, data)
        try:
            return decode_dataset_meta(doc, data)
        except InvalidInputError as exc:
            msg = f"los metadatos del dataset '{dataset_id}' no son válidos"
            raise DatasetIntegrityError(msg) from exc


def _legacy(doc: dict[str, object], data: FloatMatrix) -> DatasetRecord:
    """Dataset con metadatos de la versión 2 (sin nombres de variables ni fechas).

    Args:
        doc: Metadatos.
        data: Matriz comprobada.

    Returns:
        El dataset.
    """
    rows = doc["rows"]
    parent, origin = doc["parent_id"], doc["origin_ref"]
    return DatasetRecord(
        tenant_id=str(doc["tenant_id"]),
        dataset_id=str(doc["dataset_id"]),
        data=data,
        content_hash=str(doc["content_hash"]),
        source=DatasetSource(str(doc["source"])),
        created_at=datetime.fromisoformat(str(doc["created_at"])),
        parent_id=None if parent is None else str(parent),
        rows=None if not isinstance(rows, list) else np.asarray(rows, dtype=np.int64),
        origin_ref=None if origin is None else str(origin),
    )
