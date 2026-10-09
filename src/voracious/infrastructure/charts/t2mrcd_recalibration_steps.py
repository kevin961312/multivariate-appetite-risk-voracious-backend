"""Adaptador ``RecalibrationSteps`` de T²MRCD: traduce datos a las piezas de la recalibración.

Sin lógica estadística: decodifica parámetros con el codec de la carta (M1) y llama a
``compare``, ``decide`` y ``assemble_model`` de la carta, y construye el informe con los mismos
campos que ``T2MRCDChart.recalibrate`` (``tests/integration/test_recalibration_chain.py``
comprueba la equivalencia en bits).
"""

import dataclasses
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import numpy as np

from voracious.application.phase1_steps import Calibration
from voracious.application.recalibration_steps import RecalibrationSteps
from voracious.domain.charts.t2mrcd import (
    BootstrapLimits,
    ComparisonResult,
    LimitRegime,
    LimitsSnapshot,
    T2MRCDChart,
    T2MRCDModel,
    T2MRCDRecalibrationParams,
    T2MRCDRecalibrationReport,
    decide,
    decode_comparison,
    encode_comparison,
)
from voracious.domain.common import (
    FloatMatrix,
    RecalibrationDecision,
    RowDisposition,
    TaskMapper,
)
from voracious.domain.estimators.mrcd import MRCDFit

__all__ = ["T2MRCDRecalibrationSteps"]


def _model(value: object) -> T2MRCDModel:
    """El modelo opaco como ``T2MRCDModel``.

    Args:
        value: Modelo.

    Returns:
        El modelo.

    Raises:
        TypeError: Si no es un ``T2MRCDModel`` (error de integración).
    """
    if not isinstance(value, T2MRCDModel):
        msg = f"se esperaba T2MRCDModel, no {type(value).__name__}"
        raise TypeError(msg)
    return value


def _comparison(value: object) -> ComparisonResult:
    """La comparación opaca como ``ComparisonResult``.

    Args:
        value: Comparación.

    Returns:
        La comparación.

    Raises:
        TypeError: Si no es un ``ComparisonResult`` (error de integración).
    """
    if not isinstance(value, ComparisonResult):
        msg = f"se esperaba ComparisonResult, no {type(value).__name__}"
        raise TypeError(msg)
    return value


def _fit(value: object) -> MRCDFit:
    """El ajuste opaco como ``MRCDFit``.

    Args:
        value: Ajuste.

    Returns:
        El ajuste.

    Raises:
        TypeError: Si no es un ``MRCDFit`` (error de integración).
    """
    if not isinstance(value, MRCDFit):
        msg = f"se esperaba MRCDFit, no {type(value).__name__}"
        raise TypeError(msg)
    return value


def _limits(value: object) -> BootstrapLimits:
    """Los límites opacos como ``BootstrapLimits``.

    Args:
        value: Límites.

    Returns:
        Los límites.

    Raises:
        TypeError: Si no son ``BootstrapLimits`` (error de integración).
    """
    if not isinstance(value, BootstrapLimits):
        msg = f"se esperaba BootstrapLimits, no {type(value).__name__}"
        raise TypeError(msg)
    return value


