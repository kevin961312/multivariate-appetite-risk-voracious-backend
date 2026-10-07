"""Factor de consistencia ``.MCDcons`` de ``robustbase`` (``scfac`` de ``rrcov``).

``rrcov`` lo calcula en ``detmrcd.R:460`` como ``robustbase::.MCDcons(p, h/n)``. Por decisión del
dueño (revisión de la pregunta P3) ``scfac`` debe coincidir **bit a bit** con R: ``qchisq`` y
``pgamma`` no se toman de ``scipy`` (difieren hasta 1.2e-14 relativo) sino del port literal de
``nmath`` de R 4.5.2, con las contracciones FMA del binario del oráculo (:mod:`pymrcd._nmath`).
"""

from __future__ import annotations

from pymrcd._nmath import pgamma, qchisq

__all__ = ["mcd_cons"]


def mcd_cons(p: int, alpha: float) -> float:
    """``robustbase::.MCDcons(p, alpha)``.

    Fuente: ``robustbase-0.99-6/R/covMcd.R:602-607``: ``qalpha <- qchisq(alpha, p)``;
    ``caI <- pgamma(qalpha/2, p/2 + 1) / alpha``; devuelve ``1/caI``. ``qchisq`` y ``pgamma`` son
    los de ``nmath`` (``qchisq.c``, ``qgamma.c``, ``pgamma.c``), portados en :mod:`pymrcd._nmath`.

    Args:
        p: Dimensión.
        alpha: Proporción ``h/n``.

    Returns:
        El factor de consistencia.
    """
    qalpha = qchisq(alpha, p)
    ca_i = pgamma(qalpha / 2, p / 2 + 1) / alpha
    return 1 / ca_i
