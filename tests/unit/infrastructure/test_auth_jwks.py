"""JWKS en fichero: solo llaves públicas, asimétricas, con ``kid`` único y ``alg`` permitido."""

import json
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from support.auth import PUBLIC_JWK
from voracious.infrastructure.auth import (
    PRIVATE_MEMBERS,
    JwksError,
    add_public_key,
    generate_ed25519_key,
    load_jwks,
)

ALL = ("EdDSA", "ES256", "RS256", "PS256")


def _jwks(*keys: dict[str, Any]) -> str:
    return json.dumps({"keys": list(keys)})


def _ec_public(kid: str) -> dict[str, Any]:
    key = ec.generate_private_key(ec.SECP256R1()).public_key()
    return {**ECAlgorithm.to_jwk(key, as_dict=True), "kid": kid, "alg": "ES256"}


def _rsa_public(kid: str, alg: str = "RS256") -> dict[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    return {**RSAAlgorithm.to_jwk(key, as_dict=True), "kid": kid, "alg": alg}


def test_loads_public_keys_by_kid() -> None:
    _, other = generate_ed25519_key("k2")
    keys = load_jwks(
        _jwks(PUBLIC_JWK, other, _ec_public("e1"), _rsa_public("r1"), _rsa_public("p1", "PS256")),
        allowed_algorithms=ALL,
    )
    assert set(keys) == {"test-key", "k2", "e1", "r1", "p1"}
    assert {k: v.algorithm_name for k, v in keys.items()} == {
        "test-key": "EdDSA",
        "k2": "EdDSA",
        "e1": "ES256",
        "r1": "RS256",
        "p1": "PS256",
    }


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("{no es json", "JSON"),
        ("[]", "keys"),
        ('{"keys": {}}', "keys"),
        ('{"keys": []}', "ninguna llave"),
        ('{"keys": [1]}', "objeto"),
    ],
)
def test_rejects_malformed_documents(text: str, match: str) -> None:
    with pytest.raises(JwksError, match=match):
        load_jwks(text, allowed_algorithms=ALL)


def test_rejects_missing_or_repeated_kid_and_missing_or_disallowed_alg() -> None:
    no_kid = {k: v for k, v in PUBLIC_JWK.items() if k != "kid"}
    with pytest.raises(JwksError, match="kid"):
        load_jwks(_jwks(no_kid), allowed_algorithms=ALL)
    with pytest.raises(JwksError, match="kid"):
        load_jwks(_jwks({**PUBLIC_JWK, "kid": ""}), allowed_algorithms=ALL)
    with pytest.raises(JwksError, match="repetido"):
        load_jwks(_jwks(PUBLIC_JWK, PUBLIC_JWK), allowed_algorithms=ALL)
    no_alg = {k: v for k, v in PUBLIC_JWK.items() if k != "alg"}
    with pytest.raises(JwksError, match="alg"):
        load_jwks(_jwks(no_alg), allowed_algorithms=ALL)
    with pytest.raises(JwksError, match="alg"):
        load_jwks(_jwks(_ec_public("e1")), allowed_algorithms=("EdDSA",))
    with pytest.raises(JwksError, match="alg"):
        load_jwks(_jwks({**PUBLIC_JWK, "alg": "HS256"}), allowed_algorithms=ALL)


def test_rejects_symmetric_and_private_keys() -> None:
    with pytest.raises(JwksError, match="simétrica"):
        load_jwks(
            _jwks({"kty": "oct", "k": "c2VjcmV0", "kid": "s", "alg": "EdDSA"}),
            allowed_algorithms=ALL,
        )
    for member in sorted(PRIVATE_MEMBERS - {"k"}):
        with pytest.raises(JwksError, match="privados"):
            load_jwks(_jwks({**PUBLIC_JWK, member: "AAAA"}), allowed_algorithms=ALL)
    with pytest.raises(JwksError, match="firma"):
        load_jwks(_jwks({**PUBLIC_JWK, "use": "enc"}), allowed_algorithms=ALL)


def test_rejects_a_key_that_does_not_match_its_alg() -> None:
    with pytest.raises(JwksError, match="no es una llave ES256"):
        load_jwks(_jwks({**PUBLIC_JWK, "alg": "ES256"}), allowed_algorithms=ALL)
    with pytest.raises(JwksError, match="no es una llave EdDSA"):
        load_jwks(_jwks({**PUBLIC_JWK, "x": "!!"}), allowed_algorithms=ALL)


def test_error_messages_never_include_key_material() -> None:
    leaked = {**PUBLIC_JWK, "d": "MATERIAL-PRIVADO"}
    with pytest.raises(JwksError) as info:
        load_jwks(_jwks(leaked), allowed_algorithms=ALL)
    assert "MATERIAL-PRIVADO" not in str(info.value)
    assert PUBLIC_JWK["x"] not in str(info.value)


def test_add_public_key_is_deterministic_and_rejects_duplicates_and_private_members() -> None:
    _, second = generate_ed25519_key("k2")
    first = add_public_key(None, PUBLIC_JWK)
    assert first.endswith("}\n")
    assert first == json.dumps({"keys": [PUBLIC_JWK]}, sort_keys=True, indent=2) + "\n"
    both = add_public_key(first, second)
    assert [k["kid"] for k in json.loads(both)["keys"]] == ["test-key", "k2"]
    assert add_public_key(first, second) == both
    assert set(load_jwks(both, allowed_algorithms=("EdDSA",))) == {"test-key", "k2"}
    with pytest.raises(JwksError, match="ya está"):
        add_public_key(both, second)
    with pytest.raises(JwksError, match="privados"):
        add_public_key(first, {**second, "kid": "k3", "d": "x"})
    with pytest.raises(JwksError, match="alg"):
        add_public_key(first, {k: v for k, v in second.items() if k != "alg"} | {"kid": "k4"})
    with pytest.raises(JwksError, match="JSON"):
        add_public_key("no es json", second)
