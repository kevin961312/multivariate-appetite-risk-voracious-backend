"""``IdGenerator`` de producción: UUID versión 4."""

import uuid

__all__ = ["UuidIdGenerator"]


class UuidIdGenerator:
    """Identificadores aleatorios ``uuid4`` en texto."""

    def new_id(self) -> str:
        """Devuelve un identificador nuevo.

        Returns:
            Un UUID4 en su forma canónica.
        """
        return str(uuid.uuid4())
