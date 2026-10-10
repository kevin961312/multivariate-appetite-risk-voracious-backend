"""Punto de entrada de línea de órdenes (Paso 4.2), sin lógica propia.

    python -m voracious.cli migrate     # aplica las migraciones pendientes de Postgres

Solo traduce la orden a una llamada de ``container`` (como ``api`` y ``workers``, no importa
``infrastructure`` ni ``config`` directamente; lo vigila import-linter). Configuración por
``VORACIOUS_*`` (``VORACIOUS_REPOSITORY=postgres`` y ``VORACIOUS_DATABASE_URL``).
"""

import argparse
import sys
from collections.abc import Sequence

from voracious.container import ConfigurationError, run_migrations

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta una orden.

    Args:
        argv: Argumentos (sin el programa); ``None`` = los del proceso.

    Returns:
        Código de salida: 0 si fue bien, 2 si la configuración no es válida.
    """
    parser = argparse.ArgumentParser(prog="python -m voracious.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="aplica las migraciones pendientes de Postgres")
    args = parser.parse_args(argv)
    if args.command == "migrate":  # pragma: no branch - única orden
        try:
            applied = run_migrations()
        except ConfigurationError as exc:
            sys.stderr.write(f"configuración no válida: {exc}\n")
            return 2
        sys.stdout.write(f"migraciones aplicadas: {', '.join(applied) or 'ninguna (al día)'}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
