"""CLI ``issue-token`` y ``jwt-keygen``: por stdout solo el token o la llave, códigos 0/1/2."""

import io
import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from support.auth import (
    JWKS_FILE,
    OTHER_KEY_PEM,
    PRIVATE_KEY_PEM,
    TEST_AUDIENCE,
    TEST_ISSUER,
    TEST_KID,
    auth_settings,
)
from support.postgres import admin_url, temporary_database
from voracious import cli
from voracious.api.app import create_app
from voracious.container import build_container


class _Stream(io.TextIOWrapper):
    """Entrada o salida estándar falsa con ``isatty`` controlado y ``buffer`` binario."""

    def __init__(self, data: bytes = b"", *, tty: bool = False) -> None:
        super().__init__(io.BytesIO(data), encoding="utf-8")
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def written(self) -> bytes:
        self.flush()
        raw = self.buffer
        assert isinstance(raw, io.BytesIO)
        return raw.getvalue()


@pytest.fixture
def jwt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VORACIOUS_JWT_ISSUER", TEST_ISSUER)
    monkeypatch.setenv("VORACIOUS_JWT_AUDIENCE", TEST_AUDIENCE)
    monkeypatch.setenv("VORACIOUS_JWT_JWKS_FILE", str(JWKS_FILE))


def _issue(
    monkeypatch: pytest.MonkeyPatch, *extra: str, stdin: bytes = PRIVATE_KEY_PEM, tty: bool = False
) -> tuple[int, str, str]:
    out, err = _Stream(), io.StringIO()
    monkeypatch.setattr("sys.stdin", _Stream(stdin, tty=tty))
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    args = ["issue-token", "--tenant", "demo", "--roles", "analyst", "--subject", "ana"]
    code = cli.main([*args, "--kid", TEST_KID, *extra])
    return code, out.written().decode(), err.getvalue()


@pytest.mark.usefixtures("jwt_env")
def test_issue_token_prints_only_the_token_and_it_works_against_the_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, out, err = _issue(monkeypatch, "--ttl", "30m")
    assert code == 0, err
    raw = out.strip()
    assert out == f"{raw}\n"
    assert raw.count(".") == 2
    assert raw not in err
    assert "tenant=demo" in err
    assert "roles=analyst" in err
    monkeypatch.undo()
    with TestClient(create_app(build_container(auth_settings()))) as client:
        response = client.get("/v1/datasets/nope", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "DATASET_NOT_FOUND"


@pytest.mark.usefixtures("jwt_env")
def test_issue_token_reads_the_key_from_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = tmp_path / "key.pem"
    key.write_bytes(PRIVATE_KEY_PEM)
    code, out, _ = _issue(monkeypatch, "--private-key-file", str(key), stdin=b"")
    assert code == 0
    assert out.count(".") == 2
    code, _, err = _issue(monkeypatch, "--private-key-file", str(tmp_path / "no"), stdin=b"")
    assert code == 1
    assert "no se puede leer --private-key-file" in err


@pytest.mark.usefixtures("jwt_env")
@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (("--ttl", "8d"), "--ttl"),
        (("--ttl", "0h"), "--ttl"),
        (("--ttl", "8x"), "--ttl"),
        (("--roles", "root"), "roles desconocidos"),
        (("--roles", " , "), "--roles"),
        (("--tenant", "a b"), "tenant"),
        (("--subject", "con espacio"), "sujeto"),
    ],
)
def test_issue_token_invalid_input_exits_1(
    monkeypatch: pytest.MonkeyPatch, extra: tuple[str, ...], message: str
) -> None:
    code, out, err = _issue(monkeypatch, *extra)
    assert (code, out) == (1, "")
    assert message in err


@pytest.mark.usefixtures("jwt_env")
def test_issue_token_refuses_a_key_typed_in_a_terminal_and_bad_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, out, err = _issue(monkeypatch, tty=True)
    assert (code, out) == (1, "")
    assert "tubería" in err
    code, out, err = _issue(monkeypatch, stdin=b"no es un pem")
    assert (code, out) == (1, "")
    assert "PEM" in err
    code, out, err = _issue(monkeypatch, stdin=OTHER_KEY_PEM)  # no es la llave de su kid
    assert (code, out) == (1, "")
    assert "bad_signature" in err


