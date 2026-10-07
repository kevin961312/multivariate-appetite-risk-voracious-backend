"""Alias de tipos compartidos por los módulos de pymrcd."""

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
"""Arreglo de ``float64``."""

IntArray = npt.NDArray[np.int64]
"""Arreglo de enteros ``int64``."""

__all__ = ["FloatArray", "IntArray"]
