"""Pieza común de los repositorios Postgres: una tabla con clave, columnas indexadas y payload.

Cada registro se guarda como el JSON exacto de su ``RecordCodec`` en ``payload TEXT`` (no JSONB:
JSONB rechaza ``NaN`` e infinitos y pierde ``-0``) con ``format_version``; las demás columnas son
copias del payload para filtrar, ordenar y garantizar invariantes en la base (índices únicos
parciales). Se lee siempre del payload, así que la ida y vuelta es la del codec: exacta en bits.

Los identificadores de tabla y columna son constantes del código, compuestas con
``psycopg.sql.Identifier``; los valores van **siempre** como parámetros ligados.
"""

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, LiteralString

import psycopg
from psycopg import sql
from psycopg.errors import UniqueViolation
from psycopg_pool import ConnectionPool

from voracious.application.ports import DuplicateKeyError, RecordNotFoundError
from voracious.infrastructure.memory.codec import RecordCodec

__all__ = [
    "PAYLOAD_FORMAT_VERSION",
    "PayloadFormatError",
    "Table",
    "dump_payload",
    "ensure_tenant",
    "load_payload",
]

PAYLOAD_FORMAT_VERSION: Final = 1
"""Versión del JSON de ``payload`` (la del codec de cada registro en el Paso 4.2)."""


Conn = psycopg.Connection[tuple[object, ...]]
"""Conexión con filas como tuplas."""


class PayloadFormatError(RuntimeError):
    """Un ``payload`` guardado tiene una ``format_version`` que este código no entiende."""


def dump_payload(stored: object) -> str:
    """JSON del registro codificado, tal cual (``NaN``, ``Infinity`` y ``-0.0`` incluidos).

    Args:
        stored: Registro codificado por su codec (solo datos).

    Returns:
        El texto JSON.
    """
    return json.dumps(stored, allow_nan=True, ensure_ascii=False, separators=(",", ":"))


def load_payload(text: object, version: object, table: str) -> object:
    """Lee un ``payload`` guardado.

    Args:
        text: Texto guardado.
        version: ``format_version`` guardada.
        table: Tabla, para el mensaje.

    Returns:
        Los datos (los decodifica el codec).

    Raises:
        PayloadFormatError: Si la versión no es la que entiende este código.
    """
    if version != PAYLOAD_FORMAT_VERSION:
        msg = f"'{table}': format_version {version!r} desconocida"
        raise PayloadFormatError(msg)
    return json.loads(str(text))


def ensure_tenant(conn: Conn, tenant_id: str) -> None:
    """Registra el tenant si no existe (todas las tablas lo referencian).

    Args:
        conn: Conexión dentro de la transacción del alta.
        tenant_id: Tenant.
    """
    conn.execute(
        "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT (tenant_id) DO NOTHING",
        (tenant_id,),
    )


