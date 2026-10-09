"""``LocalDatasetStorage``: datasets en disco como ``.npy`` con su huella (mejora M6).

Cada dataset son dos ficheros bajo ``<base>/<tenant>/``: ``<id>.npy`` (la matriz ``float64``,
sin *pickle*) y ``<id>.json`` (linaje y huella ``content_hash``). Al leer se recalcula la huella
del contenido y, si no coincide, se rechaza (``DatasetIntegrityError``): un fichero corrompido o
alterado nunca entra en un ajuste. Las escrituras son atómicas (fichero temporal y
``os.replace``) y los identificadores se validan para que no puedan salir del directorio base.
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

__all__ = ["DatasetIntegrityError", "LocalDatasetStorage"]

_SAFE_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,128}")
"""Forma admitida de un tenant o un dataset en una ruta (coincidencia completa)."""

_META_VERSION: Final = 2
"""Versión del formato de los metadatos (se comprueba al leer).

La 2 quita ``lineage_round`` y el origen ``depuration_output`` (sin depuración automática
iterativa, decisión del dueño 2026-10-09).
"""


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


class LocalDatasetStorage:
    """``DatasetStorage`` en disco local.

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
        self._lock = threading.Lock()

    def _paths(self, tenant_id: str, dataset_id: str) -> tuple[Path, Path] | None:
        """Rutas de la matriz y de los metadatos.

        Args:
            tenant_id: Tenant.
            dataset_id: Dataset.

        Returns:
            ``(npy, json)``, o ``None`` si algún identificador no es seguro.
        """
        if not (_safe(tenant_id) and _safe(dataset_id)):
            return None
        folder = self.base_dir / tenant_id
        return folder / f"{dataset_id}.npy", folder / f"{dataset_id}.json"

    def add(self, record: DatasetRecord) -> None:
        """Guarda un dataset nuevo.

        Args:
            record: Dataset.

        Raises:
            DuplicateKeyError: Si ya existe.
            ValueError: Si un identificador no es seguro o la huella no corresponde a los datos.
        """
        paths = self._paths(record.tenant_id, record.dataset_id)
        if paths is None:
            msg = "identificador de tenant o de dataset no válido para el almacenamiento"
            raise ValueError(msg)
        if base_content_hash(record.data) != record.content_hash:
            msg = "la huella del dataset no corresponde a sus datos"
            raise ValueError(msg)
        npy, meta = paths
        meta_doc = {
            "format_version": _META_VERSION,
            "tenant_id": record.tenant_id,
            "dataset_id": record.dataset_id,
            "content_hash": record.content_hash,
            "source": record.source.value,
            "created_at": record.created_at.isoformat(),
            "parent_id": record.parent_id,
            "rows": None if record.rows is None else [int(i) for i in record.rows],
            "origin_ref": record.origin_ref,
        }
        with self._lock:
            if meta.exists():
                raise DuplicateKeyError(f"({record.tenant_id}, {record.dataset_id})")
            npy.parent.mkdir(parents=True, exist_ok=True)
            buffer = io.BytesIO()
            np.save(buffer, np.ascontiguousarray(record.data, dtype="<f8"), allow_pickle=False)
            _write_atomic(npy, buffer.getvalue())
            _write_atomic(meta, json.dumps(meta_doc, sort_keys=True).encode("utf-8"))

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
        paths = self._paths(tenant_id, dataset_id)
        if paths is None:
            return None
        npy, meta = paths
        if not meta.exists() or not npy.exists():
            return None
        doc = json.loads(meta.read_text(encoding="utf-8"))
        if doc.get("format_version") != _META_VERSION:
            msg = f"los metadatos del dataset '{dataset_id}' tienen un formato desconocido"
            raise DatasetIntegrityError(msg)
        data = np.load(npy, allow_pickle=False)
        if data.dtype != np.float64 or data.ndim != 2:
            msg = f"el dataset '{dataset_id}' no es una matriz float64"
            raise DatasetIntegrityError(msg)
        if base_content_hash(data) != doc["content_hash"]:
            msg = f"el contenido del dataset '{dataset_id}' no coincide con su huella"
            raise DatasetIntegrityError(msg)
        rows = doc["rows"]
        return DatasetRecord(
            tenant_id=str(doc["tenant_id"]),
            dataset_id=str(doc["dataset_id"]),
            data=frozen_base(data),
            content_hash=str(doc["content_hash"]),
            source=DatasetSource(doc["source"]),
            created_at=datetime.fromisoformat(doc["created_at"]),
            parent_id=doc["parent_id"],
            rows=None if rows is None else np.asarray(rows, dtype=np.int64),
            origin_ref=doc["origin_ref"],
        )
