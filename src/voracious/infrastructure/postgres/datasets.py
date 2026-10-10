"""``PostgresDatasetStorage``: metadatos en Postgres, matriz en el almacén de ficheros (Paso 4.2).

La matriz ``n x p`` sigue en ``LocalMatrixStore`` (``.npy`` con su huella, decisión del dueño);
Postgres guarda los metadatos (``datasets``: linaje, huella, forma, nombres de variables) y la
fecha de cada fila (``dataset_rows``). El alta es una transacción: si la matriz no se puede
escribir, los metadatos no quedan. Al leer, la matriz se comprueba contra la huella guardada.
"""

from psycopg import sql
from psycopg_pool import ConnectionPool

from voracious.application.records import DatasetRecord
from voracious.infrastructure.memory.codec import decode_dataset_meta, encode_dataset_meta
from voracious.infrastructure.postgres.store import Conn, Table, load_payload
from voracious.infrastructure.storage.local import DatasetIntegrityError, LocalMatrixStore

__all__ = ["PostgresDatasetStorage"]


class _MetaCodec:
    """Codec de los metadatos para ``Table`` (solo escribe; la lectura necesita la matriz)."""

    def encode(self, record: DatasetRecord) -> object:
        """Metadatos del dataset.

        Args:
            record: Dataset.

        Returns:
            Diccionario serializable.
        """
        return encode_dataset_meta(record)

    def decode(self, stored: object) -> DatasetRecord:
        """No se usa: un dataset se lee con su matriz (``PostgresDatasetStorage.get``).

        Args:
            stored: Metadatos.

        Raises:
            NotImplementedError: Siempre.
        """
        msg = "los metadatos de un dataset se decodifican con su matriz"
        raise NotImplementedError(msg)


class PostgresDatasetStorage:
    """``DatasetStorage`` con metadatos en Postgres y matriz en disco.

    Attributes:
        matrices: Almacén de las matrices (``VORACIOUS_STORAGE_DIR``).
    """

    def __init__(self, pool: ConnectionPool[Conn], matrices: LocalMatrixStore) -> None:
        """Construye el almacenamiento.

        Args:
            pool: Pool de conexiones.
            matrices: Almacén de las matrices.
        """
        self._pool = pool
        self.matrices = matrices
        self._t: Table[DatasetRecord] = Table(
            pool,
            "datasets",
            ("tenant_id", "dataset_id"),
            _MetaCodec(),
            lambda r: (r.tenant_id, r.dataset_id),
            lambda r: {
                "source": r.source.value,
                "parent_id": r.parent_id,
                "origin_ref": r.origin_ref,
                "content_hash": r.content_hash,
                "n_rows": int(r.data.shape[0]),
                "n_cols": int(r.data.shape[1]),
                "variables": None if r.variables is None else list(r.variables),
                "created_at": r.created_at,
            },
        )

    def add(self, record: DatasetRecord) -> None:
        """Guarda un dataset nuevo (metadatos, fechas por fila y matriz).

        Args:
            record: Dataset.

        Raises:
            DuplicateKeyError: Si ya existe.
            ValueError: Si un identificador no es seguro o la huella no corresponde a los datos.
        """
        with self._pool.connection() as conn:
            self._t.insert(conn, record)
            if record.observed_at is not None:
                with (
                    conn.cursor() as cur,
                    cur.copy(
                        "COPY dataset_rows (tenant_id, dataset_id, row_index, observed_at)"
                        " FROM STDIN"
                    ) as copy,
                ):
                    for i, when in enumerate(record.observed_at):
                        copy.write_row((record.tenant_id, record.dataset_id, i, when))
            self.matrices.put(record.tenant_id, record.dataset_id, record.data, record.content_hash)

    def get(self, tenant_id: str, dataset_id: str) -> DatasetRecord | None:
        """Lee un dataset y comprueba su matriz contra la huella.

        Args:
            tenant_id: Tenant.
            dataset_id: Dataset.

        Returns:
            El dataset (matriz de solo lectura) o ``None`` si no existe para ese tenant.

        Raises:
            DatasetIntegrityError: Si falta la matriz o no coincide con la huella.
        """
        query = sql.SQL(
            "SELECT payload, format_version FROM datasets WHERE tenant_id = %s AND dataset_id = %s"
        )
        with self._pool.connection() as conn:
            row = conn.execute(query, (tenant_id, dataset_id)).fetchone()
        if row is None:
            return None
        meta = load_payload(row[0], row[1], "datasets")
        content_hash = meta.get("content_hash") if isinstance(meta, dict) else None
        data = self.matrices.get(tenant_id, dataset_id, str(content_hash))
        if data is None:
            msg = f"falta la matriz del dataset '{dataset_id}'"
            raise DatasetIntegrityError(msg)
        return decode_dataset_meta(meta, data)
