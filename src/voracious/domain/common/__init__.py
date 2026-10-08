"""Piezas comunes a todas las cartas y estimadores, sin lógica estadística de ningún método.

ADR 0004, punto 4: tipos, errores, el contrato ``ControlChart``, los contratos de un estimador de
ubicación y dispersión, el vocabulario de la recalibración, el linaje de una ronda
(``StageLineage``), la codificación de arreglos como datos y el reparto de tareas (``TaskMapper``).
Ningún módulo de aquí importa una carta ni un estimador.
"""

from voracious.domain.common.chart import ControlChart
from voracious.domain.common.errors import (
    DomainError,
    EstimationError,
    InvalidInputError,
    MethodDecisionPendingError,
)
from voracious.domain.common.estimation import LocationScatterEstimator, LocationScatterFit
from voracious.domain.common.lineage import StageKind, StageLineage
from voracious.domain.common.parallel import SerialTaskMapper, TaskMapper
from voracious.domain.common.recalibration import (
    RecalibrationDecision,
    RecalibrationOutcome,
    RowDisposition,
)
from voracious.domain.common.types import BoolVector, FloatMatrix, FloatVector, as_matrix

__all__ = [
    "BoolVector",
    "ControlChart",
    "DomainError",
    "EstimationError",
    "FloatMatrix",
    "FloatVector",
    "InvalidInputError",
    "LocationScatterEstimator",
    "LocationScatterFit",
    "MethodDecisionPendingError",
    "RecalibrationDecision",
    "RecalibrationOutcome",
    "RowDisposition",
    "SerialTaskMapper",
    "StageKind",
    "StageLineage",
    "TaskMapper",
    "as_matrix",
]