class T2MRCDRecalibrationSteps:
    """Pasos de la recalibración de T²MRCD sobre una instancia de la carta.

    Attributes:
        chart: Carta (con su registro de estrategias y sus hilos de ``pymrcd``).
    """

    def __init__(self, chart: T2MRCDChart) -> None:
        """Construye el adaptador.

        Args:
            chart: Carta.
        """
        self.chart = chart

    @property
    def chart_id(self) -> str:
        """Identificador de la carta."""
        return self.chart.chart_id

    def _recalibration(self, data: Mapping[str, object]) -> T2MRCDRecalibrationParams:
        """Decodifica los parámetros de la recalibración.

        Args:
            data: Parámetros codificados.

        Returns:
            Los parámetros.
        """
        return self.chart.decode_recalibration_params(data)

    def inherited_params(
        self, active_model: object, recalibration_params: Mapping[str, object]
    ) -> dict[str, object]:
        """Parámetros del modelo vigente con la semilla de la recalibración (Q8), codificados.

        Es la misma sustitución que ``T2MRCDChart.recalibrate`` (B, niveles, agregaciones y
        MRCD heredados; solo la semilla es propia).

        Args:
            active_model: Modelo vigente.
            recalibration_params: Parámetros de la recalibración.

        Returns:
            Los parámetros de la carta codificados.
        """
        model = _model(active_model)
        seed = self._recalibration(recalibration_params).seed
        inherited = dataclasses.replace(
            model.params,
            bootstrap=dataclasses.replace(model.params.bootstrap, seed=seed),
        )
        return self.chart.encode_params(inherited)

    def min_observations(self, recalibration_params: Mapping[str, object]) -> int:
        """``min_observations`` de la recalibración.

        Args:
            recalibration_params: Parámetros de la recalibración.

        Returns:
            El mínimo de filas nuevas conservadas.
        """
        return self._recalibration(recalibration_params).min_observations

    def compare(
        self,
        active_model: object,
        base: FloatMatrix,
        new_kept: FloatMatrix,
        fit: object,
        recalibration_params: Mapping[str, object],
        *,
        mapper: TaskMapper,
    ) -> ComparisonResult:
        """``T2MRCDChart.compare`` con los parámetros decodificados.

        Args:
            active_model: Modelo vigente.
            base: Base vigente.
            new_kept: Filas nuevas conservadas.
            fit: Ajuste de esas filas.
            recalibration_params: Parámetros de la recalibración.
            mapper: Reparto de los remuestreos.

        Returns:
            La comparación.
        """
        return self.chart.compare(
            _model(active_model),
            base,
            new_kept,
            _fit(fit),
            self._recalibration(recalibration_params),
            mapper,
        )

    def decide(
        self,
        comparison: object | None,
        *,
        n_kept: int,
        recalibration_params: Mapping[str, object],
        force_replace: bool,
    ) -> RecalibrationDecision:
        """``revalidation.decide`` (la misma función que usa ``recalibrate``).

        Args:
            comparison: Comparación o ``None``.
            n_kept: Filas nuevas conservadas.
            recalibration_params: Parámetros de la recalibración.
            force_replace: Reemplazo forzado.

        Returns:
            La decisión.
        """
        return decide(
            None if comparison is None else _comparison(comparison),
            n_kept=n_kept,
            min_observations=self._recalibration(recalibration_params).min_observations,
            force_replace=force_replace,
        )

    def assemble_model(
        self,
        x: FloatMatrix,
        params: Mapping[str, object],
        fit: object,
        calibration: Calibration,
    ) -> T2MRCDModel:
        """Modelo recalibrado: todas las filas en la base, régimen ``PHASE2``.

        Args:
            x: Base nueva.
            params: Parámetros heredados codificados.
            fit: Ajuste de ``x``.
            calibration: Calibración de ``x``.

        Returns:
            El modelo.
        """
        return self.chart.assemble_model(
            x,
            self.chart.decode_params(params),
            _fit(fit),
            calibration.clean,
            _limits(calibration.limits),
            excluded=np.zeros(x.shape[0], dtype=np.bool_),
            regime=LimitRegime.PHASE2,
        )

    def report(
        self,
        active_model: object,
        *,
        decision: RecalibrationDecision,
        forced: bool,
        n_base: int,
        new_dispositions: Sequence[RowDisposition],
        recalibration_params: Mapping[str, object],
        comparison: object | None,
        model: object | None,
    ) -> T2MRCDRecalibrationReport:
        """Informe con los mismos campos que ``T2MRCDChart.recalibrate``.

        Args:
            active_model: Modelo vigente.
            decision: Decisión.
            forced: Reemplazo forzado.
            n_base: Filas de la base vigente.
            new_dispositions: Destino de cada fila nueva.
            recalibration_params: Parámetros de la recalibración.
            comparison: Comparación o ``None``.
            model: Modelo nuevo o ``None``.

        Returns:
            El informe.
        """
        new_model = None if model is None else _model(model)
        dispositions = tuple(new_dispositions)
        return T2MRCDRecalibrationReport(
            decision=decision,
            forced=forced,
            row_disposition=(RowDisposition.ALREADY_IN_BASE,) * n_base + dispositions,
            n_base=n_base,
            n_new=len(dispositions),
            n_excluded_assignable_cause=dispositions.count(
                RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE
            ),
            n_kept_new=dispositions.count(RowDisposition.KEPT),
            min_observations=self._recalibration(recalibration_params).min_observations,
            comparison=None if comparison is None else _comparison(comparison),
            before=LimitsSnapshot.of(_model(active_model)),
            after=None if new_model is None else LimitsSnapshot.of(new_model),
            phase2_exceeds_phase1=None
            if new_model is None
            else new_model.limits.phase2_exceeds_phase1,
        )

    def encode_comparison(self, comparison: object) -> dict[str, object]:
        """Codifica la comparación (exacta en bits).

        Args:
            comparison: Comparación.

        Returns:
            Diccionario.
        """
        return encode_comparison(_comparison(comparison))

    def decode_comparison(self, data: Mapping[str, object]) -> ComparisonResult:
        """Decodifica la comparación.

        Args:
            data: Comparación codificada.

        Returns:
            La comparación.
        """
        return decode_comparison(data)


if TYPE_CHECKING:
    # mypy verifica que el adaptador cumple el puerto de la aplicación.
    _conforms: RecalibrationSteps = T2MRCDRecalibrationSteps(T2MRCDChart())
