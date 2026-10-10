"""Almacenamiento de datasets en disco (``VORACIOUS_STORAGE=local``)."""

from voracious.infrastructure.storage.local import (
    DatasetIntegrityError,
    LocalDatasetStorage,
    LocalMatrixStore,
)

__all__ = ["DatasetIntegrityError", "LocalDatasetStorage", "LocalMatrixStore"]
