"""Carta T²MRCD: Fase I (MRCD + límite bootstrap) y Fase II (T² y señales con el mismo límite).

Estimador declarado: MRCD, siempre (ADR 0002, ADR 0004 punto 5). Sin *fallbacks*: si MRCD o una
réplica fallan, la Fase I termina en ``failed`` con su código. P2 (filas limpias = ``best`` de
MRCD con ``alpha = 0.75``), P4 (``alpha = 0.005`` y promedio de los percentiles por réplica) y P6
(cita del artículo, en proceso de publicación) están decididos (dueño, 2026-10-07). Se conserva el
mecanismo de decisiones pendientes: si se pasa ``bootstrap.aggregation = None``, ``fit_phase1``
lanza ``MethodDecisionPendingError`` (``T2MRCD_DECISION_PENDING``) **antes** de ajustar nada.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

from voracious.domain.charts.t2mrcd.bootstrap import calibrate_limits
from voracious.domain.charts.t2mrcd.model import T2MRCDModel, T2MRCDMonitoring
from voracious.domain.charts.t2mrcd.params import T2MRCDParams
from voracious.domain.charts.t2mrcd.statistic import t2
from voracious.domain.common import (
    ControlChart,
    EstimationError,
    FloatMatrix,
    InvalidInputError,
    MethodDecisionPendingError,
    TaskMapper,
    as_matrix,
)
from voracious.domain.estimators.mrcd import PYMRCD_VERSION, fit_mrcd

__all__ = [
    "CHART_ID",
    "STATISTIC_REFERENCE",
    "T2MRCD_CLEAN_CRITERION_INVALID",
    "T2MRCD_DECISION_PENDING",
    "T2MRCD_NO_CLEAN_OBSERVATIONS",
    "T2MRCDChart",
]

CHART_ID = "t2mrcd"
"""Identificador de la carta (ruta ``/v1/charts/t2mrcd``)."""

STATISTIC_REFERENCE = "Artículo T²MRCD del dueño (en proceso de publicación)"
"""Cita de la estadística T² (P6, decisión del dueño 2026-10-07); se sustituye al publicarse."""

T2MRCD_DECISION_PENDING = "T2MRCD_DECISION_PENDING"
"""Código de error: hay decisiones estadísticas pendientes (``details["pending"]``)."""

T2MRCD_CLEAN_CRITERION_INVALID = "T2MRCD_CLEAN_CRITERION_INVALID"
"""Código de error: el criterio de fila limpia no devolvió una máscara booleana de longitud n."""

T2MRCD_NO_CLEAN_OBSERVATIONS = "T2MRCD_NO_CLEAN_OBSERVATIONS"
"""Código de error: el criterio no dejó ninguna observación limpia que remuestrear."""

_MAX_REPORTED_ROWS = 20
"""Máximo de índices de fila que se informan en ``details`` (no es un parámetro estadístico)."""


def _validated(x: npt.ArrayLike, *, name: str, n_features: int | None = None) -> FloatMatrix:
    """Convierte y valida una entrada de la carta: matriz no vacía, finita y con ``p`` columnas.

    Args:
        x: Entrada.
        name: Nombre para los mensajes.
        n_features: ``p`` exigido, o ``None`` si no se exige.

    Returns:
        La matriz validada.

    Raises:
        InvalidInputError: Si no cumple el contrato.
    """
    arr = as_matrix(x, name=name)
    n, p = arr.shape
    if n == 0 or p == 0:
        raise InvalidInputError(
            f"'{name}' no puede estar vacía", details={"input": name, "shape": [n, p]}
        )
    if n_features is not None and p != n_features:
        raise InvalidInputError(
            f"'{name}' tiene {p} variables y el modelo {n_features}",
            details={"input": name, "expected_features": n_features, "got_features": p},
        )
    bad_rows = np.flatnonzero(~np.isfinite(arr).all(axis=1))
    if bad_rows.size:
        raise InvalidInputError(
            f"'{name}' contiene valores no finitos (NaN o infinito)",
            details={
                "input": name,
                "non_finite_rows": int(bad_rows.size),
                "rows": [int(i) for i in bad_rows[:_MAX_REPORTED_ROWS]],
            },
        )
    return arr


@dataclass(frozen=True)
class T2MRCDChart:
    """Carta T²MRCD (``ControlChart[T2MRCDParams, T2MRCDModel, T2MRCDMonitoring]``).

    Attributes:
        statistic_reference: Cita del artículo que define la estadística T² de la carta (P6).
            Por defecto ``STATISTIC_REFERENCE`` (artículo en proceso de publicación); se
            actualiza con la cita final cuando se publique.
    """

    statistic_reference: str = STATISTIC_REFERENCE

    @property
    def chart_id(self) -> str:
        """Identificador de la carta: ``"t2mrcd"``."""
        return CHART_ID

    def pending_decisions(self, params: T2MRCDParams) -> list[str]:
        """Elementos estadísticos sin decidir, en orden estable.

        Args:
            params: Parámetros de la carta.

        Returns:
            Nombres de los campos pendientes (vacío si no falta nada).
        """
        return params.bootstrap.pending_fields()

    def fit_phase1(
        self, x: FloatMatrix, params: T2MRCDParams, *, mapper: TaskMapper
    ) -> T2MRCDModel:
        """Fase I: valida, comprueba pendientes, ajusta MRCD, elige filas limpias y calibra.

        Args:
            x: Histórico ``n x p``, finito.
            params: Parámetros de la carta.
            mapper: Reparto de las réplicas bootstrap.

        Returns:
            El modelo de Fase I.

        Raises:
            InvalidInputError: Entrada vacía, no finita o cuya suma por fila desborda.
            MethodDecisionPendingError: ``T2MRCD_DECISION_PENDING`` (antes de ajustar).
            EstimationError: ``MRCD_FIT_FAILED``, ``BOOTSTRAP_REPLICATE_FAILED`` u otro fallo.
        """
        arr = _validated(x, name="x")
        boot = params.bootstrap
        aggregation = boot.aggregation
        if aggregation is None:
            raise MethodDecisionPendingError(
                T2MRCD_DECISION_PENDING,
                "T²MRCD tiene decisiones estadísticas pendientes (docs/metodos/t2mrcd.md)",
                self.pending_decisions(params),
            )
        fit = fit_mrcd(arr, params.mrcd)
        if not bool(fit.ok.all()):
            # Filas finitas cuya suma desborda: rrcov las descarta (CovMrcd.R:19-20); T²MRCD exige
            # puntuar todas las observaciones históricas, así que las rechaza.
            rows = np.flatnonzero(~fit.ok)
            raise InvalidInputError(
                "'x' tiene filas cuya suma desborda a infinito",
                details={"input": "x", "rows": [int(i) for i in rows[:_MAX_REPORTED_ROWS]]},
            )
        clean = np.asarray(boot.clean_criterion(fit, arr))
        if clean.dtype != np.bool_ or clean.shape != (arr.shape[0],):
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
            arr[clean],
            mrcd=params.mrcd,
            n_replicates=boot.n_replicates,
            seed=boot.seed,
            alpha=boot.alpha_limit,
            aggregation=aggregation,
            mapper=mapper,
        )
        historical_t2 = t2(fit, arr)
        return T2MRCDModel(
            params=params,
            mrcd=fit,
            n_features=int(arr.shape[1]),
            clean_mask=clean.copy(),
            limits=limits,
            historical_t2=historical_t2,
            historical_outlier=historical_t2 > limits.limit,
            pymrcd_version=PYMRCD_VERSION,
            seed=boot.seed,
            statistic_reference=self.statistic_reference,
        )

    def validate_phase2_input(self, model: T2MRCDModel, x_new: FloatMatrix) -> None:
        """Valida las observaciones de Fase II (no vacías, finitas y con ``p`` del modelo).

        Args:
            model: Modelo de Fase I.
            x_new: Observaciones nuevas.

        Raises:
            InvalidInputError: Si no son compatibles con el modelo.
        """
        _validated(x_new, name="x_new", n_features=model.n_features)

    def score_phase2(self, model: T2MRCDModel, x_new: FloatMatrix) -> T2MRCDMonitoring:
        """Fase II: T² de cada observación y señal si supera el límite de Fase I (estricto).

        Args:
            model: Modelo de Fase I.
            x_new: Observaciones nuevas ``m x p``.

        Returns:
            T², señales y el límite usado.

        Raises:
            InvalidInputError: Si no son compatibles con el modelo.
        """
        arr = _validated(x_new, name="x_new", n_features=model.n_features)
        values = t2(model.mrcd, arr)
        limit = model.limits.limit
        return T2MRCDMonitoring(t2=values, signal=values > limit, limit=limit)


if TYPE_CHECKING:
    # mypy verifica que la carta cumple el contrato común (ADR 0004, punto 8).
    _conforms: ControlChart[T2MRCDParams, T2MRCDModel, T2MRCDMonitoring] = T2MRCDChart()
