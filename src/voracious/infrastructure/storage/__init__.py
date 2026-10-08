"""Adaptadores de ``DatasetStorage`` en disco (``VORACIOUS_STORAGE=local``)."""

from voracious.infrastructure.storage.local import DatasetIntegrityError, LocalDatasetStorage

__all__ = ["DatasetIntegrityError", "LocalDatasetStorage"]
