"""Huecos fijos de semillas de T²MRCD (``SeedSequence`` con ``spawn_key``).

Cada uso aleatorio de la carta tiene un hueco fijo bajo la semilla raíz, de modo que cambiar un
parámetro (B, número de rondas, remuestreos de una prueba) no desplaza las semillas de los demás
usos y el resultado no depende del orden de ejecución ni del número de procesos:

- ``(0, r)``: calibración de la ronda ``r`` de la Fase I (``fit_phase1``) y, con ``r = 0``, la
  Fase I final de una recalibración que amplía la base (EXTEND);
- ``(1, r)``: calibración de la ronda ``r`` de la depuración de las filas nuevas al recalibrar; si
  la recalibración reemplaza la base (REPLACE), el modelo reutiliza la calibración de la última
  ronda, así que sus límites conservan ese hueco;
- ``(2,)``: prueba de cambio de la dispersión; ``(3,)``: prueba de cambio de la ubicación.

Dentro de una calibración con clave ``k``: ``k + (0, i)`` es la réplica ``i`` (``i < B``) y
``k + (1, 0)`` y ``k + (1, 1)`` los diagnósticos del error Monte Carlo de los límites de Fase I y
de Fase II.

``SeedSequence(seed, spawn_key=k + (i,))`` es exactamente el hijo ``i`` de
``SeedSequence(seed, spawn_key=k).spawn(...)``.
"""

from typing import Final

import numpy as np

__all__ = [
    "SLOT_COVARIANCE_TEST",
    "SLOT_MEAN_TEST",
    "SLOT_NEW_ROWS_DEPURATION",
    "SLOT_PHASE1",
    "SpawnKey",
    "child",
]

SpawnKey = tuple[int, ...]
"""Clave de un hijo de ``SeedSequence`` (secuencia de enteros no negativos)."""

SLOT_PHASE1: Final = 0
SLOT_NEW_ROWS_DEPURATION: Final = 1
SLOT_COVARIANCE_TEST: Final = 2
SLOT_MEAN_TEST: Final = 3


def child(seed: int, spawn_key: SpawnKey) -> np.random.SeedSequence:
    """Hijo ``spawn_key`` de ``SeedSequence(seed)``.

    Args:
        seed: Semilla raíz.
        spawn_key: Clave del hijo.

    Returns:
        La ``SeedSequence`` del hijo.
    """
    return np.random.SeedSequence(seed, spawn_key=spawn_key)
