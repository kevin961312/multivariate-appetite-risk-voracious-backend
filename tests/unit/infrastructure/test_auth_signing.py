"""Emisión de tokens de nivel A: llave Ed25519, claims completos y validación de argumentos."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from support.auth import PRIVATE_KEY_PEM
from voracious.application.auth import MAX_TOKEN_TTL, Role
from voracious.infrastructure.auth import (
    PRIVATE_MEMBERS,
    add_public_key,
    generate_ed25519_key,
    load_jwks,
    sign_token,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _sign(**overrides: object) -> str:
    key = overrides.pop("key", PRIVATE_KEY_PEM)
    kwargs: dict[str, Any] = {
        "kid": "k1",
        "issuer": "iss",
        "audience": "aud",
        "subject": "ana",
        "tenant_id": "demo",
        "roles": (Role.APPROVER, Role.ANALYST, Role.ANALYST),
        "ttl": timedelta(hours=8),
        "now": NOW,
        **overrides,
    }
    return sign_token(key, **kwargs)


def test_generated_key_is_pkcs8_and_its_jwk_is_public() -> None:
    pem, jwk = generate_ed25519_key("demo-2026-10")
    assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")
    assert jwk["kty"] == "OKP"
    assert (jwk["crv"], jwk["alg"], jwk["use"], jwk["kid"]) == (
        "Ed25519",
        "EdDSA",
        "sig",
        "demo-2026-10",
    )
    assert not PRIVATE_MEMBERS & set(jwk)
    assert set(load_jwks(add_public_key(None, jwk), allowed_algorithms=("EdDSA",))) == {
        "demo-2026-10"
    }
    with pytest.raises(ValueError, match="kid"):
        generate_ed25519_key("con espacio")


def test_token_carries_every_claim_and_the_kid() -> None:
    raw = _sign()
    header = jwt.get_unverified_header(raw)
    assert header == {"alg": "EdDSA", "kid": "k1", "typ": "JWT"}
    body = jwt.decode(raw, options={"verify_signature": False})
    issued = int(NOW.timestamp())
    assert body["iss"] == "iss"
    assert body["aud"] == "aud"
    assert body["sub"] == "ana"
    assert body["tenant"] == "demo"
    assert body["roles"] == ["analyst", "approver"]  # ordenados y sin repetir
    assert (body["iat"], body["nbf"], body["exp"]) == (issued, issued, issued + 8 * 3600)
    assert uuid.UUID(body["jti"]).version == 4
    assert _sign()  # cada token lleva su jti
    assert jwt.decode(_sign(), options={"verify_signature": False})["jti"] != body["jti"]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"kid": ""}, "kid"),
        ({"issuer": ""}, "emisor"),
        ({"audience": ""}, "audiencia"),
        ({"subject": "con espacio"}, "sujeto"),
        ({"subject": "x" * 129}, "sujeto"),
        ({"tenant_id": "a b"}, "tenant"),
        ({"roles": ()}, "rol"),
        ({"roles": ("admin",)}, "rol"),
        ({"ttl": timedelta(0)}, "vida"),
        ({"ttl": MAX_TOKEN_TTL + timedelta(seconds=1)}, "vida"),
        ({"now": NOW.replace(tzinfo=None)}, "zona horaria"),
    ],
)
def test_invalid_arguments(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _sign(**overrides)


def test_max_ttl_is_accepted() -> None:
    body = jwt.decode(_sign(ttl=MAX_TOKEN_TTL), options={"verify_signature": False})
    assert body["exp"] - body["iat"] == int(MAX_TOKEN_TTL.total_seconds())


def test_only_unencrypted_ed25519_pem_keys_are_accepted() -> None:
    ec_key = ec.generate_private_key(ec.SECP256R1())
    ec_pem = ec_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    with pytest.raises(ValueError, match="no es Ed25519"):
        _sign(key=ec_pem)
    with pytest.raises(ValueError, match="PEM"):
        _sign(key=b"no es un pem")
    encrypted = ec_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(b"clave")
    )
    with pytest.raises(ValueError, match="PEM") as info:
        _sign(key=encrypted)
    assert "BEGIN" not in str(info.value)
