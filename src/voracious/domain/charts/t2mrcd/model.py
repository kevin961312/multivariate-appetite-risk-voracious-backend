"""Modelo de Fase I y resultado de Fase II de la carta T²MRCD."""

from dataclasses import dataclass

from voracious.domain.charts.t2mrcd.bootstrap import BootstrapLimits
from voracious.domain.charts.t2mrcd.params import T2MRCDParams
from voracious.domain.common import BoolVector, FloatVector
from voracious.domain.estimators.mrcd import MRCDFit

__all__ = ["T2MRCDModel", "T2MRCDMonitoring"]


@dataclass(frozen=True, eq=False)
class T2MRCDModel:
    """Modelo de Fase I: ajuste MRCD del histórico y límites bootstrap.

    Attributes:
        params: Parámetros con los que se ajustó.
        mrcd: Ajuste MRCD del histórico completo.
        n_features: Número de variables ``p``.
        clean_mask: Filas limpias del histórico (las que se remuestrean).
        limits: Límite bootstrap, el mismo en Fase I y en Fase II.
        historical_t2: T² de cada observación histórica.
        historical_outlier: ``historical_t2 > limits.limit``.
        pymrcd_version: Versión de ``pymrcd`` del ajuste.
        seed: Semilla raíz del bootstrap.
        statistic_reference: Cita de la estadística T² con la que se ajustó.
    """

    params: T2MRCDParams
    mrcd: MRCDFit
    n_features: int
    clean_mask: BoolVector
    limits: BootstrapLimits
    historical_t2: FloatVector
    historical_outlier: BoolVector
    pymrcd_version: str
    seed: int
    statistic_reference: str


@dataclass(frozen=True, eq=False)
class T2MRCDMonitoring:
    """Resultado de Fase II.

    Attributes:
        t2: T² de cada observación nueva.
        signal: ``t2 > limit`` (estricto; decisión P5).
        limit: Límite del modelo (``limits.limit``, el mismo de Fase I; no se recalcula).
    """

    t2: FloatVector
    signal: BoolVector
    limit: float
