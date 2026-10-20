"""Autenticación y autorización de la API: token portador obligatorio y matriz de roles (D7, D8).

``AuthenticationMiddleware`` es ASGI puro (no ``BaseHTTPMiddleware``): verifica el token **antes de
leer el cuerpo** y antes del enrutado, así que una subida de 50 MB o un JSON malformado sin token
responden ``401`` sin consumir nada, y toda ruta nueva queda protegida aunque nadie se acuerde. Solo
quedan libres ``PUBLIC_PATHS`` (y solo por HTTP) y el ``lifespan``. Un WebSocket exige el mismo
token y, si falta o no vale, se cierra con ``1008`` (violación de política) antes de aceptarlo; un
scope de otro tipo no llega a la aplicación. El token se lee únicamente de ``Authorization:
Bearer`` (nunca de la query) y nunca se registra.

La matriz de roles vive aquí, en la capa API (ni dominio ni casos de uso la conocen):

- ``Reader`` (lectura, todos los ``GET`` de negocio): analyst, approver, admin.
- ``Operator`` (operación: subir datos, pedir pasos, puntuar, anotar, registrar eventos, recalibrar,
  extender, cancelar y proponer versión): analyst, admin.
- ``Decider`` (decisión: aprobar y rechazar versiones): approver, admin.

El tenant de cada caso de uso es ``principal.tenant_id``; ``X-Tenant-ID`` ya no existe y se ignora.
"""

from collections.abc import Callable, Mapping
from http import HTTPStatus
from typing import Annotated, Final

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.status import WS_1008_POLICY_VIOLATION
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from voracious.api.errors import ApiError, error_response
from voracious.application.auth import (
    MAX_TOKEN_BYTES,
    UNAUTHENTICATED,
    AuthenticationError,
    AuthFailure,
    Principal,
    Role,
)
from voracious.application.ports import TokenVerifier

__all__ = [
    "AUTH_FAILURE_STATE",
    "BEARER_SCHEME",
    "FORBIDDEN",
    "PRINCIPAL_STATE",
    "PUBLIC_PATHS",
    "WWW_AUTHENTICATE",
    "AuthenticationMiddleware",
    "Decider",
    "Operator",
    "Reader",
    "bearer_token",
    "require_roles",
]

