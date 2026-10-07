"""Port literal de ``qchisq`` y ``pgamma`` de ``nmath`` (R 4.5.2) para ``.MCDcons`` bit a bit.

``robustbase::.MCDcons`` (``robustbase-0.99-6/R/covMcd.R:602-607``) llama a ``qchisq(alpha, p)`` y
a ``pgamma(q/2, p/2 + 1)``. Por decisión del dueño (revisa P3) el factor de consistencia ``scfac``
debe coincidir **bit a bit** con R, así que se porta la cadena completa de ``nmath``:
``qchisq → qgamma → {lgammafn, qchisq_appr, pgamma_raw, pgamma, dgamma}`` y sus auxiliares
(``lgammacor``, ``gammafn``, ``chebyshev_eval``, ``lgamma1p``, ``logcf``, ``log1pmx``, ``stirlerr``,
``ebd0``, ``dpois_raw``, ``dpois_wrap``, ``pd_upper_series``, ``pd_lower_cf``, ``pd_lower_series``,
``ppois_asymp``, ``pnorm_both``, ``dnorm``, ``dpnorm``).

Reglas del port (especificación ``docs/metodos/mrcd-especificacion.md`` §3.12.7, trampa T12):

- **FMA del binario.** El ``libR.dylib`` del oráculo (``clang -O2``, arm64) contrae ``a*b + c``
  en ``fmadd``/``fmsub``/``fnmadd``/``fnmsub``/``fmla`` (un solo redondeo). Cada contracción se
  localizó desensamblando el binario (``objdump -d --disassemble-symbols=_Rf_qgamma …``; las
  funciones ``static`` ``pgamma_smallx``, ``pd_upper_series``, ``dpois_wrap``, ``dpnorm`` y
  ``ppois_asymp`` están integradas en ``_Rf_pgamma_raw``) y se reproduce con
  :func:`pymrcd._fma.fma`. Los comentarios ``# FMA`` señalan cada una.
- **libm.** ``log``, ``exp``, ``log1p``, ``expm1``, ``pow`` y ``sqrt`` vía ``math`` (la misma libm
  del sistema que usa R); ``lgamma`` de C vía ``ctypes`` porque ``math.lgamma`` de CPython es una
  implementación propia (Lanczos) y no la de libm.
- **Ramas.** Solo se portan las ramas alcanzables desde ``qchisq(p, df, lower.tail=TRUE,
  log.p=FALSE)`` y ``pgamma(q, shape, lower.tail=TRUE, log.p=FALSE)``: dentro de ``qgamma`` el paso
  de Newton usa ``log_p = TRUE`` (se porta), pero ``lower_tail`` es siempre ``TRUE`` (y ``FALSE``
  en ``ppois_asymp``, que recibe ``!lower_tail``). Los argumentos de ``lgammafn``/``gammafn`` son
  siempre positivos (forma ``alpha > 0``), así que no se portan las ramas de argumento negativo.
- Las advertencias de R (``ML_WARNING``, ``MATHLIB_WARNING``) no cambian el valor devuelto y no se
  replican.
"""

from __future__ import annotations

import ctypes
import math
import sys
from collections.abc import Callable
from typing import cast

import numpy as np

from pymrcd._fma import fma
from pymrcd._rbase import r_qnorm

__all__ = ["dgamma_log", "lgammafn", "pgamma", "pgamma_raw", "qchisq", "qgamma"]

# --------------------------------------------------------------------------------------------------
# Constantes (Rmath.h, float.h); los literales decimales se redondean igual que en C.
# --------------------------------------------------------------------------------------------------

_M_LN2 = 0.693147180559945309417232121458
_M_LN_SQRT_2PI = 0.918938533204672741780329736406
_M_LN_2PI = 1.837877066409345483560659472811
_M_1_SQRT_2PI = 0.398942280401432677939946059934
_M_SQRT_32 = 5.656854249492380195206754896838
_M_2PI = 6.283185307179586476925286766559
_M_SQRT_2PI = 2.50662827463100050241576528481104525301  # dpois.c:38
_X_LRG = 2.86111748575702815380240589208115399625e307  # dpois.c:40
_DBL_EPSILON = sys.float_info.epsilon
_DBL_MIN = sys.float_info.min
_DBL_MAX = sys.float_info.max
_INF = math.inf
_SCALEFACTOR = 2.0**256  # pgamma.c:59-61: (2^32)^8
_M_CUTOFF = _M_LN2 * 1024 / _DBL_EPSILON  # pgamma.c:65 (M_LN2 * DBL_MAX_EXP / DBL_EPSILON)
_DNORM_UNDERFLOW = float.fromhex("0x1.348b5981e26f5p+5")
"""``sqrt(-2*M_LN2*(DBL_MIN_EXP + 1 - DBL_MANT_DIG))`` (``dnorm.c:78``), constante del binario."""

# --------------------------------------------------------------------------------------------------
# lgamma de libm (ctypes)
# --------------------------------------------------------------------------------------------------


_LIBM_CANDIDATES: dict[str, tuple[str, ...]] = {
    # macOS: libm es un alias de libSystem (la libm del oráculo, R 4.5.2 aarch64-apple-darwin20).
    "darwin": ("/usr/lib/libm.dylib", "/usr/lib/libSystem.B.dylib"),
    # Linux con glibc: soname estable de la libm.
    "linux": ("libm.so.6",),
}
"""Bibliotecas de las que se toma ``lgamma``, por plataforma (``sys.platform``)."""


def _load_libm_lgamma(platform: str = sys.platform) -> Callable[[float], float]:
    """Carga ``lgamma`` de la libm de C con ``ctypes``, con resolución explícita por plataforma.

    Nunca se usa ``CDLL(None)`` ni ``find_library`` (que podría devolver otra biblioteca por
    casualidad): en macOS se carga ``libm.dylib`` (o ``libSystem.B.dylib``, que la contiene); en
    Linux, ``libm.so.6`` de glibc (un Linux sin glibc, p. ej. musl, no tiene ese soname y falla
    con ``ImportError``); en cualquier otra plataforma, ``ImportError`` con mensaje claro.

    Clase de tolerancia: la ``lgamma`` del oráculo es la de la libm de macOS. **Fuera de macOS**
    ``lgamma`` es la de otra libm (glibc) y su resultado entra en la clase **L** de la
    especificación §11 (``stirlerr.c:120``, solo para ``n > 15`` no entero; afecta a ``scfac``).

    Args:
        platform: Identificador ``sys.platform`` (parámetro para poder probar la rama de error).

    Returns:
        La función ``double lgamma(double)`` de la plataforma.

    Raises:
        ImportError: plataforma no soportada o libm no encontrada.
    """
    key = "linux" if platform.startswith("linux") else platform
    candidates = _LIBM_CANDIDATES.get(key)
    if candidates is None:
        raise ImportError(
            f"pymrcd: plataforma '{platform}' no soportada para lgamma de libm "
            "(soportadas: macOS con libm.dylib/libSystem, Linux con glibc libm.so.6)"
        )
    errors: list[str] = []
    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
        except OSError as exc:
            errors.append(f"{name}: {exc}")
            continue
        func = lib.lgamma
        func.restype = ctypes.c_double
        func.argtypes = [ctypes.c_double]
        return cast("Callable[[float], float]", func)
    raise ImportError(f"pymrcd: no se pudo cargar la libm ({'; '.join(errors)})")


_C_LGAMMA = _load_libm_lgamma()


def _c_lgamma(x: float) -> float:
    """``lgamma`` de la libm de C (usado por ``stirlerr.c:120``).

    Args:
        x: Argumento positivo.

    Returns:
        ``log|Γ(x)|`` de la libm de la plataforma.
    """
    return float(_C_LGAMMA(x))


# --------------------------------------------------------------------------------------------------
# Funciones auxiliares de la gamma: chebyshev_eval, lgammacor, gammafn, lgammafn
# --------------------------------------------------------------------------------------------------

_GAMCS = (
    +0.8571195590989331421920062399942e-2,
    +0.4415381324841006757191315771652e-2,
    +0.5685043681599363378632664588789e-1,
    -0.4219835396418560501012500186624e-2,
    +0.1326808181212460220584006796352e-2,
    -0.1893024529798880432523947023886e-3,
    +0.3606925327441245256578082217225e-4,
    -0.6056761904460864218485548290365e-5,
    +0.1055829546302283344731823509093e-5,
    -0.1811967365542384048291855891166e-6,
    +0.3117724964715322277790254593169e-7,
    -0.5354219639019687140874081024347e-8,
    +0.9193275519859588946887786825940e-9,
    -0.1577941280288339761767423273953e-9,
    +0.2707980622934954543266540433089e-10,
    -0.4646818653825730144081661058933e-11,
    +0.7973350192007419656460767175359e-12,
    -0.1368078209830916025799499172309e-12,
    +0.2347319486563800657233471771688e-13,
    -0.4027432614949066932766570534699e-14,
    +0.6910051747372100912138336975257e-15,
    -0.1185584500221992907052387126192e-15,
)
"""Los ``ngam = 22`` primeros coeficientes de ``gamcs`` (``gamma.c:47-90``, ``:111``)."""

_ALGMCS = (
    +0.1666389480451863247205729650822e0,
    -0.1384948176067563840732986059135e-4,
    +0.9810825646924729426157171547487e-8,
    -0.1809129475572494194263306266719e-10,
    +0.6221098041892605227126015543416e-13,
)
"""Los ``nalgm = 5`` primeros coeficientes de ``algmcs`` (``lgammacor.c:49-75``)."""


