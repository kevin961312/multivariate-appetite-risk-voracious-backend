"""Errores del dominio con el formato uniforme ``{code, message, details}`` (ADR 0005).

Cada error lleva un ``code`` estable que la capa de aplicación guarda en el registro ``failed`` y
que la API expone tal cual. Los errores son *picklables* para poder viajar desde un proceso de
trabajo (``TaskMapper`` con procesos).
"""

from collections.abc import Mapping, Sequence

__all__ = [
    "DomainError",
    "EstimationError",
    "InvalidInputError",
    "MethodDecisionPendingError",
]


def _rebuild(
    cls: type["DomainError"], code: str, message: str, details: dict[str, object]
) -> "DomainError":
    """Reconstruye un ``DomainError`` al deserializarlo sin pasar por su ``__init__``.

    Args:
        cls: Clase concreta del error.
        code: Código estable.
        message: Mensaje legible.
        details: Detalles serializables.

    Returns:
        El error reconstruido.
    """
    err = cls.__new__(cls)
    DomainError.__init__(err, code, message, details)
    return err


class DomainError(Exception):
    """Error base del dominio.

    Attributes:
        code: Código estable en mayúsculas (p. ej. ``MRCD_FIT_FAILED``).
        message: Mensaje legible para humanos.
        details: Datos adicionales serializables (sin trazas).
    """

    def __init__(
        self, code: str, message: str, details: Mapping[str, object] | None = None
    ) -> None:
        """Construye el error.

        Args:
            code: Código estable.
            message: Mensaje legible.
            details: Datos adicionales; se copian.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details) if details is not None else {}

    def __reduce__(
        self,
    ) -> tuple[object, tuple[type["DomainError"], str, str, dict[str, object]]]:
        """Serialización por ``pickle`` independiente de la firma de cada subclase."""
        return (_rebuild, (type(self), self.code, self.message, self.details))


class InvalidInputError(DomainError):
    """La entrada no cumple el contrato del método (forma, finitud, número de variables)."""

    CODE = "INVALID_INPUT"

    def __init__(self, message: str, details: Mapping[str, object] | None = None) -> None:
        """Construye el error con el código ``INVALID_INPUT``.

        Args:
            message: Mensaje legible.
            details: Datos adicionales.
        """
        super().__init__(self.CODE, message, details)


class EstimationError(DomainError):
    """Un método falló al estimar (sin *fallback*: el análisis termina en ``failed``)."""


class MethodDecisionPendingError(DomainError):
    """El método tiene elementos estadísticos aún no decididos y no puede ejecutarse.

    ``details["pending"]`` lista los campos pendientes, en un orden estable.
    """

    def __init__(self, code: str, message: str, pending: Sequence[str]) -> None:
        """Construye el error con la lista de campos pendientes.

        Args:
            code: Código del método (p. ej. ``T2MRCD_DECISION_PENDING``).
            message: Mensaje legible.
            pending: Nombres de los campos sin decidir.
        """
        super().__init__(code, message, {"pending": list(pending)})
