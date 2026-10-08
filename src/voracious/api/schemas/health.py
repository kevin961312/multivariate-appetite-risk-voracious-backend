"""Schemas de los endpoints de vida y disponibilidad."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Respuesta de vida del proceso.

    Attributes:
        status: Siempre ``"ok"`` si el proceso responde.
    """

    status: Literal["ok"]


class ReadyResponse(BaseModel):
    """Respuesta de disponibilidad para recibir tráfico.

    Attributes:
        status: ``"ready"`` cuando todas las dependencias están disponibles.
        checks: Resultado por dependencia externa; vacío mientras no haya ninguna.
    """

    status: Literal["ready"]
    checks: dict[str, Literal["ok", "fail"]]
