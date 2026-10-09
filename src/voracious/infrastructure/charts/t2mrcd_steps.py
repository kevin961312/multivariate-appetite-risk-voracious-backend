"""Adaptador ``Phase1Steps`` de T²MRCD: traduce datos codificados a las piezas públicas de la carta.

Sin lógica estadística: decodifica parámetros con el codec de la carta (M1) y llama a
``fit_estimator``, ``calibrate`` y ``assemble_model``. Los pasos encadenados así dan el mismo
modelo, en bits, que ``fit_phase1`` (``tests/integration/test_phase1_chain.py``).
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

import numpy as np

from voracious.application.phase1_steps import Calibration, Phase1Steps
from voracious.domain.charts.t2mrcd import (
    T2MRCD_DECISION_PENDING,
    BootstrapLimits,
    LimitRegime,
    T2MRCDChart,
    T2MRCDParams,
    decode_limits,
    decode_mrcd_params,
    encode_limits,
    encode_mrcd_params,
)
from voracious.domain.common import (
    BoolVector,
    DomainError,
    FloatMatrix,
    MethodDecisionPendingError,
    StageKind,
    TaskMapper,
)
from voracious.domain.estimators.mrcd import (
    IndexVector,
    MRCDFit,
    MRCDParams,
    decode_fit,
    encode_fit,
)

__all__ = ["T2MRCD_FIT_PARAMS_MISMATCH", "T2MRCDPhase1Steps"]

T2MRCD_FIT_PARAMS_MISMATCH: Final = "T2MRCD_FIT_PARAMS_MISMATCH"
"""Código de error: el ajuste se hizo con parámetros de MRCD distintos de los de la carta."""


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


def _rows(n: int) -> IndexVector:
    """Índices ``0..n-1`` de las filas de un dataset.

    Args:
        n: Filas.

    Returns:
        Los índices ``int64``.
    """
    return np.arange(n, dtype=np.int64)


class T2MRCDPhase1Steps:
    """Pasos de la Fase I de T²MRCD sobre una instancia de la carta.

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

    def _params(self, params: Mapping[str, object]) -> T2MRCDParams:
        """Decodifica los parámetros de la carta.

        Args:
            params: Parámetros codificados.

        Returns:
            Los parámetros.
        """
        return self.chart.decode_params(params)

    def validate_input(self, x: FloatMatrix) -> None:
        """Valida un dataset de Fase I (``validate_phase1_input``).

        Args:
            x: Matriz ``n x p``.
        """
        self.chart.validate_phase1_input(x)

    def encode_fit_params(self, fit_params: object) -> dict[str, object]:
        """Codifica los parámetros de MRCD; ``None`` usa los de la carta (``alpha`` 0.75, P2).

        Args:
            fit_params: ``MRCDParams`` o ``None``.

        Returns:
            Diccionario de MRCD.

        Raises:
            TypeError: Si no es ``MRCDParams`` ni ``None`` (error de integración).
        """
        if fit_params is None:
            return encode_mrcd_params(decode_mrcd_params({}))
        if not isinstance(fit_params, MRCDParams):
            msg = f"se esperaba MRCDParams, no {type(fit_params).__name__}"
            raise TypeError(msg)
        return encode_mrcd_params(fit_params)

    def encode_params(self, params: object) -> dict[str, object]:
        """Codifica los parámetros de la carta.

        Args:
            params: ``T2MRCDParams``.

        Returns:
            Diccionario serializable.

        Raises:
            TypeError: Si no es ``T2MRCDParams`` (error de integración).
        """
        if not isinstance(params, T2MRCDParams):
            msg = f"se esperaba T2MRCDParams, no {type(params).__name__}"
            raise TypeError(msg)
        return self.chart.encode_params(params)

    def fit_params_of(self, params: Mapping[str, object]) -> dict[str, object]:
        """Parámetros de MRCD de la carta (codificados).

        Args:
            params: Parámetros de la carta codificados.

        Returns:
            Diccionario de MRCD.
        """
        return encode_mrcd_params(self._params(params).mrcd)

    def check_params(self, params: Mapping[str, object]) -> None:
        """Decodifica los parámetros y exige que no haya decisiones pendientes.

        Args:
            params: Parámetros codificados.

        Raises:
            MethodDecisionPendingError: ``T2MRCD_DECISION_PENDING``.
        """
        pending = self.chart.pending_decisions(self._params(params))
        if pending:
            raise MethodDecisionPendingError(
                T2MRCD_DECISION_PENDING,
                "T²MRCD tiene decisiones estadísticas pendientes (docs/metodos/t2mrcd.md)",
                pending,
            )

    def check_fit_params(
        self, fit_params: Mapping[str, object], params: Mapping[str, object]
    ) -> None:
        """Exige que el ajuste se hiciera con los parámetros de MRCD de la carta.

        Args:
            fit_params: Parámetros de MRCD del ajuste.
            params: Parámetros de la carta.

        Raises:
            DomainError: ``T2MRCD_FIT_PARAMS_MISMATCH`` si no coinciden.
        """
        fitted = encode_mrcd_params(decode_mrcd_params(fit_params))
        expected = self.fit_params_of(params)
        if fitted != expected:
            raise DomainError(
                T2MRCD_FIT_PARAMS_MISMATCH,
                "el ajuste se hizo con parámetros de MRCD distintos de los de la carta",
                {"fit_mrcd": fitted, "chart_mrcd": expected},
            )

    def seed(self, params: Mapping[str, object]) -> int:
        """Semilla raíz del bootstrap.

        Args:
            params: Parámetros codificados.

        Returns:
            La semilla.
        """
        return self._params(params).bootstrap.seed

    def stage_spawn_key(self, kind: StageKind) -> tuple[int, ...]:
        """Hueco de semilla de la calibración (``T2MRCDChart.stage_spawn_key``).

        Args:
            kind: Operación.

        Returns:
            La clave.
        """
        return self.chart.stage_spawn_key(kind)

    def fit(self, x: FloatMatrix, fit_params: Mapping[str, object]) -> MRCDFit:
        """Ajuste MRCD del dataset (``fit_estimator``).

        Args:
            x: Dataset.
            fit_params: Parámetros de MRCD codificados.

        Returns:
            El ajuste.
        """
        return self.chart.fit_estimator(x, _rows(x.shape[0]), decode_mrcd_params(fit_params))

    def calibrate(
        self,
        x: FloatMatrix,
        fit: object,
        params: Mapping[str, object],
        *,
        kind: StageKind,
        mapper: TaskMapper,
    ) -> Calibration:
        """Filas limpias y límites bootstrap del ajuste (``calibrate``).

        Args:
            x: Dataset del ajuste.
            fit: Ajuste.
            params: Parámetros codificados.
            kind: Operación.
            mapper: Reparto de las réplicas.

        Returns:
            La calibración.
        """
        stage = self.chart.calibrate(x, _fit(fit), self._params(params), kind=kind, mapper=mapper)
        return Calibration(limits=stage.limits, clean=stage.clean)

    def assemble_initial_model(
        self,
        root: FloatMatrix,
        params: Mapping[str, object],
        fit: object,
        calibration: Calibration,
        *,
        excluded: BoolVector,
    ) -> object:
        """Modelo de Fase I con régimen ``PHASE1_PROVISIONAL`` (``assemble_model``).

        Args:
            root: Dataset raíz.
            params: Parámetros codificados.
            fit: Ajuste de ``root[~excluded]``.
            calibration: Calibración de ese ajuste.
            excluded: Excluidas por una persona.

        Returns:
            El ``T2MRCDModel``.
        """
        return self.chart.assemble_model(
            root,
            self._params(params),
            _fit(fit),
            calibration.clean,
            _limits(calibration.limits),
            excluded=excluded,
            regime=LimitRegime.PHASE1_PROVISIONAL,
        )

    def encode_fit(self, fit: object) -> dict[str, object]:
        """Codifica el ajuste (``encode_fit``, exacto en bits).

        Args:
            fit: Ajuste.

        Returns:
            Diccionario.
        """
        return encode_fit(_fit(fit))

    def decode_fit(self, data: Mapping[str, object]) -> MRCDFit:
        """Decodifica el ajuste.

        Args:
            data: Ajuste codificado.

        Returns:
            El ajuste.
        """
        return decode_fit(data)

    def encode_limits(self, limits: object) -> dict[str, object]:
        """Codifica los límites (``encode_limits``, exacto en bits).

        Args:
            limits: Límites.

        Returns:
            Diccionario.
        """
        return encode_limits(_limits(limits))

    def decode_limits(self, data: Mapping[str, object]) -> BootstrapLimits:
        """Decodifica los límites.

        Args:
            data: Límites codificados.

        Returns:
            Los límites.
        """
        return decode_limits(data)


if TYPE_CHECKING:
    # mypy verifica que el adaptador cumple el puerto de la aplicación.
    _conforms: Phase1Steps = T2MRCDPhase1Steps(T2MRCDChart())
