"""Casos de uso del ciclo de vida de una carta, comunes a todas las cartas.

Fase I (entrenar), Fase II (monitorear y registrar observaciones), versiones, anotaciones,
eventos estructurales, recalibración y estado de la carta (ADR 0005, ADR 0008).
"""

from voracious.application.use_cases.common import INTERNAL_ERROR
from voracious.application.use_cases.monitoring import (
    GetMonitoring,
    MonitorObservations,
    RunMonitoringJob,
)
from voracious.application.use_cases.observations import (
    AnnotatedObservation,
    AnnotateSignal,
    ListObservations,
    RegisterStructuralEvent,
)
from voracious.application.use_cases.recalibration import (
    GetRecalibration,
    RequestRecalibration,
    RunRecalibrationJob,
)
from voracious.application.use_cases.training import GetModel, RunTrainingJob, TrainModel
from voracious.application.use_cases.versions import (
    ApproveVersion,
    GetChartStatus,
    GetVersion,
    ListVersions,
    RejectVersion,
)

__all__ = [
    "INTERNAL_ERROR",
    "AnnotateSignal",
    "AnnotatedObservation",
    "ApproveVersion",
    "GetChartStatus",
    "GetModel",
    "GetMonitoring",
    "GetRecalibration",
    "GetVersion",
    "ListObservations",
    "ListVersions",
    "MonitorObservations",
    "RegisterStructuralEvent",
    "RejectVersion",
    "RequestRecalibration",
    "RunMonitoringJob",
    "RunRecalibrationJob",
    "RunTrainingJob",
    "TrainModel",
]
