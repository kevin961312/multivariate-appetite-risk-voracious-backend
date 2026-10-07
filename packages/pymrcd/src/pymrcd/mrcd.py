"""API pública: ``cov_mrcd``, port de ``rrcov::CovMrcd`` (``rrcov`` 1.7-7).

Fuente: ``rrcov-1.7-7/R/CovMrcd.R:1-82`` (especificación §3.1, §3.11). Diferencias de API
documentadas (decisiones del dueño):

- Índices en **base 0** (``best``, ``i_best``, ``init_hsets``); en R son base 1.
- ``target`` fuera de ``{"identity", "equicorrelation"}`` lanza ``RError`` (P8; R lo trataría como
  equicorrelación, ``CovMrcd.R:29``).
- Los fallos de R (columna constante, ``p == 1`` con equicorrelación, matriz no definida positiva)
  lanzan ``RError`` con el mensaje de R, sin *fallback* (P7).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pymrcd._errors import RError
from pymrcd._rlinalg import r_mahalanobis_inverted, r_matvec
from pymrcd._types import FloatArray, IntArray
from pymrcd.detmrcd import DetMrcd, detmrcd

__all__ = ["TARGETS", "MrcdResult", "cov_mrcd", "mahalanobis"]

TARGETS = ("identity", "equicorrelation")
"""Valores admitidos de ``target`` (``CovControl.R:26``)."""


@dataclass(frozen=True)
class MrcdResult:
    """Resultado de ``cov_mrcd`` con los nombres de los *slots* de ``rrcov``.

    Attributes:
        center: Centro MRCD (``center``).
        cov: Covarianza MRCD (``cov``).
        icov: Inversa de ``cov`` (``icov``).
        rho: Parámetro de regularización (``rho``).
        target: Matriz objetivo en la escala original (``target``).
        cnp2: Factor de consistencia ``.MCDcons(p, h/n)`` (``cnp2``).
        crit: ``log(det(cov))`` (``crit``).
        best: Subconjunto óptimo, base 0, ordenado (``best``).
        mah: Distancias de Mahalanobis al cuadrado de las filas de ``x`` (``mah``).
        alpha: ``alpha`` efectivo (``alpha``).
        quan: Tamaño del subconjunto ``h`` (``quan``).
        n_obs: Observaciones usadas (``n.obs``).
        x: Datos filtrados (``X``).
        ok: Máscara de filas finitas de la entrada (``ok`` de ``CovMrcd.R:19``).
        i_best: Subconjuntos iniciales empatados en el óptimo, base 0 (``iBest``).
        n_csteps: C-steps por subconjunto inicial (``n.csteps``; 0 en ``initV``).
        init_hsets: Subconjuntos iniciales ``h x 6``, base 0, orden de distancia (``initHsets``).
        detail: Salida completa de ``.detmrcd`` (intermedios).
    """

    center: FloatArray
    cov: FloatArray
    icov: FloatArray
    rho: float
    target: FloatArray
    cnp2: float
    crit: float
    best: IntArray
    mah: FloatArray
    alpha: float
    quan: int
    n_obs: int
    x: FloatArray
    ok: npt.NDArray[np.bool_]
    i_best: IntArray
    n_csteps: IntArray
    init_hsets: IntArray
    detail: DetMrcd

    @property
    def h(self) -> int:
        """Alias de ``quan`` (``h`` de ``.detmrcd``)."""
        return self.quan

    @property
    def n_csteps_total(self) -> int:
        """Suma de ``n_csteps`` (diagnóstico)."""
        return int(self.n_csteps.sum())


def cov_mrcd(
    x: npt.ArrayLike,
    alpha: float = 0.5,
    h: int | None = None,
    maxcsteps: int = 200,
    rho: float | None = None,
    target: str = "identity",
    maxcond: float = 50,
    init_hsets: npt.ArrayLike | None = None,
) -> MrcdResult:
    """Estimador MRCD, port fiel de ``rrcov::CovMrcd``.

    Fuente: ``rrcov-1.7-7/R/CovMrcd.R:1-82``: vector ⇒ matriz de una columna (``:14-16``);
    filtro ``is.finite(x %*% rep.int(1, ncol(x)))`` (``:19-20``, ``dgemv``: descarta filas con
    ``NaN``/``Inf`` y filas cuya suma desborda); ``.detmrcd`` con ``target = 0`` si
    ``"identity"``, si no ``1`` (``:27-31``); ``best = sort(best)`` (``:42``);
    ``mah = mahalanobis(x, center, icov, inverted=TRUE)`` sobre la ``x`` filtrada (``:46``,
    trampa T23). Valores por defecto de ``CovControlMrcd`` (``CovControl.R:22-28``).

    Args:
        x: Datos ``n x p`` (o vector).
        alpha: Proporción de observaciones del subconjunto (``0.5 <= alpha <= 1``).
        h: Tamaño del subconjunto; si se da, prevalece y ``alpha = h/n``.
        maxcsteps: Máximo de C-steps por subconjunto inicial.
        rho: Regularización fija o ``None`` (selección automática).
        target: ``"identity"`` o ``"equicorrelation"``.
        maxcond: Número de condición objetivo.
        init_hsets: Subconjuntos iniciales ``h' x L`` en **base 0** (``initHsets`` de R menos 1)
            o ``None`` para calcularlos con ``r6pack``.

    Returns:
        ``MrcdResult``.

    Raises:
        RError: ``target`` no válido (P8) o cualquier error de R en el camino (P7).
    """
    if target not in TARGETS:
        raise RError(f"'arg' should be one of {', '.join(repr(t) for t in TARGETS)}")
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.ndim != 2:
        raise RError("'x' must be a matrix or a vector")
    p = arr.shape[1]
    with np.errstate(over="ignore", invalid="ignore"):
        rowsum = r_matvec(arr, np.ones(p, dtype=np.float64))
    ok = np.isfinite(rowsum)
    xf = np.array(arr[ok, :], dtype=np.float64)
    n = xf.shape[0]
    if n == 0:
        raise RError("All observations have missing values!")
    hs = None if init_hsets is None else np.asarray(init_hsets)
    res = detmrcd(
        xf,
        h=h,
        alpha=alpha,
        rho=rho,
        maxcond=maxcond,
        target=0 if target == "identity" else 1,
        maxcsteps=maxcsteps,
        hsets_init=hs,
    )
    mah = r_mahalanobis_inverted(xf, res.initmean, res.icov)
    return MrcdResult(
        center=res.initmean,
        cov=res.initcovariance,
        icov=res.icov,
        rho=res.rho,
        target=res.target,
        cnp2=res.calpha,
        crit=res.mcdestimate,
        best=np.sort(res.best),
        mah=mah,
        alpha=res.alpha,
        quan=res.h,
        n_obs=n,
        x=xf,
        ok=ok,
        i_best=res.i_best,
        n_csteps=res.n_csteps,
        init_hsets=res.hsets_init,
        detail=res,
    )


def mahalanobis(x: npt.ArrayLike, center: npt.ArrayLike, icov: npt.ArrayLike) -> FloatArray:
    """Distancias de Mahalanobis al cuadrado con la inversa dada, como en ``rrcov::CovMrcd``.

    Fuente: ``stats::mahalanobis(x, center, cov, inverted=TRUE)`` de R 4.5.2
    (``R-4.5.2/src/library/stats/R/mahalanobis.R:31-47``): un vector es **una fila**
    (``:33``), ``sweep`` resta el centro por columnas (``:36``) y ``rowSums(x %*% cov * x)``
    (``:46``). Es la misma rutina con la que ``cov_mrcd`` calcula ``mah``
    (``rrcov-1.7-7/R/CovMrcd.R:46``), así que ``mahalanobis(res.x, res.center, res.icov)`` es
    igual bit a bit a ``res.mah``.

    Conformidad de ``icov`` (``mahalanobis.R:46``, ``x %*% cov * x``): si ``nrow(icov) != p``
    falla ``%*%`` con ``non-conformable arguments``; si ``nrow(icov) == p`` pero
    ``ncol(icov) != p``, ``%*%`` da ``n x k`` y falla ``*`` con ``non-conformable arrays``. Un
    ``icov`` vector se trata como columna (regla de ``%*%`` cuando ``length == ncol(x)``). Sin esta
    comprobación el *broadcasting* de numpy daría un resultado erróneo en silencio.

    Divergencia explícita con R: si ``length(center) != p``, ``sweep`` (``mahalanobis.R:36``)
    solo **avisa** («STATS does not recycle exactly across MARGIN») y recicla el centro; aquí se
    lanza ``RError``. Es deliberadamente más estricto: un centro reciclado no tiene sentido
    estadístico y casi siempre indica un error de quien llama.

    Args:
        x: Matriz ``n x p`` (o vector de longitud ``p``, que se trata como una fila).
        center: Vector de longitud ``p``.
        icov: Inversa de la covarianza ``p x p``.

    Returns:
        Vector de ``n`` distancias al cuadrado.

    Raises:
        RError: si ``x`` no es vector ni matriz, si ``center`` no tiene longitud ``p`` (más
            estricto que R, ver arriba) o si ``icov`` no es ``p x p`` (mensajes de ``%*%`` y
            ``*`` de R).
    """
    arr = np.asarray(x, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[None, :]
    if arr.ndim != 2:
        raise RError("'x' must be a matrix or a vector")
    mu = np.asarray(center, dtype=np.float64)
    inv = np.asarray(icov, dtype=np.float64)
    p = arr.shape[1]
    if mu.ndim != 1 or mu.shape[0] != p:
        raise RError("non-conformable arguments")
    if inv.ndim == 1 and inv.shape[0] == p:
        inv = inv[:, None]  # %*% trata el vector como columna p x 1
    if inv.ndim != 2 or inv.shape[0] != p:
        raise RError("non-conformable arguments")  # %*% (mahalanobis.R:46)
    if inv.shape[1] != p:
        raise RError("non-conformable arrays")  # (n x k) * (n x p) (mahalanobis.R:46)
    return r_mahalanobis_inverted(arr, mu, inv)
