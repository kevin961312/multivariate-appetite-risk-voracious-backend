"""Parámetros de la carta T²MRCD (``docs/metodos/t2mrcd.md``).

Los límites se calibran por bootstrap sobre las observaciones limpias del histórico. Cada réplica
remuestrea con reemplazo, reajusta MRCD sobre la muestra y da dos conjuntos de T² con **ese**
ajuste: los de la muestra (Fase I) y los de las filas que no entraron, *out-of-bag* (Fase II).
Estado de cada campo:

- ``n_replicates`` (B): **decidido**, 100 por defecto, configurable. Cita: Q. Heng, H. Shen y
  K. Lange (2026), «A stability framework for parameter selection in the minimum covariance
  determinant problem», *Journal of Computational and Graphical Statistics*, 35(1):27-39,
  doi:10.1080/10618600.2025.2495780.
- ``seed``: obligatoria; las semillas salen de ``SeedSequence`` con huecos fijos (``seeds.py``).
- ``clean_criterion`` (P2): **decidido** (dueño, 2026-10-07): el subconjunto ``best`` del ajuste
  MRCD del histórico (``best_subset_criterion``), que en T²MRCD se ajusta con el ``alpha`` de MRCD
  ``0.75`` (``T2MRCD_MRCD_ALPHA``): ``h = ceiling(0.75 n)`` filas (``rrcov`` 1.7-7,
  ``detmrcd.R:397``).
- ``alpha_limit`` (P4): **decidido** (dueño, 2026-10-07), default ``0.005`` (proporción: el
  cuantil tiene probabilidad ``0.995``). No es el ``alpha`` de MRCD.
- ``aggregation`` (P4): **decidido** (dueño, 2026-10-07, Paso 2b, Q1: pool): cuantil del
  *pool* de los T² de todas las réplicas (``pooled_quantile``; regla tipo 7, elección técnica
  reversible).
- ``phase2_alpha_limit``: **decidido** (dueño, 2026-10-07), default ``0.005``.
- ``phase2_aggregation``: **decidido** (dueño, 2026-10-07): igual que Fase I (``pooled_quantile``).

Sin depuración automática iterativa (decisión del dueño, 2026-10-09): la Fase I es exclusión humana
opcional, **un** ajuste MRCD y **una** calibración. Las filas fuera de ``best`` no se eliminan;
simplemente no entran en la estimación ni en el bootstrap.

Con los defaults no queda ningún campo pendiente. Si un campo decisivo se pasa explícitamente como
``None``, la Fase I termina en ``failed / T2MRCD_DECISION_PENDING`` sin ajustar nada.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from voracious.domain.charts.t2mrcd.aggregation import pooled_quantile
from voracious.domain.charts.t2mrcd.clean import best_subset_criterion
from voracious.domain.common import BoolVector, FloatMatrix, FloatVector, InvalidInputError
from voracious.domain.estimators.mrcd import MRCDFit, MRCDParams

__all__ = [
    "DEFAULT_ALPHA_LIMIT",
    "DEFAULT_N_REPLICATES",
    "DEFAULT_PHASE2_ALPHA_LIMIT",
    "T2MRCD_MRCD_ALPHA",
    "CleanCriterion",
    "LimitAggregation",
    "T2MRCDBootstrap",
    "T2MRCDParams",
]

DEFAULT_N_REPLICATES = 100
"""B por defecto: decisión del dueño (2026-10-07), t2mrcd.md.

Cita: Q. Heng, H. Shen y K. Lange (2026), «A stability framework for parameter selection in the
minimum covariance determinant problem», *Journal of Computational and Graphical Statistics*,
35(1):27-39, doi:10.1080/10618600.2025.2495780.
"""

DEFAULT_ALPHA_LIMIT = 0.005
"""``alpha_limit`` (cuantil ``1 - alpha_limit`` = 0.995): decisión del dueño 2026-10-07 (P4)."""

DEFAULT_PHASE2_ALPHA_LIMIT = 0.005
"""``phase2_alpha_limit`` (cuantil 0.995 de los T² *out-of-bag*): decisión del dueño 2026-10-07."""

T2MRCD_MRCD_ALPHA = 0.75
"""``alpha`` de MRCD en T²MRCD: decisión del dueño 2026-10-07, t2mrcd.md P2.

