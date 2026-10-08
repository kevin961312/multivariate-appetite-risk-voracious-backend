"""Una ronda de Fase I de T²MRCD: ajuste MRCD, filas limpias y límites bootstrap.

La usan la Fase I (``fit_phase1``, en cada ronda de la depuración automática) y la recalibración
(depuración de las filas nuevas y Fase I final). Estimador: MRCD, siempre (ADR 0002); muestreador:
``BootstrapOOBSampler``, siempre. Ninguno se expone en ``T2MRCDParams``.

Una ronda son dos pasos separables (vuelta 3.2 del Paso 3): ``fit_base`` (ajuste MRCD de las filas)
y ``calibrate_stage`` (criterio de fila limpia y límites bootstrap); ``fit_stage`` es su
composición. Así un orquestador puede ejecutarlos por separado sin cambiar ningún bit.
"""

from dataclasses import dataclass
from typing import Final

import numpy as np

from voracious.domain.charts.t2mrcd.bootstrap import BootstrapLimits, calibrate_limits
from voracious.domain.charts.t2mrcd.params import LimitAggregation, T2MRCDParams
from voracious.domain.charts.t2mrcd.phase2_limit import bootstrap_oob_sampler
from voracious.domain.charts.t2mrcd.seeds import SpawnKey
from voracious.domain.charts.t2mrcd.statistic import t2
from voracious.domain.common import (
    BoolVector,
    EstimationError,
    FloatMatrix,
    FloatVector,
    InvalidInputError,
    TaskMapper,
)
from voracious.domain.estimators.mrcd import IndexVector, MRCDEstimator, MRCDFit, MRCDParams

__all__ = [
    "MAX_REPORTED_ROWS",
    "T2MRCD_CLEAN_CRITERION_INVALID",
    "T2MRCD_NO_CLEAN_OBSERVATIONS",
    "Aggregations",
    "Phase1Stage",
    "calibrate_stage",
    "fit_base",
    "fit_base_mrcd",
    "fit_stage",
]

T2MRCD_CLEAN_CRITERION_INVALID: Final = "T2MRCD_CLEAN_CRITERION_INVALID"
"""Código de error: el criterio de fila limpia no devolvió una máscara booleana de longitud n."""

T2MRCD_NO_CLEAN_OBSERVATIONS: Final = "T2MRCD_NO_CLEAN_OBSERVATIONS"
"""Código de error: no quedó ninguna observación limpia que remuestrear."""

MAX_REPORTED_ROWS: Final = 20
"""Máximo de índices de fila que se informan en ``details`` (no es un parámetro estadístico)."""


@dataclass(frozen=True, eq=False)
class Phase1Stage:
    """Resultado de una ronda de Fase I sobre las filas ``rows`` de la entrada.

    Attributes:
        fit: Ajuste MRCD de esas filas.
        clean: Filas limpias, máscara sobre ``rows``.
        limits: Límites bootstrap calibrados con las filas limpias.
    """

    fit: MRCDFit
    clean: BoolVector
    limits: BootstrapLimits

    @property
    def phase1_limit(self) -> float:
        """Límite de Fase I de la ronda (el que usa la depuración automática)."""
        return self.limits.phase1_limit

    def t2(self, x: FloatMatrix) -> FloatVector:
        """T² de ``x`` con el ajuste de la ronda.

        Args:
            x: Observaciones ``m x p``.

        Returns:
            Vector de ``m`` valores T².
        """
        return t2(self.fit, x)


@dataclass(frozen=True)
class Aggregations:
    """Agregaciones de Fase I y de Fase II ya resueltas (no ``None``).

    Attributes:
        phase1: Agregación del límite de Fase I.
        phase2: Agregación del límite de Fase II.
    """

    phase1: LimitAggregation
    phase2: LimitAggregation


def fit_base(
    x: FloatMatrix, rows: IndexVector, params: T2MRCDParams, *, n_threads: int | None = None
) -> MRCDFit:
    """Ajusta MRCD sobre las filas de una ronda y exige que todas sean utilizables.

    Args:
        x: Filas de la ronda ``n_k x p`` (finitas).
        rows: Índices de esas filas en la entrada original (solo para los mensajes).
        params: Parámetros de la carta.
        n_threads: Hilos de ``pymrcd`` (rendimiento; no cambia ningún bit, ver ``fit_mrcd``).

    Returns:
        El ajuste MRCD.

    Raises:
        InvalidInputError: Filas finitas cuya suma desborda (``rrcov`` las descartaría).
        EstimationError: ``MRCD_FIT_FAILED``.
    """
    return fit_base_mrcd(x, rows, params.mrcd, n_threads=n_threads)


