"""Mapeo de errores a HTTP con el formato uniforme ``{code, message, details}`` (ADR 0005).

``CODE_TO_STATUS`` es la tabla única código → estado HTTP. Los errores síncronos (validación,
estado, recurso inexistente) se responden aquí; los fallos de dominio de un **trabajo** no son
errores HTTP: quedan en el registro ``failed`` y se devuelven en el cuerpo del ``GET`` con 200.
"""

from collections.abc import Mapping
from http import HTTPStatus

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from voracious.application.errors import ApplicationError
from voracious.application.use_cases import INTERNAL_ERROR
from voracious.domain.common import DomainError, InvalidInputError

__all__ = [
    "CODE_TO_STATUS",
    "DEFAULT_DOMAIN_STATUS",
    "ApiError",
    "error_response",
    "handle_error",
    "install_error_handlers",
    "status_for",
]

_log = structlog.get_logger(__name__)

CODE_TO_STATUS: Mapping[str, int] = {
    # 400: petición sin contexto válido.
    "TENANT_REQUIRED": 400,
    # 404: recurso inexistente o de otro tenant (indistinguibles).
    "CHART_NOT_FOUND": 404,
    "MODEL_NOT_FOUND": 404,
    "MONITORING_NOT_FOUND": 404,
    "VERSION_NOT_FOUND": 404,
    "RECALIBRATION_NOT_FOUND": 404,
    "OBSERVATION_NOT_FOUND": 404,
    "DATASET_NOT_FOUND": 404,
    "FIT_NOT_FOUND": 404,
    "LIMITS_NOT_FOUND": 404,
    "DEPURATION_NOT_FOUND": 404,
    "PIPELINE_NOT_FOUND": 404,
    "COMPARISON_NOT_FOUND": 404,
    "ROUTE_NOT_FOUND": 404,
    # 405: método no admitido en la ruta.
    "METHOD_NOT_ALLOWED": 405,
    # 409: el recurso existe pero su estado no permite la operación.
    "MODEL_NOT_READY": 409,
    "VERSION_NOT_PROPOSED": 409,
    "PROPOSAL_PENDING": 409,
    "RECALIBRATION_IN_PROGRESS": 409,
    "NOT_A_SIGNAL": 409,
    "EFFECTIVE_FROM_NOT_AFTER_SCORED": 409,
    "DEPURATION_NOT_FINAL": 409,
    "FIT_NOT_READY": 409,
    "LIMITS_NOT_READY": 409,
    "COMPARISON_NOT_READY": 409,
    "RECALIBRATION_NOT_IN_PROGRESS": 409,
    # 413 y 415: cuerpo de la subida de un dataset.
    "PAYLOAD_TOO_LARGE": 413,
    "UNSUPPORTED_MEDIA_TYPE": 415,
    # 422: la entrada no es válida para el método o el ciclo de vida.
    InvalidInputError.CODE: 422,
    "RANGE_BEFORE_STRUCTURAL_EVENT": 422,
    "RECALIBRATION_INSUFFICIENT_OBSERVATIONS": 422,
    "RECALIBRATION_DECISION_PENDING": 422,
    "OBSERVATION_BEFORE_FIRST_VERSION": 422,
    "T2MRCD_FIT_PARAMS_MISMATCH": 422,
    "LIMITS_FIT_MISMATCH": 422,
    "LIMITS_PARAMS_MISMATCH": 422,
    "RECALIBRATION_MISMATCH": 422,
    "VERSION_INPUTS_MISMATCH": 422,
    # 500: fallo inesperado (el detalle va al log, nunca al cuerpo).
    INTERNAL_ERROR: 500,
}
"""Estado HTTP de cada código síncrono del catálogo."""

DEFAULT_DOMAIN_STATUS = 422
"""Estado de un ``DomainError`` síncrono sin entrada propia en la tabla (problema de la entrada
o del método frente a esa entrada, p. ej. ``T2MRCD_DECISION_PENDING`` al validar)."""


