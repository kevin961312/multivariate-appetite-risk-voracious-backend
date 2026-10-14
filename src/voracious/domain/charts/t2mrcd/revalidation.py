"""Decisión e informe de la recalibración de T²MRCD (``docs/metodos/t2mrcd.md``).

Decisiones del dueño:

- **Sin comparación de bases (2026-10-14):** la carta T² ya es la prueba de hipótesis sobre la
  media, así que no hay pruebas de cambio de S ni de μ, ni umbral de cambio relativo. La
  recalibración amplía la base vigente (``EXTEND``) por defecto; solo la reemplaza (``REPLACE``)
  ante un evento estructural o una petición explícita (``force_replace``).
- **Sin depuración automática iterativa (2026-10-09):** las filas nuevas pasan solo por la
  exclusión humana (anotaciones con causa asignable confirmada); después se recalibra como una
  Fase I, en una sola pasada. Quitar las filas con ``T² > límite`` y repetir no converge: MRCD no
  es «de composición» y al reducir la base vuelve a dejar fuera un 25 %.
- **Mínimo de filas:** ``min_observations = 25`` (documento del dueño, 2026-10-07), sin regla por
  variable; por debajo, ``INSUFFICIENT``: no se crea modelo ni se lanza excepción.
- **Q8:** la recalibración hereda B, ``alpha_limit``, ``phase2_alpha_limit``, agregaciones y
  parámetros MRCD del modelo vigente; solo la semilla es propia.
- **Q9:** «límite de Fase II > límite de Fase I» es un diagnóstico del informe, no una invariante.
"""

from dataclasses import dataclass
from typing import Final

from voracious.domain.charts.t2mrcd.model import LimitRegime, T2MRCDModel
from voracious.domain.charts.t2mrcd.params import _is_int
from voracious.domain.common import InvalidInputError, RecalibrationDecision, RowDisposition

__all__ = [
    "DEFAULT_MIN_OBSERVATIONS",
    "LimitsSnapshot",
    "T2MRCDRecalibrationParams",
    "T2MRCDRecalibrationReport",
    "decide",
]

DEFAULT_MIN_OBSERVATIONS: Final = 25
"""Mínimo de filas nuevas conservadas para recalibrar: documento del dueño (2026-10-07)."""


@dataclass(frozen=True, kw_only=True)
class T2MRCDRecalibrationParams:
    """Parámetros de la recalibración de T²MRCD.

    Attributes:
        seed: Semilla raíz de la recalibración, entera y no negativa (obligatoria).
        min_observations: Mínimo de filas nuevas conservadas (25, documento del dueño).
    """

    seed: int
    min_observations: int = DEFAULT_MIN_OBSERVATIONS

    def __post_init__(self) -> None:
        """Valida los campos.

        Raises:
            InvalidInputError: Si ``seed`` no es un entero ``>= 0`` o ``min_observations`` no es
                un entero ``>= 1``.
        """
        if not _is_int(self.seed) or self.seed < 0:
            raise InvalidInputError(
                "'seed' debe ser un entero >= 0", details={"field": "recalibration.seed"}
            )
        if not _is_int(self.min_observations) or self.min_observations < 1:
            raise InvalidInputError(
                "'min_observations' debe ser un entero >= 1",
                details={"field": "recalibration.min_observations"},
            )


def decide(*, n_kept: int, min_observations: int, force_replace: bool) -> RecalibrationDecision:
    """Decisión de la recalibración (función pura).

    Orden: pocas filas → ``INSUFFICIENT`` (aunque se pida el reemplazo); reemplazo pedido (evento
    estructural o petición explícita) → ``REPLACE``; si no, ``EXTEND`` (por defecto).

    Args:
        n_kept: Filas nuevas conservadas tras la exclusión humana.
        min_observations: Mínimo de filas nuevas.
        force_replace: Reemplazo pedido por una persona o por un evento estructural.

    Returns:
        La decisión.
    """
    if n_kept < min_observations:
        return RecalibrationDecision.INSUFFICIENT
    if force_replace:
        return RecalibrationDecision.REPLACE
    return RecalibrationDecision.EXTEND


@dataclass(frozen=True)
class LimitsSnapshot:
    """Límites de una versión del modelo.

    Attributes:
        phase1_limit: Límite de Fase I.
        phase2_limit: Límite de Fase II.
        phase1_mc_error: Error Monte Carlo de ``phase1_limit`` (``None`` si no está disponible).
        phase2_mc_error: Error Monte Carlo de ``phase2_limit`` (``None`` si no está disponible).
        regime: Régimen de la versión.
        operative_limit: Límite con el que vigila la Fase II.
        n_base: Filas de la base.
    """

    phase1_limit: float
    phase2_limit: float
    phase1_mc_error: float | None
    phase2_mc_error: float | None
    regime: LimitRegime
    operative_limit: float
    n_base: int

    @classmethod
    def of(cls, model: T2MRCDModel) -> "LimitsSnapshot":
        """Toma los límites de un modelo.

        Args:
            model: Versión del modelo.

        Returns:
            Sus límites.
        """
        limits = model.limits
        return cls(
            phase1_limit=limits.phase1_limit,
            phase2_limit=limits.phase2_limit,
            phase1_mc_error=limits.phase1_mc_error,
            phase2_mc_error=limits.phase2_mc_error,
            regime=model.limit_regime,
            operative_limit=model.operative_limit,
            n_base=model.n_base,
        )


@dataclass(frozen=True, eq=False)
class T2MRCDRecalibrationReport:
    """Informe de una recalibración (antes/después).

    Attributes:
        decision: Decisión tomada (``REPLACE`` solo por evento estructural o petición
            explícita).
        row_disposition: Destino de cada fila de ``vstack(base, x_new)``: las de la base,
            ``ALREADY_IN_BASE``; las nuevas, ``KEPT`` o ``EXCLUDED_ASSIGNABLE_CAUSE``.
        n_base: Filas de la base vigente.
        n_new: Filas nuevas recibidas.
        n_excluded_assignable_cause: Filas nuevas excluidas por una persona.
        n_kept_new: Filas nuevas conservadas.
        min_observations: Mínimo exigido de filas nuevas conservadas.
        before: Límites del modelo vigente.
        after: Límites del modelo nuevo (``None`` si ``INSUFFICIENT``).
        phase2_exceeds_phase1: Diagnóstico (Q9) del modelo nuevo: ``phase2_limit >
            phase1_limit`` (``None`` si ``INSUFFICIENT``).
    """

    decision: RecalibrationDecision
    row_disposition: tuple[RowDisposition, ...]
    n_base: int
    n_new: int
    n_excluded_assignable_cause: int
    n_kept_new: int
    min_observations: int
    before: LimitsSnapshot
    after: LimitsSnapshot | None
    phase2_exceeds_phase1: bool | None
