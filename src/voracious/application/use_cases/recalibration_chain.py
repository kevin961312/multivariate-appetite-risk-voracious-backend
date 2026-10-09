"""Enlaces entre los pasos encadenables y una recalibración por pasos (vuelta 3.4 del Paso 3).

La recalibración es la **sesión** de sus pasos: al pedirla se fijan las candidatas (en orden),
los parámetros heredados (Q8) y el dataset ``recalibration_candidates``. Los pasos de la Fase I
(exclusión humana, ajuste y límites) reconocen que un dataset es de una recalibración por su raíz y
le piden aquí lo propio de ella: la sesión en curso, la exclusión humana (de las anotaciones), el
mínimo de filas (``min_observations``) y el cierre ``insufficient`` cuando la exclusión humana deja
menos.

``candidate_outcome`` reconstruye, a partir del linaje del dataset y de su exclusión humana, el
destino de cada candidata y las anotaciones que excluyeron filas, igual que
``ControlChart.recalibrate``.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from voracious.application.errors import (
    RecalibrationNotFoundError,
    RecalibrationNotInProgressError,
)
from voracious.application.ports import (
    Clock,
    ExclusionRepository,
    ModelVersionRepository,
    RecalibrationRepository,
    SignalAnnotationRepository,
)
from voracious.application.recalibration_steps import (
    RecalibrationStepsRegistry,
    resolve_recalibration_steps,
)
from voracious.application.records import (
    AssignableCause,
    DatasetRecord,
    ExclusionRecord,
    JobStatus,
    RecalibrationRecord,
)
from voracious.application.use_cases.common import get_version
from voracious.application.use_cases.steps import RecalibrationLinks, get_exclusion
from voracious.domain.common import RecalibrationDecision, RowDisposition

__all__ = [
    "CandidateOutcome",
    "RecalibrationChain",
    "candidate_outcome",
    "exclusion_outcome",
    "get_recalibration",
    "open_session",
]


def get_recalibration(
    recalibrations: RecalibrationRepository,
    tenant_id: str,
    chart_id: str,
    model_id: str,
    recalibration_id: str,
) -> RecalibrationRecord:
    """Busca una recalibración o lanza ``RecalibrationNotFoundError``.

    Args:
        recalibrations: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo.
        recalibration_id: Recalibración.

    Returns:
        El registro.

    Raises:
        RecalibrationNotFoundError: Si no existe para esa clave.
    """
    record = recalibrations.get(tenant_id, chart_id, model_id, recalibration_id)
    if record is None:
        raise RecalibrationNotFoundError(
            f"la recalibración '{recalibration_id}' no existe",
            details={"model_id": model_id, "recalibration_id": recalibration_id},
        )
    return record


def open_session(record: RecalibrationRecord) -> RecalibrationRecord:
    """Exige que la recalibración siga admitiendo pasos (``running`` y sin propuesta pedida).

    Args:
        record: Recalibración.

    Returns:
        La misma recalibración.

    Raises:
        RecalibrationNotInProgressError: Si terminó, no ha empezado o ya pidió su propuesta.
    """
    if record.status is not JobStatus.RUNNING or record.proposal is not None:
        raise RecalibrationNotInProgressError(
            f"la recalibración '{record.recalibration_id}' no admite más pasos",
            details={
                "recalibration_id": record.recalibration_id,
                "status": str(record.status),
                "proposal_requested": record.proposal is not None,
            },
        )
    return record


@dataclass(frozen=True)
class CandidateOutcome:
    """Destino de las candidatas según su exclusión humana.

    Attributes:
        dispositions: Destino de cada candidata (``kept`` o excluida), en orden.
        annotation_ids: Fila de candidatas → anotación que la excluyó.
    """

    dispositions: tuple[RowDisposition, ...]
    annotation_ids: dict[int, str]


def exclusion_outcome(exclusion: ExclusionRecord | None, n_candidates: int) -> CandidateOutcome:
    """Destino de las candidatas según una exclusión humana terminada (o ninguna).

    Args:
        exclusion: Exclusión de las candidatas, o ``None`` si no la hubo (se conservan todas).
        n_candidates: Número de candidatas.

    Returns:
        El destino de las candidatas.
    """
    if exclusion is None or exclusion.result is None:
        return CandidateOutcome((RowDisposition.KEPT,) * n_candidates, {})
    annotation_ids = {
        cause.row: cause.annotation_id
        for cause in exclusion.assignable_cause
        if cause.annotation_id is not None
    }
    return CandidateOutcome(tuple(exclusion.result), annotation_ids)


def candidate_outcome(
    exclusions: ExclusionRepository, chart_id: str, chain: Sequence[DatasetRecord]
) -> CandidateOutcome:
    """Destino de cada candidata a partir de la ascendencia del dataset de las filas nuevas.

    Si el dataset deriva de la exclusión humana de las candidatas (``origin_ref``), se aplica su
    resultado; si es el propio dataset de candidatas, se conservan todas.

    Args:
        exclusions: Repositorio de exclusiones.
        chart_id: Carta.
        chain: Ascendencia desde el dataset de candidatas.

    Returns:
        El destino de las candidatas.
    """
    first = chain[0]
    exclusion = None
    if len(chain) > 1 and chain[-1].origin_ref is not None:
        exclusion = get_exclusion(exclusions, first.tenant_id, chart_id, chain[-1].origin_ref)
    return exclusion_outcome(exclusion, first.data.shape[0])


@dataclass(frozen=True)
class RecalibrationChain:
    """Implementa ``RecalibrationLinks`` para los pasos de la Fase I.

    Attributes:
        recalibration_steps: Pasos de la recalibración por carta.
        recalibrations: Repositorio de recalibraciones.
        versions: Repositorio de versiones (la versión base del informe).
        annotations: Anotaciones (exclusión humana).
        clock: Reloj.
    """

    recalibration_steps: RecalibrationStepsRegistry
    recalibrations: RecalibrationRepository
    versions: ModelVersionRepository
    annotations: SignalAnnotationRepository
    clock: Clock

    def session_for(
        self, tenant_id: str, chart_id: str, root: DatasetRecord
    ) -> RecalibrationRecord:
        """Recalibración en curso dueña de un dataset raíz.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            root: Dataset raíz de recalibración.

        Returns:
            La recalibración ``running``.

        Raises:
            RecalibrationNotFoundError: Si no existe para ese tenant y esa carta.
            RecalibrationNotInProgressError: Si ya no admite pasos.
        """
        rid = root.origin_ref or ""
        record = self.recalibrations.find(tenant_id, chart_id, rid)
        if record is None:
            raise RecalibrationNotFoundError(
                f"la recalibración '{rid}' no existe", details={"recalibration_id": rid}
            )
        return open_session(record)

    def human_causes(self, session: RecalibrationRecord) -> tuple[AssignableCause, ...]:
        """Candidatas cuya anotación vigente confirma una causa asignable.

        Args:
            session: Recalibración.

        Returns:
            Filas del dataset de candidatas (con causa y anotación), en orden.
        """
        latest = self.annotations.latest_for(
            session.tenant_id, session.chart_id, session.model_id, list(session.candidate_ids)
        )
        out: list[AssignableCause] = []
        for row, observation_id in enumerate(session.candidate_ids):
            annotation = latest.get(observation_id)
            if annotation is not None and annotation.assignable_cause:
                out.append(AssignableCause(row, annotation.cause, annotation.annotation_id))
        return tuple(out)

    def min_observations(self, session: RecalibrationRecord) -> int:
        """Mínimo de filas nuevas conservadas tras la exclusión humana.

        Args:
            session: Recalibración.

        Returns:
            El mínimo.
        """
        steps = resolve_recalibration_steps(self.recalibration_steps, session.chart_id)
        return steps.min_observations(session.params)

    def close_insufficient(self, session: RecalibrationRecord, exclusion: ExclusionRecord) -> None:
        """Cierra la recalibración ``succeeded / insufficient`` con su informe (sin versión).

        Args:
            session: Recalibración.
            exclusion: Exclusión de las candidatas (con su resultado).
        """
        steps = resolve_recalibration_steps(self.recalibration_steps, session.chart_id)
        key = (session.tenant_id, session.chart_id, session.model_id)
        active = get_version(self.versions, *key, session.base_version_number)
        outcome = exclusion_outcome(exclusion, len(session.candidate_ids))
        report = steps.report(
            active.model,
            decision=RecalibrationDecision.INSUFFICIENT,
            forced=session.force_replace,
            n_base=int(active.base_data.shape[0]),
            new_dispositions=outcome.dispositions,
            recalibration_params=session.params,
            comparison=None,
            model=None,
        )
        current = self.recalibrations.get(*key, session.recalibration_id)
        if current is None or current.status is not JobStatus.RUNNING:
            return
        self.recalibrations.update(
            replace(
                current,
                status=JobStatus.SUCCEEDED,
                finished_at=self.clock.now(),
                outcome=RecalibrationDecision.INSUFFICIENT,
                report=report,
            )
        )


if TYPE_CHECKING:
    # mypy verifica que la clase cumple el protocolo de los pasos de la Fase I.
    def _conforms(chain: RecalibrationChain) -> RecalibrationLinks:
        return chain
