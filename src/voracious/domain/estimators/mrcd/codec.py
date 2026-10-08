"""Codificación de un ajuste MRCD como datos (mejora M1): ida y vuelta exacta en bits.

Cada arreglo del ajuste se guarda con ``encode_array`` (``dtype``, forma y bytes) y cada escalar
como número de Python, así que ``decode_fit(encode_fit(fit))`` reproduce el ajuste bit a bit y las
distancias que se calculen con él son idénticas. Un campo desconocido o ausente es un error.
"""

from typing import Final

from voracious.domain.common.codec import (
    decode_bool_array,
    decode_float_array,
    decode_int_array,
    encode_array,
    read_float,
    read_int,
    read_mapping,
)
from voracious.domain.estimators.mrcd.result import MRCDFit

__all__ = ["decode_fit", "encode_fit"]

_FIT_FIELDS: Final = frozenset(
    {
        "center",
        "cov",
        "icov",
        "rho",
        "cnp2",
        "crit",
        "best",
        "mah",
        "alpha",
        "h",
        "n_obs",
        "ok",
        "i_best",
        "n_csteps",
    }
)


def encode_fit(fit: MRCDFit) -> dict[str, object]:
    """Codifica un ajuste MRCD.

    Args:
        fit: Ajuste.

    Returns:
        Diccionario serializable con los catorce campos del ajuste.
    """
    return {
        "center": encode_array(fit.center),
        "cov": encode_array(fit.cov),
        "icov": encode_array(fit.icov),
        "rho": fit.rho,
        "cnp2": fit.cnp2,
        "crit": fit.crit,
        "best": encode_array(fit.best),
        "mah": encode_array(fit.mah),
        "alpha": fit.alpha,
        "h": fit.h,
        "n_obs": fit.n_obs,
        "ok": encode_array(fit.ok),
        "i_best": encode_array(fit.i_best),
        "n_csteps": encode_array(fit.n_csteps),
    }


def decode_fit(data: object, field: str = "mrcd") -> MRCDFit:
    """Decodifica un ajuste MRCD (inversa de ``encode_fit``).

    Args:
        data: Ajuste codificado.
        field: Nombre del campo, para los mensajes.

    Returns:
        El ajuste, idéntico en bits al codificado.

    Raises:
        InvalidInputError: Campo desconocido, ausente o con un tipo inválido.
    """
    raw = read_mapping(data, field, _FIT_FIELDS)
    return MRCDFit(
        center=decode_float_array(raw["center"], f"{field}.center"),
        cov=decode_float_array(raw["cov"], f"{field}.cov"),
        icov=decode_float_array(raw["icov"], f"{field}.icov"),
        rho=read_float(raw["rho"], f"{field}.rho"),
        cnp2=read_float(raw["cnp2"], f"{field}.cnp2"),
        crit=read_float(raw["crit"], f"{field}.crit"),
        best=decode_int_array(raw["best"], f"{field}.best"),
        mah=decode_float_array(raw["mah"], f"{field}.mah"),
        alpha=read_float(raw["alpha"], f"{field}.alpha"),
        h=read_int(raw["h"], f"{field}.h"),
        n_obs=read_int(raw["n_obs"], f"{field}.n_obs"),
        ok=decode_bool_array(raw["ok"], f"{field}.ok"),
        i_best=decode_int_array(raw["i_best"], f"{field}.i_best"),
        n_csteps=decode_int_array(raw["n_csteps"], f"{field}.n_csteps"),
    )
