"""Adaptador fino sobre ``pymrcd.cov_mrcd`` (ADR 0006, punto 8).

Único módulo de ``voracious`` (junto con ``result.py`` del mismo paquete) que importa ``pymrcd``
(contrato de import-linter). No hay *fallback*: si ``pymrcd`` lanza ``RError`` (lo mismo que haría
``rrcov``), el ajuste termina en ``EstimationError`` con código ``MRCD_FIT_FAILED``.

``MRCDEstimator`` envuelve ``fit_mrcd`` con sus parámetros para cumplir el contrato común
``LocationScatterEstimator`` (``domain/common/estimation.py``): así una carta reparte réplicas
bootstrap sin conocer el estimador concreto.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
import numpy.typing as npt

import pymrcd
from voracious.domain.common import EstimationError, FloatMatrix, as_matrix
from voracious.domain.estimators.mrcd.params import MRCDParams
from voracious.domain.estimators.mrcd.result import MRCDFit

if TYPE_CHECKING:
    from voracious.domain.common.estimation import LocationScatterEstimator, LocationScatterFit

__all__ = ["ESTIMATOR_NAME", "MRCD_FIT_FAILED", "PYMRCD_VERSION", "MRCDEstimator", "fit_mrcd"]

ESTIMATOR_NAME: Final = "mrcd"
"""Nombre estable del estimador (se guarda con los límites para auditar)."""

MRCD_FIT_FAILED = "MRCD_FIT_FAILED"
"""Código de error de un ajuste MRCD fallido."""

PYMRCD_VERSION: str = pymrcd.__version__
"""Versión de ``pymrcd`` con la que se ajusta (se guarda con cada modelo)."""


def fit_mrcd(x: npt.ArrayLike, params: MRCDParams, n_threads: int | None = None) -> MRCDFit:
    """Ajusta MRCD con ``pymrcd.cov_mrcd`` (subconjuntos iniciales calculados, sin inyectar).

    Las filas no finitas las descarta ``cov_mrcd`` igual que ``rrcov`` (``CovMrcd.R:19-20``) y su
    máscara queda en ``MRCDFit.ok``; cada método decide antes si las admite.

    Args:
        x: Datos ``n x p``.
        params: Parámetros de MRCD.
        n_threads: Hilos de la extensión C de ``pymrcd``. Parámetro de **rendimiento**, no
            estadístico: no forma parte de ``MRCDParams``, no se persiste y no cambia ningún bit
            del ajuste (``docs/metodos/mrcd-especificacion.md`` §3.12.9 e). ``None`` ⇒ por
            defecto de ``pymrcd``.

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
            n_threads=n_threads,
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


@dataclass(frozen=True)
class MRCDEstimator:
    """Estimador MRCD con parámetros fijos (``LocationScatterEstimator``; *picklable*).

    Attributes:
        params: Parámetros de MRCD de cada ajuste.
        n_threads: Hilos de ``pymrcd`` por ajuste (rendimiento; ver ``fit_mrcd``). No es un
            parámetro estadístico y no se guarda con la versión de la carta.
    """

    params: MRCDParams
    n_threads: int | None = None

    @property
    def name(self) -> str:
        """Nombre estable: ``"mrcd"``."""
        return ESTIMATOR_NAME

    def fit(self, x: FloatMatrix) -> MRCDFit:
        """Ajusta MRCD delegando en ``fit_mrcd`` (sin cambios de método ni *fallback*).

        Args:
            x: Datos ``n x p``.

        Returns:
            El ajuste MRCD.

        Raises:
            InvalidInputError: Si ``x`` no es una matriz numérica de dos dimensiones.
            EstimationError: ``MRCD_FIT_FAILED`` si ``rrcov`` fallaría.
        """
        return fit_mrcd(x, self.params, n_threads=self.n_threads)


if TYPE_CHECKING:
    # mypy verifica que el adaptador cumple los contratos comunes (ADR 0004, punto 4).
    _estimator_conforms: LocationScatterEstimator = MRCDEstimator(MRCDParams())

    def _fit_conforms(fit: MRCDFit) -> LocationScatterFit:
        return fit
