"""Vocabulario común de la recalibración de una carta (Fase II → nueva versión del modelo).

Solo enumeraciones y el contenedor del resultado; cómo decide cada carta (umbral, pruebas de
cambio) vive en su paquete (``domain/charts/<carta>/``). Sin lógica estadística.
"""

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["RecalibrationDecision", "RecalibrationOutcome", "RowDisposition"]


class RecalibrationDecision(StrEnum):
    """Qué hizo la recalibración con la base del modelo vigente."""

    INITIAL = "initial"
    """Versión inicial del modelo (Fase I sobre el histórico; no hay versión anterior)."""

    EXTEND = "extend"
    """Sin cambio detectado: la nueva base es la base vigente más las filas nuevas conservadas."""

    REPLACE = "replace"
    """Cambio detectado (o reemplazo forzado): la nueva base son solo las nuevas conservadas."""

    INSUFFICIENT = "insufficient"
    """Muy pocas filas nuevas conservadas: no se crea modelo; el vigente sigue activo."""


class RowDisposition(StrEnum):
    """Destino de cada fila en una recalibración o en la exclusión humana de Fase I."""

    KEPT = "kept"
    """Conservada en la base."""

    EXCLUDED_ASSIGNABLE_CAUSE = "excluded_assignable_cause"
    """Excluida por una persona: causa asignable confirmada."""

    ALREADY_IN_BASE = "already_in_base"
    """Fila de la base vigente (no se vuelve a pasar como nueva al recalibrar)."""


@dataclass(frozen=True, eq=False)
class RecalibrationOutcome[ModelT, ReportT]:
    """Resultado de una recalibración.

    Attributes:
        decision: Decisión tomada.
        model: Nueva versión del modelo, o ``None`` si ``decision`` es ``INSUFFICIENT``.
        report: Informe de la carta (antes/después, comparación, destino de cada fila).
    """

    decision: RecalibrationDecision
    model: ModelT | None
    report: ReportT
