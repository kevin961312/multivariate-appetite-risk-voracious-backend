"""Criterio de producción de fila limpia de T²MRCD (``docs/metodos/t2mrcd.md``, P2).

Decisión del dueño (2026-10-07): las observaciones limpias del histórico son «lo que está en el
0.75», es decir, el subconjunto óptimo ``best`` (las ``h`` filas) del ajuste MRCD del histórico con
``alpha = 0.75`` (``T2MRCD_MRCD_ALPHA`` en ``params.py``).
"""

import numpy as np

from voracious.domain.common import BoolVector, FloatMatrix
from voracious.domain.estimators.mrcd import MRCDFit

__all__ = ["best_subset_criterion"]


def best_subset_criterion(fit: MRCDFit, x: FloatMatrix) -> BoolVector:
    """Marca como limpias exactamente las filas del subconjunto ``best`` del ajuste MRCD.

    ``fit.best`` indexa (base 0) las filas usadas por MRCD, ``x[fit.ok]`` (``CovMrcd.R:19-20``);
    aquí se traducen a índices de ``x``.

    Args:
        fit: Ajuste MRCD del histórico completo.
        x: Histórico ``n x p`` (el mismo con el que se ajustó ``fit``).

    Returns:
        Máscara booleana de longitud ``n`` con ``True`` en las ``h`` filas de ``best``.
    """
    mask = np.zeros(x.shape[0], dtype=np.bool_)
    mask[np.flatnonzero(fit.ok)[fit.best]] = True
    return mask
