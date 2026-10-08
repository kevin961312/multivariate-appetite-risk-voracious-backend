"""Schemas comunes a todas las cartas: errores, estados de trabajo, matrices y fechas."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat

__all__ = [
    "AcceptedJob",
    "ErrorBody",
    "ErrorResponse",
    "JobState",
    "Matrix",
    "RequestModel",
    "ResponseModel",
    "UtcDatetime",
    "Vector",
]

JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
"""Estado de un trabajo asíncrono (ADR 0003); ``cancelled``: solo una recalibración por pasos."""

Vector = Annotated[list[FiniteFloat], Field(min_length=1)]
"""Vector numérico finito (sin NaN ni infinito)."""

Matrix = Annotated[list[Vector], Field(min_length=1)]
"""Matriz ``n x p`` numérica finita, por filas."""

UtcDatetime = AwareDatetime
"""Fecha con zona horaria obligatoria (se normaliza a UTC en la aplicación)."""


class RequestModel(BaseModel):
    """Base de los cuerpos de petición: rechaza campos desconocidos."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    """Base de las respuestas."""

    model_config = ConfigDict(extra="forbid")


class ErrorBody(ResponseModel):
    """Error con el formato uniforme.

    Attributes:
        code: Código estable del catálogo.
        message: Mensaje legible.
        details: Datos adicionales.
    """

    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(ErrorBody):
    """Cuerpo de una respuesta de error HTTP ``{code, message, details}``."""


class AcceptedJob(ResponseModel):
    """Respuesta ``202``: el trabajo quedó encolado.

    Attributes:
        id: Identificador del recurso creado.
        status: Siempre ``queued`` al aceptarse.
    """

    id: str
    status: JobState = "queued"
