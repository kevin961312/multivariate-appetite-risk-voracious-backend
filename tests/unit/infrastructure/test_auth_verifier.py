"""``JwtTokenVerifier``: un test por motivo de rechazo y la ida y vuelta firma → verificación."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import structlog
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)

from support.auth import (
    JWKS_FILE,
    OTHER_KEY_PEM,
    PRIVATE_KEY_PEM,
    PUBLIC_JWK,
    TEST_AUDIENCE,
    TEST_ISSUER,
    claims,
    forge,
    token,
)
from voracious.application.auth import (
    MAX_TOKEN_BYTES,
    AuthenticationError,
    AuthFailure,
    Principal,
    Role,
)
from voracious.infrastructure.auth import REQUIRED_CLAIMS, JwtTokenVerifier, load_jwks

LEEWAY = timedelta(seconds=30)


def _verifier(algorithms: tuple[str, ...] = ("EdDSA",)) -> JwtTokenVerifier:
    keys = load_jwks(JWKS_FILE.read_text(encoding="utf-8"), allowed_algorithms=algorithms)
    return JwtTokenVerifier(
        keys, issuer=TEST_ISSUER, audience=TEST_AUDIENCE, algorithms=algorithms, leeway=LEEWAY
    )


def _reason(raw: str, verifier: JwtTokenVerifier | None = None) -> AuthFailure:
    with pytest.raises(AuthenticationError) as info:
        (verifier or _verifier()).verify(raw)
    error = info.value
    assert error.code == "UNAUTHENTICATED"
    assert error.details == {"reason": error.reason.value}
    if raw:
        assert raw not in error.message
    return error.reason


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _raw(header: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    """Token sin firma válida (para comprobar la cabecera antes de la firma)."""
    body = claims() if payload is None else payload
    return ".".join(
        (_b64(json.dumps(header).encode()), _b64(json.dumps(body).encode()), _b64(b"firma"))
    )


def _segments(header: dict[str, Any], payload: dict[str, Any]) -> bytes:
    return f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(payload).encode())}".encode()


def _signed(header: dict[str, Any], payload: dict[str, Any]) -> str:
    """Token EdDSA firmado a mano con la llave de la sesión (claims que PyJWT no deja emitir)."""
    key = load_pem_private_key(PRIVATE_KEY_PEM, None)
    assert isinstance(key, Ed25519PrivateKey)
    signing_input = _segments(header, payload)
    return f"{signing_input.decode()}.{_b64(key.sign(signing_input))}"


def _hs256(secret: bytes) -> str:
    """Token HS256 hecho a mano (PyJWT se niega a usar una llave pública como secreto)."""
    signing_input = _segments({"alg": "HS256", "kid": "test-key", "typ": "JWT"}, claims())
    digest = hmac.new(secret, signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode()}.{_b64(digest)}"


def _now() -> int:
    return int(datetime.now(UTC).timestamp())


def test_round_trip_gives_the_principal() -> None:
    raw = token("tenant-x", roles=(Role.ANALYST, Role.APPROVER), subject="ana@banco")
    principal = _verifier().verify(raw)
    assert isinstance(principal, Principal)
    assert (principal.subject, principal.tenant_id) == ("ana@banco", "tenant-x")
    assert principal.roles == frozenset({Role.ANALYST, Role.APPROVER})
    assert principal.expires_at.tzinfo is not None
    assert principal.expires_at > datetime.now(UTC) + timedelta(hours=7)
    assert principal.token_id


def test_signature_from_another_key_with_the_same_kid() -> None:
    assert _reason(forge(key=OTHER_KEY_PEM)) is AuthFailure.BAD_SIGNATURE


def test_unknown_or_missing_kid() -> None:
    assert _reason(forge(headers={"kid": "otra-llave"})) is AuthFailure.UNKNOWN_KEY
    assert _reason(forge(headers={"kid": None})) is AuthFailure.UNKNOWN_KEY
    assert _reason(_raw({"alg": "EdDSA", "kid": 5})) is AuthFailure.MALFORMED


def test_alg_none_is_never_allowed() -> None:
    assert _reason(forge(algorithm="none")) is AuthFailure.ALGORITHM_NOT_ALLOWED
    assert _reason(_raw({"alg": "none", "kid": "test-key"})) is AuthFailure.ALGORITHM_NOT_ALLOWED
    assert _reason(_raw({"kid": "test-key"})) is AuthFailure.ALGORITHM_NOT_ALLOWED


def test_hs256_signed_with_the_public_key_bytes_is_rejected() -> None:
    """Confusión de algoritmo: HMAC con la llave pública como secreto."""
    public_bytes = base64.urlsafe_b64decode(PUBLIC_JWK["x"] + "=")
    forged = forge(algorithm="HS256", key=public_bytes)
    assert _reason(forged) is AuthFailure.ALGORITHM_NOT_ALLOWED
    assert _reason(forged, _verifier(("EdDSA", "ES256", "RS256", "PS256"))) is (
        AuthFailure.ALGORITHM_NOT_ALLOWED
    )
    jwk_text = json.dumps(PUBLIC_JWK).encode()
    assert _reason(_hs256(jwk_text)) is AuthFailure.ALGORITHM_NOT_ALLOWED
    assert _reason(_hs256(JWKS_FILE.read_bytes())) is AuthFailure.ALGORITHM_NOT_ALLOWED


def test_alg_different_from_the_jwk_of_its_kid() -> None:
    ec_pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    forged = forge(algorithm="ES256", key=ec_pem)  # kid test-key es Ed25519
    assert _reason(forged, _verifier(("EdDSA", "ES256"))) is AuthFailure.ALGORITHM_NOT_ALLOWED


def test_expired_and_the_leeway() -> None:
    now = _now()
    assert _reason(forge(claims(iat=now - 3600, exp=now - 60))) is AuthFailure.EXPIRED
    principal = _verifier().verify(forge(claims(iat=now - 3600, exp=now - 10)))
    assert principal.subject == "test"


def test_iat_or_nbf_in_the_future() -> None:
    now = _now()
    assert _reason(forge(claims(iat=now + 120, exp=now + 3600))) is AuthFailure.NOT_YET_VALID
    assert _reason(forge(claims(nbf=now + 120))) is AuthFailure.NOT_YET_VALID
    assert _verifier().verify(forge(claims(iat=now + 10, nbf=now + 10))).subject == "test"


@pytest.mark.parametrize(
    "issuer", ["otro-emisor", "voracious-tes", "voracious", "-test", "voracious-test-2", "test"]
)
def test_wrong_issuer_including_prefix_and_substring(issuer: str) -> None:
    """Regresión CVE-2024-53861 (PyJWT 2.10.0 comparaba ``iss`` como subcadena)."""
    assert _reason(forge(claims(iss=issuer))) is AuthFailure.WRONG_ISSUER


@pytest.mark.parametrize("issuer", [[TEST_ISSUER], [f"{TEST_ISSUER}x", TEST_ISSUER], 5])
def test_issuer_must_be_exactly_the_configured_string(issuer: object) -> None:
    header = {"alg": "EdDSA", "kid": "test-key", "typ": "JWT"}
    assert _reason(_signed(header, claims(iss=issuer))) is AuthFailure.WRONG_ISSUER


@pytest.mark.parametrize("audience", ["otra-api", "voracious-api", [TEST_AUDIENCE], ""])
def test_wrong_audience(audience: object) -> None:
    expected = AuthFailure.MISSING_CLAIM if audience == "" else AuthFailure.WRONG_AUDIENCE
    assert _reason(forge(claims(aud=audience))) is expected


@pytest.mark.parametrize("claim", REQUIRED_CLAIMS)
def test_every_required_claim(claim: str) -> None:
    assert _reason(forge(claims(**{claim: None}))) is AuthFailure.MISSING_CLAIM


@pytest.mark.parametrize("tenant", ["a b", "x" * 65, "", 5, ["tenant-a"], "../t"])
def test_invalid_tenant(tenant: object) -> None:
    assert _reason(forge(claims(tenant=tenant))) is AuthFailure.INVALID_CLAIM


@pytest.mark.parametrize("roles", [[], ["root"], "admin", [1], ["admin", "superadmin"], {}])
def test_invalid_roles(roles: object) -> None:
    assert _reason(forge(claims(roles=roles))) is AuthFailure.INVALID_CLAIM


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"sub": ""}, AuthFailure.INVALID_CLAIM),
        ({"sub": 5}, AuthFailure.INVALID_CLAIM),
        ({"sub": "a\nb"}, AuthFailure.INVALID_CLAIM),
        ({"sub": "x" * 257}, AuthFailure.INVALID_CLAIM),
        ({"jti": ""}, AuthFailure.INVALID_CLAIM),
        ({"jti": 5}, AuthFailure.INVALID_CLAIM),
        ({"jti": "j" * 129}, AuthFailure.INVALID_CLAIM),
        ({"iat": str(_now())}, AuthFailure.INVALID_CLAIM),
        ({"iat": True}, AuthFailure.INVALID_CLAIM),
        ({"nbf": str(_now())}, AuthFailure.INVALID_CLAIM),
        ({"exp": "mañana"}, AuthFailure.MALFORMED),
    ],
)
def test_invalid_registered_claims(overrides: dict[str, Any], reason: AuthFailure) -> None:
    assert _reason(forge(claims(**overrides))) is reason


def test_lifetime_longer_than_seven_days_and_exp_not_after_iat() -> None:
    """Mejora M4: la API rechaza tokens de vida larga aunque estén bien firmados."""
    now = _now()
    eight_days = forge(claims(iat=now, exp=now + 8 * 86400))
    assert _reason(eight_days) is AuthFailure.LIFETIME_TOO_LONG
    assert _verifier().verify(forge(claims(iat=now, exp=now + 7 * 86400))).subject == "test"
    assert _reason(forge(claims(iat=now + 20, nbf=now, exp=now + 20))) is (
        AuthFailure.INVALID_CLAIM
    )


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "abc",
        "a.b",
        "a.b.c.d",
        "!!!.###.$$$",
        "eyJ.e30.x",
        f"{_b64(b'[1]')}.{_b64(b'{}')}.{_b64(b'x')}",
        f"{_b64(b'no json')}.{_b64(b'{}')}.{_b64(b'x')}",
    ],
)
def test_corrupt_tokens(raw: str) -> None:
    assert _reason(raw) is AuthFailure.MALFORMED


def test_oversized_token_and_forbidden_headers() -> None:
    huge = forge(claims(padding="x" * MAX_TOKEN_BYTES))
    assert len(huge) > MAX_TOKEN_BYTES
    assert _reason(huge) is AuthFailure.MALFORMED
    header = {"alg": "EdDSA", "kid": "test-key"}
    assert _reason(_raw({**header, "crit": ["exp"]})) is AuthFailure.MALFORMED
    assert _reason(_raw({**header, "b64": False, "crit": ["b64"]})) is AuthFailure.MALFORMED


def test_the_verifier_needs_keys_issuer_audience_and_algorithms() -> None:
    keys = load_jwks(JWKS_FILE.read_text(encoding="utf-8"), allowed_algorithms=("EdDSA",))
    for kwargs in (
        {"keys": {}, "issuer": "i", "audience": "a", "algorithms": ("EdDSA",)},
        {"keys": keys, "issuer": "", "audience": "a", "algorithms": ("EdDSA",)},
        {"keys": keys, "issuer": "i", "audience": "", "algorithms": ("EdDSA",)},
        {"keys": keys, "issuer": "i", "audience": "a", "algorithms": ()},
    ):
        with pytest.raises(ValueError, match="necesita"):
            JwtTokenVerifier(
                kwargs["keys"],
                issuer=kwargs["issuer"],
                audience=kwargs["audience"],
                algorithms=kwargs["algorithms"],
                leeway=LEEWAY,
            )


def test_the_verifier_never_logs_the_token() -> None:
    good = token()
    bad = forge(key=OTHER_KEY_PEM)
    with structlog.testing.capture_logs() as logs:
        _verifier().verify(good)
        with pytest.raises(AuthenticationError):
            _verifier().verify(bad)
    text = json.dumps(logs, default=str)
    for raw in (good, bad):
        for part in raw.split(".")[1:]:
            assert part not in text
