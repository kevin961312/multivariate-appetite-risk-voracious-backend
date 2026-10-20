"""Tokens de PRUEBA (SOLO TEST): un par Ed25519 por sesión y su JWKS en un directorio temporal.

La llave se genera al importar el módulo, nunca se escribe en el repositorio y muere con el
proceso de pytest (el directorio temporal se borra al salir). Los tests de la API construyen el
contenedor con ``auth_settings(...)`` y llaman con ``bearer(...)``; los casos negativos fabrican
tokens a mano con ``forge(...)``.
"""

import atexit
import shutil
import tempfile
import uuid
from collections.abc import Collection, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from voracious.application.auth import DEFAULT_TOKEN_TTL, Role
from voracious.config import Settings
from voracious.infrastructure.auth import add_public_key, generate_ed25519_key, sign_token

TEST_KID = "test-key"
TEST_ISSUER = "voracious-test"
TEST_AUDIENCE = "voracious-api-test"
DEFAULT_TENANT = "tenant-a"

_DIR = Path(tempfile.mkdtemp(prefix="voracious-test-jwks-"))
atexit.register(shutil.rmtree, _DIR, ignore_errors=True)

PRIVATE_KEY_PEM, PUBLIC_JWK = generate_ed25519_key(TEST_KID)
"""Llave de firma de la sesión (SOLO TEST) y su JWK público."""

OTHER_KEY_PEM, _ = generate_ed25519_key(TEST_KID)
"""Otra llave con el **mismo** ``kid`` (para el caso de firma inválida)."""

JWKS_FILE = _DIR / "jwks.json"
JWKS_FILE.write_text(add_public_key(None, PUBLIC_JWK), encoding="utf-8")

TEST_RATE_LIMIT = 1_000_000
"""Límite de peticiones (por minuto y ráfaga) de los tests de la API (SOLO TEST).

``TestClient`` llama siempre como el cliente ``testclient`` (no es loopback, así que no está
exento) y una suite dispara cientos de peticiones por segundo contra la misma aplicación: con los
valores por defecto (600/min, ráfaga de 120) acabaría en ``429``. El limitador se prueba con sus
valores por defecto en ``tests/unit/test_rate_limit.py`` (se pasan explícitos a ``auth_settings``).
"""


def auth_settings(**overrides: object) -> Settings:
    """``Settings`` con la autenticación de prueba (JWKS temporal, emisor y audiencia de test).

    El límite de peticiones queda en ``TEST_RATE_LIMIT`` salvo que se pase otro en ``overrides``.
    """
    values: dict[str, Any] = {
        "jwt_jwks_file": JWKS_FILE,
        "jwt_issuer": TEST_ISSUER,
        "jwt_audience": TEST_AUDIENCE,
        "rate_limit_per_minute": TEST_RATE_LIMIT,
        "rate_limit_burst": TEST_RATE_LIMIT,
        **overrides,
    }
    return Settings(**values)


def token(
    tenant: str = DEFAULT_TENANT,
    roles: Collection[Role] = (Role.ADMIN,),
    subject: str = "test",
    ttl: timedelta = DEFAULT_TOKEN_TTL,
) -> str:
    """Token válido firmado con la llave de la sesión."""
    return sign_token(
        PRIVATE_KEY_PEM,
        kid=TEST_KID,
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        subject=subject,
        tenant_id=tenant,
        roles=roles,
        ttl=ttl,
        now=datetime.now(UTC),
    )


def bearer(
    tenant: str = DEFAULT_TENANT,
    roles: Collection[Role] = (Role.ADMIN,),
    subject: str = "test",
    ttl: timedelta = DEFAULT_TOKEN_TTL,
) -> dict[str, str]:
    """Cabecera ``Authorization: Bearer`` con un token válido."""
    return {"Authorization": f"Bearer {token(tenant, roles, subject, ttl)}"}


def claims(**overrides: object) -> dict[str, Any]:
    """Claims válidos de prueba; un valor ``None`` en ``overrides`` quita ese claim."""
    now = int(datetime.now(UTC).timestamp())
    base: dict[str, Any] = {
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "sub": "test",
        "tenant": DEFAULT_TENANT,
        "roles": ["admin"],
        "iat": now,
        "nbf": now,
        "exp": now + 3600,
        "jti": str(uuid.uuid4()),
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def forge(
    payload: Mapping[str, Any] | None = None,
    *,
    key: bytes = PRIVATE_KEY_PEM,
    headers: Mapping[str, Any] | None = None,
    algorithm: str = "EdDSA",
) -> str:
    """Token fabricado a mano (casos negativos): claims, llave, cabecera y algoritmo a elección.

    Un valor ``None`` en ``headers`` quita esa cabecera (p. ej. ``{"kid": None}``). Con
    ``algorithm="HS256"`` ``key`` se usa tal cual como secreto (confusión de algoritmo); con
    ``"none"`` no se firma.
    """
    body = dict(claims() if payload is None else payload)
    head = {k: v for k, v in {"kid": TEST_KID, **(headers or {})}.items() if v is not None}
    signing_key: Any
    if algorithm == "none":
        signing_key = None
    elif algorithm.startswith("HS"):
        signing_key = key
    else:
        signing_key = load_pem_private_key(key, None)
    return jwt.encode(body, signing_key, algorithm=algorithm, headers=head)
