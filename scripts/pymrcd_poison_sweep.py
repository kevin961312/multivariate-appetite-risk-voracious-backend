"""Barrido de la extensión C de pymrcd con el modo «poison» (especificación §3.12.9, ahorro A1).

Lo usa el trabajo ``sanitizers`` de CI (M2, Paso 4) con la extensión compilada con ASan/UBSan:
muchas formas de entrada (``n`` pequeños y grandes, empates, ``±0``, subnormales, hilos) ejercitan
las ramas de ``qn0``, ``whimed_i``, ``R_qsort`` y ``rPsort`` para que el sanitizador vea cualquier
lectura fuera de rango o sin inicializar. Con ``poison`` el espacio de trabajo se llena de basura
antes de cada columna: si ``qn0`` leyera una celda antes de escribirla, el resultado cambiaría en
bits.

Uso: ``uv run python scripts/pymrcd_poison_sweep.py [iteraciones]``. Sale con 1 si algo difiere.
"""

import sys

import numpy as np

from pymrcd import _qn_ext
from pymrcd.qn import QN_CONSTANT, QN_SMALL_N_FACTORS, default_k, qn_finite_c

_SEED = 20261009
_DEFAULT_ITERATIONS = 2000


def _bits(a: np.ndarray) -> np.ndarray:
    """Vista entera de los bits de un arreglo ``float64`` (distingue ``+0`` de ``-0``)."""
    return np.ascontiguousarray(a, dtype=np.float64).view(np.uint64)


def _sample(rng: np.random.Generator, n: int, m: int) -> np.ndarray:
    """Matriz ``n x m`` con mezcla de normales, empates, ceros con signo y subnormales."""
    kind = int(rng.integers(0, 4))
    if kind == 0:
        x = rng.normal(size=(n, m))
    elif kind == 1:
        x = rng.integers(-3, 4, size=(n, m)).astype(np.float64)
    elif kind == 2:
        x = np.where(rng.random((n, m)) < 0.6, 0.0, rng.normal(size=(n, m)))
        x = np.where(rng.random((n, m)) < 0.5, -x, x)
    else:
        x = rng.normal(size=(n, m)) * 1e-300
    return np.asarray(x, dtype=np.float64)


def main(iterations: int) -> int:
    """Corre el barrido.

    Args:
        iterations: Número de casos aleatorios.

    Returns:
        0 si todos los casos coinciden en bits; 1 si alguno difiere.
    """
    rng = np.random.default_rng(_SEED)
    failures = 0
    for i in range(iterations):
        n = int(rng.choice([2, 3, 4, 5, 7, 12, 13, 31, int(rng.integers(2, 200))]))
        m = int(rng.integers(1, 40))
        threads = int(rng.integers(1, 9))
        x = _sample(rng, n, m)
        out_plain = np.empty(m)
        out_poison = np.empty(m)
        _qn_ext.qn0_columns(x, out_plain, default_k(n), 1)
        _qn_ext.qn0_columns(x, out_poison, default_k(n), threads, True)
        if not np.array_equal(_bits(out_plain), _bits(out_poison)):
            print(f"qn0_columns difiere: caso {i}, n={n}, m={m}, hilos={threads}")
            failures += 1
        p = int(rng.integers(2, 12))
        y = _sample(rng, n, p)
        small_n = n <= 12
        factor = QN_SMALL_N_FACTORS[n - 2] if small_n else qn_finite_c(n)
        u_plain = np.eye(p)
        u_poison = np.eye(p)
        _qn_ext.ogk_u(y, u_plain, QN_CONSTANT, factor, small_n, 1)
        _qn_ext.ogk_u(y, u_poison, QN_CONSTANT, factor, small_n, threads, True)
        if not np.array_equal(_bits(u_plain), _bits(u_poison)):
            print(f"ogk_u difiere: caso {i}, n={n}, p={p}, hilos={threads}")
            failures += 1
    print(f"barrido poison: {iterations} casos, {failures} diferencias")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_ITERATIONS))