PUBLIC_PATHS: Final = frozenset(
    {"/health", "/ready", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
)
"""Rutas sin token (coincidencia exacta): salud y documentación de la API."""

FORBIDDEN: Final = "FORBIDDEN"
"""Código de error: el token es válido pero sus roles no permiten la operación (``403``)."""

PRINCIPAL_STATE: Final = "principal"
"""Clave de ``scope["state"]`` con el ``Principal`` verificado."""

AUTH_FAILURE_STATE: Final = "auth_failure"
"""Clave de ``scope["state"]`` con el motivo de un ``401`` (para el registro de acceso)."""

WWW_AUTHENTICATE: Final = 'Bearer realm="voracious"'
"""Valor de ``WWW-Authenticate`` cuando no se presentó token (RFC 6750 §3)."""

BEARER_SCHEME: Final = "bearerAuth"
"""Nombre del esquema de seguridad en OpenAPI (HTTP bearer, formato JWT)."""

_MESSAGES: Final[Mapping[AuthFailure, str]] = {
    AuthFailure.NO_CREDENTIALS: "falta la cabecera Authorization: Bearer <token>",
    AuthFailure.MALFORMED: "la cabecera Authorization no tiene un token portador válido",
}
"""Mensajes de los rechazos que se deciden aquí (los demás los da el verificador)."""

_bearer = HTTPBearer(
    scheme_name=BEARER_SCHEME,
    bearerFormat="JWT",
    description="JWT firmado (EdDSA por defecto) con los claims tenant y roles.",
    auto_error=False,
)
"""Solo declara el esquema en OpenAPI: la verificación la hace ``AuthenticationMiddleware``."""


def _reject(reason: AuthFailure) -> AuthenticationError:
    """Rechazo decidido por el middleware (sin pasar por el verificador).

    Args:
        reason: Motivo.

    Returns:
        El error (para ``raise``).
    """
    return AuthenticationError(reason, _MESSAGES[reason])


def bearer_token(scope: Scope) -> str:
    """Token portador de la cabecera ``Authorization`` (nunca de la query).

    Args:
        scope: Scope ASGI de la petición.

    Returns:
        El token.

    Raises:
        AuthenticationError: ``missing_token`` si no hay cabecera o no es ``Bearer``;
            ``malformed`` si hay varias, está vacía, tiene espacios o supera ``MAX_TOKEN_BYTES``.
    """
    values: list[bytes] = [
        value for name, value in scope.get("headers", ()) if name.lower() == b"authorization"
    ]
    if not values:
        raise _reject(AuthFailure.NO_CREDENTIALS)
    if len(values) > 1:
        raise _reject(AuthFailure.MALFORMED)
    scheme, _, token = values[0].decode("latin-1").strip().partition(" ")
    if scheme.lower() != "bearer":
        raise _reject(AuthFailure.NO_CREDENTIALS)
    token = token.strip()
    if not token or len(token) > MAX_TOKEN_BYTES or any(c.isspace() for c in token):
        raise _reject(AuthFailure.MALFORMED)
    return token


class AuthenticationMiddleware:
    """Middleware ASGI que exige un token válido salvo en ``lifespan`` y en HTTP a ``PUBLIC_PATHS``.

    Con éxito deja el ``Principal`` en ``scope["state"]["principal"]`` y liga ``sub``, ``tenant`` y
    ``jti`` a las contextvars de structlog durante la petición. Si falla, sin llamar a la
    aplicación: por HTTP responde ``401 UNAUTHENTICATED`` con ``details.reason`` y
    ``WWW-Authenticate``; por WebSocket cierra con ``1008`` y el motivo como ``reason``. Un scope
    que no es ``http``, ``websocket`` ni ``lifespan`` se descarta (falla cerrado).
    """

    def __init__(self, app: ASGIApp, verifier: TokenVerifier) -> None:
        """Construye el middleware.

        Args:
            app: Aplicación ASGI interior.
            verifier: Verificador de tokens.
        """
        self.app = app
        self.verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Atiende una conexión ASGI.

        Args:
            scope: Scope.
            receive: Canal de entrada (no se lee antes de autenticar).
            send: Canal de salida.
        """
        kind = scope["type"]
        if kind == "lifespan" or (kind == "http" and scope["path"] in PUBLIC_PATHS):
            await self.app(scope, receive, send)
            return
        if kind not in {"http", "websocket"}:
            return
        state = scope.setdefault("state", {})
        try:
            principal = self.verifier.verify(bearer_token(scope))
        except AuthenticationError as exc:
            state[AUTH_FAILURE_STATE] = exc.reason.value
            if kind == "websocket":
                close = WebSocketClose(WS_1008_POLICY_VIOLATION, exc.reason.value)
                await close(scope, receive, send)
                return
            challenge = WWW_AUTHENTICATE
            if exc.reason is not AuthFailure.NO_CREDENTIALS:
                challenge = f'{WWW_AUTHENTICATE}, error="invalid_token"'
            response = error_response(
                HTTPStatus.UNAUTHORIZED,
                UNAUTHENTICATED,
                exc.message,
                exc.details,
                headers={"WWW-Authenticate": challenge},
            )
            await response(scope, receive, send)
            return
        state[PRINCIPAL_STATE] = principal
        with structlog.contextvars.bound_contextvars(
            sub=principal.subject, tenant=principal.tenant_id, jti=principal.token_id
        ):
            await self.app(scope, receive, send)


def require_roles(*allowed: Role) -> Callable[..., Principal]:
    """Dependencia de FastAPI que exige alguno de ``allowed`` y devuelve el principal.

    Además declara ``bearerAuth`` en la operación de OpenAPI.

    Args:
        allowed: Roles que permiten la operación.

    Returns:
        La dependencia.
    """
    accepted = frozenset(allowed)
    required = sorted(role.value for role in accepted)

    def dependency(
        request: Request,
        _: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> Principal:
        """Principal de la petición con un rol permitido.

        Args:
            request: Petición.
            _: Credenciales (solo para OpenAPI; el middleware ya verificó el token).

        Returns:
            El principal.

        Raises:
            ApiError: ``UNAUTHENTICATED`` si no hay principal (middleware sin instalar) o
                ``FORBIDDEN`` con ``details.required_roles`` si ningún rol permite la operación.
        """
        principal = request.scope.get("state", {}).get(PRINCIPAL_STATE)
        if not isinstance(principal, Principal):
            raise ApiError(UNAUTHENTICATED, "la petición no está autenticada")
        if not principal.has_any(accepted):
            raise ApiError(
                FORBIDDEN,
                "los roles del token no permiten esta operación",
                {"required_roles": required},
            )
        return principal

    return dependency


Reader = Annotated[Principal, Depends(require_roles(Role.ANALYST, Role.APPROVER, Role.ADMIN))]
"""Lectura: todos los ``GET`` de negocio."""

Operator = Annotated[Principal, Depends(require_roles(Role.ANALYST, Role.ADMIN))]
"""Operación: subidas, pasos de cómputo, puntuaciones, anotaciones, eventos y recalibraciones."""

Decider = Annotated[Principal, Depends(require_roles(Role.APPROVER, Role.ADMIN))]
"""Decisión: aprobar y rechazar versiones."""
