"""Piezas comunes a todas las cartas y estimadores, sin lógica estadística de ningún método.

ADR 0004, punto 4: tipos, errores, el contrato ``ControlChart`` y el reparto de tareas
(``TaskMapper``). Ningún módulo de aquí importa una carta ni un estimador.
"""

from voracious.domain.common.chart import ControlChart
from voracious.domain.common.errors import (
    DomainError,
    EstimationError,
    InvalidInputError,
    MethodDecisionPendingError,
)
from voracious.domain.common.parallel import SerialTaskMapper, TaskMapper
from voracious.domain.common.types import BoolVector, FloatMatrix, FloatVector, as_matrix

__all__ = [
    "BoolVector",
    "ControlChart",
    "DomainError",
    "EstimationError",
    "FloatMatrix",
    "FloatVector",
    "InvalidInputError",
    "MethodDecisionPendingError",
    "SerialTaskMapper",
    "TaskMapper",
    "as_matrix",
]
