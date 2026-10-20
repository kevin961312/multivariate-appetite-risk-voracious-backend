"""Ejecución de herramientas externas en los tests (bash, git, sops, age-keygen y scripts/*.sh).

Es el único sitio de los tests que lanza procesos: la exención de la regla S603 de ruff («entrada no
confiable» en todo ``subprocess`` sin shell) se justifica una vez, en la línea de la llamada, y no
por fichero.
"""

import subprocess
from collections.abc import Mapping, Sequence


def run_tool(
    args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    stdin: str = "",
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Ejecuta una herramienta sin shell y captura su salida como texto.

    Args:
        args: Programa (ruta absoluta de ``shutil.which``) y argumentos, todos fijados por el test.
        env: Entorno completo del proceso (``None`` hereda el del test).
        stdin: Entrada estándar (vacía por defecto: nunca la del terminal).
        check: Si es ``True``, un código de salida distinto de 0 lanza ``CalledProcessError``.

    Returns:
        El proceso terminado, con ``stdout`` y ``stderr`` en texto.
    """
    return subprocess.run(  # noqa: S603 - sin shell; programa y argumentos fijos del test
        list(args),
        input=stdin,
        capture_output=True,
        text=True,
        env=None if env is None else dict(env),
        check=check,
    )
