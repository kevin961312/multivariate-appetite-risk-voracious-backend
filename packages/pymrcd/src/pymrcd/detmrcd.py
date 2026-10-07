"""Cuerpo de ``.detmrcd`` (``rrcov`` 1.7-7): estandarización, subconjuntos, ``rho``, C-steps, final.

Port de ``rrcov-1.7-7/R/detmrcd.R:26-637`` (especificación §3.2-§3.10). Trabaja, como R, con la
matriz traspuesta ``mX`` (``p x n``). Índices en **base 0**.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from pymrcd._errors import RError
from pymrcd._rbase import r_median_cols, r_pow, r_rowmeans
from pymrcd._rlinalg import r_chol, r_chol2inv, r_det, r_determinant, r_matprod, r_scale
from pymrcd._types import FloatArray, IntArray
from pymrcd.consistency import mcd_cons
from pymrcd.csteps import CStepResult, cstep_mrcd
from pymrcd.qn import qn_columns
from pymrcd.r6pack import R6Pack, r6pack
from pymrcd.rcov import InvSMW, inv_smw
from pymrcd.rho import RhoK, RhoSelection, SubsetScatter, rho_for_subset, select_rho, subset_scatter
from pymrcd.target import EquicorrTransform, TargetCorr, equicorrelation_transform, target_corr

__all__ = [
    "MINSCALE",
    "BackTransform",
    "DetMrcd",
    "FinalEstimate",
    "back_transform",
    "detmrcd",
    "final_estimate",
    "mrcd_objective",
    "resolve_h",
]

MINSCALE = 0.001
"""``minscale`` por defecto de ``.detmrcd`` (``detmrcd.R:27``)."""


def resolve_h(n: int, alpha: float | None, h: float | None) -> tuple[int, float]:
    """``h`` y ``alpha`` efectivos (``detmrcd.R:396-404``).

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:396-404``: si ``h`` no es ``NULL``, ``alpha = h/n``; si no,
    ``h = ceiling(alpha*n)``; error si ``alpha < 1/2 | alpha > 1``; ``h = as.integer(h)``
    (trunca).

    Args:
        n: Número de observaciones.
        alpha: Proporción (``None`` si se da ``h``).
        h: Tamaño del subconjunto o ``None``.

    Returns:
        ``(h, alpha)``.

    Raises:
        RError: si faltan ambos o ``alpha`` está fuera de ``[0.5, 1]``.
    """
    if h is not None:
        alpha = h / n
    elif alpha is not None:
        h = math.ceil(alpha * n)
    else:
        raise RError(
            "Either 'h' (number of observations in a subset) or 'alpha' (proportion of "
            "observations) has to be supplied!"
        )
    if math.isnan(alpha) or alpha < 1 / 2 or alpha > 1:
        raise RError("'alpha' must be between 0.5 and 1.0!")
    return int(h), float(alpha)


def mrcd_objective(cov: FloatArray, p: int) -> float:
    """``obj(x) = det(x)^(1/p)`` (``objective = "geom"``, ``detmrcd.R:409-413``).

    ``det`` como ``sign*exp(modulus)`` y ``R_pow``: puede subdesbordar a 0 y empatar (trampa T19).

    Args:
        cov: Matriz ``p x p``.
        p: Dimensión.

    Returns:
        El objetivo.
    """
    return r_pow(r_det(cov), 1 / p)


class FinalEstimate(NamedTuple):
    """Estimación final en el espacio estandarizado (``detmrcd.R:577-593``).

    Attributes:
        m_e: ``mX[, hindex] - ret$mu`` (``p x h``).
        W: ``mE %*% t(mE)/(h-1)``.
        mu: ``rowMeans(mX[, hindex])``.
        cov: ``rho*I + (1-rho)*c_alpha*W``.
        icov: Inversa (SMW si ``p > n``, si no Cholesky).
        smw: Intermedios de ``.InvSMW`` (``None`` con Cholesky).
    """

    m_e: FloatArray
    W: FloatArray
    mu: FloatArray
    cov: FloatArray
    icov: FloatArray
    smw: InvSMW | None


def final_estimate(
    mx: FloatArray, hindex: IntArray, mu_last: FloatArray, rho: float, c_alpha: float, h: int
) -> FinalEstimate:
    """Estimación MRCD final en el espacio estandarizado.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:577-593``: ``mE = mX[, hindex] - ret$mu`` (``:578``;
    ``ret$mu`` es la media de la última ``.RCOV`` del mejor subconjunto, trampa T18);
    ``W = mE %*% t(mE)/(h-1)`` (``:579``); ``MRCDmu = rowMeans(mX[, hindex])`` (``:583``);
    ``MRCDcov = rho*I + (1-rho)*c_alpha*W`` (``:584``); si ``p > n`` (``n`` = observaciones, trampa
    T11) ``.InvSMW(rho, I, nu=(1-rho)*c_alpha, mU=mE/sqrt(h-1))`` (``:588-591``), si no
    ``chol2inv(chol(MRCDcov))`` (``:593``).

    Args:
        mx: Datos ``p x n``.
        hindex: Subconjunto óptimo (base 0).
        mu_last: ``ret$mu``.
        rho: Regularización.
        c_alpha: Factor de consistencia.
        h: Tamaño del subconjunto.

    Returns:
        ``FinalEstimate``.
    """
    p, n = mx.shape
    me = mx[:, hindex] - np.asarray(mu_last, dtype=np.float64)[:, None]
    w = r_matprod(me, np.array(me.T, dtype=np.float64)) / (h - 1)
    mrcd_mu = r_rowmeans(mx[:, hindex])
    mrcd_cov = rho * np.eye(p, dtype=np.float64) + ((1 - rho) * c_alpha) * w
    smw: InvSMW | None = None
    if p > n:
        smw = inv_smw(rho, (1 - rho) * c_alpha, me / np.sqrt(np.float64(h - 1)))
        icov = smw.inv
    else:
        icov = r_chol2inv(r_chol(mrcd_cov))
    return FinalEstimate(m_e=me, W=w, mu=mrcd_mu, cov=mrcd_cov, icov=icov, smw=smw)


class BackTransform(NamedTuple):
    """Estimación en la escala original (``detmrcd.R:599-619``).

    Attributes:
        center: Centro.
        cov: Covarianza.
        icov: Inversa.
        target: Objetivo retro-transformado.
        crit: ``determinant(cov)$modulus``.
    """

    center: FloatArray
    cov: FloatArray
    icov: FloatArray
    target: FloatArray
    crit: float


def back_transform(
    mu: FloatArray,
    cov: FloatArray,
    icov: FloatArray,
    vsd: FloatArray,
    vmx: FloatArray,
    eq: EquicorrTransform | None,
) -> BackTransform:
    """Deshace la rotación de equicorrelación y la estandarización.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:599-619``: con ``target == 1``,
    ``MRCDmu = mQ %*% msqL %*% MRCDmu``, ``MRCDcov = mQ %*% msqL %*% MRCDcov %*% msqL %*% t(mQ)``,
    ``iMRCDcov`` con ``misqL`` y ``mT`` con ``msqL`` (``:603-606``, ``dgemm`` reales con
    asociatividad izquierda); después ``Dx %*% MRCDmu + vmx``, ``Dx %*% MRCDcov %*% Dx``,
    ``Dx %*% mT %*% Dx`` e ``iDx %*% iMRCDcov %*% iDx`` con ``iDx = diag(1/diag(Dx))``
    (``:610-615``); ``crit = determinant(MRCDcov)$modulus`` (``:619``).

    Args:
        mu: Centro estandarizado.
        cov: Covarianza estandarizada.
        icov: Inversa estandarizada.
        vsd: Escalas ``Qn`` (tras ``minscale``).
        vmx: Medianas.
        eq: Transformación de equicorrelación o ``None``.

    Returns:
        ``BackTransform``.
    """
    p = cov.shape[0]
    mt = np.eye(p, dtype=np.float64)
    mu_col = np.asarray(mu, dtype=np.float64)[:, None]
    if eq is not None:
        q_sql = r_matprod(eq.m_q, eq.msq_l)
        q_isql = r_matprod(eq.m_q, eq.misq_l)
        qt = np.array(eq.m_q.T, dtype=np.float64)
        mu_col = r_matprod(q_sql, mu_col)
        cov = r_matprod(r_matprod(r_matprod(q_sql, cov), eq.msq_l), qt)
        icov = r_matprod(r_matprod(r_matprod(q_isql, icov), eq.misq_l), qt)
        mt = r_matprod(r_matprod(r_matprod(q_sql, mt), eq.msq_l), qt)
    dx = _r_diag(vsd)
    mu_col = r_matprod(dx, mu_col) + np.asarray(vmx, dtype=np.float64)[:, None]
    cov = r_matprod(r_matprod(dx, cov), dx)
    mt = r_matprod(r_matprod(dx, mt), dx)
    idx_ = _r_diag(1 / np.diag(dx))
    icov = r_matprod(r_matprod(idx_, icov), idx_)
    crit = r_determinant(cov)[0]
    return BackTransform(
        center=np.asarray(mu_col[:, 0], dtype=np.float64), cov=cov, icov=icov, target=mt, crit=crit
    )


@dataclass(frozen=True)
class DetMrcd:
    """Salida de ``.detmrcd`` con los intermedios usados por los tests por etapa.

    Attributes:
        alpha: ``alpha`` efectivo.
        h: Tamaño del subconjunto.
        initmean: Centro final.
        initcovariance: Covarianza final.
        icov: Inversa final.
        rho: ``rho`` usado.
        best: Subconjunto final ``hindex`` (base 0, ordenado).
        mcdestimate: ``determinant(MRCDcov)$modulus``.
        target: Matriz objetivo retro-transformada.
        i_best: Subconjuntos empatados en el óptimo (base 0).
        n_csteps: Iteraciones por subconjunto (0 en ``initV``).
        calpha: Factor de consistencia.
        hsets_init: Subconjuntos iniciales ``h x 6`` (base 0, orden de distancia).
        vmx: Medianas por variable.
        vsd: Escalas ``Qn`` por variable (tras ``minscale``).
        vsd_raw: Escalas ``Qn`` antes de ``minscale``.
        m_u: Datos estandarizados ``n x p``.
        tgt: Salida de ``.TargetCorr``.
        eq: Transformación de equicorrelación (``None`` con identidad).
        r6: Salida de ``r6pack`` (``None`` si se dieron ``hsets_init``).
        scatters: Covarianzas por subconjunto (vacío si ``rho`` dado).
        rho_k: ``rho_k`` por subconjunto (vacío si ``rho`` dado).
        selection: Selección de ``rho`` (``None`` si ``rho`` dado).
        init_v: ``initV`` (base 0).
        sets_v: ``setsV`` (base 0).
        csteps: Resultados de C-steps en el orden de proceso ``(k, resultado, obj)``.
        fin_m_e: ``mX[, hindex] - ret$mu``.
        fin_w: ``mE %*% t(mE)/(h-1)``.
        fin_mu_std: Centro en el espacio estandarizado.
        fin_cov_std: Covarianza en el espacio estandarizado.
        fin_icov_std: Inversa en el espacio estandarizado.
        fin_smw: Intermedios de ``.InvSMW`` final (``None`` si se usó Cholesky).
    """

    alpha: float
    h: int
    initmean: FloatArray
    initcovariance: FloatArray
    icov: FloatArray
    rho: float
    best: IntArray
    mcdestimate: float
    target: FloatArray
    i_best: IntArray
    n_csteps: IntArray
    calpha: float
    hsets_init: IntArray
    vmx: FloatArray
    vsd: FloatArray
    vsd_raw: FloatArray
    m_u: FloatArray
    tgt: TargetCorr
    eq: EquicorrTransform | None
    r6: R6Pack | None
    scatters: tuple[SubsetScatter, ...]
    rho_k: tuple[RhoK, ...]
    selection: RhoSelection | None
    init_v: int
    sets_v: IntArray
    csteps: tuple[tuple[int, CStepResult, float], ...]
    fin_m_e: FloatArray
    fin_w: FloatArray
    fin_mu_std: FloatArray
    fin_cov_std: FloatArray
    fin_icov_std: FloatArray
    fin_smw: InvSMW | None


def _r_diag(v: FloatArray) -> FloatArray:
    """``diag(v)`` de R para un vector numérico.

    Fuente: ``R-4.5.2/src/library/base/R/diag.R`` (``diag(x)`` con ``length(x) == 1`` y sin
    ``nrow`` crea la identidad de orden ``as.integer(x)``). Afecta a ``Dx <- diag(vsd)`` e
    ``iDx`` (``detmrcd.R:420``, ``:614``) cuando ``p == 1``: se replica tal cual.

    Args:
        v: Vector.

    Returns:
        Matriz.

    Raises:
        RError: si el orden resultante es negativo o no finito.
    """
    arr = np.asarray(v, dtype=np.float64).ravel()
    if arr.shape[0] == 1:
        val = float(arr[0])
        if not math.isfinite(val) or val < 0:
            raise RError("invalid 'nrow' value (< 0)")
        return np.eye(int(val), dtype=np.float64)
    return np.diag(arr)


def _check_hsets(hsets: IntArray, h: int, n: int) -> IntArray:
    """Validación de ``hsets.init`` del usuario (``detmrcd.R:448-459``).

    Args:
        hsets: Matriz ``h' x L`` (o vector) en base 0.
        h: Tamaño del subconjunto.
        n: Número de observaciones.

    Returns:
        ``hsets.init[1:h, ]`` (base 0).

    Raises:
        RError: en los mismos casos que R (incluida la pérdida de dimensión de ``[1:h, ]`` con
            una columna o con ``h == 1``, que hace fallar ``ncol`` en R).
    """
    arr = np.asarray(hsets)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.ndim != 2:
        raise RError("'hsets.init' must be a  h' x L  matrix (h' >= h) of observation indices")
    if arr.shape[0] < h or arr.shape[1] < 1:
        raise RError("'hsets.init' must be a  h' x L  matrix (h' >= h) of observation indices")
    if arr.size and (int(arr.min()) < 0 or int(arr.max()) > n - 1):
        raise RError(f"'hsets.init' must be in {{1,2,...,n}}; n = {n}")
    if not np.array_equal(arr, np.round(arr)):
        raise RError("'hsets.init' must contain integer observation indices")
    if arr.shape[1] == 1 or h == 1:
        raise RError("argument of length 0")
    return np.asarray(arr[:h, :], dtype=np.int64)


def detmrcd(
    x: FloatArray,
    h: float | None = None,
    alpha: float | None = 0.75,
    rho: float | None = None,
    maxcond: float = 50,
    minscale: float = MINSCALE,
    target: int = 0,
    maxcsteps: int = 200,
    hsets_init: IntArray | None = None,
    record: bool = False,
    n_threads: int | None = None,
) -> DetMrcd:
    """``.detmrcd(x, h, alpha, rho, maxcond, minscale, target, maxcsteps, hsets.init)``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:385-637`` (especificación §3.2-§3.10):

    1. Preámbulo ``h``/``alpha`` (``:393-404``).
    2. Estandarización (``:417-422``): ``median`` y ``Qn`` por variable (sin centrar), ``minscale``,
       ``scale``.
    3. ``.TargetCorr`` y, con ``target == 1``, ``eigenEQ`` y ``mW`` (``:423-434``); ``mT = I``.
    4. ``r6pack`` local o ``hsets.init`` del usuario (``:445-459``); ``scfac = .MCDcons(p, h/n)``
       (``:460``).
    5. ``rho`` (``:465-539``): ``rho_k`` por subconjunto, ``cutoff``, ``initV``, ``setsV``; con
       ``rho`` dado ``setsV = 1:ncol`` e ``initV = 1`` (el conjunto 1 se procesa dos veces, T17).
    6. C-steps y mejor subconjunto con empates exactos (``:546-575``).
    7. Estimación final (``:577-593``; SMW si ``p > n``), retro-transformación (``:599-615``) y
       ``determinant(MRCDcov)$modulus`` (``:619``). ``mah``/``dist`` de ``:618`` no se calculan
       (``CovMrcd`` los recalcula sobre ``x``; especificación §8).

    Args:
        x: Datos ``n x p`` ya filtrados.
        h: Tamaño del subconjunto (prevalece sobre ``alpha``).
        alpha: Proporción.
        rho: Regularización fija o ``None``.
        maxcond: Número de condición objetivo.
        minscale: Escala mínima.
        target: ``0`` identidad, ``1`` equicorrelación.
        maxcsteps: Máximo de C-steps.
        hsets_init: Subconjuntos iniciales en base 0 o ``None``.
        record: Guarda los intermedios de cada C-step.
        n_threads: Hilos de la extensión C de ``Qn``/OGK (parámetro de rendimiento, no estadístico:
            no cambia ningún bit; especificación §3.12.9 e). ``None`` ⇒ ``PYMRCD_NUM_THREADS`` o
            los CPU visibles.

    Returns:
        ``DetMrcd``.

    Raises:
        RError: en los mismos casos que R (decisión P7, sin *fallback*).
    """
    xin = np.asarray(x, dtype=np.float64)
    n, p = xin.shape
    h_int, alpha_eff = resolve_h(n, alpha, h)

    # 1. Estandarización (detmrcd.R:417-422).
    vmx = r_median_cols(xin)
    vsd_raw = qn_columns(xin, n_threads=n_threads)
    vsd = vsd_raw.copy()
    vsd[vsd < minscale] = minscale
    mu = r_scale(xin, vmx, vsd)
    tgt = target_corr(mu, target)

    # 2. Objetivo de equicorrelación (detmrcd.R:426-434).
    eq: EquicorrTransform | None = None
    xw = mu
    if target == 1:
        eq = equicorrelation_transform(mu, tgt.R)
        xw = eq.m_w
    mx = np.array(xw.T, dtype=np.float64)

    # 3.1-3.3 Subconjuntos iniciales (detmrcd.R:445-459).
    r6: R6Pack | None = None
    if hsets_init is None:
        r6 = r6pack(xw, h_int, n_threads=n_threads)
        hsets = r6.hsets
    else:
        hsets = _check_hsets(hsets_init, h_int, n)
    scfac = mcd_cons(p, h_int / n)
    nsets = hsets.shape[1]

    # 3.4-3.5 rho (detmrcd.R:465-539).
    scatters: list[SubsetScatter] = []
    rho_ks: list[RhoK] = []
    selection: RhoSelection | None = None
    if rho is None:
        for k in range(nsets):
            sc = subset_scatter(mx, hsets[:, k], h_int, scfac)
            scatters.append(sc)
            rho_ks.append(rho_for_subset(sc.e1, sc.ep, maxcond))
        selection = select_rho(np.array([r.rho for r in rho_ks], dtype=np.float64))
        rho_val = selection.rho
        init_v = selection.init_v
        sets_v = selection.sets_v
    else:
        rho_val = float(rho)
        init_v = 0
        sets_v = np.arange(nsets, dtype=np.int64)

    # 3.6-3.7 C-steps y mejor subconjunto (detmrcd.R:546-575).
    n_csteps = np.zeros(nsets, dtype=np.int64)
    ret = cstep_mrcd(mx, rho_val, h_int, scfac, hsets[:, init_v], maxcsteps, record)
    objret = mrcd_objective(ret.cov, p)
    hindex = ret.subset
    best6 = [init_v]
    processed: list[tuple[int, CStepResult, float]] = [(init_v, ret, objret)]
    for k in sets_v.tolist():
        tmp = cstep_mrcd(mx, rho_val, h_int, scfac, hsets[:, k], maxcsteps, record)
        objtmp = mrcd_objective(tmp.cov, p)
        n_csteps[k] = tmp.numit
        processed.append((k, tmp, objtmp))
        if math.isnan(objtmp) or math.isnan(objret):
            raise RError("missing value where TRUE/FALSE needed")
        if objtmp < objret:
            ret, objret, hindex, best6 = tmp, objtmp, tmp.subset, [k]
        elif objtmp == objret:
            best6.append(k)

    # Estimación final (detmrcd.R:577-593) y retro-transformación (:599-619).
    c_alpha = scfac
    fin = final_estimate(mx, hindex, ret.mu, rho_val, c_alpha, h_int)
    back = back_transform(fin.mu, fin.cov, fin.icov, vsd, vmx, eq)
    me, w = fin.m_e, fin.W
    fin_smw = fin.smw
    fin_mu_std, fin_cov_std, fin_icov_std = fin.mu, fin.cov, fin.icov
    mu_col, mrcd_cov, imrcd_cov, mt, crit = (
        back.center[:, None],
        back.cov,
        back.icov,
        back.target,
        back.crit,
    )

    return DetMrcd(
        alpha=alpha_eff,
        h=h_int,
        initmean=np.asarray(mu_col[:, 0], dtype=np.float64),
        initcovariance=mrcd_cov,
        icov=imrcd_cov,
        rho=rho_val,
        best=hindex,
        mcdestimate=crit,
        target=mt,
        i_best=np.asarray(best6, dtype=np.int64),
        n_csteps=n_csteps,
        calpha=c_alpha,
        hsets_init=hsets,
        vmx=vmx,
        vsd=vsd,
        vsd_raw=vsd_raw,
        m_u=mu,
        tgt=tgt,
        eq=eq,
        r6=r6,
        scatters=tuple(scatters),
        rho_k=tuple(rho_ks),
        selection=selection,
        init_v=init_v,
        sets_v=sets_v,
        csteps=tuple(processed),
        fin_m_e=me,
        fin_w=w,
        fin_mu_std=fin_mu_std,
        fin_cov_std=fin_cov_std,
        fin_icov_std=fin_icov_std,
        fin_smw=fin_smw,
    )
