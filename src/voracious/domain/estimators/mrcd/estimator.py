"""Adaptador fino sobre ``pymrcd.cov_mrcd`` (ADR 0006, punto 8).

Único módulo de ``voracious`` (junto con ``result.py`` del mismo paquete) que importa ``pymrcd``
(contrato de import-linter). No hay *fallback*: si ``pymrcd`` lanza ``RError`` (lo mismo que haría
``rrcov``), el ajuste termina en ``EstimationError`` con código ``MRCD_FIT_FAILED``.
"""

import numpy as np
import numpy.typing as npt

import pymrcd
from voracious.domain.common import EstimationError, as_matrix
from voracious.domain.estimators.mrcd.params import MRCDParams
from voracious.domain.estimators.mrcd.result import MRCDFit

__all__ = ["MRCD_FIT_FAILED", "PYMRCD_VERSION", "fit_mrcd"]

MRCD_FIT_FAILED = "MRCD_FIT_FAILED"
"""Código de error de un ajuste MRCD fallido."""

PYMRCD_VERSION: str = pymrcd.__version__
"""Versión de ``pymrcd`` con la que se ajusta (se guarda con cada modelo)."""


def fit_mrcd(x: npt.ArrayLike, params: MRCDParams) -> MRCDFit:
    """Ajusta MRCD con ``pymrcd.cov_mrcd`` (subconjuntos iniciales calculados, sin inyectar).

    Las filas no finitas las descarta ``cov_mrcd`` igual que ``rrcov`` (``CovMrcd.R:19-20``) y su
    máscara queda en ``MRCDFit.ok``; cada método decide antes si las admite.

    Args:
        x: Datos ``n x p``.
        params: Parámetros de MRCD.

    Returns:
        El ajuste.

    Raises:
        InvalidInputError: Si ``x`` no es una matriz numérica de dos dimensiones.
        EstimationError: ``MRCD_FIT_FAILED`` con ``details["r_message"]`` si ``rrcov`` fallaría.
    """
    arr = as_matrix(x)
    try:
        res = pymrcd.cov_mrcd(
            arr,
            alpha=params.alpha,
            h=params.h,
            maxcsteps=params.maxcsteps,
            rho=params.rho,
            target=params.target,
            maxcond=params.maxcond,
        )
    except pymrcd.RError as exc:
        raise EstimationError(
            MRCD_FIT_FAILED, "el ajuste MRCD falló", details={"r_message": str(exc)}
        ) from exc
    return MRCDFit(
        center=res.center,
        cov=res.cov,
        icov=res.icov,
        rho=float(res.rho),
        cnp2=float(res.cnp2),
        crit=float(res.crit),
        best=np.asarray(res.best, dtype=np.int64),
        mah=res.mah,
        alpha=float(res.alpha),
        h=int(res.quan),
        n_obs=int(res.n_obs),
        ok=res.ok,
        i_best=np.asarray(res.i_best, dtype=np.int64),
        n_csteps=np.asarray(res.n_csteps, dtype=np.int64),
    )
