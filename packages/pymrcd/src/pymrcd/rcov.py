"""Covarianza regularizada ``.RCOV`` e inversa de Sherman-Morrison-Woodbury ``.InvSMW``.

Port de ``rrcov-1.7-7/R/detmrcd.R:269-317`` (especificación §3.8). En todas las llamadas de
``.detmrcd`` el objetivo es ``mT = diag(p)`` (``detmrcd.R:436``); se replican todas las
multiplicaciones matriciales de R como ``dgemm`` reales (incluidas las de matrices diagonales).
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from pymrcd._rbase import r_pow
from pymrcd._rlinalg import r_chol, r_chol2inv, r_matprod
from pymrcd._types import FloatArray

__all__ = ["InvSMW", "RCov", "inv_smw", "rcov"]


class InvSMW(NamedTuple):
    """Salida de ``.InvSMW`` con sus intermedios.

    Attributes:
        inv: Inversa ``p x p``.
        G: ``t(mU) %*% (imB %*% mU)`` (``h x h``).
        Temp: ``chol2inv(chol(diag(h) + nu * G))`` (``h x h``).
    """

    inv: FloatArray
    G: FloatArray
    Temp: FloatArray


def inv_smw(rho: float, nu: float, mu: FloatArray) -> InvSMW:
    """``.InvSMW(rho, mT=diag(p), nu, mU)``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:302-317``. Con ``mT = I``: ``vD = 1``, ``imD = I``,
    ``R = I``, ``constcor = R[2,1] = 0`` e ``imR = 1/(1-0)*(I - 0/(1+(p-1)*0)*J) = I`` son exactos
    (aritmética con 0 y 1); ``imB = rho^(-1) * (imD %*% imR %*% imD) = rho^(-1) * I`` (``:313``,
    ``%*%`` precede a ``*``; ``R_pow(rho, -1)``). Después, como R:
    ``G = t(mU) %*% (imB %*% mU)``; ``Temp = chol2inv(chol(diag(h) + nu*G))`` (``:314``);
    ``imB - ((imB %*% mU) %*% (nu*Temp)) %*% (t(mU) %*% imB)`` (``:316``).

    Args:
        rho: Parámetro de regularización.
        nu: ``(1-rho) * scfac``.
        mu: Datos centrados y escalados ``p x h``.

    Returns:
        ``InvSMW``.

    Raises:
        RError: si ``diag(h) + nu*G`` no es definida positiva (``chol``).
    """
    arr = np.asarray(mu, dtype=np.float64)
    p, hh = arr.shape
    imb = r_pow(rho, -1.0) * np.eye(p, dtype=np.float64)
    mut = np.array(arr.T, dtype=np.float64)
    imb_mu = r_matprod(imb, arr)
    g = r_matprod(mut, imb_mu)
    temp = r_chol2inv(r_chol(np.eye(hh, dtype=np.float64) + nu * g))
    inv = imb - r_matprod(r_matprod(imb_mu, nu * temp), r_matprod(mut, imb))
    return InvSMW(inv=inv, G=g, Temp=temp)


class RCov(NamedTuple):
    """Salida de ``.RCOV(invert=TRUE)``.

    Attributes:
        m_s: ``mE %*% t(mE) / h`` (divisor ``h``).
        rcov: ``rho*I + (1-rho)*scfac*mS``.
        inv: Inversa de ``rcov`` (SMW si ``p > h``, si no ``chol2inv(chol(rcov))``).
        smw: Intermedios de ``.InvSMW`` (``None`` si se usó Cholesky).
    """

    m_s: FloatArray
    rcov: FloatArray
    inv: FloatArray
    smw: InvSMW | None


def rcov(xx: FloatArray, vmu: FloatArray, rho: float, scfac: float) -> RCov:
    """``.RCOV(XX, vMu, rho, mT=diag(p), scfac, invert=TRUE)``.

    Fuente: ``rrcov-1.7-7/R/detmrcd.R:269-290``: ``mE = XX - vMu`` (``:271``);
    ``mS = mE %*% t(mE)/n`` con ``n = ncol(mE) = h`` (``:274``, trampa T10);
    ``rcov = rho*mT + (1-rho)*scfac*mS`` = ``rho*I + ((1-rho)*scfac)*mS`` (``:275``, asociatividad
    izquierda); si ``p > h`` ⇒ ``.InvSMW(rho, mT, nu=(1-rho)*scfac, mU=mE/sqrt(h))``
    (``:278-281``, trampa T11), si no ``chol2inv(chol(rcov))`` (``:283``).

    Args:
        xx: Datos del subconjunto ``p x h``.
        vmu: Media ``p``.
        rho: Parámetro de regularización.
        scfac: Factor de consistencia.

    Returns:
        ``RCov``.

    Raises:
        RError: si la matriz a factorizar no es definida positiva.
    """
    me = np.asarray(xx, dtype=np.float64) - np.asarray(vmu, dtype=np.float64)[:, None]
    p, hh = me.shape
    ms = r_matprod(me, np.array(me.T, dtype=np.float64)) / hh
    nu = (1 - rho) * scfac
    rc = rho * np.eye(p, dtype=np.float64) + nu * ms
    if p > hh:
        smw = inv_smw(rho, nu, me / np.sqrt(np.float64(hh)))
        return RCov(m_s=ms, rcov=rc, inv=smw.inv, smw=smw)
    return RCov(m_s=ms, rcov=rc, inv=r_chol2inv(r_chol(rc)), smw=None)
