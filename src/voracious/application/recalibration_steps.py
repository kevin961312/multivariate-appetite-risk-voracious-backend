"""Puerto de los pasos encadenables de la recalibración de una carta (vuelta 3.4 del Paso 3).

La recalibración se puede pedir paso a paso, encadenando por id los pasos de la Fase I (ajuste,
límites y depuración de las filas nuevas) con dos pasos propios: la **comparación** de la base
vigente con las filas nuevas depuradas (``/comparisons``) y la **propuesta** de versión
(``/versions``). Los casos de uso son comunes a todas las cartas y solo pasan datos (parámetros
codificados) y valores opacos (ajuste, límites, comparación, modelo e informe); la carta concreta
los interpreta a través de este puerto, cuyo adaptador vive en ``infrastructure``
(``T2MRCDRecalibrationSteps``).

Contrato de equivalencia: encadenar los pasos con el linaje que deduce la aplicación (``NEW_ROWS``
para las filas nuevas, ``EXTENSION`` para la base ampliada) da el mismo modelo e informe, en bits,
que ``ControlChart.recalibrate``.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol

from voracious.application.errors import UnknownChartError
from voracious.application.phase1_steps import Calibration
from voracious.domain.common import (
    FloatMatrix,
    RecalibrationDecision,
    RowDisposition,
    TaskMapper,
)

__all__ = ["RecalibrationSteps", "RecalibrationStepsRegistry", "resolve_recalibration_steps"]


class RecalibrationSteps(Protocol):
    """Pasos propios de la recalibración de una carta.

    ``recalibration_params`` son siempre los parámetros de la recalibración codificados
    (``ControlChart.encode_recalibration_params``); ``params``, los de la carta codificados.
    """

    @property
    def chart_id(self) -> str:
        """Carta a la que pertenecen los pasos."""
        ...

    def inherited_params(
        self, active_model: object, recalibration_params: Mapping[str, object]
    ) -> dict[str, object]:
        """Parámetros de la carta heredados del modelo vigente con la semilla de la recalibración.

        Args:
            active_model: Modelo de la versión base.
            recalibration_params: Parámetros de la recalibración.

        Returns:
            Los parámetros de la carta codificados.

        Raises:
            InvalidInputError: Si los parámetros no son válidos.
        """
        ...

    def depuration_bounds(self, recalibration_params: Mapping[str, object]) -> tuple[int, int]:
        """Rondas máximas y mínimo de filas de la depuración de las filas nuevas.

        Args:
            recalibration_params: Parámetros de la recalibración.

        Returns:
            ``(max_rounds, min_rows)``.
        """
        ...

    def compare(
        self,
        active_model: object,
        base: FloatMatrix,
        new_kept: FloatMatrix,
        fit: object,
        recalibration_params: Mapping[str, object],
        *,
        mapper: TaskMapper,
    ) -> object:
        """Compara la base vigente con las filas nuevas depuradas.

        Args:
            active_model: Modelo de la versión base.
            base: Base de la versión base.
            new_kept: Filas nuevas conservadas (las de la ronda final).
            fit: Ajuste de la ronda final.
            recalibration_params: Parámetros de la recalibración.
            mapper: Reparto de los remuestreos.

        Returns:
            La comparación (opaca).

        Raises:
            DomainError: Entrada inválida o decisiones pendientes.
        """
        ...

    def decide(
        self,
        comparison: object | None,
        *,
        n_kept: int,
        recalibration_params: Mapping[str, object],
        force_replace: bool,
    ) -> RecalibrationDecision:
        """Decisión de la recalibración.

        Args:
            comparison: Comparación, o ``None`` en un reemplazo forzado.
            n_kept: Filas nuevas conservadas.
            recalibration_params: Parámetros de la recalibración.
            force_replace: Reemplazo forzado.

        Returns:
            La decisión.
        """
        ...

    def assemble_model(
        self,
        x: FloatMatrix,
        params: Mapping[str, object],
        fit: object,
        calibration: Calibration,
    ) -> object:
        """Modelo recalibrado sobre su base, sin volver a depurarla.

        Args:
            x: Base de la versión nueva ``n x p``.
            params: Parámetros heredados codificados.
            fit: Ajuste de ``x``.
            calibration: Calibración de ``x``.

        Returns:
            El modelo de la carta.
        """
        ...

    def report(
        self,
        active_model: object,
        *,
        decision: RecalibrationDecision,
        forced: bool,
        n_base: int,
        new_dispositions: Sequence[RowDisposition],
        recalibration_params: Mapping[str, object],
        depuration_rounds: int,
        depuration_converged: bool | None,
        comparison: object | None,
        model: object | None,
    ) -> object:
        """Informe antes/después de la recalibración.

        Args:
            active_model: Modelo de la versión base.
            decision: Decisión.
            forced: Reemplazo forzado.
            n_base: Filas de la base vigente.
            new_dispositions: Destino de cada fila nueva.
            recalibration_params: Parámetros de la recalibración.
            depuration_rounds: Rondas de la depuración de las filas nuevas.
            depuration_converged: Su convergencia (``None`` si no hubo ronda final).
            comparison: Comparación, o ``None``.
            model: Modelo nuevo, o ``None`` (``insufficient``).

        Returns:
            El informe de la carta.
        """
        ...

    def encode_comparison(self, comparison: object) -> dict[str, object]:
        """Codifica una comparación como datos (ida y vuelta exacta en bits).

        Args:
            comparison: Comparación.

        Returns:
            Diccionario serializable.
        """
        ...

    def decode_comparison(self, data: Mapping[str, object]) -> object:
        """Decodifica una comparación.

        Args:
            data: Comparación codificada.

        Returns:
            La comparación.
        """
        ...


RecalibrationStepsRegistry = Mapping[str, RecalibrationSteps]
"""Pasos de la recalibración por ``chart_id`` (solo las cartas que los exponen)."""


def resolve_recalibration_steps(
    registry: RecalibrationStepsRegistry, chart_id: str
) -> RecalibrationSteps:
    """Pasos de la recalibración de una carta.

    Args:
        registry: Registro.
        chart_id: Carta.

    Returns:
        Sus pasos.

    Raises:
        UnknownChartError: Si la carta no expone pasos.
    """
    steps = registry.get(chart_id)
    if steps is None:
        raise UnknownChartError(f"la carta '{chart_id}' no existe", details={"chart_id": chart_id})
    return steps
