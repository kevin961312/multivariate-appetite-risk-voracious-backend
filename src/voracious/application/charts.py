"""Registro de cartas disponibles para los casos de uso."""

from collections.abc import Mapping
from typing import Any

from voracious.application.errors import UnknownChartError
from voracious.domain.common import ControlChart

__all__ = ["AnyChart", "ChartRegistry", "resolve_chart"]

# ``Any`` justificado: el registro es heterogéneo (cada carta tiene sus propios parámetros, modelo
# y resultado) y ``ParamsT`` es contravariante, así que no existe un supertipo común distinto de
# ``Any``. Los registros guardan esos valores como ``object`` y solo la carta que los produjo los
# vuelve a recibir (la clave ``chart_id`` del registro lo garantiza).
AnyChart = ControlChart[Any, Any, Any]
"""Una carta cualquiera del registro."""

ChartRegistry = Mapping[str, AnyChart]
"""Cartas por ``chart_id``."""


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
