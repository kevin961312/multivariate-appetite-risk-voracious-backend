"""Comprobaciones de secretos del repositorio sin sops (las comparten los tests de secretos).

- Un ``*.enc.yaml`` de SOPS solo puede tener valores ``ENC[AES256_GCM,…]`` antes de ``sops:``, con
  ``mac`` cifrado y al menos un receptor ``age1…``.
- Un ``jwks.json`` solo lleva llaves públicas, con ``kid`` único y algoritmo permitido.
- ``.sops.yaml`` solo nombra receptores age públicos (``age1…``), nunca una llave privada.
- En el árbol no hay llaves age privadas ni bloques PEM de llave privada.
"""

import os
import re
from pathlib import Path

from voracious.infrastructure.auth import JwksError, load_jwks

ROOT = Path(__file__).resolve().parents[2]
"""Raíz del repositorio."""

ALL_ALGORITHMS = ("EdDSA", "ES256", "RS256", "PS256")

_ENC_VALUE = re.compile(
    r"ENC\[AES256_GCM,data:[A-Za-z0-9+/=]*,iv:[A-Za-z0-9+/=]+,tag:[A-Za-z0-9+/=]+,type:[a-z]+\]"
)
_DATA_LINE = re.compile(r"(?:-\s+)?(?:[A-Za-z0-9_.-]+:\s*)?(?P<value>.*)")
_RECIPIENT = re.compile(r"age1[0-9a-z]{58}")

# Las piezas se concatenan para que este fichero no case consigo mismo.
_AGE_SECRET = re.compile(("AGE-SECRET-" + "KEY-1[0-9A-Z]{58}").encode())
_PEM_PRIVATE = re.compile(
    ("-----BEGIN (?:[A-Z0-9]+ )*PRIV" + r"ATE KEY-----\s+[A-Za-z0-9+/=]{16,}").encode()
)

SKIP_DIRS = frozenset(
    {
        ".git",  # objetos de git: lo versionado ya se recorre en el árbol de trabajo
        # Entornos y cachés de herramientas (ignorados por git).
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".import_linter_cache",
        ".gates",
        "build",
        "dist",
        # Material local ignorado por git (nunca se versiona): fuentes de terceros (referencias),
        # datos de trabajo (datos) y la plantilla de agentes de otro proyecto.
        "referencias",
        "datos",
        "plantilla-agentes",
    }
)
"""Directorios que no se recorren.

Solo los que git ignora (además de ``.git``): lo que no ignora puede versionarse y hay que mirarlo.
``test_every_skipped_directory_is_ignored_by_git`` lo comprueba con ``git check-ignore``.
"""

SKIP_PREFIXES = ("packages/pymrcd/tests/golden/fixtures",)
"""Fixtures golden pesados (CSV de R): datos numéricos, nunca llaves."""

MAX_BYTES = 2 * 1024 * 1024


def sops_file_problems(text: str) -> list[str]:
    """Problemas de un fichero YAML cifrado con SOPS (vacío si está bien).

    Args:
        text: Contenido.

    Returns:
        Los problemas (sin incluir ningún valor).
    """
    lines = text.splitlines()
    try:
        start = lines.index("sops:")
    except ValueError:
        return ["sin metadatos 'sops:'"]
    problems: list[str] = []
    meta = "\n".join(lines[start:])
    if re.search(r"^\s+mac: ENC\[AES256_GCM,", meta, re.MULTILINE) is None:
        problems.append("sin 'mac' cifrado")
    if _RECIPIENT.search(meta) is None:
        problems.append("sin receptor age")
    values = 0
    for number, line in enumerate(lines[:start], 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _DATA_LINE.fullmatch(stripped)
        value = match.group("value") if match is not None else stripped
        if not value:
            continue  # cabecera de un mapa anidado («clave:»)
        values += 1
        if _ENC_VALUE.fullmatch(value) is None:
            problems.append(f"línea {number}: valor sin cifrar")
    if values == 0:
        problems.append("ningún valor cifrado")
    return problems


def jwks_problems(text: str) -> list[str]:
    """Problemas de un JWKS versionado (vacío si está bien).

    Args:
        text: Contenido.

    Returns:
        Los problemas.
    """
    try:
        load_jwks(text, allowed_algorithms=ALL_ALGORITHMS)
    except JwksError as exc:
        return [str(exc)]
    return []


def sops_config_problems(text: str) -> list[str]:
    """Problemas de ``.sops.yaml`` (vacío si está bien).

    Args:
        text: Contenido.

    Returns:
        Los problemas.
    """
    problems: list[str] = []
    if _AGE_SECRET.search(text.encode()) is not None:
        problems.append("contiene una llave age PRIVADA")
    candidates = re.findall(r"age1[0-9a-z]+", text)
    if not candidates:
        problems.append("sin receptores age1…")
    problems.extend(
        f"receptor con forma inválida ({len(c)} caracteres)"
        for c in candidates
        if _RECIPIENT.fullmatch(c) is None
    )
    return problems


def leaked_key_files(root: Path = ROOT) -> list[Path]:
    """Ficheros del árbol con una llave age privada o un bloque PEM de llave privada.

    Recorre el sistema de ficheros (no git: la imagen ``gate`` no tiene ``.git``), sin entornos,
    cachés ni binarios.

    Args:
        root: Raíz.

    Returns:
        Las rutas relativas encontradas.
    """
    found: list[Path] = []
    for directory, dirs, files in os.walk(root):
        relative_dir = Path(directory).relative_to(root)
        dirs[:] = [
            d
            for d in dirs
            if d not in SKIP_DIRS
            and not any((relative_dir / d).as_posix().startswith(p) for p in SKIP_PREFIXES)
        ]
        for name in files:
            path = Path(directory) / name
            if name.startswith(".coverage") or not path.is_file() or path.is_symlink():
                continue
            if path.stat().st_size > MAX_BYTES:
                continue
            data = path.read_bytes()
            if b"\0" in data[:8192]:
                continue  # binario
            if _AGE_SECRET.search(data) or _PEM_PRIVATE.search(data):
                found.append(path.relative_to(root))
    return found
