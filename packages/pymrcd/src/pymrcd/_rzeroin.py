"""``uniroot`` de R y su núcleo ``R_zeroin2`` portados iteración por iteración.

``rrcov`` elige ``rho_k`` con ``uniroot(fncond, lower=1e-5, upper=0.99)`` (``detmrcd.R:495``).
Brent de
scipy (``brentq``) usa otra interpolación y otro criterio de parada, así que no sirve (trampa T14):
aquí se replica literalmente ``zeroin.c`` con la envoltura ``fcn2`` de ``optimize.c``.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from typing import NamedTuple

from pymrcd._errors import RError
from pymrcd._fma import fma

__all__ = ["UnirootResult", "ZeroinResult", "r_uniroot", "r_zeroin2"]

_DBL_MAX = sys.float_info.max
_DBL_EPSILON = sys.float_info.epsilon
UNIROOT_TOL = 2.0**-13
"""``.Machine$double.eps^0.25`` (``nlm.R:60``), exacto: ``(2^-52)^0.25 = 2^-13``."""


class ZeroinResult(NamedTuple):
    """Salida de ``R_zeroin2``.

    Attributes:
        root: Aproximación de la raíz.
        iterations: Iteraciones usadas (``-1`` si no convergió).
        estim_prec: Precisión estimada ``|c - b|`` (``0`` si la raíz es un extremo).
    """

    root: float
    iterations: int
    estim_prec: float


class UnirootResult(NamedTuple):
    """Salida de ``uniroot`` (con ``extendInt = "no"``).

    Attributes:
        root: Raíz.
        f_root: ``f(root)``.
        iter: Iteraciones (``maxiter`` si no convergió).
        estim_prec: Precisión estimada.
        converged: ``False`` si R habría emitido el *warning* ``_NOT_ converged``.
    """

    root: float
    f_root: float
    iter: int
    estim_prec: float
    converged: bool


def _fcn2(f: Callable[[float], float], x: float) -> float:
    """Envoltura de la función objetivo en ``zeroin2``.

    Fuente: ``R-4.5.2/src/library/stats/src/optimize.c:292-329`` (``fcn2``): un valor no finito se
    sustituye por ``-DBL_MAX`` si es ``-Inf`` y por ``+DBL_MAX`` en otro caso (``+Inf``, ``NA``,
    ``NaN``).

    Args:
        f: Función objetivo.
        x: Abscisa.

    Returns:
        ``f(x)`` saneado.
    """
    value = float(f(x))
    if not math.isfinite(value):
        return -_DBL_MAX if value == -math.inf else _DBL_MAX
    return value


def r_zeroin2(
    f: Callable[[float], float],
    ax: float,
    bx: float,
    fa: float,
    fb: float,
    tol: float,
    maxit: int,
) -> ZeroinResult:
    """Port literal de ``R_zeroin2`` (Brent con interpolación cuadrática inversa).

    Fuente: ``R-4.5.2/src/library/stats/src/zeroin.c:89-194``. Cada paso respeta el orden de las
    operaciones de C (``tol_act = 2*EPSILON*fabs(b) + tol/2``, la interpolación ``p/q`` y el
    ajuste mínimo del paso). ``f`` se evalúa a través de ``fcn2`` (``optimize.c:292-329``). En el
    ``stats.so`` del oráculo (``clang -O2``, arm64) tres expresiones se contraen a ``fmadd``
    (desensamblado de ``R_zeroin2``): ``tol_act`` (``:134``), el numerador ``p`` (``:159``) y la
    cota
    ``0.75*cb*q - fabs(tol_act*q)/2`` (``:167``); se reproducen con ``fma`` exacto.

    Args:
        f: Función objetivo.
        ax: Extremo izquierdo.
        bx: Extremo derecho.
        fa: ``f(ax)`` ya truncada.
        fb: ``f(bx)`` ya truncada.
        tol: Tolerancia.
        maxit: Máximo de iteraciones.

    Returns:
        ``ZeroinResult`` con la raíz, las iteraciones (``-1`` si falla) y ``|c - b|``.
    """
    a = ax
    b = bx
    c = a
    fc = fa
    remaining = maxit + 1

    if fa == 0.0:
        return ZeroinResult(a, 0, 0.0)
    if fb == 0.0:
        return ZeroinResult(b, 0, 0.0)

    while remaining:
        remaining -= 1
        prev_step = b - a

        if abs(fc) < abs(fb):
            a = b
            b = c
            c = a
            fa = fb
            fb = fc
            fc = fa
        # fmadd en el binario del oráculo: fma(|b|, 2*EPSILON, tol/2)
        tol_act = fma(abs(b), 2 * _DBL_EPSILON, tol / 2)
        new_step = (c - b) / 2

        if abs(new_step) <= tol_act or fb == 0.0:
            return ZeroinResult(b, maxit - remaining, abs(c - b))

        if abs(prev_step) >= tol_act and abs(fa) > abs(fb):
            cb = c - b
            if a == c:
                t1 = fb / fa
                p = cb * t1
                q = 1.0 - t1
            else:
                q = fa / fc
                t1 = fb / fc
                t2 = fb / fa
                # fmadd: fma(cb*q, q-t1, -((b-a)*(t1-1)))
                p = t2 * fma(cb * q, q - t1, -((b - a) * (t1 - 1.0)))
                q = (q - 1.0) * (t1 - 1.0) * (t2 - 1.0)
            if p > 0.0:
                q = -q
            else:
                p = -p

            # fmadd: fma(0.75*cb, q, -(|tol_act*q|/2))
            if p < fma(0.75 * cb, q, -(abs(tol_act * q) / 2)) and p < abs(prev_step * q / 2):
                new_step = p / q

        if abs(new_step) < tol_act:
            new_step = tol_act if new_step > 0.0 else -tol_act
        a = b
        fa = fb
        b += new_step
        fb = _fcn2(f, b)
        if (fb > 0 and fc > 0) or (fb < 0 and fc < 0):
            c = a
            fc = fa

    return ZeroinResult(b, -1, abs(c - b))


def _r_sign(x: float) -> float:
    """``sign()`` de R para un ``double`` no ``NaN``.

    Fuente: ``R-4.5.2/src/nmath/sign.c`` (``x > 0 ? 1 : (x == 0 ? 0 : -1)``).

    Args:
        x: Valor.

    Returns:
        ``1.0``, ``0.0`` o ``-1.0``.
    """
    if x > 0:
        return 1.0
    return 0.0 if x == 0 else -1.0


def _truncate(x: float) -> float:
    """``pmax.int(pmin(x, DBL_MAX), -DBL_MAX)`` de ``uniroot``.

    Fuente: ``R-4.5.2/src/library/stats/R/nlm.R:75-78``.

    Args:
        x: Valor no ``NaN``.

    Returns:
        ``x`` acotado a ``[-DBL_MAX, DBL_MAX]``.
    """
    return max(min(x, _DBL_MAX), -_DBL_MAX)


def r_uniroot(
    f: Callable[[float], float],
    lower: float,
    upper: float,
    tol: float = UNIROOT_TOL,
    maxiter: int = 1000,
) -> UnirootResult:
    """``uniroot(f, lower=, upper=)`` de R con ``extendInt = "no"`` y ``check.conv = FALSE``.

    Fuente: ``R-4.5.2/src/library/stats/R/nlm.R:55-170``: evalúa ``f(lower)`` y luego ``f(upper)``
    (``:57``); error si ``lower >= upper`` (``:64-65``), si alguna es ``NA`` (``:66-67``) o si
    ``!isTRUE(sign(f.lower) * sign(f.upper) <= 0)`` (``:138-141``); trunca a ``±DBL_MAX``
    (``:75-78``) y llama a ``R_zeroin2`` (``:154-156``). Sin convergencia ⇒ solo *warning* e
    ``iter = maxiter`` (``:158-166``). Con ``extendInt = "no"`` nunca se extiende el intervalo
    (``Sig = 0`` ⇒ ``doX = FALSE``, ``:79-80``). Especificación §3.7, trampa T14.

    Args:
        f: Función objetivo.
        lower: Extremo inferior.
        upper: Extremo superior.
        tol: Tolerancia (``2^-13`` por defecto, ``nlm.R:60``).
        maxiter: Iteraciones máximas (``1000`` por defecto, ``nlm.R:60``).

    Returns:
        ``UnirootResult``.

    Raises:
        RError: en los mismos casos en que ``uniroot`` llama a ``stop()``.
    """
    f_lower = float(f(lower))
    f_upper = float(f(upper))
    if lower >= upper:
        raise RError("lower < upper  is not fulfilled")
    if math.isnan(f_lower):
        raise RError("f.lower = f(lower) is NA")
    if math.isnan(f_upper):
        raise RError("f.upper = f(upper) is NA")
    if not _r_sign(f_lower) * _r_sign(f_upper) <= 0:
        raise RError("f() values at end points not of opposite sign")
    val = r_zeroin2(f, lower, upper, _truncate(f_lower), _truncate(f_upper), tol, maxiter)
    iterations = val.iterations
    converged = iterations >= 0
    if not converged:
        iterations = maxiter
    return UnirootResult(
        root=val.root,
        f_root=float(f(val.root)),
        iter=iterations,
        estim_prec=val.estim_prec,
        converged=converged,
    )
