"""Modelo de Fase I y resultado de Fase II de la carta T²MRCD."""

from dataclasses import dataclass
from enum import StrEnum

from voracious.domain.charts.t2mrcd.bootstrap import BootstrapLimits
from voracious.domain.charts.t2mrcd.params import T2MRCDParams
from voracious.domain.common import BoolVector, FloatVector, RowDisposition
from voracious.domain.estimators.mrcd import MRCDFit

__all__ = ["LimitRegime", "T2MRCDModel", "T2MRCDMonitoring"]


class LimitRegime(StrEnum):
    """Qué límite vigila la Fase II de una versión del modelo (decisión del dueño, Q2)."""

    PHASE1_PROVISIONAL = "phase1_provisional"
    """Versión inicial: se vigila con ``phase1_limit`` de forma provisional."""

    PHASE2 = "phase2"
    """Versión recalibrada: se vigila con ``phase2_limit``."""


@dataclass(frozen=True, eq=False)
class T2MRCDModel:
    """Modelo de Fase I: ajuste MRCD de la base y límites bootstrap.

    Attributes:
        params: Parámetros con los que se ajustó. En una versión recalibrada son los heredados
            del modelo vigente (incluido ``max_depuration_rounds``) con la semilla de la
            recalibración; ver ``final_depuration_skipped``.
        mrcd: Ajuste MRCD de la base (las filas conservadas de la entrada).
        n_features: Número de variables ``p``.
        base_mask: Filas de la entrada que forman la base (conservadas tras la exclusión humana y
            la depuración automática).
        row_disposition: Destino de cada fila de la entrada.
        clean_mask: Filas limpias de la entrada (las que se remuestrean; subconjunto de la base).
        limits: Límites bootstrap de Fase I y de Fase II.
        limit_regime: Qué límite vigila la Fase II de esta versión.
        historical_t2: T² de cada fila de la entrada con el ajuste final.
        historical_outlier: ``historical_t2 > limits.phase1_limit`` (estricto).
        depuration_rounds: Rondas de depuración automática que quitaron filas (0 si no se
            depuró).
        depuration_converged: ``True`` si en el ajuste final ninguna fila de la base supera el
            límite de Fase I; ``False`` si se agotaron las rondas; ``None`` si no se intentó
            depurar (``final_depuration_skipped``).
        final_depuration_skipped: ``True`` en las versiones recalibradas: la Fase I final no
            vuelve a depurar la nueva base (la base vigente ya estaba depurada y las filas
            nuevas se depuraron antes de comparar); ``False`` en la versión inicial.
        pymrcd_version: Versión de ``pymrcd`` del ajuste.
        seed: Semilla raíz del bootstrap.
        statistic_reference: Cita de la estadística T² con la que se ajustó.
    """

    params: T2MRCDParams
    mrcd: MRCDFit
    n_features: int
    base_mask: BoolVector
    row_disposition: tuple[RowDisposition, ...]
    clean_mask: BoolVector
    limits: BootstrapLimits
    limit_regime: LimitRegime
    historical_t2: FloatVector
    historical_outlier: BoolVector
    depuration_rounds: int
    depuration_converged: bool | None
    final_depuration_skipped: bool
    pymrcd_version: str
    seed: int
    statistic_reference: str

    @property
    def operative_limit(self) -> float:
        """Límite con el que se vigila la Fase II según ``limit_regime``."""
        if self.limit_regime is LimitRegime.PHASE2:
            return self.limits.phase2_limit
        return self.limits.phase1_limit

    @property
    def n_base(self) -> int:
        """Número de filas de la base."""
        return int(self.base_mask.sum())


@dataclass(frozen=True, eq=False)
class T2MRCDMonitoring:
    """Resultado de Fase II.

    Attributes:
        t2: T² de cada observación nueva.
        signal: ``t2 > limit`` (estricto; decisión P5).
        limit: Límite operativo del modelo (``operative_limit``; no se recalcula).
        limit_kind: Régimen del límite usado.
    """

    t2: FloatVector
    signal: BoolVector
    limit: float
    limit_kind: LimitRegime
