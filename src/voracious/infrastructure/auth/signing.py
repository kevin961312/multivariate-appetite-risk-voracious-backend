"""Emisión de tokens de nivel A: llave Ed25519 propia y firma EdDSA (D2, D11, D13).

Solo lo usa la CLI (``issue-token`` y ``jwt-keygen`` a través de ``container``): la API verifica y
nunca firma, y la llave privada nunca entra en ``Settings``. La llave se lee en PEM PKCS8 (de un
fichero o de la entrada estándar) y no se guarda en ningún sitio.

Cada token lleva ``iss``, ``aud``, ``sub``, ``tenant``, ``roles`` (ordenados), ``iat``,
``nbf = iat``, ``exp`` y ``jti`` (uuid4), y la cabecera ``kid``.
"""

import re
import uuid
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Final

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)
from jwt.algorithms import OKPAlgorithm

from voracious.application.auth import MAX_TOKEN_TTL, TENANT_PATTERN, Role

__all__ = [
    "KID_PATTERN",
    "SIGNING_ALGORITHM",
    "SUBJECT_PATTERN",
    "generate_ed25519_key",
    "sign_token",
]

SIGNING_ALGORITHM: Final = "EdDSA"
"""Único algoritmo con el que firma la CLI (Ed25519)."""

SUBJECT_PATTERN: Final = re.compile(r"[A-Za-z0-9_.@-]{1,128}")
"""Forma de un ``sub`` emitido por la CLI (coincidencia completa)."""

KID_PATTERN: Final = re.compile(r"[A-Za-z0-9_.-]{1,64}")
"""Forma de un ``kid`` generado o usado por la CLI (coincidencia completa)."""


def _check_kid(kid: str) -> None:
    """Comprueba la forma de un ``kid``.

    Args:
        kid: Identificador de la llave.

    Raises:
        ValueError: Si no cumple ``KID_PATTERN``.
    """
    if KID_PATTERN.fullmatch(kid) is None:
        msg = "el kid debe cumplir ^[A-Za-z0-9_.-]{1,64}$"
        raise ValueError(msg)


def generate_ed25519_key(kid: str) -> tuple[bytes, dict[str, str]]:
    """Genera un par Ed25519 nuevo.

    Args:
        kid: Identificador de la llave en el JWKS.

    Returns:
        ``(llave privada en PEM PKCS8 sin cifrar, JWK público OKP/Ed25519 con kid, alg y use)``.

    Raises:
        ValueError: Si el ``kid`` no es válido.
    """
    _check_kid(kid)
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public = OKPAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk = {
        "kty": str(public["kty"]),
        "crv": str(public["crv"]),
        "x": str(public["x"]),
        "kid": kid,
        "alg": SIGNING_ALGORITHM,
        "use": "sig",
    }
    return pem, jwk


def _load_private_key(private_key_pem: bytes) -> Ed25519PrivateKey:
    """Carga la llave privada Ed25519 de un PEM PKCS8 sin cifrar.

    Args:
        private_key_pem: PEM.

    Returns:
        La llave.

    Raises:
        ValueError: Si no es un PEM válido o no es Ed25519 (el mensaje no incluye el contenido).
    """
    try:
        key = load_pem_private_key(private_key_pem, password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        msg = "la llave privada no es un PEM PKCS8 Ed25519 sin cifrar"
        raise ValueError(msg) from exc
    if not isinstance(key, Ed25519PrivateKey):
        msg = "la llave privada no es Ed25519 (EdDSA)"
        raise ValueError(msg)
    return key


def sign_token(
    private_key_pem: bytes,
    *,
    kid: str,
    issuer: str,
    audience: str,
    subject: str,
    tenant_id: str,
    roles: Collection[Role],
    ttl: timedelta,
    now: datetime,
) -> str:
    """Firma un token EdDSA.

    Args:
        private_key_pem: Llave privada Ed25519 (PEM PKCS8).
        kid: ``kid`` de la cabecera (el de su llave pública en el JWKS).
        issuer: Claim ``iss``.
        audience: Claim ``aud``.
        subject: Claim ``sub`` (``^[A-Za-z0-9_.@-]{1,128}$``).
        tenant_id: Claim ``tenant`` (``TENANT_PATTERN``).
        roles: Claim ``roles`` (al menos uno).
        ttl: Vida del token: más de cero segundos y hasta ``MAX_TOKEN_TTL``.
        now: Instante de emisión (con zona horaria).

    Returns:
        El token compacto.

    Raises:
        ValueError: Si algún argumento no es válido o la llave no es Ed25519.
    """
    _check_kid(kid)
    if not issuer or not audience:
        msg = "el emisor y la audiencia no pueden estar vacíos"
        raise ValueError(msg)
    if SUBJECT_PATTERN.fullmatch(subject) is None:
        msg = "el sujeto debe cumplir ^[A-Za-z0-9_.@-]{1,128}$"
        raise ValueError(msg)
    if TENANT_PATTERN.fullmatch(tenant_id) is None:
        msg = "el tenant debe cumplir ^[A-Za-z0-9_-]{1,64}$"
        raise ValueError(msg)
    if not roles or any(not isinstance(r, Role) for r in roles):
        msg = "hace falta al menos un rol conocido (analyst, approver, admin)"
        raise ValueError(msg)
    if ttl < timedelta(seconds=1) or ttl > MAX_TOKEN_TTL:
        msg = f"la vida del token debe estar entre 1 s y {MAX_TOKEN_TTL.days} días"
        raise ValueError(msg)
    if now.tzinfo is None:
        msg = "now necesita zona horaria"
        raise ValueError(msg)
    key = _load_private_key(private_key_pem)
    issued = int(now.timestamp())
    claims: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "tenant": tenant_id,
        "roles": sorted({r.value for r in roles}),
        "iat": issued,
        "nbf": issued,
        "exp": issued + int(ttl.total_seconds()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, key, algorithm=SIGNING_ALGORITHM, headers={"kid": kid, "typ": "JWT"})
