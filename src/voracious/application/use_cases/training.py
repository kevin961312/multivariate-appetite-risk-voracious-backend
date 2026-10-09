"""Fase I: ``GetModel`` (consulta) e ``initial_version`` (versión 0 de un modelo ensamblado).

El modelo se ensambla a partir de los pasos encadenables (``steps.py``, vuelta 3.3); al terminar
bien, ``RunModelAssemblyJob`` añade la **versión 0**, vigente desde el origen (ADR 0008, D3): la
carta del portafolio es el modelo y sus versiones cuelgan de él (D1).
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from voracious.application.charts import ChartRegistry, as_versioned_model, resolve_chart
from voracious.application.lifecycle import base_content_hash, exclusion_reason, frozen_base
from voracious.application.ports import (
    ModelRepository,
)
from voracious.application.records import (
    BaseRowRef,
    BaseRowSource,
    Exclusion,
    ModelRecord,
    ModelVersion,
    VersionStatus,
)
from voracious.application.use_cases.common import get_model
from voracious.domain.common import RecalibrationDecision

__all__ = ["INITIAL_JUSTIFICATION", "GetModel", "initial_version"]

INITIAL_JUSTIFICATION = "initial_fit"
"""Justificación de la versión 0: ajuste de Fase I sobre el histórico."""


@dataclass(frozen=True)
class GetModel:
    """Consulta un modelo del tenant.

    Attributes:
        charts: Cartas registradas.
        models: Repositorio de modelos.
    """

    charts: ChartRegistry
    models: ModelRepository

    def execute(self, tenant_id: str, chart_id: str, model_id: str) -> ModelRecord:
        """Devuelve el modelo.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            El registro del modelo.

        Raises:
            UnknownChartError: Si la carta no existe.
            ModelNotFoundError: Si no existe para ese tenant y esa carta.
        """
        resolve_chart(self.charts, chart_id)
        return get_model(self.models, tenant_id, chart_id, model_id)


def initial_version(record: ModelRecord, model: object, now: datetime) -> ModelVersion:
    """Versión 0 de un modelo recién ajustado: vigente desde el origen.

    La base son las filas del histórico marcadas en ``base_mask``; las excluidas por la
    exclusión humana quedan en ``exclusions``.

    Args:
        record: Modelo (con su histórico).
        model: Modelo de la carta devuelto por ``fit_phase1``.
        now: Instante de creación y aprobación (UTC).

    Returns:
        La versión 0, ``active``.

    Raises:
        TypeError: Si el modelo no cumple ``VersionedModel`` o su máscara no tiene la longitud
            del histórico.
    """
    view = as_versioned_model(model)
    mask = np.asarray(view.base_mask, dtype=np.bool_)
    n_rows = record.training_data.shape[0]
    if mask.shape != (n_rows,) or len(view.row_disposition) != n_rows:
        msg = "la máscara de la base no tiene la longitud del histórico"
        raise TypeError(msg)
    base = np.ascontiguousarray(record.training_data[mask])
    refs = tuple(BaseRowRef(BaseRowSource.TRAINING, str(i)) for i in np.flatnonzero(mask))
    exclusions = tuple(
        Exclusion(ref=BaseRowRef(BaseRowSource.TRAINING, str(i)), reason=reason)
        for i, disposition in enumerate(view.row_disposition)
        if (reason := exclusion_reason(disposition)) is not None
    )
    return ModelVersion(
        tenant_id=record.tenant_id,
        chart_id=record.chart_id,
        model_id=record.model_id,
        number=0,
        status=VersionStatus.ACTIVE,
        model=model,
        base_data=frozen_base(base),
        base_hash=base_content_hash(base),
        base_refs=refs,
        exclusions=exclusions,
        decision=RecalibrationDecision.INITIAL,
        justification=INITIAL_JUSTIFICATION,
        created_at=now,
        effective_from=None,
        approved_at=now,
    )
