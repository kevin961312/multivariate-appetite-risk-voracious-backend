"""Agregación de producción de los T² bootstrap en un límite (``docs/metodos/t2mrcd.md``, P4).

Decisión del dueño (2026-10-07, Paso 2b, Q1: pool): en Fase I **y** en Fase II se juntan
(*pool*) los T² de todas las réplicas y el límite es un único cuantil de probabilidad
``1 - alpha`` de ese conjunto. Sustituye al promedio de los cuantiles por réplica, que sesgaba
el nivel: con ``h`` filas por réplica y ``h·alpha < 1`` el cuantil de cada réplica cae en la
interpolación entre los dos T² más altos y su media no tiene probabilidad de excedencia
``alpha``.

Regla de cuantil: ``numpy.quantile(..., method="linear")``, el tipo 7 de Hyndman y Fan y el
default de ``stats::quantile`` de R; **elección técnica reversible** del desarrollo.

Error Monte Carlo (mejora M6): desviación estándar *bootstrap* del cuantil *pooled* al remuestrear
con reemplazo **réplicas completas** (los T² de una réplica están correlacionados porque comparten
ajuste, así que la unidad independiente es la réplica). Estima cuánto cambiaría el límite si se
repitiera la calibración con otra semilla; no es un intervalo del límite poblacional. Con una sola
réplica no hay variabilidad entre réplicas que medir y el error es ``None`` (no disponible).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from voracious.domain.common import FloatVector

__all__ = ["MC_ERROR_RESAMPLES", "QUANTILE_METHOD", "PooledQuantile", "pooled_quantile"]

QUANTILE_METHOD: Final = "linear"
"""Regla de cuantil de numpy: tipo 7 de R (``stats::quantile``); elección técnica reversible."""

MC_ERROR_RESAMPLES: Final = 200
"""Remuestreos de réplicas para el error Monte Carlo (diagnóstico técnico, no afecta al límite)."""


def _pool(t2_by_replicate: Sequence[FloatVector]) -> FloatVector:
    """Concatena los T² de todas las réplicas.

    Args:
        t2_by_replicate: T² de cada réplica.

    Returns:
        Vector con todos los T².
    """
    return np.concatenate([np.asarray(v, dtype=np.float64) for v in t2_by_replicate])


@dataclass(frozen=True)
class PooledQuantile:
    """Cuantil ``1 - alpha`` del conjunto de los T² de todas las réplicas (producción, P4).

    Objeto con nombre estable (``name``) para poder persistir la estrategia por nombre.
    """

    @property
    def name(self) -> str:
        """Nombre estable: ``"pooled_quantile"``."""
        return "pooled_quantile"

    def __call__(self, t2_by_replicate: Sequence[FloatVector], alpha: float) -> float:
        """Calcula el límite.

        Args:
            t2_by_replicate: T² de cada réplica, en orden de réplica (al menos un valor en total).
            alpha: Nivel del límite, proporción en ``(0, 1)``; la probabilidad del cuantil es
                ``1 - alpha``. No es el ``alpha`` de MRCD.

        Returns:
            El límite.
        """
        return float(np.quantile(_pool(t2_by_replicate), 1.0 - alpha, method=QUANTILE_METHOD))

    def mc_error(
        self,
        t2_by_replicate: Sequence[FloatVector],
        alpha: float,
        seed: np.random.SeedSequence,
    ) -> float | None:
        """Error Monte Carlo del límite: desviación estándar bootstrap entre réplicas.

        Se remuestrean con reemplazo ``B`` réplicas completas ``MC_ERROR_RESAMPLES`` veces y se
        toma la desviación estándar (``ddof = 1``) de los cuantiles *pooled* resultantes. Con una
        sola réplica no está disponible (``None``): no hay variabilidad entre réplicas que medir.

        Args:
            t2_by_replicate: T² de cada réplica.
            alpha: Nivel del límite.
            seed: Semilla propia del diagnóstico.

        Returns:
            La desviación estándar bootstrap del límite, o ``None`` si ``B < 2``.
        """
        n_replicates = len(t2_by_replicate)
        if n_replicates < 2:
            return None
        rng = np.random.default_rng(seed)
        values = [np.asarray(v, dtype=np.float64) for v in t2_by_replicate]
        limits = np.empty(MC_ERROR_RESAMPLES, dtype=np.float64)
        for k in range(MC_ERROR_RESAMPLES):
            picks = rng.integers(0, n_replicates, size=n_replicates)
            limits[k] = self([values[i] for i in picks], alpha)
        return float(np.std(limits, ddof=1))


pooled_quantile: Final = PooledQuantile()
"""Agregación de producción de ambas fases (decisión del dueño 2026-10-07, Paso 2b, Q1: pool)."""
