"""Almacén con cerrojo y codec que comparten los repositorios en memoria."""

import threading
from collections.abc import Callable, Hashable, Iterator

from voracious.infrastructure.memory.codec import RecordCodec

__all__ = ["KeyedStore"]


class KeyedStore[K: Hashable, R]:
    """Diccionario ``clave → registro codificado`` protegido por un cerrojo reentrante.

    Las operaciones compuestas (comparar-y-cambiar, «añadir si no hay otro») se hacen dentro de
    ``with store.lock:`` para que sean atómicas entre hilos.

    Attributes:
        lock: Cerrojo reentrante del almacén.
        codec: Codec de los registros.
        rows: Registros codificados en orden de inserción.
    """

    def __init__(self, codec: RecordCodec[R]) -> None:
        """Construye el almacén vacío.

        Args:
            codec: Codec de los registros.
        """
        self.lock = threading.RLock()
        self.codec = codec
        self.rows: dict[K, object] = {}

    def get(self, key: K) -> R | None:
        """Registro de una clave.

        Args:
            key: Clave.

        Returns:
            El registro decodificado, o ``None``.
        """
        with self.lock:
            stored = self.rows.get(key)
            return None if stored is None else self.codec.decode(stored)

    def contains(self, key: K) -> bool:
        """Indica si la clave existe.

        Args:
            key: Clave.

        Returns:
            ``True`` si existe.
        """
        with self.lock:
            return key in self.rows

    def put(self, key: K, record: R) -> None:
        """Guarda (o reemplaza) un registro.

        Args:
            key: Clave.
            record: Registro.
        """
        with self.lock:
            self.rows[key] = self.codec.encode(record)

    def select(self, keep: Callable[[K], bool]) -> list[R]:
        """Registros cuyas claves cumplen ``keep``, en orden de inserción.

        Args:
            keep: Filtro sobre la clave.

        Returns:
            Los registros decodificados.
        """
        with self.lock:
            return [self.codec.decode(v) for k, v in self.rows.items() if keep(k)]

    def items(self) -> Iterator[tuple[K, R]]:
        """Copia de los pares ``(clave, registro)`` en orden de inserción.

        Returns:
            Un iterador sobre la copia.
        """
        with self.lock:
            pairs = [(k, self.codec.decode(v)) for k, v in self.rows.items()]
        return iter(pairs)
