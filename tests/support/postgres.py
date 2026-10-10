"""Postgres de prueba: bases desechables y limpieza entre tests (solo tests).

La compuerta (``scripts/gate.sh``, etapa ``postgres-up``) exporta ``VORACIOUS_TEST_DATABASE_URL``:
la de CI (``services: postgres``) o la de un contenedor desechable (``compose.test.yaml``). Sin
ella los tests de Postgres **fallan** (no se saltan): la compuerta exige Postgres.

Cada sesión de pytest crea su propia base (``voracious_test_<aleatorio>``), le aplica las
migraciones y la borra al terminar; cada test empieza con las tablas vacías (``TRUNCATE``).
"""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

ENV = "VORACIOUS_TEST_DATABASE_URL"

TABLES = (
    "dataset_rows",
    "datasets",
    "fits",
    "limits",
    "exclusions",
    "pipelines",
    "models",
    "version_base_rows",
    "model_versions",
    "scores",
    "observations",
    "signal_annotations",
    "structural_events",
    "recalibrations",
    "comparisons",
    "tenants",
)
"""Tablas del esquema (``0001_initial.sql``)."""


def admin_url() -> str:
    """URL de la base de prueba de la compuerta; sin ella, el test falla."""
    url = os.environ.get(ENV, "")
    if not url:
        pytest.fail(
            f"falta {ENV}: los tests de Postgres no se saltan. Corre scripts/gate.sh (levanta un "
            "Postgres desechable con Docker) o exporta la URL de un Postgres de prueba."
        )
    return url


@contextmanager
def temporary_database(base_url: str) -> Iterator[str]:
    """Crea una base vacía y la borra al salir; devuelve su URL."""
    name = f"voracious_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield make_conninfo(base_url, dbname=name)
    finally:
        with psycopg.connect(base_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def truncate_all(url: str) -> None:
    """Vacía todas las tablas del esquema."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(sql.Identifier(t) for t in TABLES)
            )
        )