class ApiError(Exception):
    """Error propio de la capa HTTP (p. ej. ``TENANT_REQUIRED``).

    Attributes:
        code: Código del catálogo.
        message: Mensaje legible.
        details: Datos adicionales.
    """

    def __init__(
        self, code: str, message: str, details: Mapping[str, object] | None = None
    ) -> None:
        """Construye el error.

        Args:
            code: Código (debe estar en ``CODE_TO_STATUS``).
            message: Mensaje legible.
            details: Datos adicionales.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details) if details is not None else {}


def status_for(code: str) -> int | None:
    """Estado HTTP de un código del catálogo.

    Args:
        code: Código.

    Returns:
        El estado, o ``None`` si el código no está mapeado.
    """
    return CODE_TO_STATUS.get(code)


def error_response(
    status: int, code: str, message: str, details: Mapping[str, object] | None = None
) -> JSONResponse:
    """Respuesta JSON de error.

    Args:
        status: Estado HTTP.
        code: Código.
        message: Mensaje.
        details: Datos adicionales.

    Returns:
        La respuesta.
    """
    body = {"code": code, "message": message, "details": dict(details or {})}
    return JSONResponse(status_code=status, content=jsonable_encoder(body))


def _internal() -> JSONResponse:
    return error_response(HTTPStatus.INTERNAL_SERVER_ERROR, INTERNAL_ERROR, "error interno")


def _coded(
    request: Request, code: str, message: str, details: Mapping[str, object]
) -> JSONResponse:
    """Respuesta de un error con código de la tabla; un código sin mapeo es ``INTERNAL_ERROR``.

    Args:
        request: Petición (para el log).
        code: Código.
        message: Mensaje.
        details: Datos adicionales.

    Returns:
        La respuesta.
    """
    status = status_for(code)
    if status is None:
        _log.error("unmapped_error_code", code=code, path=request.url.path)
        return _internal()
    return error_response(status, code, message, details)


def _validation(exc: RequestValidationError) -> JSONResponse:
    """``422 INVALID_INPUT`` con los errores del schema en ``details.errors``.

    Args:
        exc: Error de validación de FastAPI.

    Returns:
        La respuesta.
    """
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return error_response(
        CODE_TO_STATUS[InvalidInputError.CODE],
        InvalidInputError.CODE,
        "la petición no cumple el schema",
        {"errors": errors},
    )


def _http(exc: StarletteHTTPException) -> JSONResponse:
    """Errores HTTP del enrutado (ruta o método inexistentes) en el formato uniforme.

    Args:
        exc: Error HTTP de Starlette.

    Returns:
        La respuesta.
    """
    if exc.status_code == HTTPStatus.NOT_FOUND:
        return error_response(HTTPStatus.NOT_FOUND, "ROUTE_NOT_FOUND", "la ruta no existe")
    if exc.status_code == HTTPStatus.METHOD_NOT_ALLOWED:
        return error_response(
            HTTPStatus.METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED", "método no admitido en la ruta"
        )
    return error_response(exc.status_code, "HTTP_ERROR", str(exc.detail))


async def handle_error(request: Request, exc: Exception) -> JSONResponse:
    """Manejador único: traduce cualquier excepción al formato ``{code, message, details}``.

    Args:
        request: Petición.
        exc: Excepción.

    Returns:
        La respuesta de error.
    """
    if isinstance(exc, ApplicationError | ApiError):
        return _coded(request, exc.code, exc.message, exc.details)
    if isinstance(exc, DomainError):
        status = status_for(exc.code) or DEFAULT_DOMAIN_STATUS
        return error_response(status, exc.code, exc.message, exc.details)
    if isinstance(exc, RequestValidationError):
        return _validation(exc)
    if isinstance(exc, StarletteHTTPException):
        return _http(exc)
    _log.error(
        "unhandled_exception", path=request.url.path, exc_info=(type(exc), exc, exc.__traceback__)
    )
    return _internal()


def install_error_handlers(app: FastAPI) -> None:
    """Registra los manejadores de error en la aplicación.

    Args:
        app: Aplicación.
    """
    for kind in (
        ApplicationError,
        DomainError,
        ApiError,
        RequestValidationError,
        StarletteHTTPException,
        Exception,
    ):
        app.add_exception_handler(kind, handle_error)
