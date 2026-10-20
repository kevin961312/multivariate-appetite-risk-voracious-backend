"""Punto de entrada de línea de órdenes (Paso 4.2 y seguridad mínima), sin lógica propia.

    python -m voracious.cli migrate       # aplica las migraciones pendientes de Postgres
    python -m voracious.cli issue-token --tenant T --roles analyst --subject S --kid K
        [--ttl 8h] [--private-key-file PATH|-]      # el token, solo, por stdout
    python -m voracious.cli jwt-keygen --kid K --jwks PATH | sops ...   # el PEM, nunca a disco

Solo traduce la orden a una llamada de ``container`` (como ``api`` y ``workers``, no importa
``infrastructure`` ni ``config`` directamente; lo vigila import-linter). Configuración por
``VORACIOUS_*``: ``migrate`` usa ``VORACIOUS_REPOSITORY=postgres`` y la URL (directa o en
fichero); ``issue-token``, ``VORACIOUS_JWT_ISSUER``, ``VORACIOUS_JWT_AUDIENCE`` y, si está, el
JWKS para comprobar el token emitido.

La llave privada nunca entra en la configuración (D11): ``issue-token`` la lee de un fichero o de
la entrada estándar (``-``, por defecto; nunca de una terminal) y ``jwt-keygen`` la escribe solo
por la salida estándar (se niega si es una terminal). Por la salida estándar sale solo el token o
solo la llave; los mensajes van a la de error.

Códigos de salida: 0 bien; 1 entrada no válida (o el token emitido no verifica); 2 configuración
no válida (o ``jwt-keygen`` con la salida en una terminal).
"""

import argparse
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from voracious.application.auth import DEFAULT_TOKEN_TTL, MAX_TOKEN_TTL, AuthenticationError, Role
from voracious.container import (
    ConfigurationError,
    generate_signing_key,
    issue_token,
    run_migrations,
)

__all__ = ["EXIT_CONFIG", "EXIT_INPUT", "EXIT_OK", "main", "parse_ttl"]

EXIT_OK: Final = 0
EXIT_INPUT: Final = 1
EXIT_CONFIG: Final = 2

_TTL: Final = re.compile(r"(\d{1,6})([mhd])")
_UNITS: Final = {"m": "minutes", "h": "hours", "d": "days"}
_STDIN: Final = "-"
_JWKS_MODE: Final = 0o644
"""Permisos de un JWKS nuevo: es público (se versiona en claro)."""


def parse_ttl(text: str) -> timedelta:
    """Vida de un token: ``<n>m``, ``<n>h`` o ``<n>d``, de más de cero hasta ``MAX_TOKEN_TTL``.

    Args:
        text: Texto (p. ej. ``8h``).

    Returns:
        La duración.

    Raises:
        ValueError: Si no tiene la forma o queda fuera de rango.
    """
    match = _TTL.fullmatch(text.strip())
    if match is None:
        msg = "--ttl debe ser <n>m, <n>h o <n>d (p. ej. 8h)"
        raise ValueError(msg)
    ttl = timedelta(**{_UNITS[match.group(2)]: int(match.group(1))})
    if ttl <= timedelta(0) or ttl > MAX_TOKEN_TTL:
        msg = f"--ttl debe ser mayor que cero y como mucho {MAX_TOKEN_TTL.days}d"
        raise ValueError(msg)
    return ttl


def _parse_roles(text: str) -> list[Role]:
    """Roles separados por comas.

    Args:
        text: Texto (p. ej. ``analyst,approver``).

    Returns:
        Los roles.

    Raises:
        ValueError: Si está vacío o hay un rol desconocido.
    """
    names = [part.strip() for part in text.split(",") if part.strip()]
    if not names:
        msg = "--roles necesita al menos un rol (analyst, approver, admin)"
        raise ValueError(msg)
    known = {role.value: role for role in Role}
    unknown = sorted(set(names) - set(known))
    if unknown:
        msg = f"roles desconocidos: {', '.join(unknown)} (analyst, approver, admin)"
        raise ValueError(msg)
    return [known[name] for name in names]


def _read_private_key(source: str) -> bytes:
    """Llave privada de un fichero o de la entrada estándar.

    Args:
        source: Ruta o ``-``.

    Returns:
        El PEM.

    Raises:
        ValueError: Si la entrada estándar es una terminal o el fichero no se puede leer (el
            mensaje no incluye el contenido).
    """
    if source == _STDIN:
        if sys.stdin.isatty():
            msg = "la llave privada se pasa por una tubería o con --private-key-file, no tecleada"
            raise ValueError(msg)
        return sys.stdin.buffer.read()
    try:
        return Path(source).read_bytes()
    except OSError as exc:
        msg = f"no se puede leer --private-key-file ({source}): {type(exc).__name__}"
        raise ValueError(msg) from exc


