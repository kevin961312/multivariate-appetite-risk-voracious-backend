"""Operación a la que pertenece una calibración (sin estadística).

Un orquestador que ejecuta por separado el ajuste y la calibración (vuelta 3.2 del Paso 3)
necesita decirle a la carta **qué** calibración hace para que la carta elija su semilla. Este
vocabulario es común; cada carta lo traduce a sus propios huecos de semilla (en T²MRCD,
``domain/charts/t2mrcd/seeds.py``). Sin depuración automática iterativa (decisión del dueño,
2026-10-09) cada operación tiene una sola calibración, así que no hay número de ronda.
"""

from enum import StrEnum

__all__ = ["StageKind"]


class StageKind(StrEnum):
    """Operación a la que pertenece una calibración."""

    PHASE1 = "phase1"
    """Fase I (``fit_phase1``)."""

    NEW_ROWS = "new_rows"
    """Filas nuevas al recalibrar (tras la exclusión humana)."""

    EXTENSION = "extension"
    """Fase I final de una recalibración que amplía la base."""
