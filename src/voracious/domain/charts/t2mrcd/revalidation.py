"""Depuración, decisión e informe de la recalibración de T²MRCD (``docs/metodos/t2mrcd.md``).

Decisiones del dueño (2026-10-07):

- **Q3, depuración:** primero la exclusión humana (filas con causa asignable confirmada); después la
  automática iterativa: ajuste + límites de Fase I por bootstrap, quitar las filas con
  ``T² > límite de Fase I``, repetir. Se aplica a la versión inicial y a las filas nuevas.
- **Q5:** como mucho ``max_depuration_rounds`` rondas (5, parámetro técnico); si no converge se
  sigue con ``converged = False`` en el informe.
- **Mínimo de filas:** ``min_observations = 25`` (documento del dueño), sin regla por variable; por
  debajo, ``INSUFFICIENT``: no se crea modelo ni se lanza excepción.
- **Q4:** Frobenius relativa con umbral parametrizable (0.10), informativo por defecto
  (``threshold_decides = False``); deciden las pruebas formales de S y de μ (pendientes) con la
  regla «cualquiera». Con ``threshold_decides = True`` el umbral también decide.
- **Q8:** la recalibración hereda B, ``alpha_limit``, ``phase2_alpha_limit``, agregaciones y
  parámetros MRCD del modelo vigente; solo la semilla es propia.
- **Q9:** «límite de Fase II > límite de Fase I» es un diagnóstico del informe, no una invariante.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol

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
from voracious.domain.charts.t2mrcd.params import DEFAULT_MAX_DEPURATION_ROUNDS, _is_int
from voracious.domain.common import (
    BoolVector,
    FloatMatrix,
    FloatVector,
    InvalidInputError,
    RecalibrationDecision,
    RowDisposition,
)
from voracious.domain.estimators.mrcd import IndexVector

__all__ = [
    "DEFAULT_MIN_OBSERVATIONS",
    "DEFAULT_RELATIVE_CHANGE_THRESHOLD",
    "DepurationResult",
    "DepurationStage",
    "DepurationStep",
    "LimitsSnapshot",
    "T2MRCDRecalibrationParams",
    "T2MRCDRecalibrationReport",
    "decide",
    "depurate",
    "depuration_step",
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
        max_depuration_rounds: Rondas máximas de la depuración automática (5, Q5).
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
    max_depuration_rounds: int = DEFAULT_MAX_DEPURATION_ROUNDS
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
                un entero ``>= 1``, ``max_depuration_rounds`` no es un entero ``>= 0``, el umbral
                no es finito y positivo, ``threshold_decides`` no es booleano o
                ``n_test_resamples`` no es ``None`` ni un entero ``>= 1``.
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
        if not _is_int(self.max_depuration_rounds) or self.max_depuration_rounds < 0:
            raise InvalidInputError(
                "'max_depuration_rounds' debe ser un entero >= 0",
                details={"field": "recalibration.max_depuration_rounds"},
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


class DepurationStage(Protocol):
    """Lo que la depuración necesita de una ronda: el límite de Fase I y el T²."""

    @property
    def phase1_limit(self) -> float:
        """Límite de Fase I de la ronda."""
        ...

    def t2(self, x: FloatMatrix) -> FloatVector:
        """T² de ``x`` con el ajuste de la ronda.

        Args:
            x: Observaciones ``m x p``.

        Returns:
            Vector de ``m`` valores T².
        """
        ...


@dataclass(frozen=True, eq=False)
class DepurationResult[StageT: DepurationStage]:
    """Resultado de la depuración automática.

    Attributes:
        stage: Ronda final (ajustada sobre ``kept``), o ``None`` si quedaron menos de
            ``min_rows`` filas.
        kept: Filas conservadas (máscara sobre la entrada).
        excluded_automatic: Filas quitadas por la depuración automática.
        rounds: Rondas que quitaron filas.
        converged: ``True`` si en la ronda final ninguna fila conservada supera el límite.
    """

    stage: StageT | None
    kept: BoolVector
    excluded_automatic: BoolVector
    rounds: int
    converged: bool


@dataclass(frozen=True, eq=False)
class DepurationStep:
    """Resultado de evaluar una ronda de la depuración automática (``depuration_step``).

    Attributes:
        kept: Filas conservadas tras la ronda (máscara sobre la entrada; copia propia).
        excluded_automatic_now: Filas que esta ronda quita (máscara sobre la entrada).
        above_t2: Filas de la ronda con ``T² > límite de Fase I`` (máscara sobre ``rows``).
        converged: ``True`` si ninguna fila de la ronda supera el límite.
        final: ``True`` si la depuración termina en esta ronda: convergió, se agotaron las rondas
            (la ronda queda como final, sin quitar filas) o, tras quitar filas, quedan menos de
            ``min_rows`` (``exhausted``: no hay ronda final).
    """

    kept: BoolVector
    excluded_automatic_now: BoolVector
    above_t2: BoolVector
    converged: bool
    final: bool

    @property
    def exhausted(self) -> bool:
        """``True`` si la depuración terminó por quedar menos de ``min_rows`` filas."""
        return self.final and bool(self.excluded_automatic_now.any())


def depuration_step(
    stage: DepurationStage,
    x_rows: FloatMatrix,
    rows: IndexVector,
    kept: BoolVector,
    round_index: int,
    *,
    max_rounds: int,
    min_rows: int = 1,
) -> DepurationStep:
    """Una ronda de la depuración automática (Q3, Q5), sin ajustar nada (función pura).

    Con la ronda ``round_index`` ya ajustada sobre ``x_rows`` (las filas ``rows`` de la entrada,
    las conservadas en ``kept``): si ninguna supera el límite de Fase I (estricto), converge; si
    alguna lo supera y ya se hicieron ``max_rounds`` rondas de exclusión, termina sin converger y
    sin quitar filas; si no, quita **todas** las que lo superan y termina solo si quedan menos de
    ``min_rows`` filas.

    Args:
        stage: Ronda ajustada (límite de Fase I y T²).
        x_rows: Filas de la ronda (``x[rows]``).
        rows: Índices de esas filas en la entrada.
        kept: Filas conservadas antes de la ronda (máscara sobre la entrada; no se muta).
        round_index: Número de la ronda (desde 0) = rondas de exclusión ya hechas.
        max_rounds: Rondas máximas de exclusión (``>= 0``).
        min_rows: Mínimo de filas para seguir ajustando (``>= 1``).

    Returns:
        El resultado de la ronda.
    """
    above = stage.t2(x_rows) > stage.phase1_limit
    kept = kept.copy()
    now = np.zeros(kept.shape[0], dtype=np.bool_)
    if not bool(above.any()):
        return DepurationStep(kept, now, above, converged=True, final=True)
    if round_index >= max_rounds:
        return DepurationStep(kept, now, above, converged=False, final=True)
    removed = rows[above]
    kept[removed] = False
    now[removed] = True
    return DepurationStep(kept, now, above, converged=False, final=int(kept.sum()) < min_rows)


def depurate[StageT: DepurationStage](
    x: FloatMatrix,
    kept: BoolVector,
    *,
    fit_round: Callable[[FloatMatrix, IndexVector, int], StageT],
    max_rounds: int,
    min_rows: int,
) -> DepurationResult[StageT]:
    """Depuración automática iterativa (Q3, Q5): bucle de ``depuration_step``.

    En cada ronda ``r`` (desde 0) se ajusta ``fit_round(x[rows], rows, r)`` con las filas
    conservadas y se evalúa con ``depuration_step``; se repite hasta que la ronda sea final.
    Termina cuando ninguna fila supera el límite (``converged``), cuando ya se hicieron
    ``max_rounds`` rondas de exclusión (la ronda final se ajusta igual y ``converged = False``) o
    cuando quedan menos de ``min_rows`` filas (``stage = None``, sin ajustar).

    Args:
        x: Entrada ``n x p``.
        kept: Filas de partida (tras la exclusión humana); se copia.
        fit_round: Ajuste de una ronda: filas, sus índices en ``x`` y el número de ronda.
        max_rounds: Rondas máximas de exclusión (``>= 0``).
        min_rows: Mínimo de filas para seguir ajustando (``>= 1``).

    Returns:
        El resultado de la depuración.
    """
    kept = kept.copy()
    automatic = np.zeros(x.shape[0], dtype=np.bool_)
    rounds = 0
    if int(kept.sum()) < min_rows:
        return DepurationResult(None, kept, automatic, rounds, converged=False)
    while True:
        rows = np.flatnonzero(kept).astype(np.int64)
        x_rows = x[rows]
        stage = fit_round(x_rows, rows, rounds)
        step = depuration_step(
            stage, x_rows, rows, kept, rounds, max_rounds=max_rounds, min_rows=min_rows
        )
        kept = step.kept
        automatic |= step.excluded_automatic_now
        if step.exhausted:
            return DepurationResult(None, kept, automatic, rounds + 1, converged=False)
        if step.final:
            return DepurationResult(stage, kept, automatic, rounds, converged=step.converged)
        rounds += 1


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
        n_kept: Filas nuevas conservadas tras la depuración.
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
            ``ALREADY_IN_BASE``; las nuevas, ``KEPT`` o excluidas.
        n_base: Filas de la base vigente.
        n_new: Filas nuevas recibidas.
        n_excluded_assignable_cause: Filas nuevas excluidas por una persona.
        n_excluded_automatic: Filas nuevas excluidas por la depuración automática.
        n_kept_new: Filas nuevas conservadas.
        min_observations: Mínimo exigido de filas nuevas conservadas.
        depuration_rounds: Rondas de la depuración automática de las filas nuevas.
        depuration_converged: Convergencia de esa depuración (``None`` si no se ajustó nada).
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
    n_excluded_automatic: int
    n_kept_new: int
    min_observations: int
    depuration_rounds: int
    depuration_converged: bool | None
    comparison: ComparisonResult | None
    before: LimitsSnapshot
    after: LimitsSnapshot | None
    phase2_exceeds_phase1: bool | None