def _issue_token(args: argparse.Namespace) -> int:
    """Orden ``issue-token``.

    Args:
        args: Argumentos.

    Returns:
        El código de salida.
    """
    try:
        ttl = parse_ttl(args.ttl)
        roles = _parse_roles(args.roles)
        pem = _read_private_key(args.private_key_file)
        token = issue_token(
            pem, kid=args.kid, subject=args.subject, tenant_id=args.tenant, roles=roles, ttl=ttl
        )
    except ConfigurationError as exc:
        sys.stderr.write(f"configuración no válida: {exc}\n")
        return EXIT_CONFIG
    except AuthenticationError as exc:
        sys.stderr.write(
            f"el token emitido no verifica con el JWKS configurado ({exc.reason.value})\n"
        )
        return EXIT_INPUT
    except ValueError as exc:
        sys.stderr.write(f"entrada no válida: {exc}\n")
        return EXIT_INPUT
    expires = (datetime.now(UTC) + ttl).replace(microsecond=0).isoformat()
    sys.stdout.write(f"{token}\n")
    sys.stderr.write(
        f"token emitido: tenant={args.tenant} roles={','.join(sorted({r.value for r in roles}))} "
        f"sub={args.subject} kid={args.kid} caduca={expires}\n"
    )
    return EXIT_OK


def _write_atomically(path: Path, text: str) -> None:
    """Escribe ``text`` en ``path`` de forma atómica (temporal en el mismo directorio y rename).

    Args:
        path: Destino.
        text: Contenido.

    Raises:
        OSError: Si no se puede escribir (el destino queda como estaba).
    """
    mode = path.stat().st_mode & 0o777 if path.exists() else _JWKS_MODE
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp).chmod(mode)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _jwt_keygen(args: argparse.Namespace) -> int:
    """Orden ``jwt-keygen``.

    Args:
        args: Argumentos.

    Returns:
        El código de salida.
    """
    if sys.stdout.isatty():
        sys.stderr.write(
            "jwt-keygen escribe la llave privada por la salida estándar: redirígela (p. ej. a "
            "sops con scripts/jwt_keygen.sh); no se imprime en una terminal\n"
        )
        return EXIT_CONFIG
    path = Path(args.jwks)
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else None
        pem, jwks = generate_signing_key(args.kid, current)
        _write_atomically(path, jwks)
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"no se puede leer o escribir --jwks ({path}): {type(exc).__name__}\n")
        return EXIT_INPUT
    except ValueError as exc:
        sys.stderr.write(f"entrada no válida: {exc}\n")
        return EXIT_INPUT
    sys.stdout.buffer.write(pem)
    sys.stdout.flush()
    sys.stderr.write(f"JWKS actualizado: {path} (kid {args.kid}); la llave salió por stdout\n")
    return EXIT_OK


def _migrate() -> int:
    """Orden ``migrate``.

    Returns:
        El código de salida.
    """
    try:
        applied = run_migrations()
    except ConfigurationError as exc:
        sys.stderr.write(f"configuración no válida: {exc}\n")
        return EXIT_CONFIG
    sys.stdout.write(f"migraciones aplicadas: {', '.join(applied) or 'ninguna (al día)'}\n")
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    """Analizador de argumentos de las tres órdenes.

    Returns:
        El analizador.
    """
    parser = argparse.ArgumentParser(prog="python -m voracious.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="aplica las migraciones pendientes de Postgres")
    issue = commands.add_parser(
        "issue-token", help="emite un token firmado (iss y aud de VORACIOUS_JWT_*)"
    )
    issue.add_argument("--tenant", required=True, help="claim tenant")
    issue.add_argument("--roles", required=True, help="roles separados por comas")
    issue.add_argument("--subject", required=True, help="claim sub (quién es)")
    issue.add_argument("--kid", required=True, help="kid de la llave de firma en el JWKS")
    default_ttl = f"{int(DEFAULT_TOKEN_TTL.total_seconds() // 3600)}h"
    issue.add_argument(
        "--ttl", default=default_ttl, help=f"vida del token (por defecto {default_ttl}, máx. 7d)"
    )
    issue.add_argument(
        "--private-key-file",
        default=_STDIN,
        help="PEM de la llave privada; '-' (por defecto) = entrada estándar",
    )
    keygen = commands.add_parser(
        "jwt-keygen", help="genera una llave Ed25519 y añade su parte pública al JWKS"
    )
    keygen.add_argument("--kid", required=True, help="kid nuevo (no puede existir ya)")
    keygen.add_argument("--jwks", required=True, help="JWKS a ampliar (se crea si no existe)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta una orden.

    Args:
        argv: Argumentos (sin el programa); ``None`` = los del proceso.

    Returns:
        Código de salida: 0 bien, 1 entrada no válida, 2 configuración no válida.
    """
    args = _parser().parse_args(argv)
    if args.command == "issue-token":
        return _issue_token(args)
    if args.command == "jwt-keygen":
        return _jwt_keygen(args)
    return _migrate()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
