"""Una ronda de Fase I de T²MRCD: ajuste MRCD, filas limpias y límites bootstrap.

La usan la Fase I (``fit_phase1``, en cada ronda de la depuración automática) y la recalibración
(depuración de las filas nuevas y Fase I final). Estimador: MRCD, siempre (ADR 0002); muestreador:
``BootstrapOOBSampler``, siempre. Ninguno se expone en ``T2MRCDParams``.
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
from voracious.domain.estimators.mrcd import IndexVector, MRCDEstimator, MRCDFit

__all__ = [
    "MAX_REPORTED_ROWS",
    "T2MRCD_CLEAN_CRITERION_INVALID",
    "T2MRCD_NO_CLEAN_OBSERVATIONS",
    "Phase1Stage",
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
) -> Phase1Stage:
    """Ajusta MRCD, aplica el criterio de fila limpia y calibra los límites.

    Args:
        x: Filas de la ronda ``n_k x p`` (finitas).
        rows: Índices de esas filas en la entrada original (solo para los mensajes).
        params: Parámetros de la carta.
        aggregation: Agregación de Fase I (ya resuelta, no ``None``).
        phase2_aggregation: Agregación de Fase II (ya resuelta, no ``None``).
        seed: Semilla raíz.
        spawn_key: Hueco fijo de esta calibración (``seeds.py``).
        mapper: Reparto de las réplicas.

    Returns:
        La ronda.

    Raises:
        InvalidInputError: Filas finitas cuya suma desborda (``rrcov`` las descartaría).
        EstimationError: ``MRCD_FIT_FAILED``, ``T2MRCD_CLEAN_CRITERION_INVALID``,
            ``T2MRCD_NO_CLEAN_OBSERVATIONS`` o un fallo del bootstrap.
    """
    estimator = MRCDEstimator(params.mrcd)
    fit = estimator.fit(x)
    if not bool(fit.ok.all()):
        # Filas finitas cuya suma desborda: rrcov las descarta (CovMrcd.R:19-20); T²MRCD exige
        # puntuar todas las observaciones históricas, así que las rechaza.
        bad = rows[~fit.ok]
        raise InvalidInputError(
            "'x' tiene filas cuya suma desborda a infinito",
            details={"input": "x", "rows": [int(i) for i in bad[:MAX_REPORTED_ROWS]]},
        )
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
        estimator=estimator,
        sampler=bootstrap_oob_sampler,
        n_replicates=boot.n_replicates,
        seed=seed,
        spawn_key=spawn_key,
        alpha=boot.alpha_limit,
        phase2_alpha=boot.phase2_alpha_limit,
        aggregation=aggregation,
        phase2_aggregation=phase2_aggregation,
        mapper=mapper,
    )
    return Phase1Stage(fit=fit, clean=clean.copy(), limits=limits)
