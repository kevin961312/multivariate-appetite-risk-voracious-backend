"""Estimador MRCD: adaptador sobre ``pymrcd``, fiel a ``rrcov::CovMrcd`` 1.7-7 (ADR 0002, 0006).

Documento de fidelidad: ``docs/metodos/mrcd.md``. Este paquete no conoce ninguna carta.
"""

from voracious.domain.estimators.mrcd.estimator import MRCD_FIT_FAILED, PYMRCD_VERSION, fit_mrcd
from voracious.domain.estimators.mrcd.params import MRCDParams, MRCDTarget
from voracious.domain.estimators.mrcd.result import IndexVector, MRCDFit

__all__ = [
    "MRCD_FIT_FAILED",
    "PYMRCD_VERSION",
    "IndexVector",
    "MRCDFit",
    "MRCDParams",
    "MRCDTarget",
    "fit_mrcd",
]
