"""``JwtTokenVerifier``: verifica un JWT firmado con una llave del JWKS (puerto ``TokenVerifier``).

Pasos, en este orden y sin registrar nunca el token:

1. Forma: ≤ ``MAX_TOKEN_BYTES`` y tres segmentos (si no, ``malformed``).
2. Cabecera sin verificar: ``alg`` en la lista permitida (``none`` y ``HS*`` nunca lo están),
   ``kid`` presente y en el JWKS, y ``alg`` igual al de la llave de ese ``kid`` (impide la
   confusión de algoritmo). Sin ``crit`` ni ``b64``.
3. Firma y claims registrados con PyJWT ≥ 2.10.1 (CVE-2024-53861: ``iss`` se compara entero):
   ``exp``, ``iat``, ``iss``, ``aud`` (exacta), ``sub`` y ``jti`` obligatorios, ``nbf`` si viene,
   todo con el margen de reloj.
4. Claims propios: ``tenant`` con ``TENANT_PATTERN``, ``roles`` lista no vacía de roles conocidos,
   ``sub`` imprimible de 1 a 256 caracteres, ``jti`` de 1 a 128, fechas enteras y vida
   ``exp - iat`` ≤ ``MAX_TOKEN_TTL`` (mejora M4: un token robado de vida larga no sirve).

Cada excepción se traduce a un ``AuthFailure`` con un mensaje fijo; el texto de la librería no
llega al cliente ni a los logs.
"""

from collections.abc import Collection, Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

import jwt
from jwt import PyJWK
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAlgorithmError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidKeyError,
    InvalidSignatureError,
    MissingRequiredClaimError,
    PyJWTError,
)

from voracious.application.auth import (
    MAX_TOKEN_BYTES,
    MAX_TOKEN_TTL,
    TENANT_PATTERN,
    AuthenticationError,
    AuthFailure,
    Principal,
    Role,
)

__all__ = ["REQUIRED_CLAIMS", "JwtTokenVerifier"]

REQUIRED_CLAIMS: Final = ("exp", "iat", "iss", "aud", "sub", "jti", "tenant", "roles")
"""Claims obligatorios (D5 con la mejora M4: también ``jti``)."""

_PYJWT_REQUIRED: Final = ["exp", "iat", "iss", "aud", "sub", "jti"]
"""Los que comprueba PyJWT; ``tenant`` y ``roles`` se comprueban aquí."""

_MAX_SUBJECT: Final = 256
_MAX_TOKEN_ID: Final = 128
_SEGMENT_SEPARATORS: Final = 2
"""Puntos de un JWS compacto (``header.payload.firma``)."""

_MESSAGES: Final[Mapping[AuthFailure, str]] = {
    AuthFailure.MALFORMED: "el token no tiene la forma de un JWT válido",
    AuthFailure.UNKNOWN_KEY: "el token no identifica una llave conocida (kid)",
    AuthFailure.ALGORITHM_NOT_ALLOWED: "el algoritmo del token no está permitido",
    AuthFailure.BAD_SIGNATURE: "la firma del token no es válida",
    AuthFailure.EXPIRED: "el token caducó",
    AuthFailure.NOT_YET_VALID: "el token aún no es válido",
    AuthFailure.WRONG_ISSUER: "el emisor del token no es el esperado",
    AuthFailure.WRONG_AUDIENCE: "la audiencia del token no es la esperada",
    AuthFailure.MISSING_CLAIM: "falta un claim obligatorio en el token",
    AuthFailure.INVALID_CLAIM: "un claim del token no es válido",
    AuthFailure.LIFETIME_TOO_LONG: "la vida del token supera el máximo permitido",
}
"""Mensaje fijo de cada motivo (sin datos del token)."""

_FORBIDDEN_HEADERS: Final = frozenset({"crit", "b64"})
"""Cabeceras JWS que no se admiten (extensiones críticas y carga desacoplada)."""


def _fail(reason: AuthFailure) -> AuthenticationError:
    """Error de autenticación con el mensaje fijo de ``reason``.

    Args:
        reason: Motivo.

    Returns:
        El error (para ``raise``).
    """
    return AuthenticationError(reason, _MESSAGES[reason])


def _translate(exc: PyJWTError) -> AuthFailure:
    """Motivo de una excepción de PyJWT (las subclases antes que sus bases).

    Args:
        exc: Excepción.

    Returns:
        El motivo.
    """
    table: tuple[tuple[type[PyJWTError], AuthFailure], ...] = (
        (InvalidSignatureError, AuthFailure.BAD_SIGNATURE),
        (ExpiredSignatureError, AuthFailure.EXPIRED),
        (ImmatureSignatureError, AuthFailure.NOT_YET_VALID),
        (InvalidIssuerError, AuthFailure.WRONG_ISSUER),
        (InvalidAudienceError, AuthFailure.WRONG_AUDIENCE),
        (MissingRequiredClaimError, AuthFailure.MISSING_CLAIM),
        (InvalidAlgorithmError, AuthFailure.ALGORITHM_NOT_ALLOWED),
        (InvalidKeyError, AuthFailure.UNKNOWN_KEY),
        (DecodeError, AuthFailure.MALFORMED),
    )
    for kind, reason in table:
        if isinstance(exc, kind):
            return reason
    return AuthFailure.INVALID_CLAIM


