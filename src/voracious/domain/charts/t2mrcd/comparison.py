"""Comparación de la base vigente con las filas nuevas al recalibrar (``docs/metodos/t2mrcd.md``).

Decisiones del dueño (2026-10-07, Q4, revisada en la vuelta de corrección del Paso 2b.1):

- **Cambio relativo, informativo por defecto:** norma de Frobenius relativa
  ``‖S₁ - S₀‖_F / ‖S₀‖_F`` entre la dispersión MRCD de la base vigente (``S₀``) y la de las filas
  nuevas conservadas (``S₁``), con umbral parametrizable (0.10 por defecto, documento del dueño).
  Siempre se calcula y se informa (``exceeds_threshold``). Con ``threshold_decides = False``
  (default) **no decide**: con datos estables el ruido de estimación de MRCD entre dos muestras
  de la misma distribución ya la lleva por encima de 0.10 (≈ 0.25-0.5 con n = 200 y p = 3).
  Con ``threshold_decides = True`` también decide: hay cambio si **cualquiera** (umbral, prueba
  de S o prueba de μ) lo detecta.
- **Pruebas formales** de igualdad de dispersiones y de ubicaciones por remuestreo: **pendientes**
  (sin cita). Son ``Protocol`` inyectables; con ``None`` la recalibración termina en
  ``T2MRCD_DECISION_PENDING`` salvo ``force_replace``. Las estrategias de prueba viven solo en
  ``tests/support/`` («SOLO TEST»).
- **Regla de decisión:** reemplazar la base si **cualquiera de las dos pruebas formales** (de S o
  de μ) detecta cambio (``any_formal_test_change``), más el umbral si ``threshold_decides``.

Las estrategias de producción son objetos con nombre estable (``name``) para poder persistirlas
por nombre (mejora M1, Paso 2b.2).
"""

from dataclasses import dataclass
from typing import Final, Protocol

import numpy as np

from voracious.domain.charts.t2mrcd.seeds import (
    SLOT_COVARIANCE_TEST,
    SLOT_MEAN_TEST,
    child,
)
from voracious.domain.common import (
    FloatMatrix,
    LocationScatterEstimator,
    LocationScatterFit,
    TaskMapper,
)

__all__ = [
    "AnyFormalTestChangeRule",
    "ChangeTestResult",
    "ComparisonResult",
    "CovarianceChangeTest",
    "DecisionRule",
    "FrobeniusRelativeChange",
    "MeanChangeTest",
    "RelativeChangeMetric",
    "any_formal_test_change",
    "compare_bases",
    "frobenius_relative_change",
]


class RelativeChangeMetric(Protocol):
    """Medida del cambio relativo entre dos dispersiones."""

    @property
    def name(self) -> str:
        """Nombre estable de la medida."""
        ...

    def __call__(self, s0: FloatMatrix, s1: FloatMatrix) -> float:
        """Calcula el cambio relativo de ``s1`` respecto a ``s0``.

        Args:
            s0: Dispersión de la base vigente, ``p x p``.
            s1: Dispersión de las filas nuevas, ``p x p``.

        Returns:
            El cambio relativo (``>= 0``).
        """
        ...


@dataclass(frozen=True)
class FrobeniusRelativeChange:
    """``‖S₁ - S₀‖_F / ‖S₀‖_F`` (decisión del dueño 2026-10-07, Q4)."""

    @property
    def name(self) -> str:
        """Nombre estable: ``"frobenius_relative"``."""
        return "frobenius_relative"

    def __call__(self, s0: FloatMatrix, s1: FloatMatrix) -> float:
        """Norma de Frobenius de la diferencia, relativa a la de ``s0``.

        Args:
            s0: Dispersión de la base vigente.
            s1: Dispersión de las filas nuevas.

        Returns:
            El cambio relativo.
        """
        return float(np.linalg.norm(s1 - s0, ord="fro") / np.linalg.norm(s0, ord="fro"))


frobenius_relative_change: Final = FrobeniusRelativeChange()
"""Medida de producción del cambio relativo (Q4; solo informativa)."""


@dataclass(frozen=True)
class ChangeTestResult:
    """Resultado de una prueba formal de cambio.

    Attributes:
        name: Nombre estable de la prueba.
        statistic: Estadístico observado.
        p_value: Valor p, si la prueba lo define.
        changed: ``True`` si la prueba detecta cambio.
    """

    name: str
    statistic: float
    p_value: float | None
    changed: bool


class _ChangeTest(Protocol):
    """Forma común de una prueba formal de cambio por remuestreo (pendiente, sin cita)."""

    @property
    def name(self) -> str:
        """Nombre estable de la prueba."""
        ...

    def __call__(
        self,
        base: FloatMatrix,
        new: FloatMatrix,
        *,
        fit0: LocationScatterFit,
        fit1: LocationScatterFit,
        estimator: LocationScatterEstimator,
        seed: np.random.SeedSequence,
        n_resamples: int,
        mapper: TaskMapper,
    ) -> ChangeTestResult:
        """Contrasta la base vigente con las filas nuevas.

        Args:
            base: Base vigente ``n0 x p``.
            new: Filas nuevas conservadas ``n1 x p``.
            fit0: Ajuste de la base vigente.
            fit1: Ajuste de las filas nuevas.
            estimator: Estimador de la carta (para reajustar en cada remuestreo).
            seed: Semilla propia de la prueba (hueco fijo).
            n_resamples: Número de remuestreos.
            mapper: Reparto de los remuestreos.

        Returns:
            El resultado de la prueba.
        """
        ...


