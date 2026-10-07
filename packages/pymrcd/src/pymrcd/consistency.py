"""Factor de consistencia ``.MCDcons`` de ``robustbase`` (``scfac`` de ``rrcov``).

``rrcov`` lo calcula en ``detmrcd.R:460`` como ``robustbase::.MCDcons(p, h/n)``. Por la decisión
P3 del
dueño se usa ``scipy`` (no se porta ``nmath``): la diferencia relativa medida con R es ≤ 6.5e-15
(especificación §3.6, sonda S5) y la tolerancia declarada es ``rtol = 1e-14`` (§11, trampa T21).
"""

from __future__ import annotations

from scipy import special, stats

__all__ = ["mcd_cons"]


def mcd_cons(p: int, alpha: float) -> float:
    """``robustbase::.MCDcons(p, alpha)``.

    Fuente: ``robustbase-0.99-6/R/covMcd.R:602-607``: ``qalpha = qchisq(alpha, p)``;
    ``caI = pgamma(qalpha/2, p/2 + 1) / alpha``; devuelve ``1/caI``. ``qchisq`` ↔
    ``scipy.stats.chi2.ppf`` y ``pgamma(q, a)`` ↔ ``scipy.special.gammainc(a, q)`` (P regularizada).

    Args:
        p: Dimensión.
        alpha: Proporción ``h/n``.

    Returns:
        El factor de consistencia.
    """
    qalpha = float(stats.chi2.ppf(alpha, p))
    ca_i = float(special.gammainc(p / 2 + 1, qalpha / 2)) / alpha
    return 1 / ca_i