def _int_claim(value: object) -> int:
    """Fecha de un claim como entero JSON de verdad (``bool`` es subclase de ``int``).

    Args:
        value: Valor del claim.

    Returns:
        El entero.

    Raises:
        AuthenticationError: ``invalid_claim`` si no es un entero.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise _fail(AuthFailure.INVALID_CLAIM)
    return value


class JwtTokenVerifier:
    """Verificador de JWT con llaves públicas de un JWKS.

    Attributes:
        issuer: ``iss`` exigido.
        audience: ``aud`` exigida.
        algorithms: Algoritmos admitidos.
        leeway: Margen de reloj.
        max_lifetime: Vida máxima ``exp - iat``.
    """

    def __init__(
        self,
        keys: Mapping[str, PyJWK],
        *,
        issuer: str,
        audience: str,
        algorithms: Collection[str],
        leeway: timedelta,
        max_lifetime: timedelta = MAX_TOKEN_TTL,
    ) -> None:
        """Construye el verificador.

        Args:
            keys: ``kid → llave pública`` (``load_jwks``).
            issuer: ``iss`` exigido (comparación exacta).
            audience: ``aud`` exigida (comparación exacta, un solo valor).
            algorithms: Algoritmos admitidos.
            leeway: Margen de reloj para ``exp``, ``nbf`` e ``iat``.
            max_lifetime: Vida máxima de un token (``exp - iat``).

        Raises:
            ValueError: Si no hay llaves, algoritmos, emisor o audiencia.
        """
        if not keys or not algorithms or not issuer or not audience:
            msg = "el verificador necesita llaves, algoritmos, emisor y audiencia"
            raise ValueError(msg)
        self._keys = dict(keys)
        self.issuer = issuer
        self.audience = audience
        self.algorithms = frozenset(algorithms)
        self.leeway = leeway
        self.max_lifetime = max_lifetime

    def _key_for(self, token: str) -> PyJWK:
        """Llave del ``kid`` de la cabecera, tras comprobar forma y algoritmo.

        Args:
            token: Token.

        Returns:
            La llave con la que se verifica.

        Raises:
            AuthenticationError: ``malformed``, ``algorithm_not_allowed`` o ``unknown_key``.
        """
        if len(token.encode("utf-8")) > MAX_TOKEN_BYTES or (
            token.count(".") != _SEGMENT_SEPARATORS
        ):
            raise _fail(AuthFailure.MALFORMED)
        try:
            header = jwt.get_unverified_header(token)
        except PyJWTError as exc:
            raise _fail(AuthFailure.MALFORMED) from exc
        if _FORBIDDEN_HEADERS & set(header):
            raise _fail(AuthFailure.MALFORMED)
        alg = header.get("alg")
        if not isinstance(alg, str) or alg not in self.algorithms:
            raise _fail(AuthFailure.ALGORITHM_NOT_ALLOWED)
        kid = header.get("kid")
        key = self._keys.get(kid) if isinstance(kid, str) else None
        if key is None:
            raise _fail(AuthFailure.UNKNOWN_KEY)
        if key.algorithm_name != alg:
            raise _fail(AuthFailure.ALGORITHM_NOT_ALLOWED)
        return key

    def verify(self, token: str) -> Principal:
        """Verifica el token y devuelve el principal.

        Args:
            token: Token compacto (``header.payload.firma``).

        Returns:
            El principal.

        Raises:
            AuthenticationError: Con el motivo del rechazo.
        """
        key = self._key_for(token)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[key.algorithm_name],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={
                    "require": list(_PYJWT_REQUIRED),
                    "strict_aud": True,
                    "enforce_minimum_key_length": True,
                },
            )
        except PyJWTError as exc:
            raise _fail(_translate(exc)) from exc
        return self._principal(claims)

    def _principal(self, claims: Mapping[str, object]) -> Principal:
        """Comprueba los claims propios y construye el principal.

        Args:
            claims: Claims ya verificados por PyJWT.

        Returns:
            El principal.

        Raises:
            AuthenticationError: ``missing_claim``, ``invalid_claim`` o ``lifetime_too_long``.
        """
        tenant, roles = claims.get("tenant"), claims.get("roles")
        if tenant is None or roles is None:
            raise _fail(AuthFailure.MISSING_CLAIM)
        if not isinstance(tenant, str) or TENANT_PATTERN.fullmatch(tenant) is None:
            raise _fail(AuthFailure.INVALID_CLAIM)
        if not isinstance(roles, list) or not roles:
            raise _fail(AuthFailure.INVALID_CLAIM)
        known = {r.value for r in Role}
        if any(not isinstance(r, str) or r not in known for r in roles):
            raise _fail(AuthFailure.INVALID_CLAIM)
        subject, token_id = claims["sub"], claims["jti"]
        if not isinstance(subject, str) or not 0 < len(subject) <= _MAX_SUBJECT:
            raise _fail(AuthFailure.INVALID_CLAIM)
        if not subject.isprintable():
            raise _fail(AuthFailure.INVALID_CLAIM)
        if not isinstance(token_id, str) or not 0 < len(token_id) <= _MAX_TOKEN_ID:
            raise _fail(AuthFailure.INVALID_CLAIM)
        issued, expires = _int_claim(claims["iat"]), _int_claim(claims["exp"])
        if claims.get("nbf") is not None:
            _int_claim(claims["nbf"])
        if expires <= issued:
            raise _fail(AuthFailure.INVALID_CLAIM)
        if timedelta(seconds=expires - issued) > self.max_lifetime:
            raise _fail(AuthFailure.LIFETIME_TOO_LONG)
        return Principal(
            subject=subject,
            tenant_id=tenant,
            roles=frozenset(Role(r) for r in roles),
            expires_at=datetime.fromtimestamp(expires, UTC),
            token_id=token_id,
        )