def _chebyshev_eval(x: float, a: tuple[float, ...]) -> float:
    """``chebyshev_eval(x, a, n)`` con ``n = len(a)``.

    Fuente: ``R-4.5.2/src/nmath/chebyshev.c:69-87``. FMA: ``b0 = twox*b1 - b2`` es ``fnmsub`` y
    luego ``+ a[n-i]`` (desensamblado de ``_Rf_chebyshev_eval``).

    Args:
        x: Punto en ``[-1.1, 1.1]``.
        a: Coeficientes.

    Returns:
        La serie de Chebyshev evaluada.
    """
    if x < -1.1 or x > 1.1:
        return math.nan
    twox = x * 2
    b2 = b1 = b0 = 0.0
    for coef in reversed(a):
        b2 = b1
        b1 = b0
        b0 = fma(twox, b1, -b2) + coef  # FMA
    return (b0 - b2) * 0.5


def _lgammacor(x: float) -> float:
    """``lgammacor(x)`` para ``x >= 10``.

    Fuente: ``R-4.5.2/src/nmath/lgammacor.c:47-88``. FMA: ``tmp*tmp*2 - 1`` es ``fmadd``.

    Args:
        x: Argumento ``>= 10``.

    Returns:
        La corrección de Stirling de ``lgamma``.
    """
    if x < 10:
        return math.nan
    if x < 94906265.62425156:  # xbig
        tmp = 10 / x
        return _chebyshev_eval(fma(tmp * tmp, 2.0, -1.0), _ALGMCS) / x  # FMA
    return 1 / (x * 12)


def _gammafn_small(x: float) -> float:
    """``gammafn(x)`` para ``0 < x <= 10`` (única rama que alcanza ``lgammafn``).

    Fuente: ``R-4.5.2/src/nmath/gamma.c:118-176``. FMA: ``y*2 - 1`` es ``fmadd``.

    Args:
        x: Argumento en ``(0, 10]``.

    Returns:
        ``Γ(x)``.
    """
    n = int(x)  # :136 (int) x, x > 0
    y = x - n  # :138
    n -= 1  # :139
    value = _chebyshev_eval(fma(y, 2.0, -1.0), _GAMCS) + 0.9375  # :140 FMA
    if n == 0:
        return value
    if n < 0:  # 0 < x < 1 ⇒ n = -1
        if y < 2.2474362225598545e-308:  # :156 xsml
            return _INF
        return value / x  # :164-166 (i = 0)
    for i in range(1, n + 1):  # :172-174
        value *= y + i
    return value


def lgammafn(x: float) -> float:
    """``lgammafn(x)`` de R para ``x > 0`` (o ``NaN``).

    Fuente: ``R-4.5.2/src/nmath/lgamma.c:46-123`` (``lgammafn_sign`` con ``sgn = NULL``). FMA:
    ``M_LN_SQRT_2PI + (x - 0.5)*log(x)`` es ``fmadd`` (desensamblado de ``_Rf_lgammafn_sign``).

    Args:
        x: Argumento positivo.

    Returns:
        ``log Γ(x)``.

    Raises:
        ValueError: si ``x <= 0`` (rama de argumento no positivo, no portada).
    """
    if math.isnan(x):
        return x
    if x <= 0:
        raise ValueError("lgammafn: argumento no positivo fuera del port (lgamma.c:79-123)")
    if x < 1e-306:
        return -math.log(x)  # :84
    if x <= 10:
        return math.log(abs(_gammafn_small(x)))  # :85
    if x > 2.5327372760800758e305:  # xmax
        return _INF
    if x > 1e17:
        return x * (math.log(x) - 1.0)
    val = fma(x - 0.5, math.log(x), _M_LN_SQRT_2PI) - x  # FMA
    if x > 4934720.0:
        return val
    return val + _lgammacor(x)


# --------------------------------------------------------------------------------------------------
# logcf, log1pmx, lgamma1p (pgamma.c)
# --------------------------------------------------------------------------------------------------

_LGAMMA1P_COEFFS = (
    0.3224670334241132182362075833230126e-0,
    0.6735230105319809513324605383715000e-1,
    0.2058080842778454787900092413529198e-1,
    0.7385551028673985266273097291406834e-2,
    0.2890510330741523285752988298486755e-2,
    0.1192753911703260977113935692828109e-2,
    0.5096695247430424223356548135815582e-3,
    0.2231547584535793797614188036013401e-3,
    0.9945751278180853371459589003190170e-4,
    0.4492623673813314170020750240635786e-4,
    0.2050721277567069155316650397830591e-4,
    0.9439488275268395903987425104415055e-5,
    0.4374866789907487804181793223952411e-5,
    0.2039215753801366236781900709670839e-5,
    0.9551412130407419832857179772951265e-6,
    0.4492469198764566043294290331193655e-6,
    0.2120718480555466586923135901077628e-6,
    0.1004322482396809960872083050053344e-6,
    0.4769810169363980565760193417246730e-7,
    0.2271109460894316491031998116062124e-7,
    0.1083865921489695409107491757968159e-7,
    0.5183475041970046655121248647057669e-8,
    0.2483674543802478317185008663991718e-8,
    0.1192140140586091207442548202774640e-8,
    0.5731367241678862013330194857961011e-9,
    0.2759522885124233145178149692816341e-9,
    0.1330476437424448948149715720858008e-9,
    0.6422964563838100022082448087644648e-10,
    0.3104424774732227276239215783404066e-10,
    0.1502138408075414217093301048780668e-10,
    0.7275974480239079662504549924814047e-11,
    0.3527742476575915083615072228655483e-11,
    0.1711991790559617908601084114443031e-11,
    0.8315385841420284819798357793954418e-12,
    0.4042200525289440065536008957032895e-12,
    0.1966475631096616490411045679010286e-12,
    0.9573630387838555763782200936508615e-13,
    0.4664076026428374224576492565974577e-13,
    0.2273736960065972320633279596737272e-13,
    0.1109139947083452201658320007192334e-13,
)
"""``coeffs[i] = (zeta(i+2)-1)/(i+2)``, ``pgamma.c:155-196``."""


def _logcf(x: float, i: float, d: float, eps: float) -> float:
    """Fracción continua ``Σ x^k/(i + k·d)`` (``logcf``).

    Fuente: ``R-4.5.2/src/nmath/pgamma.c:72-118``. FMA (desensamblado de ``_logcf``): ``c2 - i*x``
    (``fmsub``), ``c4*c2 - b2`` y ``c4*b1 - (i*b2)`` (``fmadd`` con el producto restado redondeado),
    el test ``a2*b1 - (a1*b2)`` y las recurrencias ``c4*a - (c3*a')`` (``fmadd``).

    Args:
        x: Variable.
        i: Primer denominador.
        d: Incremento del denominador.
        eps: Tolerancia relativa.

    Returns:
        El valor de la fracción continua.
    """
    c1 = 2 * d
    c2 = i + d
    c4 = c2 + d
    a1 = c2
    b1 = i * fma(-i, x, c2)  # FMA: c2 - i*x
    b2 = d * d * x
    a2 = fma(c4, c2, -b2)  # FMA
    b2 = fma(c4, b1, -(i * b2))  # FMA
    while abs(fma(a2, b1, -(a1 * b2))) > abs(eps * b1 * b2):  # FMA
        c3 = c2 * c2 * x
        c2 += d
        c4 += d
        a1 = fma(c4, a2, -(c3 * a1))  # FMA
        b1 = fma(c4, b2, -(c3 * b1))  # FMA
        c3 = c1 * c1 * x
        c1 += d
        c4 += d
        a2 = fma(c4, a1, -(c3 * a2))  # FMA
        b2 = fma(c4, b1, -(c3 * b2))  # FMA
        if abs(b2) > _SCALEFACTOR:
            a1 /= _SCALEFACTOR
            b1 /= _SCALEFACTOR
            a2 /= _SCALEFACTOR
            b2 /= _SCALEFACTOR
        elif abs(b2) < 1 / _SCALEFACTOR:
            a1 *= _SCALEFACTOR
            b1 *= _SCALEFACTOR
            a2 *= _SCALEFACTOR
            b2 *= _SCALEFACTOR
    return a2 / b2


def _log1pmx(x: float) -> float:
    """``log(1+x) - x`` exacto para ``x`` pequeño (``log1pmx``).

    Fuente: ``R-4.5.2/src/nmath/pgamma.c:121-142``. FMA (desensamblado de ``_Rf_log1pmx``): el
    Horner en ``y`` (tres ``fmadd``) y ``(…)*y - x`` / ``2*y*logcf(…) - x`` (``fnmsub``).

    Args:
        x: Argumento ``> -1``.

    Returns:
        ``log1p(x) - x``.
    """
    if x > 1 or x < -0.79149064:
        return math.log1p(x) - x
    r = x / (2 + x)
    y = r * r
    if abs(x) < 1e-2:
        two = 2.0
        poly = fma(fma(fma(y, two / 9, two / 7), y, two / 5), y, two / 3)  # FMA
        return r * fma(poly, y, -x)  # FMA
    return r * fma(2 * y, _logcf(y, 3, 2, 1e-14), -x)  # FMA


