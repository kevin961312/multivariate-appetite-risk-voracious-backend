"""Identidad de la petición: roles, principal y error de autenticación (seguridad mínima).

Solo tipos y reglas de la aplicación (stdlib): la verificación del token es un adaptador de
``infrastructure/auth`` detrás del puerto ``TokenVerifier`` (``application/ports.py``), y la matriz
de roles por ruta vive en la capa API. Ni el dominio ni los casos de uso conocen los roles.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from voracious.application.errors import ApplicationError

__all__ = [
    "DEFAULT_TOKEN_TTL",
    "MAX_TOKEN_BYTES",
    "MAX_TOKEN_TTL",
    "TENANT_PATTERN",
    "UNAUTHENTICATED",
    "AuthFailure",
    "AuthenticationError",
    "Principal",
    "Role",
]

TENANT_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
"""Forma válida de un tenant (se exige coincidencia completa, ``fullmatch``)."""

DEFAULT_TOKEN_TTL = timedelta(hours=8)
"""Duración por defecto de un token emitido por la CLI (D13)."""

MAX_TOKEN_TTL = timedelta(days=7)
"""Duración máxima de un token: la CLI no emite más y la API rechaza más (D13, mejora M4)."""

MAX_TOKEN_BYTES = 8192
"""Tamaño máximo de un token: por encima se rechaza sin decodificarlo (``malformed``)."""

UNAUTHENTICATED = "UNAUTHENTICATED"
"""Código de error: falta el token o no es válido (``401``)."""


class Role(StrEnum):
    """Rol de quien llama, tal como viaja en el claim ``roles`` (D6).

    Un token puede llevar varios. ``admin`` lo es **de su tenant**: no hay superadministrador
    entre tenants.
    """

    ANALYST = "analyst"
    APPROVER = "approver"
    ADMIN = "admin"


class AuthFailure(StrEnum):
    """Motivo cerrado de un ``401 UNAUTHENTICATED`` (``details.reason``).

    Attributes:
        NO_CREDENTIALS: ``missing_token``: no hay cabecera ``Authorization: Bearer`` (el nombre
            evita la regla S105 de ruff, que toma por contraseña todo nombre con «token»).
        MALFORMED: El token no tiene la forma de un JWT compacto o supera ``MAX_TOKEN_BYTES``.
        UNKNOWN_KEY: La cabecera no trae ``kid`` o no está en el JWKS.
        ALGORITHM_NOT_ALLOWED: ``alg`` fuera de la lista permitida o distinto del de la llave.
        BAD_SIGNATURE: La firma no corresponde a la llave del ``kid``.
        EXPIRED: ``exp`` ya pasó (con el margen de reloj).
        NOT_YET_VALID: ``iat`` o ``nbf`` en el futuro (con el margen de reloj).
        WRONG_ISSUER: ``iss`` no es exactamente el configurado.
        WRONG_AUDIENCE: ``aud`` no es exactamente la configurada.
        MISSING_CLAIM: Falta un claim obligatorio.
        INVALID_CLAIM: Un claim tiene un tipo o una forma no válidos.
        LIFETIME_TOO_LONG: ``exp - iat`` supera ``MAX_TOKEN_TTL`` (mejora M4).
    """

    NO_CREDENTIALS = "missing_token"
    MALFORMED = "malformed"
    UNKNOWN_KEY = "unknown_key"
    ALGORITHM_NOT_ALLOWED = "algorithm_not_allowed"
    BAD_SIGNATURE = "bad_signature"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    WRONG_ISSUER = "wrong_issuer"
    WRONG_AUDIENCE = "wrong_audience"
    MISSING_CLAIM = "missing_claim"
    INVALID_CLAIM = "invalid_claim"
    LIFETIME_TOO_LONG = "lifetime_too_long"


@dataclass(frozen=True)
class Principal:
    """Identidad verificada de quien llama.

    Attributes:
        subject: Claim ``sub`` (quién es); es el ``actor`` de anotaciones, eventos y decisiones.
        tenant_id: Claim ``tenant``; todo caso de uso se ejecuta en este tenant.
        roles: Claim ``roles`` (al menos uno).
        expires_at: Claim ``exp`` (con zona horaria).
        token_id: Claim ``jti`` (identificador del token, para el registro de acceso).
    """

    subject: str
    tenant_id: str
    roles: frozenset[Role]
    expires_at: datetime
    token_id: str

    def __post_init__(self) -> None:
        """Comprueba las invariantes.

        Raises:
            ValueError: Si el tenant no cumple ``TENANT_PATTERN``, no hay roles, el sujeto o el
                identificador del token están vacíos o ``expires_at`` no tiene zona horaria.
        """
        if TENANT_PATTERN.fullmatch(self.tenant_id) is None:
            msg = "el tenant no cumple ^[A-Za-z0-9_-]{1,64}$"
            raise ValueError(msg)
        if not self.roles:
            msg = "un principal necesita al menos un rol"
            raise ValueError(msg)
        if not self.subject or not self.token_id:
            msg = "sujeto e identificador del token no pueden estar vacíos"
            raise ValueError(msg)
        if self.expires_at.tzinfo is None:
            msg = "expires_at necesita zona horaria"
            raise ValueError(msg)

    def has_any(self, roles: Collection[Role]) -> bool:
        """Indica si el principal tiene alguno de ``roles``.

        Args:
            roles: Roles admitidos.

        Returns:
            ``True`` si comparte al menos uno.
        """
        return not self.roles.isdisjoint(roles)


class AuthenticationError(ApplicationError):
    """El token falta o no es válido (``401 UNAUTHENTICATED`` con ``details.reason``).

    El mensaje es fijo por motivo: nunca incluye el token ni el texto de la excepción de la
    librería.

    Attributes:
        reason: Motivo del rechazo.
    """

    code = UNAUTHENTICATED

    def __init__(self, reason: AuthFailure, message: str) -> None:
        """Construye el error.

        Args:
            reason: Motivo del rechazo.
            message: Mensaje legible (sin datos del token).
        """
        super().__init__(message, {"reason": reason.value})
        self.reason = reason