def fit_base_mrcd(
    x: FloatMatrix, rows: IndexVector, mrcd: MRCDParams, *, n_threads: int | None = None
) -> MRCDFit:
    """``fit_base`` con solo los parámetros de MRCD (el ajuste no usa nada más de la carta).

    Lo usa el ajuste suelto (``/fits``, vuelta 3.3), que solo conoce los parámetros de MRCD.

    Args:
        x: Filas ``n_k x p`` (finitas).
        rows: Índices de esas filas en la entrada original (solo para los mensajes).
        mrcd: Parámetros de MRCD.
        n_threads: Hilos de ``pymrcd`` (rendimiento; no cambia ningún bit, ver ``fit_mrcd``).

    Returns:
        El ajuste MRCD.

    Raises:
        InvalidInputError: Filas finitas cuya suma desborda (``rrcov`` las descartaría).
        EstimationError: ``MRCD_FIT_FAILED``.
    """
    fit = MRCDEstimator(mrcd, n_threads).fit(x)
    if not bool(fit.ok.all()):
        # Filas finitas cuya suma desborda: rrcov las descarta (CovMrcd.R:19-20); T²MRCD exige
        # puntuar todas las observaciones históricas, así que las rechaza.
        bad = rows[~fit.ok]
        raise InvalidInputError(
            "'x' tiene filas cuya suma desborda a infinito",
            details={"input": "x", "rows": [int(i) for i in bad[:MAX_REPORTED_ROWS]]},
        )
    return fit


def calibrate_stage(
    x: FloatMatrix,
    fit: MRCDFit,
    params: T2MRCDParams,
    *,
    aggregations: Aggregations,
    seed: int,
    spawn_key: SpawnKey,
    mapper: TaskMapper,
    n_threads: int | None = None,
) -> Phase1Stage:
    """Aplica el criterio de fila limpia al ajuste de la ronda y calibra los límites.

    Args:
        x: Filas de la ronda ``n_k x p``, las mismas con las que se ajustó ``fit``.
        fit: Ajuste MRCD de esas filas (``fit_base``).
        params: Parámetros de la carta.
        aggregations: Agregaciones de Fase I y de Fase II resueltas.
        seed: Semilla raíz.
        spawn_key: Hueco fijo de esta calibración (``seeds.py``).
        mapper: Reparto de las réplicas.
        n_threads: Hilos de ``pymrcd`` en cada réplica (rendimiento; no cambia ningún bit).

    Returns:
        La ronda.

    Raises:
        EstimationError: ``T2MRCD_CLEAN_CRITERION_INVALID``, ``T2MRCD_NO_CLEAN_OBSERVATIONS`` o un
            fallo del bootstrap.
    """
    boot = params.bootstrap
    clean = np.asarray(boot.clean_criterion(fit, x))
    if clean.dtype != np.bool_ or clean.shape != (x.shape[0],):
        raise EstimationError(
            T2MRCD_CLEAN_CRITERION_INVALID,
            "el criterio de fila limpia debe devolver una máscara booleana de longitud n",
            details={"dtype": str(clean.dtype), "shape": list(clean.shape)},
        )
    if not bool(clean.any()):
        raise EstimationError(
            T2MRCD_NO_CLEAN_OBSERVATIONS, "no hay observaciones limpias que remuestrear"
        )
    limits = calibrate_limits(
        x[clean],
        estimator=MRCDEstimator(params.mrcd, n_threads),
        sampler=bootstrap_oob_sampler,
        n_replicates=boot.n_replicates,
        seed=seed,
        spawn_key=spawn_key,
        alpha=boot.alpha_limit,
        phase2_alpha=boot.phase2_alpha_limit,
        aggregation=aggregations.phase1,
        phase2_aggregation=aggregations.phase2,
        mapper=mapper,
    )
    return Phase1Stage(fit=fit, clean=clean.copy(), limits=limits)


def fit_stage(
    x: FloatMatrix,
    rows: IndexVector,
    params: T2MRCDParams,
    *,
    aggregation: LimitAggregation,
    phase2_aggregation: LimitAggregation,
    seed: int,
    spawn_key: SpawnKey,
    mapper: TaskMapper,
    n_threads: int | None = None,
) -> Phase1Stage:
    """Ronda completa: ``fit_base`` seguido de ``calibrate_stage`` (composición, sin más lógica).

    Args:
        x: Filas de la ronda ``n_k x p`` (finitas).
        rows: Índices de esas filas en la entrada original (solo para los mensajes).
        params: Parámetros de la carta.
        aggregation: Agregación de Fase I (ya resuelta, no ``None``).
        phase2_aggregation: Agregación de Fase II (ya resuelta, no ``None``).
        seed: Semilla raíz.
        spawn_key: Hueco fijo de esta calibración (``seeds.py``).
        mapper: Reparto de las réplicas.
        n_threads: Hilos de ``pymrcd`` (rendimiento; no cambia ningún bit).

    Returns:
        La ronda.

    Raises:
        InvalidInputError: Filas finitas cuya suma desborda (``rrcov`` las descartaría).
        EstimationError: ``MRCD_FIT_FAILED``, ``T2MRCD_CLEAN_CRITERION_INVALID``,
            ``T2MRCD_NO_CLEAN_OBSERVATIONS`` o un fallo del bootstrap.
    """
    fit = fit_base(x, rows, params, n_threads=n_threads)
    return calibrate_stage(
        x,
        fit,
        params,
        aggregations=Aggregations(phase1=aggregation, phase2=phase2_aggregation),
        seed=seed,
        spawn_key=spawn_key,
        mapper=mapper,
        n_threads=n_threads,
    )
