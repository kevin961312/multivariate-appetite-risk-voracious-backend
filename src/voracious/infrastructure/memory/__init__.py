"""Adaptadores en memoria de los repositorios (``VORACIOUS_REPOSITORY=memory``).

Seguros entre hilos (un cerrojo por repositorio) y aislados por tenant: toda clave empieza por
``tenant_id``. Los registros pasan por un ``RecordCodec`` (mejora M1): los que llevan modelo o
informe de una carta se guardan codificados como datos (``codec.py``).
"""

from voracious.infrastructure.memory.codec import (
    ComparisonRecordCodec,
    FitRecordCodec,
    LimitsRecordCodec,
    ModelRecordCodec,
    ModelVersionCodec,
    PassthroughCodec,
    RecalibrationRecordCodec,
    RecordCodec,
)
from voracious.infrastructure.memory.jobs import (
    InMemoryComparisonRepository,
    InMemoryModelRepository,
    InMemoryMonitoringRepository,
    InMemoryRecalibrationRepository,
)
from voracious.infrastructure.memory.logs import (
    InMemoryObservationRepository,
    InMemorySignalAnnotationRepository,
    InMemoryStructuralEventRepository,
)
from voracious.infrastructure.memory.steps import (
    InMemoryDatasetStorage,
    InMemoryDepurationRepository,
    InMemoryFitRepository,
    InMemoryLimitsRepository,
    InMemoryPipelineRepository,
)
from voracious.infrastructure.memory.store import KeyedStore
from voracious.infrastructure.memory.versions import InMemoryModelVersionRepository

__all__ = [
    "ComparisonRecordCodec",
    "FitRecordCodec",
    "InMemoryComparisonRepository",
    "InMemoryDatasetStorage",
    "InMemoryDepurationRepository",
    "InMemoryFitRepository",
    "InMemoryLimitsRepository",
    "InMemoryModelRepository",
    "InMemoryModelVersionRepository",
    "InMemoryMonitoringRepository",
    "InMemoryObservationRepository",
    "InMemoryPipelineRepository",
    "InMemoryRecalibrationRepository",
    "InMemorySignalAnnotationRepository",
    "InMemoryStructuralEventRepository",
    "KeyedStore",
    "LimitsRecordCodec",
    "ModelRecordCodec",
    "ModelVersionCodec",
    "PassthroughCodec",
    "RecalibrationRecordCodec",
    "RecordCodec",
]