@dataclass(frozen=True)
class Table[R]:
    """Una tabla de un repositorio.

    Attributes:
        pool: Pool de conexiones.
        name: Nombre de la tabla.
        keys: Columnas de la clave primaria (la primera es ``tenant_id``).
        codec: Codec del registro.
        key_of: Valores de la clave de un registro (en el orden de ``keys``).
        columns: Columnas indexadas de un registro (copias del payload).
    """

    pool: ConnectionPool[Conn]
    name: LiteralString
    keys: tuple[LiteralString, ...]
    codec: RecordCodec[R]
    key_of: Callable[[R], tuple[object, ...]]
    columns: Callable[[R], Mapping[LiteralString, object]]

    # --- piezas de SQL --------------------------------------------------------------------------

    def _ident(self) -> sql.Identifier:
        return sql.Identifier(self.name)

    def where_key(self, keys: Sequence[LiteralString] | None = None) -> sql.Composed:
        """``col1 = %s AND col2 = %s …`` sobre las columnas dadas (por defecto, la clave).

        Args:
            keys: Columnas; ``None`` = la clave primaria.

        Returns:
            El fragmento.
        """
        cols = self.keys if keys is None else keys
        return sql.SQL(" AND ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols)

    def decode(self, row: Sequence[object]) -> R:
        """Registro de una fila ``(payload, format_version)``.

        Args:
            row: Fila.

        Returns:
            El registro.
        """
        return self.codec.decode(load_payload(row[0], row[1], self.name))

    # --- operaciones ----------------------------------------------------------------------------

    def insert(self, conn: Conn, record: R) -> None:
        """Inserta un registro nuevo dentro de una transacción abierta.

        Args:
            conn: Conexión.
            record: Registro.

        Raises:
            DuplicateKeyError: Si la clave ya existe (o se viola un índice único).
        """
        key = self.key_of(record)
        ensure_tenant(conn, str(key[0]))
        cols = dict(self.columns(record))
        names: list[LiteralString] = [*self.keys, *cols, "format_version", "payload"]
        values: list[object] = [
            *key,
            *cols.values(),
            PAYLOAD_FORMAT_VERSION,
            dump_payload(self.codec.encode(record)),
        ]
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            self._ident(),
            sql.SQL(", ").join(sql.Identifier(n) for n in names),
            sql.SQL(", ").join(sql.Placeholder() for _ in names),
        )
        try:
            conn.execute(query, values)
        except UniqueViolation as exc:
            raise DuplicateKeyError(f"{self.name}: {key}") from exc

    def add(self, record: R) -> None:
        """Inserta un registro nuevo en su propia transacción.

        Args:
            record: Registro.

        Raises:
            DuplicateKeyError: Si la clave ya existe.
        """
        with self.pool.connection() as conn:
            self.insert(conn, record)

    def write(self, conn: Conn, record: R) -> bool:
        """Reescribe payload y columnas de un registro existente dentro de una transacción.

        Args:
            conn: Conexión.
            record: Registro nuevo.

        Returns:
            ``True`` si existía.
        """
        cols = dict(self.columns(record))
        names: list[LiteralString] = [*cols, "payload"]
        values: list[object] = [*cols.values(), dump_payload(self.codec.encode(record))]
        query = sql.SQL("UPDATE {} SET {} WHERE {} RETURNING 1").format(
            self._ident(),
            sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(n)) for n in names),
            self.where_key(),
        )
        return conn.execute(query, [*values, *self.key_of(record)]).fetchone() is not None

    def update(self, record: R) -> None:
        """Reemplaza un registro existente.

        Args:
            record: Registro nuevo.

        Raises:
            RecordNotFoundError: Si no existe.
        """
        with self.pool.connection() as conn:
            if not self.write(conn, record):
                raise RecordNotFoundError(f"{self.name}: {self.key_of(record)}")

    def get(self, key: Sequence[object]) -> R | None:
        """Registro de una clave.

        Args:
            key: Valores de la clave (empieza por el tenant: nunca se lee sin él).

        Returns:
            El registro o ``None``.
        """
        rows = self.select(self.where_key(), key)
        return rows[0] if rows else None

    def select(
        self,
        where: sql.Composable,
        params: Iterable[object],
        order: sql.Composable | None = None,
        conn: Conn | None = None,
    ) -> list[R]:
        """Registros que cumplen ``where``, ordenados por ``order`` (por defecto, ``seq``).

        Args:
            where: Condición (fragmento con marcadores ``%s``).
            params: Valores ligados de la condición.
            order: Orden; ``None`` = orden de inserción.
            conn: Conexión de una transacción abierta, o ``None`` para una propia.

        Returns:
            Los registros.
        """
        query = sql.SQL("SELECT payload, format_version FROM {} WHERE {} ORDER BY {}").format(
            self._ident(), where, order if order is not None else sql.SQL("seq")
        )
        if conn is not None:
            return [self.decode(row) for row in conn.execute(query, list(params)).fetchall()]
        with self.pool.connection() as own:
            return [self.decode(row) for row in own.execute(query, list(params)).fetchall()]

    def transition(
        self,
        key: Sequence[object],
        condition: sql.Composable,
        condition_params: Iterable[object],
        change: Callable[[R], R],
    ) -> R | None:
        """Comparar-y-cambiar atómico: si la fila cumple ``condition``, la cambia con ``change``.

        ``SELECT … FOR UPDATE`` bloquea la fila hasta el final de la transacción: de dos llamadas
        concurrentes, la segunda espera y vuelve a evaluar la condición sobre la fila ya cambiada
        (``READ COMMITTED``), así que solo una la cumple.

        Args:
            key: Clave.
            condition: Condición extra sobre las columnas (fragmento con ``%s``).
            condition_params: Sus valores.
            change: Registro nuevo a partir del actual.

        Returns:
            El registro cambiado, o ``None`` si no existía o no cumplía la condición.
        """
        query = sql.SQL(
            "SELECT payload, format_version FROM {} WHERE {} AND ({}) FOR UPDATE"
        ).format(self._ident(), self.where_key(), condition)
        with self.pool.connection() as conn:
            row = conn.execute(query, [*key, *condition_params]).fetchone()
            if row is None:
                return None
            updated = change(self.decode(row))
            self.write(conn, updated)
            return updated

    def claim(self, key: Sequence[object], start: Callable[[R], R]) -> R | None:
        """Pasa un trabajo de ``queued`` a ``running`` de forma atómica.

        ``UPDATE … SET status = 'running' WHERE <clave> AND status = 'queued' RETURNING``: de dos
        llamadas concurrentes solo una encuentra la fila ``queued``; la otra espera al bloqueo
        de la fila, vuelve a evaluar la condición y no actualiza nada. En la misma transacción
        se reescribe el payload con el registro en ``running``.

        Args:
            key: Clave.
            start: Registro en ``running`` a partir del ``queued``.

        Returns:
            El registro en ``running``, o ``None`` si no existía o no estaba ``queued``.
        """
        query = sql.SQL(
            "UPDATE {} SET status = 'running' WHERE {} AND status = 'queued'"
            " RETURNING payload, format_version"
        ).format(self._ident(), self.where_key())
        with self.pool.connection() as conn:
            row = conn.execute(query, list(key)).fetchone()
            if row is None:
                return None
            running = start(self.decode(row))
            self.write(conn, running)
            return running

    def unfinished(self) -> list[R]:
        """Registros ``queued`` o ``running`` de todos los tenants (recuperación al arrancar).

        Returns:
            Los registros, en orden de inserción.
        """
        return self.select(sql.SQL("status IN ('queued', 'running')"), ())