def _lgamma1p(a: float) -> float:
    """``log Γ(a+1)`` exacto también para ``a`` pequeño (``lgamma1p``).

    Fuente: ``R-4.5.2/src/nmath/pgamma.c:146-213``. FMA (desensamblado de ``_Rf_lgamma1p``):
    ``coeffs[i] - a*lgam`` (``fmadd``), ``a*lgam - eulers_const`` (``fmadd``) y
    ``(…)*a - log1pmx(a)`` (``fnmsub``).

    Args:
        a: Argumento ``> -1``.

    Returns:
        ``lgamma(a + 1)``.
    """
    if abs(a) >= 0.5:
        return lgammafn(a + 1)
    eulers_const = 0.5772156649015328606065120900824024
    c = 0.2273736845824652515226821577978691e-12
    lgam = c * _logcf(-a / 2, 40 + 2, 1, 1e-14)
    for coef in reversed(_LGAMMA1P_COEFFS):
        lgam = fma(-a, lgam, coef)  # FMA
    return fma(fma(a, lgam, -eulers_const), a, -_log1pmx(a))  # FMA (dos)


# --------------------------------------------------------------------------------------------------
# stirlerr, ebd0, dpois_raw, dgamma
# --------------------------------------------------------------------------------------------------

_SFERR_HALVES = (
    0.0,
    0.1534264097200273452913848,
    0.0810614667953272582196702,
    0.0548141210519176538961390,
    0.0413406959554092940938221,
    0.03316287351993628748511048,
    0.02767792568499833914878929,
    0.02374616365629749597132920,
    0.02079067210376509311152277,
    0.01848845053267318523077934,
    0.01664469118982119216319487,
    0.01513497322191737887351255,
    0.01387612882307074799874573,
    0.01281046524292022692424986,
    0.01189670994589177009505572,
    0.01110455975820691732662991,
    0.010411265261972096497478567,
    0.009799416126158803298389475,
    0.009255462182712732917728637,
    0.008768700134139385462952823,
    0.008330563433362871256469318,
    0.007934114564314020547248100,
    0.007573675487951840794972024,
    0.007244554301320383179543912,
    0.006942840107209529865664152,
    0.006665247032707682442354394,
    0.006408994188004207068439631,
    0.006171712263039457647532867,
    0.005951370112758847735624416,
    0.005746216513010115682023589,
    0.005554733551962801371038690,
)
"""``sferr_halves`` (``stirlerr.c:78-110``)."""

_S0 = 0.083333333333333333333
_S1 = 0.00277777777777777777778
_S2 = 0.00079365079365079365079365
_S3 = 0.000595238095238095238095238
_S4 = 0.0008417508417508417508417508
_S5 = 0.0019175269175269175269175262
_S6 = 0.0064102564102564102564102561
_S7 = 0.029550653594771241830065352
_S8 = 0.17964437236883057316493850
_S9 = 1.3924322169059011164274315
_S10 = 13.402864044168391994478957
_S11 = 156.84828462600201730636509
_S12 = 2193.1033333333333333333333
_S13 = 36108.771253724989357173269
_S14 = 691472.26885131306710839498
_S15 = 15238221.539407416192283370
_S16 = 382900751.39141414141414141


def _stirlerr(n: float) -> float:
    """``stirlerr(n) = log(n!) - log(sqrt(2πn)(n/e)^n)``.

    Fuente: ``R-4.5.2/src/nmath/stirlerr.c:53-152``. FMA (desensamblado de ``_Rf_stirlerr``):
    ``lgamma1p(n) - (n + 0.5)*log(n)`` (``fmsub``, rama ``n < 1``) y ``lgamma(n) + n*(1 - l_n)``
    (``fmadd``, rama ``1 <= n <= 5.25``). Las series en ``1/n²`` no tienen contracciones.

    Args:
        n: Argumento positivo.

    Returns:
        El término de error de Stirling.
    """
    if n <= 23.5:
        nn = n + n
        if n <= 15.0 and nn == int(nn):
            return _SFERR_HALVES[int(nn)]
        if n <= 5.25:
            if n >= 1.0:
                l_n = math.log(n)
                return fma(n, 1 - l_n, _c_lgamma(n)) + math.ldexp(l_n - _M_LN_2PI, -1)  # FMA
            return fma(-(n + 0.5), math.log(n), _lgamma1p(n)) + n - _M_LN_SQRT_2PI  # FMA
        nn = n * n
        if n > 12.8:
            return (
                _S0 - (_S1 - (_S2 - (_S3 - (_S4 - (_S5 - _S6 / nn) / nn) / nn) / nn) / nn) / nn
            ) / n
        if n > 12.3:
            return (
                _S0
                - (_S1 - (_S2 - (_S3 - (_S4 - (_S5 - (_S6 - _S7 / nn) / nn) / nn) / nn) / nn) / nn)
                / nn
            ) / n
        if n > 8.9:
            return (
                _S0
                - (
                    _S1
                    - (
                        _S2
                        - (_S3 - (_S4 - (_S5 - (_S6 - (_S7 - _S8 / nn) / nn) / nn) / nn) / nn) / nn
                    )
                    / nn
                )
                / nn
            ) / n
        if n > 7.3:
            t = _S9 - _S10 / nn
            for s in (_S8, _S7, _S6, _S5, _S4, _S3, _S2, _S1, _S0):
                t = s - t / nn
            return t / n
        if n > 6.6:
            t = _S11 - _S12 / nn
            for s in (_S10, _S9, _S8, _S7, _S6, _S5, _S4, _S3, _S2, _S1, _S0):
                t = s - t / nn
            return t / n
        if n > 6.1:
            t = _S13 - _S14 / nn
            for s in (_S12, _S11, _S10, _S9, _S8, _S7, _S6, _S5, _S4, _S3, _S2, _S1, _S0):
                t = s - t / nn
            return t / n
        t = _S15 - _S16 / nn
        for s in (_S14, _S13, _S12, _S11, _S10, _S9, _S8, _S7, _S6, _S5, _S4, _S3, _S2, _S1, _S0):
            t = s - t / nn
        return t / n
    nn = n * n
    if n > 15.7e6:
        return _S0 / n
    if n > 6180:
        return (_S0 - _S1 / nn) / n
    if n > 205:
        return (_S0 - (_S1 - _S2 / nn) / nn) / n
    if n > 86:
        return (_S0 - (_S1 - (_S2 - _S3 / nn) / nn) / nn) / n
    if n > 27:
        return (_S0 - (_S1 - (_S2 - (_S3 - _S4 / nn) / nn) / nn) / nn) / n
    return (_S0 - (_S1 - (_S2 - (_S3 - (_S4 - _S5 / nn) / nn) / nn) / nn) / nn) / n