class CovarianceChangeTest(_ChangeTest, Protocol):
    """Prueba formal de igualdad de dispersiones (pendiente: sin estrategia de producción)."""


class MeanChangeTest(_ChangeTest, Protocol):
    """Prueba formal de igualdad de ubicaciones (pendiente: sin estrategia de producción)."""


class DecisionRule(Protocol):
    """Combina las pruebas formales en la decisión «hay cambio».

    El cambio relativo de la dispersión no entra en la regla: ``compare_bases`` lo añade solo si
    ``threshold_decides`` (Q4).
    """

    @property
    def name(self) -> str:
        """Nombre estable de la regla."""
        ...

    def __call__(self, covariance: ChangeTestResult, mean: ChangeTestResult) -> bool:
        """Decide si hay cambio.

        Args:
            covariance: Resultado de la prueba de dispersión.
            mean: Resultado de la prueba de ubicación.

        Returns:
            ``True`` si hay que reemplazar la base.
        """
        ...


@dataclass(frozen=True)
class AnyFormalTestChangeRule:
    """Hay cambio si **cualquiera** de las dos pruebas formales lo detecta (dueño, 2026-10-07)."""

    @property
    def name(self) -> str:
        """Nombre estable: ``"any_formal_test_change"``."""
        return "any_formal_test_change"

    def __call__(self, covariance: ChangeTestResult, mean: ChangeTestResult) -> bool:
        """``covariance.changed or mean.changed``.

        Args:
            covariance: Resultado de la prueba de dispersión.
            mean: Resultado de la prueba de ubicación.

        Returns:
            ``True`` si alguna de las dos detecta cambio.
        """
        return covariance.changed or mean.changed


any_formal_test_change: Final = AnyFormalTestChangeRule()
"""Regla de decisión de producción (Q4): solo las pruebas formales deciden."""


@dataclass(frozen=True)
class ComparisonResult:
    """Resultado de comparar la base vigente con las filas nuevas.

    Attributes:
        metric_name: Medida del cambio relativo.
        relative_change: Cambio relativo de la dispersión (informativo).
        threshold: Umbral del cambio relativo.
        exceeds_threshold: ``relative_change > threshold`` (estricto). Solo interviene en
            ``changed`` si ``threshold_decides``.
        threshold_decides: El umbral decide además de las pruebas formales.
        covariance: Prueba de dispersión.
        mean: Prueba de ubicación.
        decision_rule_name: Regla de decisión aplicada a las pruebas formales.
        changed: Decisión: la regla de las pruebas, o además ``exceeds_threshold`` si
            ``threshold_decides``.
    """

    metric_name: str
    relative_change: float
    threshold: float
    exceeds_threshold: bool
    threshold_decides: bool
    covariance: ChangeTestResult
    mean: ChangeTestResult
    decision_rule_name: str
    changed: bool


def compare_bases(
    base: FloatMatrix,
    new: FloatMatrix,
    *,
    fit0: LocationScatterFit,
    fit1: LocationScatterFit,
    metric: RelativeChangeMetric,
    threshold: float,
    threshold_decides: bool,
    covariance_test: CovarianceChangeTest,
    mean_test: MeanChangeTest,
    decision_rule: DecisionRule,
    estimator: LocationScatterEstimator,
    seed: int,
    n_test_resamples: int,
    mapper: TaskMapper,
) -> ComparisonResult:
    """Compara la base vigente con las filas nuevas conservadas.

    Args:
        base: Base vigente ``n0 x p``.
        new: Filas nuevas conservadas ``n1 x p``.
        fit0: Ajuste de la base vigente (``μ₀``, ``S₀``).
        fit1: Ajuste de las filas nuevas (``μ₁``, ``S₁``).
        metric: Medida del cambio relativo.
        threshold: Umbral del cambio relativo.
        threshold_decides: Si ``True``, superar el umbral también decide el cambio; si
            ``False``, es solo informativo.
        covariance_test: Prueba de dispersión.
        mean_test: Prueba de ubicación.
        decision_rule: Regla de decisión.
        estimator: Estimador de la carta.
        seed: Semilla raíz de la recalibración (cada prueba usa su hueco fijo).
        n_test_resamples: Remuestreos de cada prueba.
        mapper: Reparto de los remuestreos.

    Returns:
        El resultado de la comparación.
    """
    relative = float(metric(fit0.cov, fit1.cov))
    exceeds = relative > threshold
    covariance = covariance_test(
        base,
        new,
        fit0=fit0,
        fit1=fit1,
        estimator=estimator,
        seed=child(seed, (SLOT_COVARIANCE_TEST,)),
        n_resamples=n_test_resamples,
        mapper=mapper,
    )
    mean = mean_test(
        base,
        new,
        fit0=fit0,
        fit1=fit1,
        estimator=estimator,
        seed=child(seed, (SLOT_MEAN_TEST,)),
        n_resamples=n_test_resamples,
        mapper=mapper,
    )
    return ComparisonResult(
        metric_name=metric.name,
        relative_change=relative,
        threshold=threshold,
        exceeds_threshold=exceeds,
        threshold_decides=threshold_decides,
        covariance=covariance,
        mean=mean,
        decision_rule_name=decision_rule.name,
        changed=bool(decision_rule(covariance, mean)) or (threshold_decides and exceeds),
    )
