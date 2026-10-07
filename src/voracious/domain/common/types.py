"""Tipos numéricos comunes y conversión de la entrada ``n x p`` a matriz ``float64``."""

import numpy as np
import numpy.typing as npt

from voracious.domain.common.errors import InvalidInputError

FloatMatrix = npt.NDArray[np.float64]
"""Matriz ``float64`` (``n x p``: filas = observaciones, columnas = variables)."""

FloatVector = npt.NDArray[np.float64]
"""Vector ``float64``."""

BoolVector = npt.NDArray[np.bool_]
"""Vector booleano (máscaras por observación)."""

__all__ = ["BoolVector", "FloatMatrix", "FloatVector", "as_matrix"]


def as_matrix(data: npt.ArrayLike, *, name: str = "x") -> FloatMatrix:
    """Convierte la entrada a una matriz ``float64`` de dos dimensiones.

    No valida finitud ni tamaño: cada método decide qué admite (p. ej. T²MRCD rechaza valores no
    finitos). Siempre devuelve una copia propia, para que el llamador no pueda mutar los datos ya
    validados.

    Args:
        data: Datos ``n x p`` (lista de listas o arreglo).
        name: Nombre de la entrada para el mensaje de error.

    Returns:
        Matriz ``float64`` de forma ``(n, p)``.

    Raises:
        InvalidInputError: Si no es numérica o no tiene exactamente dos dimensiones.
    """
    try:
        arr = np.array(data, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError(
            f"'{name}' debe ser una matriz numérica n x p", details={"input": name}
        ) from exc
    if arr.ndim != 2:
        raise InvalidInputError(
            f"'{name}' debe tener dos dimensiones (n x p)",
            details={"input": name, "ndim": int(arr.ndim)},
        )
    return arr
