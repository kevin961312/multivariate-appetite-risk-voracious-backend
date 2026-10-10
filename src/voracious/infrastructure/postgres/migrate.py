"""Ejecutor propio de migraciones SQL versionadas (decisión del dueño, 2026-10-09).

Las migraciones son ficheros ``NNNN_nombre.sql`` en ``postgres/migrations/``, en orden. Cada una
se aplica en **su propia transacción** junto con su fila en ``schema_migrations(version,
checksum, applied_at)``: o se aplica entera o no se aplica. Todo el proceso corre bajo un
``pg_advisory_lock`` de sesión, así que dos ejecutores a la vez (dos ``migrate`` al arrancar) se
esperan y la migración se aplica una sola vez. Una migración ya aplicada cuyo fichero ha cambiado
(otro checksum SHA-256) es un error: no se aplica nada y hay que escribir una migración nueva.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Final

import psycopg

__all__ = [
    "MIGRATIONS_LOCK_KEY",
    "Migration",
    "MigrationChecksumError",
    "bundled_migrations",
    "migrate",
]

MIGRATIONS_LOCK_KEY: Final = 0x766F7261_6D696772
"""Clave del ``pg_advisory_lock`` de las migraciones (``"voramigr"`` en ASCII)."""


class MigrationChecksumError(RuntimeError):
    """Una migración ya aplicada no coincide con su fichero (se editó tras aplicarla)."""


@dataclass(frozen=True)
class Migration:
    """Una migración SQL.

    Attributes:
        version: Número de versión (``0001``…), el prefijo del fichero.
        name: Nombre del fichero.
        sql: Contenido exacto del fichero.
    """

    version: str
    name: str
    sql: bytes

    @property
    def checksum(self) -> str:
        """SHA-256 del contenido.

        Returns:
            La huella en hexadecimal.
        """
        return hashlib.sha256(self.sql).hexdigest()


def bundled_migrations() -> list[Migration]:
    """Migraciones del paquete (``voracious/infrastructure/postgres/migrations``), en orden.

    Returns:
        Las migraciones ordenadas por versión.

    Raises:
        ValueError: Si un fichero no se llama ``NNNN_nombre.sql`` o hay versiones repetidas.
    """
    folder = resources.files("voracious.infrastructure.postgres").joinpath("migrations")
    out: list[Migration] = []
    for entry in folder.iterdir():
        if not entry.name.endswith(".sql"):
            continue
        version = entry.name.split("_", 1)[0]
        if not version.isdigit():
            msg = f"migración con nombre no válido: {entry.name}"
            raise ValueError(msg)
        out.append(Migration(version, entry.name, entry.read_bytes()))
    out.sort(key=lambda m: m.version)
    versions = [m.version for m in out]
    if len(set(versions)) != len(versions):
        msg = f"versiones de migración repetidas: {versions}"
        raise ValueError(msg)
    return out


def migrate(conninfo: str, migrations: Sequence[Migration] | None = None) -> list[str]:
    """Aplica las migraciones pendientes.

    Args:
        conninfo: Cadena de conexión (nunca se registra en logs).
        migrations: Migraciones a aplicar, en orden; ``None`` usa las del paquete.

    Returns:
        Las versiones aplicadas ahora (vacía si ya estaba todo aplicado).

    Raises:
        MigrationChecksumError: Si una migración aplicada no coincide con su fichero.
        psycopg.Error: Si falla la conexión o una migración (la transacción de esa migración se
            deshace; las anteriores quedan aplicadas).
    """
    pending = list(migrations) if migrations is not None else bundled_migrations()
    applied_now: list[str] = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATIONS_LOCK_KEY,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version TEXT PRIMARY KEY,"
                " checksum TEXT NOT NULL,"
                " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
            applied = {str(version): str(checksum) for version, checksum in rows}
            changed = [
                m.name for m in pending if m.version in applied and applied[m.version] != m.checksum
            ]
            if changed:
                msg = f"migraciones aplicadas que han cambiado: {changed}; añade una nueva"
                raise MigrationChecksumError(msg)
            for migration in pending:
                if migration.version in applied:
                    continue
                with conn.transaction():
                    conn.execute(migration.sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (migration.version, migration.checksum),
                    )
                applied_now.append(migration.version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATIONS_LOCK_KEY,))
    return applied_now
