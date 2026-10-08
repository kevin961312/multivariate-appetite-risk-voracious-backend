"""Catálogo de códigos → HTTP (T9): todo código mapeado responde su estado y su cuerpo."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from voracious.api.errors import CODE_TO_STATUS, ApiError, install_error_handlers
from voracious.api.tenant import TENANT_REQUIRED
from voracious.application import errors as app_errors
from voracious.application.errors import ApplicationError
from voracious.domain.common import DomainError, InvalidInputError

_RAISE: dict[str, Exception] = {}


def _subclasses(cls: type[ApplicationError]) -> Iterator[type[ApplicationError]]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


APPLICATION_ERRORS = sorted(
    {c for c in _subclasses(ApplicationError) if c.__module__ == app_errors.__name__},
    key=lambda c: c.code,
)


class _Body(BaseModel):
    n: int


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/raise/{key}")
    def raise_it(key: str) -> None:
        raise _RAISE[key]

    @app.post("/body")
    def body(payload: _Body) -> int:
        return payload.n

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _call(client: TestClient, exc: Exception) -> tuple[int, dict[str, object]]:
    key = str(len(_RAISE))
    _RAISE[key] = exc
    response = client.get(f"/raise/{key}")
    return response.status_code, response.json()


def test_every_application_error_code_is_mapped() -> None:
    missing = [c.code for c in APPLICATION_ERRORS if c.code not in CODE_TO_STATUS]
    assert missing == [], f"códigos sin estado HTTP en CODE_TO_STATUS: {missing}"
    assert {InvalidInputError.CODE, TENANT_REQUIRED, "INTERNAL_ERROR"} <= set(CODE_TO_STATUS)


@pytest.mark.parametrize("cls", APPLICATION_ERRORS, ids=lambda c: c.code)
def test_application_errors_respond_with_their_status(
    client: TestClient, cls: type[ApplicationError]
) -> None:
    status, body = _call(client, cls("mensaje", {"k": 1}))
    assert status == CODE_TO_STATUS[cls.code]
    assert body == {"code": cls.code, "message": "mensaje", "details": {"k": 1}}


@pytest.mark.parametrize(("code", "status"), sorted(CODE_TO_STATUS.items()))
def test_every_catalog_code_round_trips(client: TestClient, code: str, status: int) -> None:
    got, body = _call(client, ApiError(code, "m"))
    assert got == status
    assert body["code"] == code


def test_unmapped_codes_and_unexpected_errors_are_internal(client: TestClient) -> None:
    class _UnmappedError(ApplicationError):
        code = "NOT_IN_TABLE"

    assert _call(client, _UnmappedError("x"))[0] == 500
    assert _call(client, ApiError("NOT_IN_TABLE", "x"))[1]["code"] == "INTERNAL_ERROR"
    status, body = _call(client, RuntimeError("traza secreta"))
    assert status == 500
    assert body == {"code": "INTERNAL_ERROR", "message": "error interno", "details": {}}


def test_domain_errors(client: TestClient) -> None:
    assert _call(client, InvalidInputError("malo", {"input": "x"})) == (
        422,
        {"code": "INVALID_INPUT", "message": "malo", "details": {"input": "x"}},
    )
    assert _call(client, DomainError("T2MRCD_DECISION_PENDING", "p"))[0] == 422


def test_validation_and_routing_errors(client: TestClient) -> None:
    response = client.post("/body", json={"n": "no"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INVALID_INPUT"
    assert body["details"]["errors"][0]["loc"] == ["body", "n"]
    assert client.get("/nada").json()["code"] == "ROUTE_NOT_FOUND"
    assert client.delete("/body").json()["code"] == "METHOD_NOT_ALLOWED"
    status, body = _call(client, HTTPException(status_code=418, detail="tetera"))
    assert (status, body["code"]) == (418, "HTTP_ERROR")
