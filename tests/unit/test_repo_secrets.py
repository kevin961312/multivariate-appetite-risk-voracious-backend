"""Ningún secreto en claro en el repositorio (sin sops): cifrados, JWKS, ``.sops.yaml`` y scripts.

Si ``deploy/`` aún no tiene cifrados (antes del redespliegue) las comprobaciones (a) y (b) pasan sin
nada que mirar; las autopruebas de cada comprobador demuestran que muerden.
"""

import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from support.auth import PUBLIC_JWK
from support.repo_secrets import (
    ROOT,
    SKIP_DIRS,
    jwks_problems,
    leaked_key_files,
    sops_config_problems,
    sops_file_problems,
)
from support.tools import run_tool

DEPLOY = ROOT / "deploy"
SCRIPTS = sorted((ROOT / "scripts").glob("*.sh"))

_ENC = "ENC[AES256_GCM,data:QUJD,iv:aXY=,tag:dGFn,type:str]"
_RECIPIENT = "age1" + "q" * 58
_SOPS_OK = f"""postgres_password: {_ENC}
database_url: {_ENC}
sops:
    age:
        - recipient: {_RECIPIENT}
          enc: |
            -----BEGIN AGE ENCRYPTED FILE-----
            YWdl
            -----END AGE ENCRYPTED FILE-----
    mac: {_ENC}
    version: 3.13.3
"""


def test_every_sops_file_is_encrypted() -> None:
    for path in sorted(DEPLOY.rglob("*.enc.yaml")) if DEPLOY.exists() else []:
        assert sops_file_problems(path.read_text(encoding="utf-8")) == [], path


def test_every_jwks_is_public() -> None:
    for path in sorted(DEPLOY.rglob("jwks.json")) if DEPLOY.exists() else []:
        assert jwks_problems(path.read_text(encoding="utf-8")) == [], path


def test_sops_config_only_names_public_recipients() -> None:
    config = ROOT / ".sops.yaml"
    if config.exists():
        assert sops_config_problems(config.read_text(encoding="utf-8")) == []


def test_auth_env_only_has_public_jwt_settings() -> None:
    allowed = {"VORACIOUS_JWT_ISSUER", "VORACIOUS_JWT_AUDIENCE", "VORACIOUS_JWT_JWKS_FILE"}
    for path in sorted(DEPLOY.rglob("auth.env")) if DEPLOY.exists() else []:
        names = {
            line.split("=", 1)[0].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        assert names <= allowed, path


def test_no_private_keys_anywhere_in_the_tree() -> None:
    assert leaked_key_files() == []


BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None, reason="sin bash")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_parse(script: Path) -> None:
    assert BASH is not None
    result = run_tool([BASH, "-n", str(script)])
    assert result.returncode == 0, result.stderr


GIT = shutil.which("git")
needs_git = pytest.mark.skipif(
    GIT is None or not (ROOT / ".git").exists(),
    reason="sin git o sin .git (la imagen gate no copia .git: .dockerignore)",
)


def _ignored_by_git(paths: Sequence[str]) -> set[str]:
    """Rutas que ``.gitignore`` ignora (``--no-index``: también si ya estuvieran versionadas)."""
    assert GIT is not None
    result = run_tool([GIT, "-C", str(ROOT), "check-ignore", "--no-index", "--", *paths])
    assert result.returncode in {0, 1}, result.stderr  # 1: ninguna ignorada
    return set(result.stdout.splitlines())