Las filas limpias son el subconjunto ``best`` de este ajuste. El adaptador ``MRCDParams`` conserva
el default de ``rrcov`` (0.5); solo cambia el default de la carta.
"""


class CleanCriterion(Protocol):
    """Criterio de fila «limpia» del histórico (P2; en producción, ``best_subset_criterion``)."""

    def __call__(self, fit: MRCDFit, x: FloatMatrix) -> BoolVector:
        """Marca las filas limpias del histórico.

        Args:
            fit: Ajuste MRCD del histórico completo.
            x: Histórico ``n x p`` (el mismo con el que se ajustó ``fit``).

        Returns:
            Máscara booleana de longitud ``n`` (``True`` = limpia).
        """
        ...


class LimitAggregation(Protocol):
    """Agregación de los T² bootstrap en un límite (P4; en producción, ``pooled_quantile``).

    Engloba cómo se combinan las réplicas y la regla de cuantil, y sabe estimar su propio error
    Monte Carlo (M6). Tiene un nombre estable para poder persistirla por nombre.
    """

    @property
    def name(self) -> str:
        """Nombre estable de la agregación."""
        ...

    def __call__(self, t2_by_replicate: Sequence[FloatVector], alpha: float) -> float:
        """Calcula el límite a partir de los T² de cada réplica.

        Args:
            t2_by_replicate: T² de cada réplica, en orden de réplica (puede haber vectores vacíos).
            alpha: Nivel del límite (``alpha_limit``, proporción en ``(0, 1)``); la probabilidad
                del cuantil es ``1 - alpha``. No es el ``alpha`` de MRCD.

        Returns:
            El límite de control.
        """
        ...

    def mc_error(
        self,
        t2_by_replicate: Sequence[FloatVector],
        alpha: float,
        seed: np.random.SeedSequence,
    ) -> float | None:
        """Error Monte Carlo del límite (diagnóstico, M6).

        Args:
            t2_by_replicate: T² de cada réplica.
            alpha: Nivel del límite.
            seed: Semilla propia del diagnóstico.

        Returns:
            Una medida de la variabilidad del límite entre calibraciones con distinta semilla, o
            ``None`` si no está disponible (p. ej., con una sola réplica).
        """
        ...


def _is_int(value: object) -> bool:
    """Indica si ``value`` es un entero (``int`` o entero de numpy), excluyendo ``bool``.

    Args:
        value: Valor a comprobar.

    Returns:
        ``True`` si es entero y no booleano.
    """
    return isinstance(value, int | np.integer) and not isinstance(value, bool)


@dataclass(frozen=True, kw_only=True)
class T2MRCDBootstrap:
    """Configuración del bootstrap de límites.

    Attributes:
        n_replicates: Número de remuestreos B (decidido; 100 por defecto).
        seed: Semilla raíz, entera y no negativa (obligatoria).
        alpha_limit: Nivel del límite, proporción en ``(0, 1)``: el cuantil tiene probabilidad
            ``1 - alpha_limit`` (decidido, P4; 0.005 por defecto, es decir, 0.995). Distinto del
            ``alpha`` de MRCD (``T2MRCDParams.mrcd.alpha``).
        clean_criterion: Criterio de fila limpia (decidido, P2; por defecto el subconjunto
            ``best`` del ajuste MRCD).
        aggregation: Agregación de Fase I (decidido, P4; por defecto ``pooled_quantile``).
            ``None`` explícito deja la Fase I en ``T2MRCD_DECISION_PENDING``.
        phase2_alpha_limit: Nivel del límite de Fase II, proporción en ``(0, 1)`` (decidido;
            0.005 por defecto).
        phase2_aggregation: Agregación de Fase II (decidido; por defecto ``pooled_quantile``,
            igual que Fase I). ``None`` explícito deja la Fase I en ``T2MRCD_DECISION_PENDING``.
    """

    n_replicates: int = DEFAULT_N_REPLICATES
    seed: int
    alpha_limit: float = DEFAULT_ALPHA_LIMIT
    clean_criterion: CleanCriterion = best_subset_criterion
    aggregation: LimitAggregation | None = pooled_quantile
    phase2_alpha_limit: float = DEFAULT_PHASE2_ALPHA_LIMIT
    phase2_aggregation: LimitAggregation | None = pooled_quantile

    def __post_init__(self) -> None:
        """Valida los campos decididos.

        Raises:
            InvalidInputError: Si ``n_replicates`` no es un entero ``>= 1``, ``seed`` no es un
                entero ``>= 0`` (``bool`` y ``float`` se rechazan) o ``alpha_limit`` o
                ``phase2_alpha_limit`` están fuera de ``(0, 1)``.
        """
        if not _is_int(self.n_replicates) or self.n_replicates < 1:
            raise InvalidInputError(
                "'n_replicates' debe ser un entero >= 1",
                details={"field": "bootstrap.n_replicates"},
            )
        if not _is_int(self.seed) or self.seed < 0:
            raise InvalidInputError(
                "'seed' debe ser un entero >= 0", details={"field": "bootstrap.seed"}
            )
        if not 0.0 < self.alpha_limit < 1.0:
            raise InvalidInputError(
                "'alpha_limit' debe estar en (0, 1)", details={"field": "bootstrap.alpha_limit"}
            )
        if not 0.0 < self.phase2_alpha_limit < 1.0:
            raise InvalidInputError(
                "'phase2_alpha_limit' debe estar en (0, 1)",
                details={"field": "bootstrap.phase2_alpha_limit"},
            )

    def pending_fields(self) -> list[str]:
        """Campos estadísticos aún sin decidir, en orden estable.

        Returns:
            Nombres con el prefijo ``bootstrap.``.
        """
        pending: list[str] = []
        if self.aggregation is None:
            pending.append("bootstrap.aggregation")
        if self.phase2_aggregation is None:
            pending.append("bootstrap.phase2_aggregation")
        return pending


@dataclass(frozen=True)
class T2MRCDParams:
    """Parámetros de la carta T²MRCD.

    Attributes:
        bootstrap: Configuración del bootstrap de límites.
        mrcd: Parámetros de MRCD; se usan en el ajuste del histórico y en cada réplica. Por
            defecto, los de ``rrcov`` salvo ``alpha = T2MRCD_MRCD_ALPHA`` (0.75, decisión del
            dueño, P2).
    """

    bootstrap: T2MRCDBootstrap
    mrcd: MRCDParams = field(default_factory=lambda: MRCDParams(alpha=T2MRCD_MRCD_ALPHA))
