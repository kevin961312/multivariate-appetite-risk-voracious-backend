"""Mapeo de errores a HTTP con el formato uniforme ``{code, message, details}`` (ADR 0005).

``CODE_TO_STATUS`` es la tabla única código → estado HTTP. Los errores síncronos (validación,
estado, recurso inexistente) se responden aquí; los fallos de dominio de un **trabajo** no son
errores HTTP: quedan en el registro ``failed`` y se devuelven en el cuerpo del ``GET`` con 200.

Una excepción inesperada no la atiende un manejador de FastAPI sino ``ErrorBoundaryMiddleware``:
Starlette instala el manejador de ``Exception`` en ``ServerErrorMiddleware``, **fuera** de los
middlewares de usuario, y ese ``500`` saldría sin las cabeceras de CORS. La barrera va dentro de
``CORSMiddleware`` (paso E, E14).
"""

from collections.abc import Mapping
from http import HTTPStatus

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from voracious.application.auth import UNAUTHENTICATED
from voracious.application.errors import ApplicationError
from voracious.application.use_cases import INTERNAL_ERROR, JOB_INTERRUPTED
from voracious.domain.common import DomainError, InvalidInputError

__all__ = [
    "CODE_TO_STATUS",
    "DEFAULT_DOMAIN_STATUS",
    "UNHANDLED_EXCEPTION_EVENT",
    "ApiError",
    "ErrorBoundaryMiddleware",
    "error_response",
    "handle_error",
    "install_error_handlers",
    "status_for",
]

_log = structlog.get_logger(__name__)

UNHANDLED_EXCEPTION_EVENT = "unhandled_exception"
"""Evento del log de una excepción inesperada (con la traza; nunca va al cuerpo)."""

CODE_TO_STATUS: Mapping[str, int] = {
    # 401: falta el token o no es válido (``details.reason``; con ``WWW-Authenticate``).
    UNAUTHENTICATED: 401,
    # 403: el token es válido pero sus roles no permiten la operación (``details.required_roles``).
    "FORBIDDEN": 403,
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
    "EXCLUSION_NOT_FOUND": 404,
    "PIPELINE_NOT_FOUND": 404,
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
    "FIT_NOT_READY": 409,
    "LIMITS_NOT_READY": 409,
    "RECALIBRATION_NOT_IN_PROGRESS": 409,
    # 413 y 415: cuerpo de la subida de un dataset.
    "PAYLOAD_TOO_LARGE": 413,
    "UNSUPPORTED_MEDIA_TYPE": 415,
    # 422: la entrada no es válida para el método o el ciclo de vida.
    InvalidInputError.CODE: 422,
    "RANGE_BEFORE_STRUCTURAL_EVENT": 422,
    "RECALIBRATION_INSUFFICIENT_OBSERVATIONS": 422,
    "OBSERVATION_BEFORE_FIRST_VERSION": 422,
    "T2MRCD_FIT_PARAMS_MISMATCH": 422,
    "LIMITS_FIT_MISMATCH": 422,
    "RECALIBRATION_MISMATCH": 422,
    "VERSION_INPUTS_MISMATCH": 422,
    "VARIABLES_MISMATCH": 422,
    # 429: demasiadas peticiones por IP (``Retry-After``) o demasiados trabajos de cómputo en
    # cola o en curso para el tenant (``details.max_active_jobs``).
    "RATE_LIMITED": 429,
    "TOO_MANY_JOBS": 429,
    # 500: fallo inesperado (el detalle va al log, nunca al cuerpo).
    INTERNAL_ERROR: 500,
    # 503: el servicio se reinició con el trabajo en curso (Paso 4.2). Solo aparece en el cuerpo
    # de un trabajo ``failed`` (``GET`` con 200); se vuelve a pedir.
    JOB_INTERRUPTED: 503,
}
"""Estado HTTP de cada código síncrono del catálogo."""

DEFAULT_DOMAIN_STATUS = 422
"""Estado de un ``DomainError`` síncrono sin entrada propia en la tabla (problema de la entrada
o del método frente a esa entrada, p. ej. ``T2MRCD_DECISION_PENDING`` al validar)."""


class ApiError(Exception):
    """Error propio de la capa HTTP (p. ej. ``FORBIDDEN``).

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
    status: int,
    code: str,
    message: str,
    details: Mapping[str, object] | None = None,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Respuesta JSON de error.

    Args:
        status: Estado HTTP.
        code: Código.
        message: Mensaje.
        details: Datos adicionales.
        headers: Cabeceras adicionales (p. ej. ``WWW-Authenticate`` en un ``401``).

    Returns:
        La respuesta.
    """
    body = {"code": code, "message": message, "details": dict(details or {})}
    return JSONResponse(
        status_code=status,
        content=jsonable_encoder(body),
        headers=dict(headers) if headers is not None else None,
    )


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
    """Manejador de los errores conocidos: los traduce al formato ``{code, message, details}``.

    Args:
        request: Petición.
        exc: Excepción (de uno de los tipos que registra ``install_error_handlers``).

    Returns:
        La respuesta de error.

    Raises:
        Exception: La propia ``exc`` si no es de un tipo conocido, para que la atienda
            ``ErrorBoundaryMiddleware``.
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
    raise exc


def install_error_handlers(app: FastAPI) -> None:
    """Registra los manejadores de los errores conocidos en la aplicación.

    Las excepciones inesperadas no tienen manejador aquí: las atiende ``ErrorBoundaryMiddleware``.

    Args:
        app: Aplicación.
    """
    for kind in (
        ApplicationError,
        DomainError,
        ApiError,
        RequestValidationError,
        StarletteHTTPException,
    ):
        app.add_exception_handler(kind, handle_error)


class ErrorBoundaryMiddleware:
    """Middleware ASGI que convierte una excepción inesperada en ``500 INTERNAL_ERROR``.

    Registra ``unhandled_exception`` con la traza (una vez) y, si la respuesta aún no empezó,
    responde en el formato uniforme sin detalles; si ya empezó, relanza la excepción (no se puede
    cambiar un estado ya enviado). Solo ``http``: ``lifespan`` y WebSocket pasan intactos.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Construye el middleware.

        Args:
            app: Aplicación ASGI interior.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Atiende una conexión ASGI.

        Args:
            scope: Scope.
            receive: Canal de entrada.
            send: Canal de salida.

        Raises:
            Exception: La excepción de la aplicación si la respuesta ya había empezado.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            _log.error(
                UNHANDLED_EXCEPTION_EVENT,
                path=scope.get("path"),
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            if started:
                raise
            await _internal()(scope, receive, send)
