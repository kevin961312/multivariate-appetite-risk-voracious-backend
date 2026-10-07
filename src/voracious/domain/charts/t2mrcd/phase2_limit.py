"""Remuestreo de cada réplica: muestra de ajuste y filas *out-of-bag* (``docs/metodos/t2mrcd.md``).

Decisión del dueño (2026-10-07): el límite de Fase II es **no paramétrico**. En cada réplica se
remuestrean con reemplazo ``n_clean`` filas limpias (``h`` con el criterio de producción), se
reajusta MRCD **sobre esa muestra** y se calculan con **ese** ajuste dos conjuntos de T²:

- los de la muestra (las mismas filas que estimaron ``center`` y ``cov``) → límite de Fase I;
- los de las filas que **no** entraron en la muestra (*out-of-bag*) → límite de Fase II, porque
  imitan una observación nueva, independiente del ajuste.

Nunca se usa la dispersión del ajuste base para los *out-of-bag*: el T² de una observación
independiente con la dispersión estimada es mayor que con la que la estimó, y eso es justo lo que
el límite de Fase II debe capturar.

El ``ReplicateSampler`` es un ``Protocol`` para que los tests puedan comprobar el procedimiento
contra la teoría clásica con un muestreador «SOLO TEST» (``tests/support/``); en producción solo
existe ``BootstrapOOBSampler``.
"""

from dataclasses import dataclass
from typing import Final, Protocol

import numpy as np

from voracious.domain.common import FloatMatrix

__all__ = [
    "BOOTSTRAP_OOB_EMPTY",
    "BootstrapOOBSampler",
    "ReplicateSampler",
    "bootstrap_oob_sampler",
]

BOOTSTRAP_OOB_EMPTY: Final = "BOOTSTRAP_OOB_EMPTY"
"""Código de error: una réplica no dejó filas *out-of-bag* (la Fase I falla; no se descarta)."""


class ReplicateSampler(Protocol):
    """Genera la muestra de ajuste y las observaciones «nuevas» de una réplica (*picklable*)."""

    @property
    def name(self) -> str:
        """Nombre estable del muestreador."""
        ...

    def sample(
        self, x_clean: FloatMatrix, rng: np.random.Generator
    ) -> tuple[FloatMatrix, FloatMatrix]:
        """Genera las dos partes de la réplica.

        Args:
            x_clean: Observaciones limpias ``n_clean x p``.
            rng: Generador propio de la réplica.

        Returns:
            ``(muestra de ajuste, observaciones nuevas)``; la segunda puede estar vacía.
        """
        ...


@dataclass(frozen=True)
class BootstrapOOBSampler:
    """Bootstrap no paramétrico con *out-of-bag* (producción).

    Remuestrea con reemplazo ``n_clean`` índices de ``x_clean``; las filas nunca elegidas son las
    *out-of-bag*, en orden de fila.
    """

    @property
    def name(self) -> str:
        """Nombre estable: ``"bootstrap_oob"``."""
        return "bootstrap_oob"

    def sample(
        self, x_clean: FloatMatrix, rng: np.random.Generator
    ) -> tuple[FloatMatrix, FloatMatrix]:
        """Remuestrea con reemplazo y separa las filas *out-of-bag*.

        Args:
            x_clean: Observaciones limpias ``n_clean x p``.
            rng: Generador propio de la réplica.

        Returns:
            ``(x_clean[in_sample], x_clean[out_of_bag])``.
        """
        n_clean = x_clean.shape[0]
        in_sample = rng.integers(0, n_clean, size=n_clean)
        out_of_bag = np.ones(n_clean, dtype=np.bool_)
        out_of_bag[in_sample] = False
        return x_clean[in_sample], x_clean[out_of_bag]


bootstrap_oob_sampler: Final = BootstrapOOBSampler()
"""Muestreador de producción (decisión del dueño 2026-10-07)."""
