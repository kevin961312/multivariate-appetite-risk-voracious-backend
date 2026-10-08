"""Linaje de una ronda de ajuste y calibración: de qué operación forma parte (sin estadística).

Un orquestador que ejecuta por separado el ajuste y la calibración de una ronda (vuelta 3.2 del
Paso 3) necesita decirle a la carta **qué** ronda calibra para que la carta elija su semilla. Este
vocabulario es común; cada carta lo traduce a sus propios huecos de semilla (en T²MRCD,
``domain/charts/t2mrcd/seeds.py``).
"""

from dataclasses import dataclass
from enum import StrEnum

from voracious.domain.common.errors import InvalidInputError

__all__ = ["StageKind", "StageLineage"]


class StageKind(StrEnum):
    """Operación a la que pertenece una ronda."""

    PHASE1 = "phase1"
    """Ronda ``round`` de la depuración de la Fase I (``fit_phase1``)."""

    NEW_ROWS = "new_rows"
    """Ronda ``round`` de la depuración de las filas nuevas al recalibrar."""

    EXTENSION = "extension"
    """Fase I final de una recalibración que amplía la base (una sola ronda, ``round = 0``)."""


@dataclass(frozen=True)
class StageLineage:
    """Identifica una ronda: su operación y su número.

    Attributes:
        kind: Operación.
        round: Número de ronda, entero ``>= 0`` (``0`` en ``EXTENSION``).
    """

    kind: StageKind
    round: int = 0

    def __post_init__(self) -> None:
        """Normaliza ``kind`` a ``StageKind`` y valida el número de ronda.

        El linaje puede llegar de un registro o de JSON como texto (``"phase1"``); se convierte
        al miembro de la enumeración para que la carta nunca reciba un valor desconocido.

        Raises:
            InvalidInputError: Si ``kind`` no es una operación conocida, ``round`` no es un
                entero ``>= 0`` (``bool`` se rechaza) o si ``kind`` es ``EXTENSION`` y ``round``
                no es ``0``.
        """
        try:
            kind = StageKind(self.kind)
        except ValueError as exc:
            raise InvalidInputError(
                f"'kind' no es una operación conocida: {self.kind!r}",
                details={"field": "lineage.kind"},
            ) from exc
        object.__setattr__(self, "kind", kind)
        if isinstance(self.round, bool) or not isinstance(self.round, int) or self.round < 0:
            raise InvalidInputError(
                "'round' debe ser un entero >= 0", details={"field": "lineage.round"}
            )
        if self.kind is StageKind.EXTENSION and self.round != 0:
            raise InvalidInputError(
                "la extensión de la base tiene una sola ronda (round = 0)",
                details={"field": "lineage.round"},
            )
