"""Scripts de despliegue con sops + age reales (opcional: se salta sin ``sops`` o ``age-keygen``).

Todo en directorios temporales con una llave age de PRUEBA: ``deploy.sh --decrypt-only`` crea el
directorio 0700 con ficheros 0444, rechaza llaves abiertas, directorios dentro del repo y ``.env``
con secretos; ``jwt_keygen.sh`` + ``issue_token.sh --via uv`` emiten un token que verifica con el
JWKS generado. Ningún valor secreto aparece en la salida.
"""

import json
import os
import shutil
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from support.repo_secrets import ROOT, jwks_problems, sops_file_problems
from support.tools import run_tool
from voracious.infrastructure.auth import JwtTokenVerifier, load_jwks

SOPS = shutil.which("sops")
AGE_KEYGEN = shutil.which("age-keygen")
BASH = shutil.which("bash")
UV = shutil.which("uv")

pytestmark = pytest.mark.skipif(
    SOPS is None or AGE_KEYGEN is None or BASH is None, reason="sin sops, age-keygen o bash"
)

FAKE_PG_CREDENTIAL = "contraseña-de-prueba-9f2"
URL = "postgresql://voracious:contrase%C3%B1a-de-prueba-9f2@postgres:5432/voracious"


@dataclass(frozen=True)
class Age:
    """Llave age de PRUEBA y su receptor público."""

    key_file: Path
    recipient: str


def _run(args: list[str], env: Mapping[str, str]) -> CompletedProcess[str]:
    full_env = {**os.environ, "UV_NO_SYNC": "1", **env}
    full_env.pop("DEPLOY_SECRETS_DIR", None)
    return run_tool(args, env=full_env)


@pytest.fixture
def age(tmp_path: Path) -> Age:
    assert AGE_KEYGEN is not None
    key_file = tmp_path / "keys.txt"
    run_tool([AGE_KEYGEN, "-o", str(key_file)], check=True)
    key_file.chmod(0o600)
    recipient = run_tool([AGE_KEYGEN, "-y", str(key_file)], check=True).stdout.strip()
    return Age(key_file, recipient)


def _encrypt(age: Age, target: Path, plaintext: str) -> None:
    assert SOPS is not None
    result = run_tool(
        [
            SOPS,
            "--disable-version-check",
            "encrypt",
            "--age",
            age.recipient,
            "--input-type",
            "yaml",
            "--output-type",
            "yaml",
            "/dev/stdin",
        ],
        stdin=plaintext,
        check=True,
    )
    target.write_text(result.stdout, encoding="utf-8")


@pytest.fixture
def deploy_dir(tmp_path: Path, age: Age) -> Path:
    directory = tmp_path / "deploy"
    directory.mkdir()
    plaintext = json.dumps({"postgres_password": FAKE_PG_CREDENTIAL, "database_url": URL})
    _encrypt(age, directory / "secrets.enc.yaml", plaintext)
    return directory


def _deploy(*args: str, env: Mapping[str, str]) -> CompletedProcess[str]:
    assert BASH is not None
    return _run([BASH, str(ROOT / "scripts" / "deploy.sh"), *args], env)


def test_the_encrypted_file_passes_the_repository_check(deploy_dir: Path) -> None:
    text = (deploy_dir / "secrets.enc.yaml").read_text(encoding="utf-8")
    assert sops_file_problems(text) == []
    assert FAKE_PG_CREDENTIAL not in text


def test_decrypt_only_writes_0444_files_in_a_0700_directory(
    deploy_dir: Path, age: Age, tmp_path: Path
) -> None:
    out = tmp_path / "state" / "secrets"
    env = {"DEPLOY_DIR": str(deploy_dir), "SOPS_AGE_KEY_FILE": str(age.key_file)}
    for _ in range(2):  # idempotente: reemplaza ficheros 0444 ya existentes
        result = _deploy("--decrypt-only", str(out), env=env)
        assert result.returncode == 0, result.stderr
        assert FAKE_PG_CREDENTIAL not in result.stdout + result.stderr
        assert URL not in result.stdout + result.stderr
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    assert sorted(p.name for p in out.iterdir()) == ["database_url", "postgres_password"]
    assert (out / "postgres_password").read_text(encoding="utf-8") == FAKE_PG_CREDENTIAL
    assert (out / "database_url").read_text(encoding="utf-8") == URL
    for name in ("postgres_password", "database_url"):
        assert stat.S_IMODE((out / name).stat().st_mode) == 0o444


def test_decrypt_only_refusals(deploy_dir: Path, age: Age, tmp_path: Path) -> None:
    env = {"DEPLOY_DIR": str(deploy_dir), "SOPS_AGE_KEY_FILE": str(age.key_file)}
    age.key_file.chmod(0o644)
    open_key = _deploy("--decrypt-only", str(tmp_path / "a"), env=env)
    assert open_key.returncode == 2
    assert "modo 600" in open_key.stderr
    age.key_file.chmod(0o600)
    inside = ROOT / ".deploy-test-secrets"
    in_repo = _deploy("--decrypt-only", str(inside), env=env)
    assert in_repo.returncode == 2
    assert "dentro del repositorio" in in_repo.stderr
    assert not inside.exists()
    missing = _deploy(
        "--decrypt-only", str(tmp_path / "b"), env={**env, "DEPLOY_DIR": str(tmp_path)}
    )
    assert missing.returncode == 2
    assert "secrets.enc.yaml" in missing.stderr
    no_key = _deploy(
        "--decrypt-only", str(tmp_path / "c"), env={**env, "SOPS_AGE_KEY_FILE": str(tmp_path / "x")}
    )
    assert no_key.returncode == 2
    assert _deploy("--otra-cosa", env=env).returncode == 2


