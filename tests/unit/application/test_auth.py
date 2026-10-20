"""Tipos de identidad de la aplicación: ``Principal``, roles y el error ``UNAUTHENTICATED``."""

from datetime import UTC, datetime

import pytest

from voracious.application.auth import (
    DEFAULT_TOKEN_TTL,
    MAX_TOKEN_TTL,
    TENANT_PATTERN,
    AuthenticationError,
    AuthFailure,
    Principal,
    Role,
)
from voracious.application.errors import ApplicationError

EXPIRES = datetime(2026, 10, 21, tzinfo=UTC)


def _principal(**overrides: object) -> Principal:
    values: dict[str, object] = {
        "subject": "ana",
        "tenant_id": "demo",
        "roles": frozenset({Role.ANALYST}),
        "expires_at": EXPIRES,
        "token_id": "j-1",
        **overrides,
    }
    return Principal(**values)


def test_principal_and_roles() -> None:
    principal = _principal(roles=frozenset({Role.ANALYST, Role.APPROVER}))
    assert principal.has_any({Role.APPROVER, Role.ADMIN})
    assert not principal.has_any({Role.ADMIN})
    assert [r.value for r in Role] == ["analyst", "approver", "admin"]
    with pytest.raises(AttributeError):
        principal.tenant_id = "otro"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"tenant_id": "a b"}, "tenant"),
        ({"tenant_id": "x" * 65}, "tenant"),
        ({"roles": frozenset()}, "rol"),
        ({"subject": ""}, "vacíos"),
        ({"token_id": ""}, "vacíos"),
        ({"expires_at": EXPIRES.replace(tzinfo=None)}, "zona horaria"),
    ],
)
def test_principal_invariants(overrides: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _principal(**overrides)


def test_authentication_error_has_code_and_closed_reason() -> None:
    error = AuthenticationError(AuthFailure.EXPIRED, "el token caducó")
    assert isinstance(error, ApplicationError)
    assert error.code == "UNAUTHENTICATED"
    assert error.details == {"reason": "expired"}
    assert error.reason is AuthFailure.EXPIRED
    assert AuthFailure.NO_CREDENTIALS.value == "missing_token"
    assert AuthFailure.LIFETIME_TOO_LONG.value == "lifetime_too_long"


def test_constants() -> None:
    assert TENANT_PATTERN.fullmatch("tenant_A-1")
    assert TENANT_PATTERN.fullmatch("tenant a") is None
    assert DEFAULT_TOKEN_TTL.total_seconds() == 8 * 3600
    assert MAX_TOKEN_TTL.days == 7