_BD0_SCALE_HEX = (
    ("0x1.62e430p-1", "-0x1.05c610p-29", "-0x1.950d88p-54", "0x1.d9cc02p-79"),
    ("0x1.5ee02cp-1", "-0x1.6dbe98p-25", "-0x1.51e540p-50", "0x1.2bfa48p-74"),
    ("0x1.5ad404p-1", "0x1.86b3e4p-26", "0x1.9f6534p-50", "0x1.54be04p-74"),
    ("0x1.570124p-1", "-0x1.9ed750p-25", "-0x1.f37dd0p-51", "0x1.10b770p-77"),
    ("0x1.5326e4p-1", "-0x1.9b9874p-25", "-0x1.378194p-49", "0x1.56feb2p-74"),
    ("0x1.4f4528p-1", "0x1.aca70cp-28", "0x1.103e74p-53", "0x1.9c410ap-81"),
    ("0x1.4b5bd8p-1", "-0x1.6a91d8p-25", "-0x1.8e43d0p-50", "-0x1.afba9ep-77"),
    ("0x1.47ae54p-1", "-0x1.abb51cp-25", "0x1.19b798p-51", "0x1.45e09cp-76"),
    ("0x1.43fa00p-1", "-0x1.d06318p-25", "-0x1.8858d8p-49", "-0x1.1927c4p-75"),
    ("0x1.3ffa40p-1", "0x1.1a427cp-25", "0x1.151640p-53", "-0x1.4f5606p-77"),
    ("0x1.3c7c80p-1", "-0x1.19bf48p-34", "0x1.05fc94p-58", "-0x1.c096fcp-82"),
    ("0x1.38b320p-1", "0x1.6b5778p-25", "0x1.be38d0p-50", "-0x1.075e96p-74"),
    ("0x1.34e288p-1", "0x1.d9ce1cp-25", "0x1.316eb8p-49", "0x1.2d885cp-73"),
    ("0x1.315124p-1", "0x1.c2fc60p-29", "-0x1.4396fcp-53", "0x1.acf376p-78"),
    ("0x1.2db954p-1", "0x1.720de4p-25", "-0x1.d39b04p-49", "-0x1.f11176p-76"),
    ("0x1.2a1b08p-1", "-0x1.562494p-25", "0x1.a7863cp-49", "0x1.85dd64p-73"),
    ("0x1.267620p-1", "0x1.3430e0p-29", "-0x1.96a958p-56", "0x1.f8e636p-82"),
    ("0x1.23130cp-1", "0x1.7bebf4p-25", "0x1.416f1cp-52", "-0x1.78dd36p-77"),
    ("0x1.1faa34p-1", "0x1.70e128p-26", "0x1.81817cp-50", "-0x1.c2179cp-76"),
    ("0x1.1bf204p-1", "0x1.3a9620p-28", "0x1.2f94c0p-52", "0x1.9096c0p-76"),
    ("0x1.187ce4p-1", "-0x1.077870p-27", "0x1.655a80p-51", "0x1.eaafd6p-78"),
    ("0x1.1501c0p-1", "-0x1.406cacp-25", "-0x1.e72290p-49", "0x1.5dd800p-73"),
    ("0x1.11cb80p-1", "0x1.787cd0p-25", "-0x1.efdc78p-51", "-0x1.5380cep-77"),
    ("0x1.0e4498p-1", "0x1.747324p-27", "-0x1.024548p-51", "0x1.77a5a6p-75"),
    ("0x1.0b036cp-1", "0x1.690c74p-25", "0x1.5d0cc4p-50", "-0x1.c0e23cp-76"),
    ("0x1.077070p-1", "-0x1.a769bcp-27", "0x1.452234p-52", "0x1.6ba668p-76"),
    ("0x1.04240cp-1", "-0x1.a686acp-27", "-0x1.ef46b0p-52", "-0x1.5ce10cp-76"),
    ("0x1.00d22cp-1", "0x1.fc0e10p-25", "0x1.6ee034p-50", "-0x1.19a2ccp-74"),
    ("0x1.faf588p-2", "0x1.ef1e64p-27", "-0x1.26504cp-54", "-0x1.b15792p-82"),
    ("0x1.f4d87cp-2", "0x1.d7b980p-26", "-0x1.a114d8p-50", "0x1.9758c6p-75"),
    ("0x1.ee1414p-2", "0x1.2ec060p-26", "0x1.dc00fcp-52", "0x1.f8833cp-76"),
    ("0x1.e7e32cp-2", "-0x1.ac796cp-27", "-0x1.a68818p-54", "0x1.235d02p-78"),
    ("0x1.e108a0p-2", "-0x1.768ba4p-28", "-0x1.f050a8p-52", "0x1.00d632p-82"),
    ("0x1.dac354p-2", "-0x1.d3a6acp-30", "0x1.18734cp-57", "-0x1.f97902p-83"),
    ("0x1.d47424p-2", "0x1.7dbbacp-31", "-0x1.d5ada4p-56", "0x1.56fcaap-81"),
    ("0x1.ce1af0p-2", "0x1.70be7cp-27", "0x1.6f6fa4p-51", "0x1.7955a2p-75"),
    ("0x1.c7b798p-2", "0x1.ec36ecp-26", "-0x1.07e294p-50", "-0x1.ca183cp-75"),
    ("0x1.c1ef04p-2", "0x1.c1dfd4p-26", "0x1.888eecp-50", "-0x1.fd6b86p-75"),
    ("0x1.bb7810p-2", "0x1.478bfcp-26", "0x1.245b8cp-50", "0x1.ea9d52p-74"),
    ("0x1.b59da0p-2", "-0x1.882b08p-27", "0x1.31573cp-53", "-0x1.8c249ap-77"),
    ("0x1.af1294p-2", "-0x1.b710f4p-27", "0x1.622670p-51", "0x1.128578p-76"),
    ("0x1.a925d4p-2", "-0x1.0ae750p-27", "0x1.574ed4p-51", "0x1.084996p-75"),
    ("0x1.a33040p-2", "0x1.027d30p-29", "0x1.b9a550p-53", "-0x1.b2e38ap-78"),
    ("0x1.9d31c0p-2", "-0x1.5ec12cp-26", "-0x1.5245e0p-52", "0x1.2522d0p-79"),
    ("0x1.972a34p-2", "0x1.135158p-30", "0x1.a5c09cp-56", "0x1.24b70ep-80"),
    ("0x1.911984p-2", "0x1.0995d4p-26", "0x1.3bfb5cp-50", "0x1.2c9dd6p-75"),
    ("0x1.8bad98p-2", "-0x1.1d6144p-29", "0x1.5b9208p-53", "0x1.1ec158p-77"),
    ("0x1.858b58p-2", "-0x1.1b4678p-27", "0x1.56cab4p-53", "-0x1.2fdc0cp-78"),
    ("0x1.7f5fa0p-2", "0x1.3aaf48p-27", "0x1.461964p-51", "0x1.4ae476p-75"),
    ("0x1.79db68p-2", "-0x1.7e5054p-26", "0x1.673750p-51", "-0x1.a11f7ap-76"),
    ("0x1.744f88p-2", "-0x1.cc0e18p-26", "-0x1.1e9d18p-50", "-0x1.6c06bcp-78"),
    ("0x1.6e08ecp-2", "-0x1.5d45e0p-26", "-0x1.c73ec8p-50", "0x1.318d72p-74"),
    ("0x1.686c80p-2", "0x1.e9b14cp-26", "-0x1.13bbd4p-50", "-0x1.efeb1cp-78"),
    ("0x1.62c830p-2", "-0x1.a8c70cp-27", "-0x1.5a1214p-51", "-0x1.bab3fcp-79"),
    ("0x1.5d1bdcp-2", "-0x1.4fec6cp-31", "0x1.423638p-56", "0x1.ee3feep-83"),
    ("0x1.576770p-2", "0x1.7455a8p-26", "-0x1.3ab654p-50", "-0x1.26be4cp-75"),
    ("0x1.5262e0p-2", "-0x1.146778p-26", "-0x1.b9f708p-52", "-0x1.294018p-77"),
    ("0x1.4c9f08p-2", "0x1.e152c4p-26", "-0x1.dde710p-53", "0x1.fd2208p-77"),
    ("0x1.46d2d8p-2", "0x1.c28058p-26", "-0x1.936284p-50", "0x1.9fdd68p-74"),
    ("0x1.41b940p-2", "0x1.cce0c0p-26", "-0x1.1a4050p-50", "0x1.bc0376p-76"),
    ("0x1.3bdd24p-2", "0x1.d6296cp-27", "0x1.425b48p-51", "-0x1.cddb2cp-77"),
    ("0x1.36b578p-2", "-0x1.287ddcp-27", "-0x1.2d0f4cp-51", "0x1.38447ep-75"),
    ("0x1.31871cp-2", "0x1.2a8830p-27", "0x1.3eae54p-52", "-0x1.898136p-77"),
    ("0x1.2b9304p-2", "-0x1.51d8b8p-28", "0x1.27694cp-52", "-0x1.fd852ap-76"),
    ("0x1.265620p-2", "-0x1.d98f3cp-27", "0x1.a44338p-51", "-0x1.56e85ep-78"),
    ("0x1.211254p-2", "0x1.986160p-26", "0x1.73c5d0p-51", "0x1.4a861ep-75"),
    ("0x1.1bc794p-2", "0x1.fa3918p-27", "0x1.879c5cp-51", "0x1.16107cp-78"),
    ("0x1.1675ccp-2", "-0x1.4545a0p-26", "0x1.c07398p-51", "0x1.f55c42p-76"),
    ("0x1.111ce4p-2", "0x1.f72670p-37", "-0x1.b84b5cp-61", "0x1.a4a4dcp-85"),
    ("0x1.0c81d4p-2", "0x1.0c150cp-27", "0x1.218600p-51", "-0x1.d17312p-76"),
    ("0x1.071b84p-2", "0x1.fcd590p-26", "0x1.a3a2e0p-51", "0x1.fe5ef8p-76"),
    ("0x1.01ade4p-2", "-0x1.bb1844p-28", "0x1.db3cccp-52", "0x1.1f56fcp-77"),
    ("0x1.fa01c4p-3", "-0x1.12a0d0p-29", "-0x1.f71fb0p-54", "0x1.e287a4p-78"),
    ("0x1.ef0adcp-3", "0x1.7b8b28p-28", "-0x1.35bce4p-52", "-0x1.abc8f8p-79"),
    ("0x1.e598ecp-3", "0x1.5a87e4p-27", "-0x1.134bd0p-51", "0x1.c2cebep-76"),
    ("0x1.da85d8p-3", "-0x1.df31b0p-27", "0x1.94c16cp-57", "0x1.8fd7eap-82"),
    ("0x1.d0fb80p-3", "-0x1.bb5434p-28", "-0x1.ea5640p-52", "-0x1.8ceca4p-77"),
    ("0x1.c765b8p-3", "0x1.e4d68cp-27", "0x1.5b59b4p-51", "0x1.76f6c4p-76"),
    ("0x1.bdc46cp-3", "-0x1.1cbb50p-27", "0x1.2da010p-51", "0x1.eb282cp-75"),
    ("0x1.b27980p-3", "-0x1.1b9ce0p-27", "0x1.7756f8p-52", "0x1.2ff572p-76"),
    ("0x1.a8bed0p-3", "-0x1.bbe874p-30", "0x1.85cf20p-56", "0x1.b9cf18p-80"),
    ("0x1.9ef83cp-3", "0x1.2769a4p-27", "-0x1.85bda0p-52", "0x1.8c8018p-79"),
    ("0x1.9525a8p-3", "0x1.cf456cp-27", "-0x1.7137d8p-52", "-0x1.f158e8p-76"),
    ("0x1.8b46f8p-3", "0x1.11b12cp-30", "0x1.9f2104p-54", "-0x1.22836ep-78"),
    ("0x1.83040cp-3", "0x1.2379e4p-28", "0x1.b71c70p-52", "-0x1.990cdep-76"),
    ("0x1.790ed4p-3", "0x1.dc4c68p-28", "-0x1.910ac8p-52", "0x1.dd1bd6p-76"),
    ("0x1.6f0d28p-3", "0x1.5cad68p-28", "0x1.737c94p-52", "-0x1.9184bap-77"),
    ("0x1.64fee8p-3", "0x1.04bf88p-28", "0x1.6fca28p-52", "0x1.8884a8p-76"),
    ("0x1.5c9400p-3", "0x1.d65cb0p-29", "-0x1.b2919cp-53", "0x1.b99bcep-77"),
    ("0x1.526e60p-3", "-0x1.c5e4bcp-27", "-0x1.0ba380p-52", "0x1.d6e3ccp-79"),
    ("0x1.483bccp-3", "0x1.9cdc7cp-28", "-0x1.5ad8dcp-54", "-0x1.392d3cp-83"),
    ("0x1.3fb25cp-3", "-0x1.a6ad74p-27", "0x1.5be6b4p-52", "-0x1.4e0114p-77"),
    ("0x1.371fc4p-3", "-0x1.fe1708p-27", "-0x1.78864cp-52", "-0x1.27543ap-76"),
    ("0x1.2cca10p-3", "-0x1.4141b4p-28", "-0x1.ef191cp-52", "0x1.00ee08p-76"),
    ("0x1.242310p-3", "0x1.3ba510p-27", "-0x1.d003c8p-51", "0x1.162640p-76"),
    ("0x1.1b72acp-3", "0x1.52f67cp-27", "-0x1.fd6fa0p-51", "0x1.1a3966p-77"),
    ("0x1.10f8e4p-3", "0x1.129cd8p-30", "0x1.31ef30p-55", "0x1.a73e38p-79"),
    ("0x1.08338cp-3", "-0x1.005d7cp-27", "-0x1.661a9cp-51", "0x1.1f138ap-79"),
    ("0x1.fec914p-4", "-0x1.c482a8p-29", "-0x1.55746cp-54", "0x1.99f932p-80"),
    ("0x1.ed1794p-4", "0x1.d06f00p-29", "0x1.75e45cp-53", "-0x1.d0483ep-78"),
    ("0x1.db5270p-4", "0x1.87d928p-32", "-0x1.0f52a4p-57", "0x1.81f4a6p-84"),
    ("0x1.c97978p-4", "0x1.af1d24p-29", "-0x1.0977d0p-60", "-0x1.8839d0p-84"),
    ("0x1.b78c84p-4", "-0x1.44f124p-28", "-0x1.ef7bc4p-52", "0x1.9e0650p-78"),
    ("0x1.a58b60p-4", "0x1.856464p-29", "0x1.c651d0p-55", "0x1.b06b0cp-79"),
    ("0x1.9375e4p-4", "0x1.5595ecp-28", "0x1.dc3738p-52", "0x1.86c89ap-81"),
    ("0x1.814be4p-4", "-0x1.c073fcp-28", "-0x1.371f88p-53", "-0x1.5f4080p-77"),
    ("0x1.6f0d28p-4", "0x1.5cad68p-29", "0x1.737c94p-53", "-0x1.9184bap-78"),
    ("0x1.60658cp-4", "-0x1.6c8af4p-28", "0x1.d8ef74p-55", "0x1.c4f792p-80"),
    ("0x1.4e0110p-4", "0x1.146b5cp-29", "0x1.73f7ccp-54", "-0x1.d28db8p-79"),
    ("0x1.3b8758p-4", "0x1.8b1b70p-28", "-0x1.20aca4p-52", "-0x1.651894p-76"),
    ("0x1.28f834p-4", "0x1.43b6a4p-30", "-0x1.452af8p-55", "0x1.976892p-80"),
    ("0x1.1a0fbcp-4", "-0x1.e4075cp-28", "0x1.1fe618p-52", "0x1.9d6dc2p-77"),
    ("0x1.075984p-4", "-0x1.4ce370p-29", "-0x1.d9fc98p-53", "0x1.4ccf12p-77"),
    ("0x1.f0a30cp-5", "0x1.162a68p-37", "-0x1.e83368p-61", "-0x1.d222a6p-86"),
    ("0x1.cae730p-5", "-0x1.1a8f7cp-31", "-0x1.5f9014p-55", "0x1.2720c0p-79"),
    ("0x1.ac9724p-5", "-0x1.e8ee08p-29", "0x1.a7de04p-54", "-0x1.9bba74p-78"),
    ("0x1.868a84p-5", "-0x1.ef8128p-30", "0x1.dc5eccp-54", "-0x1.58d250p-79"),
    ("0x1.67f950p-5", "-0x1.ed684cp-30", "-0x1.f060c0p-55", "-0x1.b1294cp-80"),
    ("0x1.494accp-5", "0x1.a6c890p-32", "-0x1.c3ad48p-56", "-0x1.6dc66cp-84"),
    ("0x1.22c71cp-5", "-0x1.8abe2cp-32", "-0x1.7e7078p-56", "-0x1.ddc3dcp-86"),
    ("0x1.03d5d8p-5", "0x1.79cfbcp-31", "-0x1.da7c4cp-58", "0x1.4e7582p-83"),
    ("0x1.c98d18p-6", "0x1.a01904p-31", "-0x1.854164p-55", "0x1.883c36p-79"),
    ("0x1.8b31fcp-6", "-0x1.356500p-30", "0x1.c3ab48p-55", "0x1.b69bdap-80"),
    ("0x1.3cea44p-6", "0x1.a352bcp-33", "-0x1.8865acp-57", "-0x1.48159cp-81"),
    ("0x1.fc0a8cp-7", "-0x1.e07f84p-32", "0x1.e7cf6cp-58", "0x1.3a69c0p-82"),
    ("0x1.7dc474p-7", "0x1.f810a8p-31", "-0x1.245b5cp-56", "-0x1.a1f4f8p-80"),
    ("0x1.fe02a8p-8", "-0x1.4ef988p-32", "0x1.1f86ecp-57", "0x1.20723cp-81"),
    ("0x1.ff00acp-9", "-0x1.d4ef44p-33", "0x1.2821acp-63", "0x1.5a6d32p-87"),
    ("0x0p+0", "0x0p+0", "0x0p+0", "0x0p+0"),
)
"""``bd0_scale[128 + 1][4]`` (``bd0.c:102-232``), literales ``float`` en hexadecimal."""

