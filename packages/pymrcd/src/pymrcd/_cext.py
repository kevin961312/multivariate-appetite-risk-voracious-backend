"""Carga de la extensión C ``pymrcd._qn_ext`` (especificación §3.12.9; decisión P1 del dueño).

No hay respaldo en Python: si la extensión no está compilada, importar ``pymrcd`` falla aquí con
un ``ImportError`` que explica cómo compilarla. Los módulos de ``pymrcd`` importan ``qn_ext`` desde
este módulo, nunca ``_qn_ext`` directamente.
"""

from __future__ import annotations

try:
    from pymrcd import _qn_ext as qn_ext
except ImportError as exc:  # pragma: no cover - cubierto en subproceso (test_qn_ext.py)
    raise ImportError(
        "pymrcd: falta la extensión C 'pymrcd._qn_ext' (port literal de qn0, especificación "
        "§3.12.9). Compílala desde la raíz del repositorio con "
        "'uv sync --reinstall-package pymrcd' (requiere un compilador de C con pthreads). "
        "No hay implementación de respaldo en Python."
    ) from exc

__all__ = ["qn_ext"]
