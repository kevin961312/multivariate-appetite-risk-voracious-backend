"""Fixtures comunes: Postgres de prueba (``support.postgres``)."""

from collections.abc import Iterator

import pytest
from psycopg_pool import ConnectionPool

from support.postgres import admin_url, temporary_database, truncate_all
from voracious.infrastructure.postgres import create_pool, migrate


@pytest.fixture(scope="session")
def pg_session_url() -> Iterator[str]:
    """Base de la sesión con las migraciones aplicadas (se borra al terminar)."""
    with temporary_database(admin_url()) as url:
        migrate(url)
        yield url


@pytest.fixture
def pg_url(pg_session_url: str) -> str:
    """URL de la base de la sesión con las tablas vacías."""
    truncate_all(pg_session_url)
    return pg_session_url


@pytest.fixture
def pg_pool(pg_url: str) -> Iterator[ConnectionPool]:
    """Pool sobre la base vacía."""
    pool = create_pool(pg_url, 10)
    try:
        yield pool
    finally:
        pool.close()