_BD0_SCALE = tuple(
    tuple(float(np.float32(float.fromhex(v))) for v in row) for row in _BD0_SCALE_HEX
)
"""La tabla como ``double`` (cada entrada es un ``float`` de C promovido)."""


def _ebd0(x: float, m: float) -> tuple[float, float]:
    """``ebd0(x, M)``: ``x·log(x/M) + M - x`` en dos partes ``(yh, yl)``.

    Fuente: ``R-4.5.2/src/nmath/bd0.c:241-355`` (tabla ``bd0_scale``, ``:102-232``). FMA
    (desensamblado de ``_Rf_ebd0``): ``(r - 0.5)*(2N) + 0.5`` (``fmadd``) y ``M*fg - x``
    (``fnmsub``) en el argumento de ``log1pmx``.

    Args:
        x: Argumento ``>= 0``.
        m: Media ``>= 0``.

    Returns:
        Tupla ``(yh, yl)``.
    """
    yh = 0.0
    yl = 0.0
    if x == m:
        return yh, yl
    if x == 0:
        return m, yl
    if m == 0:
        return _INF, yl
    if m / x == _INF:
        return m, yl
    r, e = math.frexp(m / x)
    if _M_LN2 * float(-e) > 1.0 + _DBL_MAX / x:
        return _INF, yl
    i = math.floor(fma(r - 0.5, 2 * 128, 0.5))  # FMA
    f = math.floor(1024 / (0.5 + i / (2.0 * 128)) + 0.5)
    fg = math.ldexp(f, -(e + 10))
    if fg == _INF:
        return fg, yl

    def add1(d: float) -> None:
        nonlocal yh, yl
        d1 = math.floor(d + 0.5)
        d2 = d - d1
        yh += d1
        yl += d2

    add1(-x * _log1pmx(fma(m, fg, -x) / x))  # FMA: M*fg - x
    if fg == 1:
        return yh, yl
    for j in range(4):
        add1(x * _BD0_SCALE[i][j])
        add1(-x * _BD0_SCALE[0][j] * e)
        if not math.isfinite(yh):
            return _INF, 0.0
    add1(m)
    add1(-m * fg)
    return yh, yl


def _dpois_raw(x: float, lam: float, give_log: bool) -> float:
    """``dpois_raw(x, lambda, give_log)`` (``x`` no necesariamente entero).

    Fuente: ``R-4.5.2/src/nmath/dpois.c:43-69``. FMA (desensamblado de ``_Rf_dpois_raw``):
    ``-lambda + x*log(lambda)`` es ``fnmsub``.

    Args:
        x: Argumento.
        lam: Media.
        give_log: Devolver el logaritmo.

    Returns:
        La densidad de Poisson (o su logaritmo).
    """
    d0 = -_INF if give_log else 0.0
    if lam == 0:
        return (0.0 if give_log else 1.0) if x == 0 else d0
    if not math.isfinite(lam) or x < 0:
        return d0
    if x <= lam * _DBL_MIN:
        return -lam if give_log else math.exp(-lam)
    if lam < x * _DBL_MIN:
        if not math.isfinite(x):
            return d0
        v = fma(x, math.log(lam), -lam) - lgammafn(x + 1)  # FMA
        return v if give_log else math.exp(v)
    yh, yl = _ebd0(x, lam)
    yl = _stirlerr(x) + yl
    lrg_x = x >= _X_LRG
    r = _M_SQRT_2PI * math.sqrt(x) if lrg_x else _M_2PI * x
    if give_log:
        return -yl - yh - (math.log(r) if lrg_x else 0.5 * math.log(r))
    return math.exp(-yl) * math.exp(-yh) / (r if lrg_x else math.sqrt(r))


