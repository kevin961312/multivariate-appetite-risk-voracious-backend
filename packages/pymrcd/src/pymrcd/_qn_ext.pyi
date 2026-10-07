"""Tipos de la extensión C ``pymrcd._qn_ext`` (``src/pymrcd/_ext/qnmodule.c``).

Especificación ``docs/metodos/mrcd-especificacion.md`` §3.12.9. Los búferes se reciben con el
protocolo de búfer de CPython (sin cabeceras de numpy).
"""

from collections.abc import Buffer

def qn0_columns(x: Buffer, out: Buffer, k: int, n_threads: int, poison: bool = ..., /) -> None:
    """``qn0`` por columna (``qn_sn.c:118-296``); escribe en ``out`` (``m``, float64)."""

def ogk_u(
    y: Buffer,
    out: Buffer,
    constant: float,
    factor: float,
    small_n: bool,
    n_threads: int,
    poison: bool = ...,
    /,
) -> None:
    """Triángulos de ``U`` de ``ogkscatter`` (``detmrcd.R:87-97``) en ``out`` (``p x p``)."""

def default_threads() -> int:
    """Hilos por defecto (``PYMRCD_NUM_THREADS`` o CPU visibles por afinidad)."""

def build_info() -> dict[str, str | int | bool]:
    """Salvaguardas de compilación y del entorno de coma flotante (spec §3.12.9 b)."""

def _r_qsort(v: Buffer, /) -> None:
    """``R_qsort(v, 1, n)`` en sitio (``qsort.c:164-167``)."""

def _rpsort(x: Buffer, k: int, /) -> None:
    """``rPsort(x, n, k)`` en sitio (``sort.c:724-727``)."""

def _whimed_i(a: Buffer, w: Buffer, /) -> float:
    """``whimed_i`` (``wgt_himed_templ.h:27-122``); modifica ``a`` y ``w`` en sitio."""

def _k_l(n: int, /) -> int:
    """``k_L`` de ``qn_sn.c:154``."""
