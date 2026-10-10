"""Pool de conexiones Postgres (``psycopg_pool``) y comprobación de disponibilidad.

Cada conexión trabaja en UTC (``TimeZone=UTC``). La cadena de conexión llega como ``SecretStr``
desde la configuración y solo se revela aquí, al abrir el pool: nunca se registra en logs.
"""

from typing import Final

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from voracious.infrastructure.postgres.store import Conn

__all__ = ["READY_TIMEOUT_SECONDS", "create_pool", "database_ready"]

READY_TIMEOUT_SECONDS: Final = 2.0
"""Espera máxima de ``/ready`` por una conexión y por ``SELECT 1`` (no es estadístico)."""


def create_pool(conninfo: str, size: int) -> ConnectionPool[Conn]:
    """Abre el pool de conexiones.

    No espera a la base: si no está disponible, el pool reintenta en segundo plano y ``/ready``
    responde 503 hasta que lo esté.

    Args:
        conninfo: Cadena de conexión.
        size: Máximo de conexiones.

    Returns:
        El pool, abierto.
    """
    return ConnectionPool(
        conninfo,
        kwargs={"options": "-c TimeZone=UTC"},
        min_size=1,
        max_size=size,
        open=True,
        check=ConnectionPool.check_connection,
        name="voracious",
    )


def database_ready(pool: ConnectionPool[Conn], timeout: float = READY_TIMEOUT_SECONDS) -> bool:
    """``SELECT 1`` con un tiempo máximo corto.

    Args:
        pool: Pool.
        timeout: Segundos máximos de espera (conexión y consulta).

    Returns:
        ``True`` si la base respondió.
    """
    try:
        with pool.connection(timeout=timeout) as conn:
            conn.execute("SELECT set_config('statement_timeout', %s, true)", (f"{timeout}s",))
            conn.execute("SELECT 1")
    except (PoolTimeout, psycopg.Error):
        return False
    return True
