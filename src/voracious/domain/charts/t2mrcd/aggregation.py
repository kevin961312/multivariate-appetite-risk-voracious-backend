"""Agregación de producción de los T² bootstrap en el límite (``docs/metodos/t2mrcd.md``, P4).

Decisión del dueño (2026-10-07), opción (b): en **cada** réplica se calcula el cuantil de
probabilidad ``1 - alpha_limit`` de sus T² (con ``alpha_limit = 0.005``, la probabilidad es
``0.995``: proporción, no porcentaje) y el límite es el **promedio** de los B cuantiles.
``alpha_limit`` es el nivel del límite y no tiene relación con el ``alpha`` de MRCD (0.75, tamaño
del subconjunto ``h = ceiling(0.75 n)``).

Regla de cuantil: ``numpy.quantile(..., method="linear")``, que es el tipo 7 de Hyndman y Fan y el
default de ``stats::quantile`` de R. Es una **elección técnica reversible** del desarrollo (no la
fijó el dueño ni la cita un artículo); cambiarla solo afecta a esta función.
"""

from collections.abc import Sequence
from typing import Final

import numpy as np

from voracious.domain.common import FloatVector

__all__ = ["QUANTILE_METHOD", "mean_of_replicate_quantiles"]

QUANTILE_METHOD: Final = "linear"
"""Regla de cuantil de numpy: tipo 7 de R (``stats::quantile``); elección técnica reversible."""


def mean_of_replicate_quantiles(t2_by_replicate: Sequence[FloatVector], alpha: float) -> float:
    """Promedio de los cuantiles de probabilidad ``1 - alpha`` de los T² de cada réplica.

    Cada réplica aporta los T² de su muestra remuestreada (``n_clean >= 1`` filas), así que
    ninguna está vacía.

    Args:
        t2_by_replicate: T² de cada réplica, en orden de réplica (al menos una).
        alpha: Nivel del límite (``alpha_limit``, p. ej. 0.005), como proporción en ``(0, 1)``;
            la probabilidad del cuantil es ``1 - alpha``. No es el ``alpha`` de MRCD.

    Returns:
        El límite: media de los B cuantiles por réplica.
    """
    quantiles = [
        float(
            np.quantile(np.asarray(values, dtype=np.float64), 1.0 - alpha, method=QUANTILE_METHOD)
        )
        for values in t2_by_replicate
    ]
    return float(np.mean(quantiles))
