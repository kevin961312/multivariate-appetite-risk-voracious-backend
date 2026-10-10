"""Adaptadores Postgres (``VORACIOUS_REPOSITORY=postgres``, Paso 4.2).

Único lugar del proyecto que importa ``psycopg`` y ``psycopg_pool`` (lo vigila import-linter).
Esquema en ``migrations/`` (SQL versionado, ``migrate.py``); repositorios en
``repositories.py``; datasets (metadatos aquí, matriz en disco) en ``datasets.py``.
"""

from voracious.infrastructure.postgres.datasets import PostgresDatasetStorage
from voracious.infrastructure.postgres.migrate import (
    Migration,
    MigrationChecksumError,
    bundled_migrations,
    migrate,
)
from voracious.infrastructure.postgres.pool import create_pool, database_ready
from voracious.infrastructure.postgres.repositories import (
    PostgresComparisonRepository,
    PostgresExclusionRepository,
    PostgresFitRepository,
    PostgresLimitsRepository,
    PostgresModelRepository,
    PostgresModelVersionRepository,
    PostgresMonitoringRepository,
    PostgresObservationRepository,
    PostgresPipelineRepository,
    PostgresRecalibrationRepository,
    PostgresSignalAnnotationRepository,
    PostgresStructuralEventRepository,
)
from voracious.infrastructure.postgres.store import PayloadFormatError, dump_payload, load_payload

__all__ = [
    "Migration",
    "MigrationChecksumError",
    "PayloadFormatError",
    "PostgresComparisonRepository",
    "PostgresDatasetStorage",
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
    "bundled_migrations",
    "create_pool",
    "database_ready",
    "dump_payload",
    "load_payload",
    "migrate",
]
