"""Benchmark de rendimiento de ``ogk_u``, ``qn_columns`` y ``cov_mrcd`` (solo tiempos).

No forma parte de los tests ni de la compuerta: mide la mediana de 3 ejecuciones
(``time.perf_counter``) sobre datos normales estándar generados con
``numpy.random.default_rng(20261007)`` en dos formas ``n x p`` (200x300 y 100x250). Los datos solo
sirven para medir rendimiento; la fidelidad con R se comprueba con los golden de ``tests/``.

Entradas de cada función, idénticas a las que recibe dentro de ``cov_mrcd``:

- ``ogk_u``: ``R6Pack.x`` (la salida de ``doScale`` de ``r6pack``, ``detmrcd.R:123-125``).
- ``qn_columns`` (``n x p``): la matriz original, como en la estandarización
  (``detmrcd.R:417-422``).
- ``qn_columns`` (lote OGK): el primer lote de columnas ``Y_i + Y_j`` y ``Y_i - Y_j`` que el
  ``ogk_u`` numpy anterior a M5 pasaba a ``qn_columns`` (lotes de ``2**22`` elementos); se conserva
  para comparar con la línea base.

Cada medición se repite con cada número de hilos de ``--threads`` (por defecto ``1`` y ``all``,
todos los CPU visibles; ``n_threads`` de ``pymrcd``, especificación §3.12.9 e).

Uso::

    uv run python packages/pymrcd/benchmarks/bench_qn.py salida.json [--threads 1,all]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from collections.abc import Callable
from functools import partial
from importlib.metadata import version
from pathlib import Path

import numpy as np

from pymrcd import _qn_ext, cov_mrcd
from pymrcd._types import FloatArray
from pymrcd.ogk import ogk_u
from pymrcd.qn import qn_columns

_PAIR_CHUNK_ELEMENTS = 1 << 22
"""Lote de pares del ``ogk_u`` numpy anterior a M5 (solo para el lote de ``qn_columns``)."""

SEED = 20261007
SHAPES: tuple[tuple[int, int], ...] = ((200, 300), (100, 250))
REPEATS = 3


def _median_time(fn: Callable[[], object]) -> dict[str, float | list[float]]:
    """Ejecuta ``fn`` ``REPEATS`` veces y devuelve la mediana y los tiempos individuales.

    Args:
        fn: Función sin argumentos a medir.

    Returns:
        Diccionario con ``median_s`` y ``runs_s`` (segundos).
    """
    runs: list[float] = []
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        fn()
        runs.append(time.perf_counter() - t0)
    return {"median_s": statistics.median(runs), "runs_s": runs}


def _ogk_input(x: FloatArray, alpha: float) -> FloatArray:
    """Entrada exacta de ``ogk_u`` dentro de ``cov_mrcd`` (``target = "identity"``).

    Args:
        x: Datos ``n x p``.
        alpha: Proporción usada para ``h`` (solo afecta a ``r6pack``, no a ``doScale``).

    Returns:
        ``R6Pack.x``: datos tras ``doScale``.
    """
    res = cov_mrcd(x, alpha=alpha)
    r6 = res.detail.r6
    if r6 is None:  # pragma: no cover - cov_mrcd sin init_hsets siempre ejecuta r6pack
        raise RuntimeError("r6pack no se ejecutó")
    return r6.x


def _first_ogk_batch(y: FloatArray) -> FloatArray:
    """Primer lote de columnas que ``ogk_u`` pasa a ``qn_columns`` (``pymrcd/ogk.py``).

    Args:
        y: Entrada de ``ogk_u``.

    Returns:
        Matriz ``n x 2m`` con ``Y_i + Y_j`` y ``Y_i - Y_j`` del primer lote de pares ``i > j``.
    """
    n, p = y.shape
    ii, jj = np.tril_indices(p, -1)
    step = max(1, _PAIR_CHUNK_ELEMENTS // max(2 * n, 1))
    yi = y[:, ii[:step]]
    yj = y[:, jj[:step]]
    return np.concatenate((yi + yj, yi - yj), axis=1)


def _measure(x: FloatArray, n_threads: int) -> dict[str, object]:
    """Mide todas las funciones sobre ``x`` con ``n_threads`` hilos.

    Args:
        x: Datos ``n x p``.
        n_threads: Hilos de la extensión C.

    Returns:
        Tiempos por función.
    """
    y = _ogk_input(x, 0.75)
    batch = _first_ogk_batch(y)
    return {
        "ogk_u": _median_time(partial(ogk_u, y, n_threads=n_threads)),
        "qn_columns_nxp": _median_time(partial(qn_columns, x, n_threads=n_threads)),
        "qn_columns_ogk_batch": {
            "shape": list(batch.shape),
            **_median_time(partial(qn_columns, batch, n_threads=n_threads)),
        },
        "cov_mrcd_alpha0.75": _median_time(partial(cov_mrcd, x, alpha=0.75, n_threads=n_threads)),
        "cov_mrcd_default": _median_time(partial(cov_mrcd, x, n_threads=n_threads)),
    }


def run(thread_specs: list[str]) -> dict[str, object]:
    """Ejecuta todas las mediciones.

    Args:
        thread_specs: Números de hilos (``"all"`` = todos los CPU visibles).

    Returns:
        Diccionario serializable con entorno y tiempos por número de hilos.
    """
    rng = np.random.default_rng(SEED)
    data = {f"{n}x{p}": rng.standard_normal((n, p)) for n, p in SHAPES}
    all_threads = _qn_ext.default_threads()
    by_threads: dict[str, object] = {}
    for spec in thread_specs:
        n_threads = all_threads if spec == "all" else int(spec)
        results: dict[str, object] = {}
        for key, x in data.items():
            entry = _measure(x, n_threads)
            results[key] = entry
            print(f"threads={spec} ({n_threads}) {key}")
            for name, val in entry.items():
                print(f"  {name:24s} {val}")
        by_threads[spec] = {"n_threads": n_threads, "results": results}
    return {
        "seed": SEED,
        "repeats": REPEATS,
        "env": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": version("scipy"),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "default_threads": all_threads,
            "build_info": _qn_ext.build_info(),
        },
        "threads": by_threads,
    }


def main() -> None:
    """Punto de entrada: ejecuta el benchmark y escribe el JSON en la ruta dada."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("output", type=Path, help="Ruta del JSON de salida")
    parser.add_argument(
        "--threads",
        default="1,all",
        help="Lista de hilos separada por comas ('all' = todos los CPU visibles)",
    )
    args = parser.parse_args()
    out = run([t.strip() for t in str(args.threads).split(",") if t.strip()])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"JSON escrito en {args.output}")


if __name__ == "__main__":
    main()