def dgamma_log(x: float, shape: float, scale: float) -> float:
    """``dgamma(x, shape, scale, log = TRUE)``.

    Fuente: ``R-4.5.2/src/nmath/dgamma.c:42-74`` (sin contracciones FMA en ``_Rf_dgamma``). Solo la
    rama ``give_log = TRUE``, la única que usa ``qgamma`` (``qgamma.c:279``).

    Args:
        x: Cuantil.
        shape: Forma ``> 0``.
        scale: Escala ``> 0``.

    Returns:
        El logaritmo de la densidad.
    """
    if math.isnan(x) or math.isnan(shape) or math.isnan(scale):
        return x + shape + scale
    if shape < 0 or scale <= 0:
        return math.nan
    if x < 0:
        return -_INF
    if x == 0:
        if shape < 1:
            return _INF
        if shape > 1:
            return -_INF
        return -math.log(scale)
    if shape < 1:
        pr = _dpois_raw(shape, x / scale, True)
        ratio = shape / x
        return pr + (math.log(ratio) if math.isfinite(ratio) else math.log(shape) - math.log(x))
    pr = _dpois_raw(shape - 1, x / scale, True)
    return pr - math.log(scale)


# --------------------------------------------------------------------------------------------------
# Normal: dnorm, pnorm (cola inferior), dpnorm
# --------------------------------------------------------------------------------------------------


def _dnorm(x: float) -> float:
    """``dnorm(x, 0, 1, log = FALSE)``.

    Fuente: ``R-4.5.2/src/nmath/dnorm.c:34-93`` (rama ``MATHLIB_FAST_dnorm`` desactivada). FMA
    (desensamblado de ``_Rf_dnorm4``): ``(-0.5*x2 - x1)`` es ``fnmsub`` (rama ``|x| >= 5``).

    Args:
        x: Cuantil finito.

    Returns:
        La densidad normal estándar.
    """
    if not math.isfinite(x):
        return 0.0
    x = abs(x)
    if x >= 2 * math.sqrt(_DBL_MAX):
        return 0.0
    if x < 5:
        return _M_1_SQRT_2PI * math.exp(-0.5 * x * x)
    if x > _DNORM_UNDERFLOW:
        return 0.0
    x1 = math.ldexp(float(round(math.ldexp(x, 16))), -16)  # R_forceint = nearbyint (par)
    x2 = x - x1
    return _M_1_SQRT_2PI * (math.exp(-0.5 * x1 * x1) * math.exp(fma(x2, -0.5, -x1) * x2))  # FMA


_PN_A = (
    2.2352520354606839287,
    161.02823106855587881,
    1067.6894854603709582,
    18154.981253343561249,
    0.065682337918207449113,
)
_PN_B = (47.20258190468824187, 976.09855173777669322, 10260.932208618978205, 45507.789335026729956)
_PN_C = (
    0.39894151208813466764,
    8.8831497943883759412,
    93.506656132177855979,
    597.27027639480026226,
    2494.5375852903726711,
    6848.1904505362823326,
    11602.651437647350124,
    9842.7148383839780218,
    1.0765576773720192317e-8,
)
_PN_D = (
    22.266688044328115691,
    235.38790178262499861,
    1519.377599407554805,
    6485.558298266760755,
    18615.571640885098091,
    34900.952721145977266,
    38912.003286093271411,
    19685.429676859990727,
)
_PN_P = (
    0.21589853405795699,
    0.1274011611602473639,
    0.022235277870649807,
    0.001421619193227893466,
    2.9112874951168792e-5,
    0.02307344176494017303,
)
_PN_Q = (
    1.28426009614491121,
    0.468238212480865118,
    0.0659881378689285515,
    0.00378239633202758244,
    7.29751555083966205e-5,
)


def _pnorm_lower(x: float, log_p: bool) -> float:
    """``pnorm(x, 0, 1, lower.tail = TRUE, log.p)`` (``pnorm5`` + ``pnorm_both``, ``i_tail = 0``).

    Fuente: ``R-4.5.2/src/nmath/pnorm.c:62-87`` y ``:90-286``. FMA (desensamblado de
    ``_Rf_pnorm_both``): en ``do_del`` con ``log_p``, ``(-xsq*d_2(xsq)) - d_2(del)`` es ``fnmsub``.

    Args:
        x: Cuantil.
        log_p: Devolver el logaritmo.

    Returns:
        ``P[X <= x]`` (o su logaritmo).
    """
    if math.isnan(x):
        return x
    if not math.isfinite(x):
        return (-_INF if log_p else 0.0) if x < 0 else (0.0 if log_p else 1.0)
    eps = _DBL_EPSILON * 0.5
    y = abs(x)
    if y <= 0.67448975:
        if y > eps:
            xsq = x * x
            xnum = _PN_A[4] * xsq
            xden = xsq
            for i in range(3):
                xnum = (xnum + _PN_A[i]) * xsq
                xden = (xden + _PN_B[i]) * xsq
        else:
            xnum = xden = 0.0
        temp = x * (xnum + _PN_A[3]) / (xden + _PN_B[3])
        cum = 0.5 + temp
        return math.log(cum) if log_p else cum
    if y <= _M_SQRT_32:
        xnum = _PN_C[8] * y
        xden = y
        for i in range(7):
            xnum = (xnum + _PN_C[i]) * y
            xden = (xden + _PN_D[i]) * y
        temp = (xnum + _PN_C[7]) / (xden + _PN_D[7])
        big = y
    elif (log_p and y < 1e170) or (-38.4674 < x < 8.2924):
        xsq = 1.0 / (x * x)
        xnum = _PN_P[5] * xsq
        xden = xsq
        for i in range(4):
            xnum = (xnum + _PN_P[i]) * xsq
            xden = (xden + _PN_Q[i]) * xsq
        temp = xsq * (xnum + _PN_P[4]) / (xden + _PN_Q[4])
        temp = (_M_1_SQRT_2PI - temp) / y
        big = x
    else:
        if x > 0:
            return 0.0 if log_p else 1.0
        return -_INF if log_p else 0.0
    # do_del(big) (pnorm.c:194-206) y swap_tail (:208-211) para la cola inferior.
    xsq = math.ldexp(math.trunc(math.ldexp(big, 4)), -4)
    dl = (big - xsq) * (big + xsq)
    half_xsq = math.ldexp(xsq, -1)
    half_del = math.ldexp(dl, -1)
    if log_p:
        cum = fma(-xsq, half_xsq, -half_del) + math.log(temp)  # FMA
        if x > 0:
            return math.log1p(-(math.exp(-xsq * half_xsq) * math.exp(-half_del)) * temp)
        return cum
    cum = math.exp(-xsq * half_xsq) * math.exp(-half_del) * temp
    return 1.0 - cum if x > 0 else cum


def _dpnorm(x: float, lower_tail: bool, lp: float) -> float:
    """``dnorm(x)/pnorm(x, lower_tail)`` con ``lp = pnorm(x, lower_tail, log = TRUE)``.

    Fuente: ``R-4.5.2/src/nmath/pgamma.c:514-548`` (integrada en ``_Rf_pgamma_raw``, sin FMA).

    Args:
        x: Cuantil.
        lower_tail: Cola.
        lp: Logaritmo de la probabilidad de la cola.

    Returns:
        El cociente densidad/probabilidad.
    """
    if x < 0:
        x = -x
        lower_tail = not lower_tail
    if x > 10 and not lower_tail:
        term = 1 / x
        total = term
        x2 = x * x
        i = 1.0
        while True:
            term *= -i / x2
            total += term
            i += 2
            if not abs(term) > _DBL_EPSILON * total:
                break
        return 1 / total
    return _dnorm(x) / math.exp(lp)


# --------------------------------------------------------------------------------------------------
# pgamma
# --------------------------------------------------------------------------------------------------

_COEFS_A = (
    2 / 3.0,
    -4 / 135.0,
    8 / 2835.0,
    16 / 8505.0,
    -8992 / 12629925.0,
    -334144 / 492567075.0,
    698752 / 1477701225.0,
)
_COEFS_B = (
    1 / 12.0,
    1 / 288.0,
    -139 / 51840.0,
    -571 / 2488320.0,
    163879 / 209018880.0,
    5246819 / 75246796800.0,
    -534703531 / 902961561600.0,
)


def _r_log1_exp(x: float) -> float:
    """``R_Log1_Exp(x) = log(1 - exp(x))`` (``dpq.h:43``).

    Args:
        x: Argumento ``<= 0``.

    Returns:
        ``log(1 - exp(x))``.
    """
    return math.log(-math.expm1(x)) if x > -_M_LN2 else math.log1p(-math.exp(x))


