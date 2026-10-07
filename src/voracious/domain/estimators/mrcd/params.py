"""Parámetros de MRCD, con los defaults de ``rrcov::CovControlMrcd`` (``rrcov`` 1.7-7).

Cada default cita su origen en ``docs/metodos/mrcd.md`` (tabla «Parámetros»). Aquí no se valida
nada: ``pymrcd.cov_mrcd`` reproduce las validaciones de ``rrcov`` (``0.5 <= alpha <= 1`` en
``detmrcd.R:400-401``; ``target`` en ``CovControl.R:26``) y sus errores llegan como
``EstimationError`` con código ``MRCD_FIT_FAILED``. ``maxcsteps``, ``rho`` y ``maxcond`` no se
validan en ``rrcov`` y tampoco aquí.
"""

from dataclasses import dataclass
from typing import Literal

__all__ = ["MRCDParams", "MRCDTarget"]

MRCDTarget = Literal["identity", "equicorrelation"]
"""Matriz objetivo de la regularización (``CovControl.R:26``)."""


@dataclass(frozen=True)
class MRCDParams:
    """Parámetros de ``CovMrcd``.

    Attributes:
        alpha: Proporción del subconjunto. Default ``0.5`` (``CovControl.R:22``;
            ``AllClasses.R:138``).
        h: Tamaño del subconjunto; si se da, prevalece y ``alpha = h/n`` (``detmrcd.R:396``).
            Default ``None`` (``CovControl.R:23``).
        maxcsteps: Máximo de C-steps por subconjunto inicial. Default ``200``
            (``CovControl.R:24``).
        rho: Regularización fija o ``None`` para la selección automática por número de condición
            (``detmrcd.R:465``). Default ``None`` (``CovControl.R:25``).
        target: ``"identity"`` o ``"equicorrelation"``. Default ``"identity"``
            (``CovControl.R:26,:34``).
        maxcond: Número de condición objetivo. Default ``50`` (``CovControl.R:27``).
    """

    alpha: float = 0.5
    h: int | None = None
    maxcsteps: int = 200
    rho: float | None = None
    target: MRCDTarget = "identity"
    maxcond: float = 50.0