def test_decrypt_only_with_the_wrong_key_fails_without_showing_values(
    deploy_dir: Path, tmp_path: Path
) -> None:
    assert AGE_KEYGEN is not None
    other = tmp_path / "other.txt"
    run_tool([AGE_KEYGEN, "-o", str(other)], check=True)
    other.chmod(0o600)
    env = {"DEPLOY_DIR": str(deploy_dir), "SOPS_AGE_KEY_FILE": str(other)}
    result = _deploy("--decrypt-only", str(tmp_path / "out"), env=env)
    assert result.returncode == 1
    assert "no pudo descifrar" in result.stderr
    assert FAKE_PG_CREDENTIAL not in result.stdout + result.stderr
    assert not any((tmp_path / "out").iterdir())  # ni temporales ni secretos a medias


def test_deploy_refuses_an_env_file_with_secrets(
    deploy_dir: Path, age: Age, tmp_path: Path
) -> None:
    (deploy_dir / "jwks.json").write_text('{"keys": []}', encoding="utf-8")
    (deploy_dir / "auth.env").write_text("VORACIOUS_JWT_ISSUER=i\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"POSTGRES_USER=voracious\nPOSTGRES_PASSWORD={FAKE_PG_CREDENTIAL}\n"
        "export GITHUB_PRIVATE_TOKEN=x\nVORACIOUS_DATABASE_URL=\n",
        encoding="utf-8",
    )
    env = {
        "DEPLOY_DIR": str(deploy_dir),
        "SOPS_AGE_KEY_FILE": str(age.key_file),
        "DEPLOY_ENV_FILE": str(env_file),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    result = _deploy(env=env)
    assert result.returncode == 2
    if shutil.which("docker") is None or shutil.which("curl") is None:
        return  # la precondición que falla antes es otra (sin Docker o sin curl)
    assert "POSTGRES_PASSWORD" in result.stderr
    assert "GITHUB_PRIVATE_TOKEN" in result.stderr
    assert "VORACIOUS_DATABASE_URL" not in result.stderr  # vacía: no es un secreto
    assert FAKE_PG_CREDENTIAL not in result.stdout + result.stderr
    assert not (tmp_path / "state").exists()  # no descifra nada si se niega


@pytest.mark.skipif(UV is None, reason="sin uv")
def test_keygen_and_issue_token_round_trip(age: Age, tmp_path: Path) -> None:
    assert BASH is not None
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copy(ROOT / "deploy" / "demo" / "auth.env", deploy / "auth.env")
    config = tmp_path / "sops.yaml"
    config.write_text(
        f"creation_rules:\n  - path_regex: .*\\.enc\\.yaml$\n    age: {age.recipient}\n",
        encoding="utf-8",
    )
    env = {
        "DEPLOY_DIR": str(deploy),
        "SOPS_AGE_KEY_FILE": str(age.key_file),
        "SOPS_CONFIG": str(config),
    }
    keygen_args = [BASH, str(ROOT / "scripts" / "jwt_keygen.sh"), "--via", "uv", "test-2026-10"]
    keygen = _run(keygen_args, env)
    assert keygen.returncode == 0, keygen.stderr
    signing = (deploy / "jwt-signing.enc.yaml").read_text(encoding="utf-8")
    assert sops_file_problems(signing) == []
    assert "PRIVATE KEY" not in signing
    jwks_text = (deploy / "jwks.json").read_text(encoding="utf-8")
    assert jwks_problems(jwks_text) == []
    repeated = _run(keygen_args, env)
    assert repeated.returncode == 1
    assert (deploy / "jwks.json").read_text(encoding="utf-8") == jwks_text
    args = ["--via", "uv", "--tenant", "demo", "--roles", "analyst", "--subject", "kevin"]
    issued = _run([BASH, str(ROOT / "scripts" / "issue_token.sh"), *args, "--ttl", "1h"], env)
    assert issued.returncode == 0, issued.stderr
    raw = issued.stdout.strip()
    assert issued.stdout == f"{raw}\n"  # solo el token por stdout
    assert raw not in issued.stderr
    verifier = JwtTokenVerifier(
        load_jwks(jwks_text, allowed_algorithms=("EdDSA",)),
        issuer="voracious-demo",
        audience="voracious-api",
        algorithms=("EdDSA",),
        leeway=timedelta(seconds=30),
    )
    principal = verifier.verify(raw)
    assert (principal.subject, principal.tenant_id) == ("kevin", "demo")
    too_long = _run([BASH, str(ROOT / "scripts" / "issue_token.sh"), *args, "--ttl", "8d"], env)
    assert (too_long.returncode, too_long.stdout) == (1, "")