def _dpois_wrap(x_plus_1: float, lam: float, give_log: bool) -> float:
    """``dpois_wrap(x+1, lambda) = dpois(x, lambda)``.

    Fuente: ``R-4.5.2/src/nmath/pgamma.c:282-304`` (integrada en ``_Rf_pgamma_raw``, sin FMA).

    Args:
        x_plus_1: ``x + 1``.
        lam: Media.
        give_log: Devolver el logaritmo.

    Returns:
        La densidad (o su logaritmo).
    """
    if not math.isfinite(lam):
        return -_INF if give_log else 0.0
    if x_plus_1 > 1:
        return _dpois_raw(x_plus_1 - 1, lam, give_log)
    if lam > abs(x_plus_1 - 1) * _M_CUTOFF:
        v = -lam - lgammafn(x_plus_1)
        return v if give_log else math.exp(v)
    d = _dpois_raw(x_plus_1, lam, give_log)
    return d + math.log(x_plus_1 / lam) if give_log else d * (x_plus_1 / lam)


def _pgamma_smallx(x: float, alph: float, log_p: bool) -> float:
    """``pgamma_smallx`` con ``lower_tail = TRUE`` (A&S 6.5.29).

    Fuente: ``R-4.5.2/src/nmath/pgamma.c:309-346``. FMA (desensamblado de ``_Rf_pgamma_raw``):
    ``alph*log(x) - lgamma1p(alph)`` es ``fnmsub``.

    Args:
        x: Cuantil ``< 1``.
        alph: Forma.
        log_p: Devolver el logaritmo.

    Returns:
        ``P[X <= x]`` (o su logaritmo).
    """
    total = 0.0
    c = alph
    n = 0.0
    while True:
        n += 1
        c *= -x / n
        term = c / (alph + n)
        total += term
        if not abs(term) > _DBL_EPSILON * abs(total):
            break
    f1 = math.log1p(total) if log_p else 1 + total
    if alph > 1:
        f2 = _dpois_raw(alph, x, log_p)
        f2 = f2 + x if log_p else f2 * math.exp(x)
    elif log_p:
        f2 = fma(alph, math.log(x), -_lgamma1p(alph))  # FMA
    else:
        f2 = math.pow(x, alph) / math.exp(_lgamma1p(alph))
    return f1 + f2 if log_p else f1 * f2


def _pd_upper_series(x: float, y: float, log_p: bool) -> float:
    """``pd_upper_series`` (``pgamma.c:364-382``, sin FMA).

    Args:
        x: Cuantil.
        y: Forma.
        log_p: Devolver el logaritmo.

    Returns:
        ``Σ x^(n+1)/(y(y+1)…(y+n))`` (o su logaritmo).
    """
    term = x / y
    total = term
    while True:
        y += 1
        term *= x / y
        total += term
        if not term > total * _DBL_EPSILON:
            break
    return math.log(total) if log_p else total


def _pd_lower_cf(y: float, d: float) -> float:
    """Fracción continua de la cola superior escalada (``pd_lower_cf``).

    Fuente: ``R-4.5.2/src/nmath/pgamma.c:388-458``. FMA (desensamblado de ``_pd_lower_cf``, con
    ``fmla.2d``): ``c4*a2 + (c3*a1)`` y análogas, con el producto ``c3*·`` redondeado.

    Args:
        y: Primer argumento.
        d: Segundo argumento.

    Returns:
        El valor de la fracción continua.
    """
    f = 0.0
    if y == 0:
        return 0.0
    f0 = y / d
    if abs(y - 1) < abs(d) * _DBL_EPSILON:
        return f0
    f0 = min(f0, 1.0)
    c2 = y
    c4 = d
    a1 = 0.0
    b1 = 1.0
    a2 = y
    b2 = d
    while b2 > _SCALEFACTOR:
        a1 /= _SCALEFACTOR
        b1 /= _SCALEFACTOR
        a2 /= _SCALEFACTOR
        b2 /= _SCALEFACTOR
    i = 0.0
    of = -1.0
    while i < 200000:
        i += 1
        c2 -= 1
        c3 = i * c2
        c4 += 2
        a1 = fma(c4, a2, c3 * a1)  # FMA
        b1 = fma(c4, b2, c3 * b1)  # FMA
        i += 1
        c2 -= 1
        c3 = i * c2
        c4 += 2
        a2 = fma(c4, a1, c3 * a2)  # FMA
        b2 = fma(c4, b1, c3 * b2)  # FMA
        if b2 > _SCALEFACTOR:
            a1 /= _SCALEFACTOR
            b1 /= _SCALEFACTOR
            a2 /= _SCALEFACTOR
            b2 /= _SCALEFACTOR
        if b2 != 0:
            f = a2 / b2
            af = abs(f)
            fmax = f0 + af if math.isnan(f0) or math.isnan(af) else max(f0, af)  # fmax2
            if abs(f - of) <= _DBL_EPSILON * fmax:
                return f
            of = f
    return f  # sin convergencia: R solo avisa (pgamma.c:455-457)


def _pd_lower_series(lam: float, y: float) -> float:
    """``pd_lower_series`` (``pgamma.c:462-502``).

    FMA (desensamblado de ``_pd_lower_series``): ``sum + term*f`` es ``fmadd``.

    Args:
        lam: Cuantil.
        y: ``alph - 1``.

    Returns:
        ``Σ y(y-1)…(y-n)/lambda^(n+1)``.
    """
    term = 1.0
    total = 0.0
    while y >= 1 and term > total * _DBL_EPSILON:
        term *= y / lam
        total += term
        y -= 1
    if y != math.floor(y):
        f = _pd_lower_cf(y, lam + 1 - y)
        total = fma(term, f, total)  # FMA
    return total


def _ppois_asymp_upper(x: float, lam: float, log_p: bool) -> float:
    """``ppois_asymp(x, lambda, lower_tail = FALSE, log_p)``.

    Fuente: ``R-4.5.2/src/nmath/pgamma.c:556-639`` (integrada y desenrollada en ``_Rf_pgamma_raw``).
    FMA: ``res12 += res1_ig*coefs_a[i]``, ``res12 += res2_ig*coefs_b[i]`` y
    ``elfb += elfb_term*coefs_b[i]`` (``fmadd``; para ``i = 1`` el producto ``1*coefs_b[1]`` es
    exacto), y ``np + f*nd`` (``fmadd``).

    Args:
        x: ``alph - 1``.
        lam: Cuantil.
        log_p: Devolver el logaritmo.

    Returns:
        La probabilidad de la cola superior de Poisson (o su logaritmo).
    """
    dfm = lam - x
    pt_ = -_log1pmx(dfm / x)
    s2pt = math.sqrt(2 * x * pt_)
    if dfm < 0:
        s2pt = -s2pt
    res12 = 0.0
    res1_ig = res1_term = math.sqrt(x)
    res2_ig = res2_term = s2pt
    for i in range(1, 8):
        res12 = fma(res1_ig, _COEFS_A[i - 1], res12)  # FMA
        res12 = fma(res2_ig, _COEFS_B[i - 1], res12)  # FMA
        res1_term *= pt_ / i
        res2_term *= 2 * pt_ / (2 * i + 1)
        res1_ig = res1_ig / x + res1_term
        res2_ig = res2_ig / x + res2_term
    elfb = x
    elfb_term = 1.0
    for i in range(1, 8):
        elfb = fma(elfb_term, _COEFS_B[i - 1], elfb)  # FMA
        elfb_term /= x
    elfb = -elfb  # lower_tail = FALSE
    f = res12 / elfb
    np_ = _pnorm_lower(s2pt, log_p)  # pnorm(s2pt, 0, 1, !lower_tail = TRUE, log_p)
    if log_p:
        n_d_over_p = _dpnorm(s2pt, True, np_)
        return np_ + math.log1p(f * n_d_over_p)
    return fma(f, _dnorm(s2pt), np_)  # FMA


def pgamma_raw(x: float, alph: float, log_p: bool) -> float:
    """``pgamma_raw(x, alph, lower_tail = TRUE, log_p)``.

    Fuente: ``R-4.5.2/src/nmath/pgamma.c:642-718``. FMA (desensamblado de ``_Rf_pgamma_raw``):
    ``1 - d*sum`` (``fmsub``) en la rama de ``x`` grande, más las de las funciones integradas.

    Args:
        x: Cuantil (escala 1).
        alph: Forma ``> 0``.
        log_p: Devolver el logaritmo.

    Returns:
        ``P[X <= x]`` (o su logaritmo).
    """
    if x <= 0:
        return -_INF if log_p else 0.0
    if x >= _INF:
        return 0.0 if log_p else 1.0
    if x < 1:
        res = _pgamma_smallx(x, alph, log_p)
    elif x <= alph - 1 and x < 0.8 * (alph + 50):
        total = _pd_upper_series(x, alph, log_p)
        d = _dpois_wrap(alph, x, log_p)
        res = total + d if log_p else total * d
    elif alph - 1 < x and alph < 0.8 * (x + 50):
        d = _dpois_wrap(alph, x, log_p)
        if alph < 1:
            if x * _DBL_EPSILON > 1 - alph:
                total = 0.0 if log_p else 1.0
            else:
                f = _pd_lower_cf(alph, x - (alph - 1)) * x / alph
                total = math.log(f) if log_p else f
        else:
            total = _pd_lower_series(x, alph - 1)
            total = math.log1p(total) if log_p else 1 + total
        res = _r_log1_exp(d + total) if log_p else fma(-d, total, 1.0)  # FMA
    else:
        res = _ppois_asymp_upper(alph - 1, x, log_p)
    if not log_p and res < _DBL_MIN / _DBL_EPSILON:
        return math.exp(pgamma_raw(x, alph, True))
    return res