@needs_git
def test_deploy_is_an_allowlist_in_gitignore() -> None:
    kept = [
        "deploy/demo/auth.env",
        "deploy/demo/api.env",
        "deploy/demo/proxy.env",
        "deploy/demo/jwks.json",
        "deploy/demo/x.enc.yaml",
        "deploy/otro/sub/secrets.enc.yaml",
        "deploy/proxy/Dockerfile",
        "deploy/proxy/Caddyfile",
        "deploy/proxy/tls-acme.caddy",
    ]
    dropped = [
        "deploy/demo/secrets.yaml",
        "deploy/demo/secrets.dec.yaml",
        "deploy/demo/jwt-signing.pem",
        "deploy/demo/keys.txt",
        "deploy/demo/notas.txt",
        "deploy/otro/sub/.env",
        "deploy/proxy/root.crt",
        "deploy/proxy/notas.txt",
        "deploy/proxy/.env",
    ]
    assert _ignored_by_git([*kept, *dropped]) == set(dropped)


@needs_git
def test_every_skipped_directory_is_ignored_by_git() -> None:
    """El escáner de llaves solo se salta lo que git nunca versionaría."""
    probes = [f"{name}/x" for name in sorted(SKIP_DIRS - {".git"})]
    assert _ignored_by_git(probes) == set(probes)


def test_the_deploy_scripts_exist_and_are_executable() -> None:
    names = {p.name for p in SCRIPTS}
    assert {"deploy.sh", "issue_token.sh", "jwt_keygen.sh"} <= names
    for script in SCRIPTS:
        assert script.stat().st_mode & 0o111, script


# --- autopruebas: cada comprobador muerde --------------------------------------------------------


def test_sops_checker_accepts_an_encrypted_file_and_rejects_plaintext() -> None:
    assert sops_file_problems(_SOPS_OK) == []
    assert sops_file_problems("postgres_password: hunter2\n") == ["sin metadatos 'sops:'"]
    plain = _SOPS_OK.replace(f"database_url: {_ENC}", "database_url: postgresql://u:p@h/db")
    assert sops_file_problems(plain) == ["línea 2: valor sin cifrar"]
    no_mac = _SOPS_OK.replace(f"    mac: {_ENC}\n", "")
    assert sops_file_problems(no_mac) == ["sin 'mac' cifrado"]
    nested = _SOPS_OK.replace("database_url:", "group:\n    database_url:", 1)
    assert sops_file_problems(nested) == []
    assert sops_file_problems(f"sops:\n    mac: {_ENC}\n    - recipient: {_RECIPIENT}\n") == [
        "ningún valor cifrado"
    ]


def test_jwks_checker_rejects_private_members() -> None:
    assert jwks_problems(json.dumps({"keys": [PUBLIC_JWK]})) == []
    assert jwks_problems(json.dumps({"keys": [{**PUBLIC_JWK, "d": "x"}]})) != []
    assert jwks_problems("{}") != []


def test_sops_config_checker() -> None:
    good = (
        f"creation_rules:\n  - path_regex: ^deploy/demo/.*\\.enc\\.yaml$\n    age: {_RECIPIENT}\n"
    )
    assert sops_config_problems(good) == []
    assert sops_config_problems("creation_rules: []\n") == ["sin receptores age1…"]
    assert sops_config_problems(good.replace(_RECIPIENT, "age1corto")) == [
        "receptor con forma inválida (9 caracteres)"
    ]
    secret = "AGE-SECRET-" + "KEY-1" + "Q" * 58
    assert "contiene una llave age PRIVADA" in sops_config_problems(f"{good}# {secret}\n")


def test_leak_scanner_finds_private_keys_and_skips_caches(tmp_path: Path) -> None:
    from support.auth import PRIVATE_KEY_PEM

    (tmp_path / "ok.txt").write_text("-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA\n", "utf-8")
    (tmp_path / "leak.pem").write_bytes(PRIVATE_KEY_PEM)
    (tmp_path / "keys.txt").write_text("AGE-SECRET-" + "KEY-1" + "A" * 58 + "\n", "utf-8")
    cache = tmp_path / ".venv"
    cache.mkdir()
    (cache / "x.pem").write_bytes(PRIVATE_KEY_PEM)
    assert sorted(leaked_key_files(tmp_path)) == [Path("keys.txt"), Path("leak.pem")]
