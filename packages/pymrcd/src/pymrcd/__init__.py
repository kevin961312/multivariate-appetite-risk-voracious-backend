"""pymrcd: port a Python de ``rrcov::CovMrcd`` (MRCD, Boudt et al. 2020).

Referencia fijada: ``rrcov`` 1.7-7 oficial de CRAN. Runtime limitado a ``numpy`` y ``scipy``;
no depende de ``voracious``. API pública: ``cov_mrcd`` (``rrcov-1.7-7/R/CovMrcd.R:1-82``).
"""

from pymrcd._errors import RError
from pymrcd.mrcd import MrcdResult, cov_mrcd

__all__ = ["MrcdResult", "RError", "cov_mrcd"]

__version__ = "0.1.0"
