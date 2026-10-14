"""Extensión de la base de una recalibración por pasos (``POST …/recalibrations/{id}/extension``).

Sin comparación de bases (decisión del dueño, 2026-10-14): la carta T² ya es la prueba de
hipótesis sobre la media, así que una recalibración **amplía** la base vigente por defecto
(``EXTEND``) y solo la reemplaza ante un evento estructural o una petición explícita
(``force_replace``). La extensión es el paso síncrono que construye el dataset
``recalibration_extension`` = ``vstack(base vigente, filas nuevas conservadas)``, raíz de la
operación ``EXTENSION`` (hueco ``(0, 0)``): el mismo ``vstack`` que hace
``ControlChart.recalibrate``, así que encadenar extensión → ajuste → límites → versión da el mismo
modelo en bits.

Las filas nuevas conservadas son el dataset de candidatas de la sesión (si ninguna candidata tiene
anotación con causa asignable) o la salida de su exclusión humana. El dataset se crea primero y
después se fija en la sesión con comparar-y-cambiar (``RecalibrationRepository.set_extension``):
repetir la petición con las mismas filas devuelve la misma extensión; con otras, se rechaza.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from voracious.application.charts import ChartRegistry, resolve_chart
from voracious.application.errors import (
    RecalibrationMismatchError,
    RecalibrationNotInProgressError,
)
from voracious.application.lifecycle import base_content_hash, frozen_base
from voracious.application.ports import (
    Clock,
    DatasetStorage,
    IdGenerator,
    ModelVersionRepository,
    RecalibrationRepository,
)
from voracious.application.recalibration_steps import (
    RecalibrationStepsRegistry,
    resolve_recalibration_steps,
)
from voracious.application.records import (
    DatasetRecord,
    DatasetSource,
    ModelVersion,
    RecalibrationRecord,
)
from voracious.application.use_cases.common import get_version
from voracious.application.use_cases.recalibration_chain import get_recalibration, open_session
from voracious.application.use_cases.steps import (
    RecalibrationLinks,
    dataset_chain,
    get_dataset,
)
from voracious.domain.common import InvalidInputError

__all__ = ["RequestRecalibrationExtension"]


def _built(record: RecalibrationRecord, dataset_id: str) -> str | None:
    """Extensión ya construida de la sesión, si es la de ``dataset_id``.

    Args:
        record: Recalibración.
        dataset_id: Filas nuevas conservadas pedidas.

    Returns:
        El id de la extensión, o ``None`` si aún no se construyó.

    Raises:
        InvalidInputError: Si ya se construyó con otras filas (``extension_already_built``).
    """
    if record.extension_dataset_id is None:
        return None
    if record.kept_dataset_id != dataset_id:
        raise InvalidInputError(
            "la extensión de esta recalibración ya se construyó con otras filas",
            details={
                "recalibration_id": record.recalibration_id,
                "reason": "extension_already_built",
                "dataset_id": record.kept_dataset_id,
                "extension_dataset_id": record.extension_dataset_id,
            },
        )
    return record.extension_dataset_id


@dataclass(frozen=True)
class RequestRecalibrationExtension:
    """Construye (síncrono) el dataset de extensión de una recalibración que amplía la base.

    Attributes:
        charts: Cartas registradas.
        recalibration_steps: Pasos de la recalibración por carta.
        recalibrations: Repositorio de recalibraciones.
        versions: Repositorio de versiones (la base vigente).
        datasets: Almacenamiento (recibe el dataset de extensión).
        links: Enlaces con la recalibración (exclusión humana de las candidatas).
        ids: Identificadores.
        clock: Reloj.
    """

    charts: ChartRegistry
    recalibration_steps: RecalibrationStepsRegistry
    recalibrations: RecalibrationRepository
    versions: ModelVersionRepository
    datasets: DatasetStorage
    links: RecalibrationLinks
    ids: IdGenerator
    clock: Clock

    def execute(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        recalibration_id: str,
        *,
        dataset_id: str,
        extension_id: str | None = None,
    ) -> str:
        """Construye la extensión y la fija en la sesión; idempotente con el mismo dataset.

        Orden: recalibración en curso; sin reemplazo pedido; ``dataset_id`` con raíz
        ``recalibration_candidates`` de esa recalibración, y es el propio dataset de candidatas
        (sin anotaciones con causa asignable) o la salida de su exclusión humana; si ya hay
        extensión, la misma (mismo ``dataset_id``) o error.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            recalibration_id: Recalibración.
            dataset_id: Filas nuevas conservadas (candidatas o salida de su exclusión humana).
            extension_id: Identificador ya reservado para el dataset (tubería).

        Returns:
            El id del dataset ``recalibration_extension``.

        Raises:
            UnknownChartError: Si la carta no existe o no expone pasos de recalibración.
            RecalibrationNotFoundError: Si la recalibración no existe para ese modelo.
            RecalibrationNotInProgressError: Si ya no admite pasos.
            InvalidInputError: Reemplazo pedido (``forced_replace_has_no_extension``), candidatas
                con causa asignable sin excluir (``human_exclusion_required``) o extensión ya
                construida con otras filas (``extension_already_built``).
            DatasetNotFoundError: Si el dataset no existe.
            RecalibrationMismatchError: Si el dataset no son las filas nuevas conservadas de esa
                recalibración.
        """
        resolve_chart(self.charts, chart_id)
        resolve_recalibration_steps(self.recalibration_steps, chart_id)
        session = open_session(
            get_recalibration(self.recalibrations, tenant_id, chart_id, model_id, recalibration_id)
        )
        if session.force_replace:
            raise InvalidInputError(
                "un reemplazo (evento estructural o petición explícita) no amplía la base",
                details={
                    "recalibration_id": recalibration_id,
                    "reason": "forced_replace_has_no_extension",
                },
            )
        kept = self._kept(session, dataset_id)
        built = _built(session, dataset_id)
        if built is not None:
            return built
        active = get_version(
            self.versions, tenant_id, chart_id, model_id, session.base_version_number
        )
        extension = self._dataset(
            session, active, kept, extension_id if extension_id is not None else self.ids.new_id()
        )
        self.datasets.add(extension)
        updated = self.recalibrations.set_extension(
            tenant_id,
            chart_id,
            model_id,
            recalibration_id,
            kept_dataset_id=dataset_id,
            extension_dataset_id=extension.dataset_id,
        )
        if updated is None:
            # Otra petición concurrente fijó la extensión, o la sesión se cerró entretanto.
            current = get_recalibration(
                self.recalibrations, tenant_id, chart_id, model_id, recalibration_id
            )
            built = _built(current, dataset_id)
            if built is not None:
                return built
            open_session(current)
            raise RecalibrationNotInProgressError(
                f"la recalibración '{recalibration_id}' no admite más pasos",
                details={"recalibration_id": recalibration_id, "reason": "concurrent_request"},
            )
        return extension.dataset_id

    def _kept(self, session: RecalibrationRecord, dataset_id: str) -> DatasetRecord:
        """Comprueba que ``dataset_id`` sean las filas nuevas conservadas de la sesión.

        Args:
            session: Recalibración en curso.
            dataset_id: Dataset pedido.

        Returns:
            El dataset.

        Raises:
            DatasetNotFoundError: Si no existe.
            RecalibrationMismatchError: Si no es de la sesión o no son sus filas conservadas.
            InvalidInputError: Si son las candidatas y alguna tiene causa asignable.
        """
        dataset = get_dataset(self.datasets, session.tenant_id, dataset_id)
        chain = dataset_chain(self.datasets, dataset)
        root = chain[0]
        of_session = (
            root.source is DatasetSource.RECALIBRATION_CANDIDATES
            and root.origin_ref == session.recalibration_id
        )
        kept_rows = len(chain) == 1 or (
            len(chain) == 2 and chain[1].source is DatasetSource.EXCLUSION_OUTPUT
        )
        if not (of_session and kept_rows):
            raise RecalibrationMismatchError(
                "el dataset no son las filas nuevas conservadas de esa recalibración",
                details={
                    "dataset_id": dataset_id,
                    "recalibration_id": session.recalibration_id,
                    "reason": "not_kept_rows_of_recalibration",
                },
            )
        if len(chain) == 1 and self.links.human_causes(session):
            raise InvalidInputError(
                "hay candidatas con causa asignable: primero la exclusión humana",
                details={"dataset_id": dataset_id, "reason": "human_exclusion_required"},
            )
        return dataset

    def _dataset(
        self,
        session: RecalibrationRecord,
        active: ModelVersion,
        kept: DatasetRecord,
        extension_id: str,
    ) -> DatasetRecord:
        """Dataset ``recalibration_extension`` = ``vstack(base, nuevas conservadas)``.

        Hereda los nombres de variables de las conservadas y, solo si se conocen **todas**, las
        fechas de la base (``base_refs``) seguidas de las de las conservadas; si falta alguna, el
        dataset va sin fechas (las de cada fila siguen en los ``base_refs`` de la versión).

        Args:
            session: Recalibración.
            active: Versión base.
            kept: Filas nuevas conservadas.
            extension_id: Identificador del dataset.

        Returns:
            El dataset (aún sin guardar).
        """
        stacked = np.vstack([active.base_data, kept.data])
        data = frozen_base(np.ascontiguousarray(stacked, dtype=np.float64))
        base_dates = tuple(r.observed_at for r in active.base_refs)
        # ``DatasetRecord.observed_at`` es todo o nada (una fecha por fila, o ``None``): si alguna
        # fila de la base no tiene fecha (histórico sin fechas), el dataset de extensión va sin
        # fechas. No se pierde trazabilidad: la versión propuesta toma las fechas por fila de
        # ``active.base_refs`` (``new_base``), no de este dataset.
        dates: tuple[datetime, ...] | None = None
        if kept.observed_at is not None and all(d is not None for d in base_dates):
            dates = tuple(d for d in base_dates if d is not None) + kept.observed_at
        return DatasetRecord(
            tenant_id=session.tenant_id,
            dataset_id=extension_id,
            data=data,
            content_hash=base_content_hash(data),
            source=DatasetSource.RECALIBRATION_EXTENSION,
            created_at=self.clock.now(),
            origin_ref=session.recalibration_id,
            variables=kept.variables,
            observed_at=dates,
        )
