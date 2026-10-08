"""Adaptador ``Phase1Steps`` de T²MRCD: traduce datos codificados a las piezas públicas de la carta.

Sin lógica estadística: decodifica parámetros con el codec de la carta (M1), reconstruye la ronda
(``Phase1Stage``) a partir del ajuste y la calibración guardados y llama a ``fit_estimator``,
``calibrate``, ``depurate_step`` y ``assemble_model``. Los pasos encadenados así dan el mismo
modelo, en bits, que ``fit_phase1`` (``tests/integration/test_phase1_chain.py``).
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

import numpy as np

from voracious.application.phase1_steps import Calibration, DepurationOutcome, Phase1Steps
from voracious.domain.charts.t2mrcd import (
    T2MRCD_DECISION_PENDING,
    BootstrapLimits,
    LimitRegime,
    Phase1Stage,
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
    StageLineage,
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

    def stage_spawn_key(self, lineage: StageLineage) -> tuple[int, ...]:
        """Hueco de semilla de la ronda (``T2MRCDChart.stage_spawn_key``).

        Args:
            lineage: Linaje.

        Returns:
            La clave.
        """
        return self.chart.stage_spawn_key(lineage)

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
        lineage: StageLineage,
        mapper: TaskMapper,
    ) -> Calibration:
        """Filas limpias y límites bootstrap de la ronda (``calibrate``).

        Args:
            x: Dataset del ajuste.
            fit: Ajuste.
            params: Parámetros codificados.
            lineage: Linaje.
            mapper: Reparto de las réplicas.

        Returns:
            La calibración.
        """
        stage = self.chart.calibrate(
            x, _fit(fit), self._params(params), lineage=lineage, mapper=mapper
        )
        return Calibration(limits=stage.limits, clean=stage.clean)

    def depurate(
        self,
        x: FloatMatrix,
        fit: object,
        calibration: Calibration,
        params: Mapping[str, object],
        *,
        round_index: int,
        evaluate_only: bool = False,
        max_rounds: int | None = None,
        min_rows: int = 1,
    ) -> DepurationOutcome:
        """Una ronda de la depuración automática sobre todas las filas del dataset.

        Con ``evaluate_only`` las rondas máximas son las ya hechas: la ronda es final y no quita
        filas (como ``fit_phase1`` al agotar las rondas).

        Args:
            x: Dataset del ajuste.
            fit: Ajuste.
            calibration: Calibración.
            params: Parámetros codificados (``max_depuration_rounds``).
            round_index: Ronda.
            evaluate_only: No quitar filas.
            max_rounds: Rondas máximas; ``None`` usa ``max_depuration_rounds`` de ``params``.
            min_rows: Mínimo de filas para seguir (``min_observations`` al recalibrar).

        Returns:
            El resultado.
        """
        n = x.shape[0]
        stage = Phase1Stage(
            fit=_fit(fit), clean=calibration.clean, limits=_limits(calibration.limits)
        )
        if evaluate_only:
            rounds = round_index
        elif max_rounds is not None:
            rounds = max_rounds
        else:
            rounds = self._params(params).max_depuration_rounds
        step = self.chart.depurate_step(
            stage,
            x,
            _rows(n),
            np.ones(n, dtype=np.bool_),
            round_index,
            max_rounds=rounds,
            min_rows=min_rows,
        )
        return DepurationOutcome(
            kept=step.kept,
            excluded_automatic=step.excluded_automatic_now,
            converged=step.converged,
            final=step.final,
            exhausted=step.exhausted,
        )

    def assemble_initial_model(
        self,
        root: FloatMatrix,
        params: Mapping[str, object],
        fit: object,
        calibration: Calibration,
        *,
        kept: BoolVector,
        excluded: BoolVector,
        automatic: BoolVector,
        rounds: int,
        converged: bool,
    ) -> object:
        """Modelo de Fase I con régimen ``PHASE1_PROVISIONAL`` (``assemble_model``).

        Args:
            root: Dataset raíz.
            params: Parámetros codificados.
            fit: Ajuste final.
            calibration: Calibración final.
            kept: Filas de la base.
            excluded: Excluidas por una persona.
            automatic: Excluidas por la depuración automática.
            rounds: Rondas que quitaron filas.
            converged: Convergencia.

        Returns:
            El ``T2MRCDModel``.
        """
        return self.chart.assemble_model(
            root,
            self._params(params),
            _fit(fit),
            calibration.clean,
            _limits(calibration.limits),
            kept=kept,
            excluded=excluded,
            automatic=automatic,
            rounds=rounds,
            converged=converged,
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
