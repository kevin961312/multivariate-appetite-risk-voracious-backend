"""Puerto de los pasos encadenables de la Fase I de una carta (vuelta 3.3 del Paso 3).

La Fase I se puede pedir por pasos independientes, cada uno con su recurso y su trabajo:
ajuste del estimador (``/fits``), límites (``/limits``), depuración (``/depurations``) y
ensamblado del modelo (``/models``). Los casos de uso (``use_cases/steps.py``) son comunes a todas
las cartas y solo guardan y pasan **datos** (parámetros codificados) y valores opacos (el ajuste y
los límites de la carta); la carta concreta los interpreta a través de este puerto, cuyo
adaptador vive en ``infrastructure`` (``T2MRCDPhase1Steps``). Así ``application`` no depende de
ninguna carta (ADR 0004, enmienda 2b.2).

Contrato de equivalencia: encadenar ``fit``, ``calibrate``, ``depurate`` y
``assemble_initial_model`` con el linaje que deduce la aplicación da el mismo modelo, en bits,
que ``ControlChart.fit_phase1``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from voracious.application.errors import UnknownChartError
from voracious.domain.common import BoolVector, FloatMatrix, StageLineage, TaskMapper

__all__ = [
    "Calibration",
    "DepurationOutcome",
    "Phase1Steps",
    "Phase1StepsRegistry",
    "resolve_steps",
]


@dataclass(frozen=True, eq=False)
class Calibration:
    """Límites de una ronda y sus filas limpias.

    Attributes:
        limits: Límites de la carta (opacos para la aplicación).
        clean: Filas limpias del ajuste, máscara sobre las filas del dataset.
    """

    limits: object
    clean: BoolVector


@dataclass(frozen=True, eq=False)
class DepurationOutcome:
    """Resultado de evaluar una ronda de la depuración automática sobre su dataset.

    Attributes:
        kept: Filas conservadas (máscara sobre las filas del dataset).
        excluded_automatic: Filas que la ronda quita (máscara sobre las filas del dataset).
        converged: ``True`` si ninguna fila supera el límite.
        final: ``True`` si la depuración termina en esta ronda.
        exhausted: ``True`` si terminó por quedarse sin filas (no hay ronda final).
    """

    kept: BoolVector
    excluded_automatic: BoolVector
    converged: bool
    final: bool
    exhausted: bool


class Phase1Steps(Protocol):
    """Pasos de la Fase I de una carta, con parámetros codificados como datos.

    ``params`` son siempre los parámetros de la carta codificados (``encode_params``);
    ``fit_params``, los del estimador codificados (``encode_fit_params``).
    """

    @property
    def chart_id(self) -> str:
        """Carta a la que pertenecen los pasos."""
        ...

    def validate_input(self, x: FloatMatrix) -> None:
        """Valida de forma síncrona un dataset de Fase I (``validate_phase1_input``).

        Args:
            x: Matriz ``n x p``.

        Raises:
            InvalidInputError: Si la carta no la admite.
        """
        ...

    def encode_fit_params(self, fit_params: object) -> dict[str, object]:
        """Codifica los parámetros del estimador (``object``: cada carta tiene los suyos).

        Args:
            fit_params: Parámetros del estimador, o ``None`` para los de la carta por defecto.

        Returns:
            Diccionario serializable.
        """
        ...

    def encode_params(self, params: object) -> dict[str, object]:
        """Codifica los parámetros de la carta (``object``: la carta comprueba el tipo).

        Args:
            params: Parámetros de la carta.

        Returns:
            Diccionario serializable.

        Raises:
            InvalidInputError: Si no se pueden codificar.
        """
        ...

    def fit_params_of(self, params: Mapping[str, object]) -> dict[str, object]:
        """Parámetros del estimador (codificados) que usa la carta con ``params``.

        Args:
            params: Parámetros de la carta codificados.

        Returns:
            Los del estimador, codificados como ``encode_fit_params``.
        """
        ...

    def check_params(self, params: Mapping[str, object]) -> None:
        """Valida los parámetros codificados y que no haya decisiones pendientes.

        Args:
            params: Parámetros codificados.

        Raises:
            InvalidInputError: Si no son válidos.
            MethodDecisionPendingError: Si hay decisiones estadísticas pendientes.
        """
        ...

    def check_fit_params(
        self, fit_params: Mapping[str, object], params: Mapping[str, object]
    ) -> None:
        """Exige que el ajuste se hiciera con los parámetros del estimador que usará la carta.

        Args:
            fit_params: Parámetros del ajuste.
            params: Parámetros de la carta.

        Raises:
            DomainError: Con el código de la carta si no coinciden.
        """
        ...

    def seed(self, params: Mapping[str, object]) -> int:
        """Semilla raíz de los parámetros.

        Args:
            params: Parámetros codificados.

        Returns:
            La semilla.
        """
        ...

    def stage_spawn_key(self, lineage: StageLineage) -> tuple[int, ...]:
        """Hueco de semilla de una ronda.

        Args:
            lineage: Operación y ronda.

        Returns:
            La clave bajo la semilla raíz.
        """
        ...

    def fit(self, x: FloatMatrix, fit_params: Mapping[str, object]) -> object:
        """Ajusta el estimador de la carta sobre un dataset.

        Args:
            x: Dataset ``n x p``.
            fit_params: Parámetros del estimador codificados.

        Returns:
            El ajuste (opaco).

        Raises:
            DomainError: Entrada inválida o fallo de estimación.
        """
        ...

    def calibrate(
        self,
        x: FloatMatrix,
        fit: object,
        params: Mapping[str, object],
        *,
        lineage: StageLineage,
        mapper: TaskMapper,
    ) -> Calibration:
        """Filas limpias y límites de una ronda ya ajustada.

        Args:
            x: Dataset del ajuste.
            fit: Ajuste.
            params: Parámetros de la carta codificados.
            lineage: Linaje de la ronda (elige el hueco de semilla).
            mapper: Reparto de las réplicas.

        Returns:
            La calibración.

        Raises:
            DomainError: Decisión pendiente o fallo de la calibración.
        """
        ...

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
        """Evalúa una ronda de la depuración automática (sin ajustar nada).

        Args:
            x: Dataset del ajuste.
            fit: Ajuste de la ronda.
            calibration: Calibración de la ronda.
            params: Parámetros de la carta codificados (rondas máximas).
            round_index: Número de ronda.
            evaluate_only: Si ``True``, no quita filas (la ronda es final): modelo sin más
                depuración automática.
            max_rounds: Rondas máximas de exclusión; ``None`` usa las de ``params`` (en una
                recalibración, las de sus parámetros).
            min_rows: Mínimo de filas para seguir (1 en la Fase I; ``min_observations`` al
                recalibrar: por debajo la depuración se agota).

        Returns:
            El resultado.
        """
        ...

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
        """Construye el modelo de Fase I (versión inicial) con la ronda final.

        Args:
            root: Dataset raíz ``n x p``.
            params: Parámetros de la carta codificados.
            fit: Ajuste final (sobre ``root[kept]``).
            calibration: Calibración final.
            kept: Filas de la base (máscara sobre ``root``).
            excluded: Filas excluidas por una persona.
            automatic: Filas excluidas por la depuración automática.
            rounds: Rondas de depuración que quitaron filas.
            converged: Convergencia de la depuración.

        Returns:
            El modelo de la carta.
        """
        ...

    def encode_fit(self, fit: object) -> dict[str, object]:
        """Codifica un ajuste como datos (ida y vuelta exacta en bits).

        Args:
            fit: Ajuste.

        Returns:
            Diccionario serializable.
        """
        ...

    def decode_fit(self, data: Mapping[str, object]) -> object:
        """Decodifica un ajuste.

        Args:
            data: Ajuste codificado.

        Returns:
            El ajuste.
        """
        ...

    def encode_limits(self, limits: object) -> dict[str, object]:
        """Codifica unos límites como datos (ida y vuelta exacta en bits).

        Args:
            limits: Límites.

        Returns:
            Diccionario serializable.
        """
        ...

    def decode_limits(self, data: Mapping[str, object]) -> object:
        """Decodifica unos límites.

        Args:
            data: Límites codificados.

        Returns:
            Los límites.
        """
        ...


Phase1StepsRegistry = Mapping[str, Phase1Steps]
"""Pasos de la Fase I por ``chart_id`` (solo las cartas que los exponen)."""


def resolve_steps(registry: Phase1StepsRegistry, chart_id: str) -> Phase1Steps:
    """Pasos de la Fase I de una carta.

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