def pgamma(x: float, alph: float, scale: float = 1.0, log_p: bool = False) -> float:
    """``pgamma(x, shape = alph, scale, lower.tail = TRUE, log.p)`` de R.

    Fuente: ``R-4.5.2/src/nmath/pgamma.c:721-737`` (sin FMA en ``_Rf_pgamma``).

    Args:
        x: Cuantil.
        alph: Forma.
        scale: Escala.
        log_p: Devolver el logaritmo.

    Returns:
        La función de distribución gamma (o su logaritmo).
    """
    if math.isnan(x) or math.isnan(alph) or math.isnan(scale):
        return x + alph + scale
    if alph < 0.0 or scale <= 0.0:
        return math.nan
    x /= scale
    if math.isnan(x):
        return x
    if alph == 0.0:
        if x <= 0:
            return -_INF if log_p else 0.0
        return 0.0 if log_p else 1.0
    return pgamma_raw(x, alph, log_p)


# --------------------------------------------------------------------------------------------------
# qgamma, qchisq
# --------------------------------------------------------------------------------------------------


def _qchisq_appr(p: float, nu: float, g: float, tol: float) -> float:
    """``qchisq_appr(p, nu, g, lower_tail = TRUE, log_p = FALSE, tol)``.

    Fuente: ``R-4.5.2/src/nmath/qgamma.c:49-114``. FMA (desensamblado de ``_Rf_qchisq_appr``):
    ``x*sqrt(p1) + 1`` y ``2.2*nu + 6`` (``fmadd``), ``R_DT_Clog(p) - c*log(0.5*ch)`` (``fmsub``),
    ``Clog + g + c*M_LN2`` y todo el bucle de ``nu <= 0.32`` (``fmadd``).

    Args:
        p: Probabilidad.
        nu: Grados de libertad.
        g: ``lgamma(nu/2)``.
        tol: Tolerancia relativa (``EPS1``).

    Returns:
        La aproximación inicial ``ch``.
    """
    if math.isnan(p) or math.isnan(nu):
        return p + nu
    if p < 0 or p > 1 or nu <= 0:
        return math.nan
    alpha = 0.5 * nu
    c = alpha - 1
    p1 = math.log(p)  # R_DT_log(p)
    if nu < (-1.24) * p1:
        lgam1pa = _lgamma1p(alpha) if alpha < 0.5 else math.log(alpha) + g
        return math.exp((lgam1pa + p1) / alpha + _M_LN2)
    if nu > 0.32:
        x = float(r_qnorm(np.array([p]))[0])
        p1 = 2.0 / (9 * nu)
        ch = nu * math.pow(fma(x, math.sqrt(p1), 1.0) - p1, 3)  # FMA
        if ch > fma(nu, 2.2, 6.0):  # FMA
            ch = -2 * (fma(-c, math.log(0.5 * ch), math.log1p(-p)) + g)  # FMA
        return ch
    ch = 0.4
    a = fma(c, _M_LN2, math.log1p(-p) + g)  # FMA
    while True:
        q = ch
        p1 = 1.0 / fma(ch, 4.67 + ch, 1.0)  # FMA
        p2 = ch * fma(ch, 6.66 + ch, 6.73)  # FMA
        t = fma(fma(ch, 2.0, 4.67), p1, -0.5) - fma(ch, fma(ch, 3.0, 13.32), 6.73) / p2  # FMA
        ch -= fma(-(math.exp(fma(ch, 0.5, a)) * p2), p1, 1.0) / t  # FMA
        if not abs(q - ch) > tol * abs(ch):
            return ch


_I420 = 1.0 / 420.0
_I2520 = 1.0 / 2520.0
_I5040 = 1.0 / 5040


def _qgamma_phase2(p_: float, alpha: float, g: float, ch: float) -> tuple[float, int | None]:
    """Fase II de ``qgamma`` (AS 91, serie de Taylor de 7 términos).

    Fuente: ``R-4.5.2/src/nmath/qgamma.c:194-228``. FMA (desensamblado de ``_Rf_qgamma``): ``s6``,
    ``alpha*M_LN2 + g``, ``… - c*log(ch)``, ``0.5*t - b*c``, los polinomios ``s1``…``s5`` y la
    corrección ``ch + t*(1 + 0.5*t*s1 - b*c*(s1 - b*(…)))`` (todas ``fmadd``).

    Args:
        p_: Probabilidad de la cola inferior.
        alpha: Forma.
        g: ``lgamma(alpha)``.
        ch: Aproximación inicial.

    Returns:
        ``(ch, max_it_Newton)``: ``None`` si la iteración no cambia ``max_it_Newton``; ``27`` si
        ``p2`` no es finito o ``ch <= 0`` (``:207-211``).
    """
    c = alpha - 1
    s6 = fma(c, fma(c, 127.0, 346.0), 120.0) * _I5040  # FMA
    base = fma(alpha, _M_LN2, g)  # FMA
    ch0 = ch
    for _ in range(1000):
        q = ch
        p1 = 0.5 * ch
        p2 = p_ - pgamma_raw(p1, alpha, False)
        if not math.isfinite(p2) or ch <= 0:
            return ch0, 27
        t = p2 * math.exp(fma(-c, math.log(ch), base + p1))  # FMA
        b = t / ch
        bc = b * c
        a = fma(t, 0.5, -bc)  # FMA
        s1 = fma(a, fma(a, fma(a, fma(a, fma(a, 60.0, 70.0), 84.0), 105.0), 140.0), 210.0) * _I420
        s2 = fma(a, fma(a, fma(a, fma(a, 1278.0, 1141.0), 966.0), 735.0), 420.0) * _I2520
        s3 = fma(a, fma(a, fma(a, 932.0, 707.0), 462.0), 210.0) * _I2520
        s4 = fma(c, fma(a, fma(a, 1740.0, 889.0), 294.0), fma(a, fma(a, 1182.0, 672.0), 252.0))
        s4 *= _I5040
        s5 = fma(c, fma(a, 606.0, 1175.0), fma(a, 2264.0, 84.0)) * _I2520
        nb = -b
        inner = fma(nb, s6, s5)
        inner = fma(nb, inner, s4)
        inner = fma(nb, inner, s3)
        inner = fma(nb, inner, s2)
        inner = fma(nb, inner, s1)
        ch = fma(t, fma(-bc, inner, fma(0.5 * t, s1, 1.0)), ch)  # FMA
        if abs(q - ch) < 5e-7 * ch:
            return ch, None
        if abs(q - ch) > 0.1 * ch:
            ch = 0.9 * q if ch < q else 1.1 * q
    return ch, None


def qgamma(p: float, alpha: float, scale: float) -> float:
    """``qgamma(p, shape = alpha, scale, lower.tail = TRUE, log.p = FALSE)`` de R.

    Fuente: ``R-4.5.2/src/nmath/qgamma.c:116-313``: fase I (``qchisq_appr``), fase II (AS 91,
    :func:`_qgamma_phase2`) y pasos de Newton finales en escala logarítmica (``:238-312``, con
    ``pgamma``/``dgamma`` en ``log_p = TRUE``). FMA: ver :func:`_qgamma_phase2` (el bloque ``END``
    no tiene contracciones).

    Args:
        p: Probabilidad.
        alpha: Forma.
        scale: Escala.

    Returns:
        El cuantil.
    """
    if math.isnan(p) or math.isnan(alpha) or math.isnan(scale):
        return p + alpha + scale
    if p < 0 or p > 1:
        return math.nan
    if p == 0:
        return 0.0
    if p == 1:
        return _INF
    if alpha < 0 or scale <= 0:
        return math.nan
    if alpha == 0:
        return 0.0
    max_it_newton = 7 if alpha < 1e-10 else 1
    p_ = p  # R_DT_qIv(p)
    g = lgammafn(alpha)
    ch = _qchisq_appr(p, 2 * alpha, g, 1e-2)
    if not math.isfinite(ch):
        return 0.5 * scale * ch
    if ch < 5e-7 or p_ > 1 - 1e-14 or p_ < 1e-100:
        max_it_newton = 20
    else:
        ch, new_max = _qgamma_phase2(p_, alpha, g, ch)
        if new_max is not None:
            max_it_newton = new_max
    # END (qgamma.c:248-312), siempre con log_p = TRUE.
    x = 0.5 * scale * ch
    lp = math.log(p)
    if x == 0:
        x = _DBL_MIN
        p_ = pgamma(x, alpha, scale, True)
        if p_ > lp * (1.0 + 1e-7):
            return 0.0
    else:
        p_ = pgamma(x, alpha, scale, True)
    if p_ == -_INF:
        return 0.0
    for i in range(1, max_it_newton + 1):
        p1 = p_ - lp
        if abs(p1) < abs(1e-15 * lp):
            break
        g = dgamma_log(x, alpha, scale)
        if g == -_INF:
            break
        t = x - p1 * math.exp(p_ - g)
        p_ = pgamma(t, alpha, scale, True)
        if abs(p_ - lp) > abs(p1) or (i > 1 and abs(p_ - lp) == abs(p1)):
            break
        x = t
    return x


def qchisq(p: float, df: float) -> float:
    """``qchisq(p, df, lower.tail = TRUE, log.p = FALSE)`` de R.

    Fuente: ``R-4.5.2/src/nmath/qchisq.c:28-31``: ``qgamma(p, 0.5*df, 2.0, …)``.

    Args:
        p: Probabilidad.
        df: Grados de libertad.

    Returns:
        El cuantil de la ji cuadrado.
    """
    return qgamma(p, 0.5 * df, 2.0)