@pytest.mark.usefixtures("jwt_env")
def test_issue_token_with_an_unknown_kid_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = _Stream(), io.StringIO()
    monkeypatch.setattr("sys.stdin", _Stream(PRIVATE_KEY_PEM))
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    args = ["issue-token", "--tenant", "demo", "--roles", "admin", "--subject", "s", "--kid", "x"]
    assert cli.main(args) == 1
    assert "unknown_key" in err.getvalue()
    assert out.written() == b""


def test_issue_token_without_issuer_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VORACIOUS_JWT_ISSUER", raising=False)
    monkeypatch.setenv("VORACIOUS_JWT_AUDIENCE", TEST_AUDIENCE)
    code, out, err = _issue(monkeypatch)
    assert (code, out) == (2, "")
    assert "VORACIOUS_JWT_ISSUER" in err


def _keygen(
    monkeypatch: pytest.MonkeyPatch, jwks: Path, kid: str, *, tty: bool = False
) -> tuple[int, bytes, str]:
    out, err = _Stream(tty=tty), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    code = cli.main(["jwt-keygen", "--kid", kid, "--jwks", str(jwks)])
    return code, out.written(), err.getvalue()


def test_jwt_keygen_writes_the_public_jwks_and_prints_the_private_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jwks = tmp_path / "jwks.json"
    code, pem, err = _keygen(monkeypatch, jwks, "demo-2026-10")
    assert code == 0, err
    assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")
    document = json.loads(jwks.read_text(encoding="utf-8"))
    assert [k["kid"] for k in document["keys"]] == ["demo-2026-10"]
    assert "d" not in document["keys"][0]
    assert stat.S_IMODE(jwks.stat().st_mode) == 0o644
    assert b"PRIVATE" not in jwks.read_bytes()
    code, second, _ = _keygen(monkeypatch, jwks, "demo-2026-11")
    assert code == 0
    assert second != pem
    kids = [k["kid"] for k in json.loads(jwks.read_text(encoding="utf-8"))["keys"]]
    assert kids == ["demo-2026-10", "demo-2026-11"]
    assert list(tmp_path.iterdir()) == [jwks]  # sin temporales


def test_jwt_keygen_with_a_repeated_kid_leaves_the_file_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jwks = tmp_path / "jwks.json"
    assert _keygen(monkeypatch, jwks, "k1")[0] == 0
    before = jwks.read_bytes()
    code, out, err = _keygen(monkeypatch, jwks, "k1")
    assert (code, out) == (1, b"")
    assert "ya está" in err
    assert jwks.read_bytes() == before
    assert _keygen(monkeypatch, jwks, "con espacio")[0] == 1
    jwks.write_text("no es json", encoding="utf-8")
    assert _keygen(monkeypatch, jwks, "k2")[0] == 1
    assert _keygen(monkeypatch, tmp_path / "no" / "jwks.json", "k3")[0] == 1


def test_jwt_keygen_refuses_to_print_the_key_in_a_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jwks = tmp_path / "jwks.json"
    code, out, err = _keygen(monkeypatch, jwks, "k1", tty=True)
    assert (code, out) == (2, b"")
    assert "terminal" in err
    assert not jwks.exists()


def test_migrate_reads_the_url_from_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with temporary_database(admin_url()) as url:
        secret = tmp_path / "database_url"
        secret.write_text(f"{url}\n", encoding="utf-8")
        monkeypatch.setenv("VORACIOUS_REPOSITORY", "postgres")
        monkeypatch.delenv("VORACIOUS_DATABASE_URL", raising=False)
        monkeypatch.setenv("VORACIOUS_DATABASE_URL_FILE", str(secret))
        assert cli.main(["migrate"]) == 0
        assert "0001" in capsys.readouterr().out
        monkeypatch.setenv("VORACIOUS_DATABASE_URL", url)
        assert cli.main(["migrate"]) == 2
        assert "excluyentes" in capsys.readouterr().err
