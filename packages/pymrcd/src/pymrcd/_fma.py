"""``fma(a, b, c)`` exacto (un solo redondeo) sin ``math.fma`` (Python 3.12).

El R del oráculo (``aarch64-apple-darwin20``, ``clang -O2``) se compiló con contracción de
coma flotante: ``clang`` fusiona ``x*y + z`` en una instrucción ``fmadd`` (un redondeo) en el
código C
de R (``cov.c``, ``zeroin.c``, ``qnorm.c``…). Para reproducir esos bits hay que calcular
``RN(a·b + c)`` exactamente. Se usa el algoritmo de Boldo y Melquiond (2008, *Emulation of FMA and
correctly rounded sums: proved algorithms using rounding to odd*, IEEE TC 57(4), alg. 5.4):

1. ``(uh, ul) = ExactMult(a, b)`` (Dekker/Veltkamp, exacto sin desbordamientos);
2. ``(th, tl) = TwoSum(c, uh)``;
3. ``v = RO(tl + ul)`` (redondeo a impar);
4. ``z = RN(th + v)``.

Fuera del rango donde el producto exacto de Dekker es válido (exponentes extremos) se calcula con
aritmética racional exacta (``fractions.Fraction``), cuya conversión a ``float`` redondea al más
cercano con empates a par: es el mismo resultado, solo más lento. Con entradas no finitas el
resultado
IEEE de ``fma`` coincide con el de ``a*b + c`` salvo si ``c`` es infinito y ``a*b`` desborda, caso
que se
trata aparte.
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np

from pymrcd._types import FloatArray

__all__ = ["fma", "fma_array"]

_SPLITTER = 134217729.0  # 2^27 + 1
_BIG = 2.0**995
_TINY = 2.0**-900


def _two_sum(a: float, b: float) -> tuple[float, float]:
    """Suma exacta de Knuth: ``a + b = s + e`` exactamente.

    Args:
        a: Sumando.
        b: Sumando.

    Returns:
        ``(s, e)`` con ``s = RN(a + b)``.
    """
    s = a + b
    bb = s - a
    e = (a - (s - bb)) + (b - bb)
    return s, e


def _split(a: float) -> tuple[float, float]:
    """Partición de Veltkamp en dos mitades de 26 bits.

    Args:
        a: Valor con ``|a| < 2^995``.

    Returns:
        ``(hi, lo)`` con ``a = hi + lo``.
    """
    t = _SPLITTER * a
    hi = t - (t - a)
    return hi, a - hi


def _round_to_odd_sum(x: float, y: float) -> float:
    """``RO(x + y)``: si la suma es inexacta, el vecino con bit menos significativo impar.

    Args:
        x: Sumando.
        y: Sumando.

    Returns:
        La suma redondeada a impar.
    """
    s, e = _two_sum(x, y)
    if e != 0.0 and (int(np.float64(s).view(np.int64)) & 1) == 0:
        s = math.nextafter(s, math.inf if e > 0 else -math.inf)
    return s


def _fma_exact_rational(a: float, b: float, c: float) -> float:
    """``fma`` finito por aritmética racional exacta (camino lento, exponentes extremos).

    Args:
        a: Factor finito no nulo.
        b: Factor finito no nulo.
        c: Sumando finito.

    Returns:
        ``RN(a·b + c)``.
    """
    exact = Fraction(a) * Fraction(b) + Fraction(c)
    if exact == 0:
        return 0.0
    try:
        return float(exact)
    except OverflowError:
        return math.inf if exact > 0 else -math.inf


def fma(a: float, b: float, c: float) -> float:
    """``fma(a, b, c) = RN(a·b + c)`` con un único redondeo (``fmadd`` de AArch64).

    Args:
        a: Factor.
        b: Factor.
        c: Sumando.

    Returns:
        El resultado correctamente redondeado.
    """
    if not (math.isfinite(a) and math.isfinite(b)):
        return a * b + c
    if not math.isfinite(c):
        return c  # a·b finito (exacto) más ±Inf/NaN
    if a == 0.0 or b == 0.0:
        return a * b + c  # producto ±0 exacto: el resultado IEEE es el mismo
    prod = a * b
    if (
        abs(a) >= _BIG
        or abs(b) >= _BIG
        or abs(c) >= _BIG
        or abs(prod) < _TINY
        or (c != 0.0 and abs(c) < _TINY)
    ):
        return _fma_exact_rational(a, b, c)
    a_hi, a_lo = _split(a)
    b_hi, b_lo = _split(b)
    ul = ((a_hi * b_hi - prod) + a_hi * b_lo + a_lo * b_hi) + a_lo * b_lo
    th, tl = _two_sum(c, prod)
    v = _round_to_odd_sum(tl, ul)
    return th + v


def fma_array(
    a: FloatArray | float,
    b: FloatArray | float,
    c: FloatArray | float,
) -> FloatArray:
    """``fma`` elemento a elemento (con difusión de numpy).

    Usa la misma transformación exacta que ``fma`` vectorizada en numpy (las operaciones de
    numpy son
    IEEE con un redondeo y nunca se fusionan). Los elementos fuera del rango seguro o no finitos se
    resuelven con ``fma`` escalar.

    Args:
        a: Factores.
        b: Factores.
        c: Sumandos.

    Returns:
        Arreglo ``RN(a·b + c)``.
    """
    aa, bb, cc = np.broadcast_arrays(
        np.asarray(a, dtype=np.float64),
        np.asarray(b, dtype=np.float64),
        np.asarray(c, dtype=np.float64),
    )
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        prod = aa * bb
        safe = (
            np.isfinite(aa)
            & np.isfinite(bb)
            & np.isfinite(cc)
            & (aa != 0.0)
            & (bb != 0.0)
            & (np.abs(aa) < _BIG)
            & (np.abs(bb) < _BIG)
            & (np.abs(cc) < _BIG)
            & (np.abs(prod) >= _TINY)
            & ((cc == 0.0) | (np.abs(cc) >= _TINY))
        )
        t = _SPLITTER * aa
        a_hi = t - (t - aa)
        a_lo = aa - a_hi
        t = _SPLITTER * bb
        b_hi = t - (t - bb)
        b_lo = bb - b_hi
        ul = ((a_hi * b_hi - prod) + a_hi * b_lo + a_lo * b_hi) + a_lo * b_lo
        th = cc + prod
        bv = th - cc
        tl = (cc - (th - bv)) + (prod - bv)
        s = tl + ul
        sv = s - tl
        e = (tl - (s - sv)) + (ul - sv)
        even = (s.view(np.int64) & 1) == 0
        bump = (e != 0.0) & even
        s = np.where(bump, np.nextafter(s, np.where(e > 0, np.inf, -np.inf)), s)
        out = th + s
    out = np.array(out, dtype=np.float64)
    for idx in zip(*np.nonzero(~safe), strict=True):
        out[idx] = fma(float(aa[idx]), float(bb[idx]), float(cc[idx]))
    return out
