"""Registro de cartas disponibles para los casos de uso y lo que el ciclo de vida lee de ellas."""

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from voracious.application.errors import UnknownChartError
from voracious.domain.common import BoolVector, ControlChart, FloatVector, RowDisposition

__all__ = [
    "AnyChart",
    "ChartRegistry",
    "Phase2Scores",
    "RecalibrationParamsView",
    "RecalibrationReportView",
    "VersionedModel",
    "as_phase2_scores",
    "as_recalibration_params",
    "as_recalibration_report",
    "as_versioned_model",
    "resolve_chart",
]

# ``Any`` justificado: el registro es heterogéneo (cada carta tiene sus propios parámetros, modelo,
# resultado, parámetros e informe de recalibración) y los parámetros son contravariantes, así que
# no existe un supertipo común distinto de ``Any``. Los registros guardan esos valores como
# ``object`` y solo la carta que los produjo los vuelve a recibir (la clave ``chart_id`` del
# registro lo garantiza).
AnyChart = ControlChart[Any, Any, Any, Any, Any]
"""Una carta cualquiera del registro."""

ChartRegistry = Mapping[str, AnyChart]
"""Cartas por ``chart_id``."""


@runtime_checkable
class Phase2Scores(Protocol):
    """Forma mínima del resultado de Fase II que el registro de observaciones necesita."""

    @property
    def t2(self) -> FloatVector:
        """Estadístico de cada observación."""
        ...

    @property
    def signal(self) -> BoolVector:
        """Señal de cada observación."""
        ...

    @property
    def limit(self) -> float:
        """Límite usado."""
        ...

    @property
    def limit_kind(self) -> str:
        """Régimen del límite usado."""
        ...


@runtime_checkable
class VersionedModel(Protocol):
    """Forma mínima del modelo de Fase I que una versión necesita para guardar su base."""

    @property
    def base_mask(self) -> BoolVector:
        """Filas de la entrada que forman la base."""
        ...

    @property
    def row_disposition(self) -> tuple[RowDisposition, ...]:
        """Destino de cada fila de la entrada."""
        ...


@runtime_checkable
class RecalibrationReportView(Protocol):
    """Forma mínima del informe de recalibración: el destino de cada fila de base + nuevas."""

    @property
    def row_disposition(self) -> tuple[RowDisposition, ...]:
        """Destino de cada fila de ``vstack(base, x_new)``."""
        ...


@runtime_checkable
class RecalibrationParamsView(Protocol):
    """Forma mínima de los parámetros de recalibración: el mínimo de observaciones."""

    @property
    def min_observations(self) -> int:
        """Mínimo de observaciones nuevas."""
        ...


def _shape_error(what: str, protocol: str) -> TypeError:
    """Error de integración: un valor de la carta no tiene la forma que el ciclo de vida necesita.

    Args:
        what: Descripción del valor.
        protocol: Protocolo exigido.

    Returns:
        El error a lanzar.
    """
    return TypeError(f"{what} de la carta no cumple {protocol}")


def as_phase2_scores(value: object) -> Phase2Scores:
    """Resultado de Fase II con la forma ``Phase2Scores``.

    Args:
        value: Resultado de ``score_phase2``.

    Returns:
        El resultado.

    Raises:
        TypeError: Si no cumple el protocolo.
    """
    if not isinstance(value, Phase2Scores):
        raise _shape_error("el resultado de Fase II", "Phase2Scores")
    return value


def as_versioned_model(value: object) -> VersionedModel:
    """Modelo con la forma ``VersionedModel``.

    Args:
        value: Modelo de la carta.

    Returns:
        El modelo.

    Raises:
        TypeError: Si no cumple el protocolo.
    """
    if not isinstance(value, VersionedModel):
        raise _shape_error("el modelo", "VersionedModel")
    return value


def as_recalibration_report(value: object) -> RecalibrationReportView:
    """Informe con la forma ``RecalibrationReportView``.

    Args:
        value: Informe de ``recalibrate``.

    Returns:
        El informe.

    Raises:
        TypeError: Si no cumple el protocolo.
    """
    if not isinstance(value, RecalibrationReportView):
        raise _shape_error("el informe de recalibración", "RecalibrationReportView")
    return value


def as_recalibration_params(value: object) -> RecalibrationParamsView:
    """Parámetros de recalibración con la forma ``RecalibrationParamsView``.

    Args:
        value: Parámetros decodificados.

    Returns:
        Los parámetros.

    Raises:
        TypeError: Si no cumple el protocolo.
    """
    if not isinstance(value, RecalibrationParamsView):
        raise _shape_error("los parámetros de recalibración", "RecalibrationParamsView")
    return value


def resolve_chart(charts: ChartRegistry, chart_id: str) -> AnyChart:
    """Devuelve la carta registrada con ``chart_id``.

    Args:
        charts: Registro de cartas.
        chart_id: Identificador pedido.

    Returns:
        La carta.

    Raises:
        UnknownChartError: Si no está registrada.
    """
    chart = charts.get(chart_id)
    if chart is None:
        raise UnknownChartError(f"la carta '{chart_id}' no existe", details={"chart_id": chart_id})
    return chart
