"""Coherencia del borde público (``deploy/proxy``) con la app, Compose y CI, sin Docker (paso E).

- El tope del cuerpo de Caddy es ``VORACIOUS_MAX_UPLOAD_MB`` + 1 MiB (margen del multipart): entre
  los dos responde la API con su ``413`` detallado.
- La base de la imagen del proxy va fijada por versión y ``@sha256``; corre sin root y sin la
  capacidad de fichero que impediría arrancar con ``cap_drop: ALL``.
- Caddy solo publica ``/health`` y ``/v1/*``, sin ``trusted_proxies`` (reescribe
  ``X-Forwarded-For``: un cliente no puede hacerse pasar por loopback ante el límite de peticiones).
- La IP fija del proxy es la única en la que confía la API y cae dentro de la subred ``edge``.
- ``proxy.env`` y ``api.env`` solo llevan configuración pública, aceptada por la app.
- Los ficheros del borde se versionan (``deploy/`` es una lista blanca en ``.gitignore``).

``caddy validate`` y ``caddy fmt`` con la imagen real corren en CI (trabajo ``image``).
"""

import ipaddress
import re
import shutil
from pathlib import Path

import pytest

from support.repo_secrets import ROOT
from support.tools import run_tool
from voracious.config import Settings

PROXY = ROOT / "deploy" / "proxy"
DEMO = ROOT / "deploy" / "demo"
CADDYFILE = (PROXY / "Caddyfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _env_file(path: Path) -> dict[str, str]:
    """Pares ``CLAVE=valor`` de un fichero ``env_file`` de Compose (sin comentarios ni vacías)."""
    pairs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            pairs[key.strip()] = value.strip()
    return pairs


def test_caddy_body_limit_is_the_upload_limit_plus_one_mib(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VORACIOUS_MAX_UPLOAD_MB", raising=False)
    limits = re.findall(r"^\s*max_size\s+(\d+)MiB\s*$", CADDYFILE, flags=re.MULTILINE)
    assert limits == [str(Settings().max_upload_mb + 1)]


def test_proxy_image_is_pinned_by_version_and_digest() -> None:
    dockerfile = (PROXY / "Dockerfile").read_text(encoding="utf-8")
    bases = re.findall(r"^FROM\s+(\S+)", dockerfile, flags=re.MULTILINE)
    assert len(bases) == 1
    assert re.fullmatch(r"caddy:2\.\d+\.\d+-alpine@sha256:[0-9a-f]{64}", bases[0]), bases[0]


def test_proxy_image_runs_without_root_and_without_file_capabilities() -> None:
    dockerfile = (PROXY / "Dockerfile").read_text(encoding="utf-8")
    assert "setcap -r /usr/bin/caddy" in dockerfile
    users = re.findall(r"^USER\s+(\S+)", dockerfile, flags=re.MULTILINE)
    assert users == ["10002:10002"]


def test_caddyfile_only_publishes_health_and_the_business_api() -> None:
    assert re.search(r"^\s*@api path /health /v1/\*\s*$", CADDYFILE, flags=re.MULTILINE)
    assert re.findall(r"reverse_proxy\s+(\S+)", CADDYFILE) == ["api:8000"]
    for option in ("admin off", "protocols h1 h2", "auto_https disable_redirects"):
        assert re.search(rf"^\s*{option}\s*$", CADDYFILE, flags=re.MULTILINE), option
    # Sin trusted_proxies Caddy reescribe X-Forwarded-For con la IP real del cliente.
    assert "trusted_proxies" not in CADDYFILE
    assert "-Server" in CADDYFILE
    assert "-Via" in CADDYFILE


@pytest.mark.parametrize("mode", ["acme", "internal"])
def test_each_tls_mode_defines_its_snippets(mode: str) -> None:
    text = (PROXY / f"tls-{mode}.caddy").read_text(encoding="utf-8")
    assert re.search(r"^\(tls_global\) \{$", text, flags=re.MULTILINE)
    assert re.search(r"^\(tls_site\) \{$", text, flags=re.MULTILINE)
    assert "import tls-{$PROXY_TLS_MODE}.caddy" in CADDYFILE
    assert re.search(r"^\timport tls_global$", CADDYFILE, flags=re.MULTILINE)
    assert re.search(r"^\timport tls_site$", CADDYFILE, flags=re.MULTILINE)


def test_acme_mode_is_lets_encrypt_without_http_challenge_nor_email() -> None:
    text = (PROXY / "tls-acme.caddy").read_text(encoding="utf-8")
    assert "dir https://acme-v02.api.letsencrypt.org/directory" in text
    assert "disable_http_challenge" in text
    assert "email" not in re.sub(r"#.*", "", text)


def _compose_default(variable: str) -> list[str]:
    return re.findall(rf"\$\{{{variable}:-([^}}]+)\}}", COMPOSE)


def test_the_proxy_ip_is_the_only_trusted_proxy_and_lies_in_the_edge_subnet() -> None:
    proxy_ips = _compose_default("DEPLOY_PROXY_IP")
    assert len(proxy_ips) == 2  # ipv4_address del proxy y VORACIOUS_TRUSTED_PROXIES de la API
    assert len(set(proxy_ips)) == 1
    assert re.search(r"^\s+ipv4_address: \$\{DEPLOY_PROXY_IP:-", COMPOSE, flags=re.MULTILINE)
    assert re.search(
        r"^\s+VORACIOUS_TRUSTED_PROXIES: \$\{DEPLOY_PROXY_IP:-", COMPOSE, flags=re.MULTILINE
    )
    (subnet,) = _compose_default("DEPLOY_EDGE_SUBNET")
    assert ipaddress.ip_address(proxy_ips[0]) in ipaddress.ip_network(subnet)


def test_compose_publishes_only_443_tcp_on_the_proxy_and_keeps_the_api_on_loopback() -> None:
    published = re.findall(r'^\s+- "([^"]+)"\s*$', COMPOSE.split("\nnetworks:\n")[0], re.MULTILINE)
    port_like = [item for item in published if re.fullmatch(r"[\d.:]+(/tcp|/udp)?", item)]
    assert sorted(port_like) == ["127.0.0.1:8000:8000", "443:443/tcp"]
    assert re.search(r"^  backend:\n    internal: true$", COMPOSE, flags=re.MULTILINE)
    assert re.search(r"^    profiles: \[public\]$", COMPOSE, flags=re.MULTILINE)


def test_demo_proxy_env_is_public_and_points_to_the_permanent_host() -> None:
    assert _env_file(DEMO / "proxy.env") == {
        "PROXY_PUBLIC_HOST": "api.voracious.cloud",
        "PROXY_TLS_MODE": "acme",
    }


def test_demo_api_env_only_has_public_settings_the_app_accepts() -> None:
    pairs = _env_file(DEMO / "api.env")
    assert set(pairs) == {"VORACIOUS_CORS_ALLOWED_ORIGINS"}
    settings = Settings(cors_allowed_origins=pairs["VORACIOUS_CORS_ALLOWED_ORIGINS"])
    assert settings.cors_allowed_origins


def test_dependabot_follows_the_proxy_base_image() -> None:
    text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert re.search(r"- package-ecosystem: docker\n    directory: /deploy/proxy\n", text), (
        "falta la entrada docker de /deploy/proxy"
    )


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_actions_are_pinned_by_sha(workflow: Path) -> None:
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", workflow.read_text(encoding="utf-8"), re.MULTILINE)
    assert uses
    for action in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", action), action


GIT = shutil.which("git")


@pytest.mark.skipif(
    GIT is None or not (ROOT / ".git").exists(),
    reason="sin git o sin .git (la imagen gate no copia .git: .dockerignore)",
)
def test_the_edge_files_are_versioned() -> None:
    assert GIT is not None
    files = [
        "deploy/proxy/Dockerfile",
        "deploy/proxy/Caddyfile",
        "deploy/proxy/tls-acme.caddy",
        "deploy/proxy/tls-internal.caddy",
        "deploy/demo/proxy.env",
        "deploy/demo/api.env",
    ]
    result = run_tool([GIT, "-C", str(ROOT), "check-ignore", "--no-index", "--", *files])
    assert result.returncode in {0, 1}, result.stderr  # 1: ninguno ignorado
    assert result.stdout.splitlines() == []
