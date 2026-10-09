"""Puerto de los pasos encadenables de la Fase I de una carta (vuelta 3.3 del Paso 3).

La Fase I se puede pedir por pasos independientes, cada uno con su recurso y su trabajo:
exclusión humana opcional (``/exclusions``), ajuste del estimador (``/fits``), límites
(``/limits``) y ensamblado del modelo (``/models``). Los casos de uso (``use_cases/steps.py``)
son comunes a todas las cartas y solo guardan y pasan **datos** (parámetros codificados) y
valores opacos (el ajuste y los límites de la carta); la carta concreta los interpreta a través
de este puerto, cuyo adaptador vive en ``infrastructure`` (``T2MRCDPhase1Steps``). Así
``application`` no depende de ninguna carta (ADR 0004, enmienda 2b.2).

Contrato de equivalencia: encadenar ``fit``, ``calibrate`` y ``assemble_initial_model`` con la
operación que deduce la aplicación da el mismo modelo, en bits, que ``ControlChart.fit_phase1``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from voracious.application.errors import UnknownChartError
from voracious.domain.common import BoolVector, FloatMatrix, StageKind, TaskMapper

__all__ = [
    "Calibration",
    "Phase1Steps",
    "Phase1StepsRegistry",
    "resolve_steps",
]


@dataclass(frozen=True, eq=False)
class Calibration:
    """Límites de un ajuste y sus filas limpias.

    Attributes:
        limits: Límites de la carta (opacos para la aplicación).
        clean: Filas limpias del ajuste, máscara sobre las filas del dataset.
    """

    limits: object
    clean: BoolVector


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

    def stage_spawn_key(self, kind: StageKind) -> tuple[int, ...]:
        """Hueco de semilla de una calibración.

        Args:
            kind: Operación.

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
        kind: StageKind,
        mapper: TaskMapper,
    ) -> Calibration:
        """Filas limpias y límites de un ajuste.

        Args:
            x: Dataset del ajuste.
            fit: Ajuste.
            params: Parámetros de la carta codificados.
            kind: Operación (elige el hueco de semilla).
            mapper: Reparto de las réplicas.

        Returns:
            La calibración.

        Raises:
            DomainError: Decisión pendiente o fallo de la calibración.
        """
        ...

    def assemble_initial_model(
        self,
        root: FloatMatrix,
        params: Mapping[str, object],
        fit: object,
        calibration: Calibration,
        *,
        excluded: BoolVector,
    ) -> object:
        """Construye el modelo de Fase I (versión inicial).

        Args:
            root: Dataset raíz ``n x p``.
            params: Parámetros de la carta codificados.
            fit: Ajuste de ``root[~excluded]``.
            calibration: Calibración de ese ajuste.
            excluded: Filas excluidas por una persona (máscara sobre ``root``).

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
