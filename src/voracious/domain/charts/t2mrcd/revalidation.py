"""Decisión e informe de la recalibración de T²MRCD (``docs/metodos/t2mrcd.md``).

Decisiones del dueño:

- **Sin depuración automática iterativa (2026-10-09):** las filas nuevas pasan solo por la
  exclusión humana (anotaciones con causa asignable confirmada); después se recalibra como una
  Fase I, en una sola pasada. Quitar las filas con ``T² > límite`` y repetir no converge: MRCD no
  es «de composición» y al reducir la base vuelve a dejar fuera un 25 %.
- **Mínimo de filas:** ``min_observations = 25`` (documento del dueño, 2026-10-07), sin regla por
  variable; por debajo, ``INSUFFICIENT``: no se crea modelo ni se lanza excepción.
- **Q4:** Frobenius relativa con umbral parametrizable (0.10), informativo por defecto
  (``threshold_decides = False``); deciden las pruebas formales de S y de μ (pendientes) con la
  regla «cualquiera». Con ``threshold_decides = True`` el umbral también decide.
- **Q8:** la recalibración hereda B, ``alpha_limit``, ``phase2_alpha_limit``, agregaciones y
  parámetros MRCD del modelo vigente; solo la semilla es propia.
- **Q9:** «límite de Fase II > límite de Fase I» es un diagnóstico del informe, no una invariante.
"""

from dataclasses import dataclass
from typing import Final

import numpy as np

from voracious.domain.charts.t2mrcd.comparison import (
    ComparisonResult,
    CovarianceChangeTest,
    DecisionRule,
    MeanChangeTest,
    RelativeChangeMetric,
    any_formal_test_change,
    frobenius_relative_change,
)
from voracious.domain.charts.t2mrcd.model import LimitRegime, T2MRCDModel
from voracious.domain.charts.t2mrcd.params import _is_int
from voracious.domain.common import InvalidInputError, RecalibrationDecision, RowDisposition

__all__ = [
    "DEFAULT_MIN_OBSERVATIONS",
    "DEFAULT_RELATIVE_CHANGE_THRESHOLD",
    "LimitsSnapshot",
    "T2MRCDRecalibrationParams",
    "T2MRCDRecalibrationReport",
    "decide",
]

DEFAULT_MIN_OBSERVATIONS: Final = 25
"""Mínimo de filas nuevas conservadas para recalibrar: documento del dueño (2026-10-07)."""

DEFAULT_RELATIVE_CHANGE_THRESHOLD: Final = 0.10
"""Umbral de la Frobenius relativa: documento del dueño (2026-10-07), Q4; informativo salvo
``threshold_decides``."""


