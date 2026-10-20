"""Autenticación de la API: JWKS en fichero, verificación de JWT y emisión de tokens de nivel A.

Único lugar del proyecto que importa ``jwt`` (PyJWT ≥ 2.10.1) y ``cryptography`` (contrato 17
de import-linter). La API recibe el verificador a través de ``container``.
"""

from voracious.infrastructure.auth.jwks import PRIVATE_MEMBERS, JwksError, add_public_key, load_jwks
from voracious.infrastructure.auth.signing import (
    KID_PATTERN,
    SIGNING_ALGORITHM,
    SUBJECT_PATTERN,
    generate_ed25519_key,
    sign_token,
)
from voracious.infrastructure.auth.verifier import REQUIRED_CLAIMS, JwtTokenVerifier

__all__ = [
    "KID_PATTERN",
    "PRIVATE_MEMBERS",
    "REQUIRED_CLAIMS",
    "SIGNING_ALGORITHM",
    "SUBJECT_PATTERN",
    "JwksError",
    "JwtTokenVerifier",
    "add_public_key",
    "generate_ed25519_key",
    "load_jwks",
    "sign_token",
]
