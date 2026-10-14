"""Huecos fijos de semillas de T²MRCD (``SeedSequence`` con ``spawn_key``).

Cada uso aleatorio de la carta tiene un hueco fijo bajo la semilla raíz, de modo que cambiar un
parámetro (B) no desplaza las semillas de los demás usos y el resultado no depende del orden de
ejecución ni del número de procesos:

- ``(0, 0)``: calibración de la Fase I (``fit_phase1``) y de la Fase I final de una recalibración
  que amplía la base (EXTEND);
- ``(1, 0)``: calibración de las filas nuevas cuando la recalibración reemplaza la base (REPLACE:
  evento estructural o petición explícita); el modelo es esa calibración, así que sus límites
  conservan ese hueco.

Los huecos ``2`` y ``3`` los usaban las pruebas de cambio de la comparación de bases, eliminada
(decisión del dueño, 2026-10-14); quedan libres y los huecos ``0`` y ``1`` no cambian, así que los
bits de los modelos tampoco.

Dentro de una calibración con clave ``k``: ``k + (0, i)`` es la réplica ``i`` (``i < B``) y
``k + (1, 0)`` y ``k + (1, 1)`` los diagnósticos del error Monte Carlo de los límites de Fase I y
de Fase II.

El segundo componente de los dos primeros huecos (``0``) se conserva para que las semillas, y por
tanto los bits, sean los mismos que antes de quitar la depuración automática iterativa (decisión
del dueño, 2026-10-09), cuando era el número de ronda.

``SeedSequence(seed, spawn_key=k + (i,))`` es exactamente el hijo ``i`` de
``SeedSequence(seed, spawn_key=k).spawn(...)``.
"""

from typing import Final

import numpy as np

__all__ = [
    "SLOT_NEW_ROWS",
    "SLOT_PHASE1",
    "STAGE_INDEX",
    "SpawnKey",
    "child",
]

SpawnKey = tuple[int, ...]
"""Clave de un hijo de ``SeedSequence`` (secuencia de enteros no negativos)."""

SLOT_PHASE1: Final = 0
SLOT_NEW_ROWS: Final = 1

STAGE_INDEX: Final = 0
"""Segundo componente, fijo, de los huecos de calibración (``(SLOT_PHASE1, 0)``, ``(1, 0)``)."""


def child(seed: int, spawn_key: SpawnKey) -> np.random.SeedSequence:
    """Hijo ``spawn_key`` de ``SeedSequence(seed)``.

    Args:
        seed: Semilla raíz.
        spawn_key: Clave del hijo.

    Returns:
        La ``SeedSequence`` del hijo.
    """
    return np.random.SeedSequence(seed, spawn_key=spawn_key)