@dataclass(frozen=True, kw_only=True)
class T2MRCDRecalibrationParams:
    """Parámetros de la recalibración de T²MRCD.

    Attributes:
        seed: Semilla raíz de la recalibración, entera y no negativa (obligatoria).
        min_observations: Mínimo de filas nuevas conservadas (25, documento del dueño).
        relative_change_threshold: Umbral del cambio relativo de la dispersión (0.10, Q4;
            configurable, finito y ``> 0``).
        threshold_decides: Si ``True``, superar el umbral también reemplaza la base
            («cualquiera»: umbral, prueba de S o prueba de μ); si ``False`` (default), el umbral
            es solo informativo. Default informativo porque con datos estables la Frobenius
            relativa de MRCD suele superar 0.10 por ruido de estimación (≈ 0.25-0.5 con
            n = 200, p = 3). En ambos modos las pruebas formales siguen siendo obligatorias.
        relative_change_metric: Medida del cambio relativo (Frobenius relativa, Q4).
        covariance_test: Prueba formal de dispersión. **Pendiente** (``None``).
        mean_test: Prueba formal de ubicación. **Pendiente** (``None``).
        decision_rule: Regla de decisión (``any_formal_test_change``, Q4).
        n_test_resamples: Remuestreos de las pruebas formales. **Pendiente** (``None``).
    """

    seed: int
    min_observations: int = DEFAULT_MIN_OBSERVATIONS
    relative_change_threshold: float = DEFAULT_RELATIVE_CHANGE_THRESHOLD
    threshold_decides: bool = False
    relative_change_metric: RelativeChangeMetric = frobenius_relative_change
    covariance_test: CovarianceChangeTest | None = None
    mean_test: MeanChangeTest | None = None
    decision_rule: DecisionRule = any_formal_test_change
    n_test_resamples: int | None = None

    def __post_init__(self) -> None:
        """Valida los campos.

        Raises:
            InvalidInputError: Si ``seed`` no es un entero ``>= 0``, ``min_observations`` no es
                un entero ``>= 1``, el umbral no es finito y positivo, ``threshold_decides`` no es
                booleano o ``n_test_resamples`` no es ``None`` ni un entero ``>= 1``.
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
        threshold = self.relative_change_threshold
        if not (np.isfinite(threshold) and threshold > 0.0):
            raise InvalidInputError(
                "'relative_change_threshold' debe ser finito y > 0",
                details={"field": "recalibration.relative_change_threshold"},
            )
        if not isinstance(self.threshold_decides, bool):
            raise InvalidInputError(
                "'threshold_decides' debe ser booleano",
                details={"field": "recalibration.threshold_decides"},
            )
        if self.n_test_resamples is not None and (
            not _is_int(self.n_test_resamples) or self.n_test_resamples < 1
        ):
            raise InvalidInputError(
                "'n_test_resamples' debe ser un entero >= 1",
                details={"field": "recalibration.n_test_resamples"},
            )

    def pending_fields(self) -> list[str]:
        """Campos estadísticos aún sin decidir, en orden estable.

        Returns:
            Nombres con el prefijo ``recalibration.``.
        """
        pending: list[str] = []
        if self.covariance_test is None:
            pending.append("recalibration.covariance_test")
        if self.mean_test is None:
            pending.append("recalibration.mean_test")
        if self.n_test_resamples is None:
            pending.append("recalibration.n_test_resamples")
        return pending


def decide(
    comparison: ComparisonResult | None,
    *,
    n_kept: int,
    min_observations: int,
    force_replace: bool,
) -> RecalibrationDecision:
    """Decisión de la recalibración (función pura).

    Orden: pocas filas → ``INSUFFICIENT`` (aunque se fuerce el reemplazo); reemplazo forzado →
    ``REPLACE``; cambio detectado → ``REPLACE``; si no, ``EXTEND``.

    Args:
        comparison: Comparación de bases, o ``None`` si no se hizo (forzado o insuficiente).
        n_kept: Filas nuevas conservadas tras la exclusión humana.
        min_observations: Mínimo de filas nuevas.
        force_replace: Reemplazo forzado por una persona.

    Returns:
        La decisión.

    Raises:
        ValueError: Si no hay comparación y no se forzó el reemplazo con filas suficientes.
    """
    if n_kept < min_observations:
        return RecalibrationDecision.INSUFFICIENT
    if force_replace:
        return RecalibrationDecision.REPLACE
    if comparison is None:
        msg = "sin comparación solo se puede decidir INSUFFICIENT o un reemplazo forzado"
        raise ValueError(msg)
    return RecalibrationDecision.REPLACE if comparison.changed else RecalibrationDecision.EXTEND


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
        decision: Decisión tomada.
        forced: Reemplazo forzado por una persona.
        row_disposition: Destino de cada fila de ``vstack(base, x_new)``: las de la base,
            ``ALREADY_IN_BASE``; las nuevas, ``KEPT`` o ``EXCLUDED_ASSIGNABLE_CAUSE``.
        n_base: Filas de la base vigente.
        n_new: Filas nuevas recibidas.
        n_excluded_assignable_cause: Filas nuevas excluidas por una persona.
        n_kept_new: Filas nuevas conservadas.
        min_observations: Mínimo exigido de filas nuevas conservadas.
        comparison: Comparación de bases (``None`` si se forzó o no hubo filas suficientes).
        before: Límites del modelo vigente.
        after: Límites del modelo nuevo (``None`` si ``INSUFFICIENT``).
        phase2_exceeds_phase1: Diagnóstico (Q9) del modelo nuevo: ``phase2_limit >
            phase1_limit`` (``None`` si ``INSUFFICIENT``).
    """

    decision: RecalibrationDecision
    forced: bool
    row_disposition: tuple[RowDisposition, ...]
    n_base: int
    n_new: int
    n_excluded_assignable_cause: int
    n_kept_new: int
    min_observations: int
    comparison: ComparisonResult | None
    before: LimitsSnapshot
    after: LimitsSnapshot | None
    phase2_exceeds_phase1: bool | None
