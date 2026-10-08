"""Enlaces entre los pasos encadenables y una recalibración por pasos (vuelta 3.4 del Paso 3).

La recalibración es la **sesión** de sus pasos: al pedirla se fijan las candidatas (en orden),
los parámetros heredados (Q8) y el dataset ``recalibration_candidates``. Los pasos de la Fase I
(ajuste, límites y depuración) reconocen que un dataset es de una recalibración por su raíz y le
piden aquí lo propio de ella: la sesión en curso, la exclusión humana (de las anotaciones), los
límites de la depuración (``max_depuration_rounds`` y ``min_observations``) y el cierre
``insufficient`` cuando la depuración se agota.

``candidate_outcome`` reconstruye, a partir del linaje de datasets y depuraciones, el destino de
cada candidata, las anotaciones que excluyeron filas y las rondas, igual que la depuración de
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
    DepurationRepository,
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
    DepurationRecord,
    IndexVector,
    JobStatus,
    RecalibrationRecord,
)
from voracious.application.use_cases.common import get_version
from voracious.application.use_cases.steps import (
    RecalibrationLinks,
    get_depuration,
    root_indices,
)
from voracious.domain.common import RecalibrationDecision, RowDisposition

__all__ = [
    "CandidateOutcome",
    "RecalibrationChain",
    "candidate_outcome",
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
    """Destino de las candidatas según el linaje de la depuración de las filas nuevas.

    Attributes:
        dispositions: Destino de cada candidata (``kept`` o excluida), en orden.
        annotation_ids: Fila de candidatas → anotación que la excluyó (exclusión humana).
        rounds: Rondas de depuración automática que quitaron filas (como ``recalibrate``).
    """

    dispositions: tuple[RowDisposition, ...]
    annotation_ids: dict[int, str]
    rounds: int


def _apply(
    depuration: DepurationRecord,
    rows: IndexVector,
    dispositions: list[RowDisposition],
    annotation_ids: dict[int, str],
) -> bool:
    """Vuelca el resultado de una depuración sobre las candidatas.

    Args:
        depuration: Depuración terminada.
        rows: Índices en las candidatas de las filas de su dataset.
        dispositions: Destinos (se modifican).
        annotation_ids: Anotaciones de las excluidas por una persona (se modifican).

    Returns:
        ``True`` si quitó filas de forma automática.
    """
    removed = False
    for i, disposition in enumerate(depuration.result or ()):
        if disposition is not RowDisposition.KEPT:
            dispositions[int(rows[i])] = disposition
        removed |= disposition is RowDisposition.EXCLUDED_AUTOMATIC
    for cause in depuration.assignable_cause:
        if cause.annotation_id is not None:
            annotation_ids[int(rows[cause.row])] = cause.annotation_id
    return removed


def candidate_outcome(
    depurations: DepurationRepository,
    chart_id: str,
    chain: Sequence[DatasetRecord],
    final: DepurationRecord | None,
) -> CandidateOutcome:
    """Destino de cada candidata a partir de la ascendencia del último dataset depurado.

    Cada dataset derivado de la cadena guarda la depuración que lo creó (``origin_ref``); la
    depuración ``final`` (si se pasa y no creó dataset: agotada o final) se aplica sobre el
    último. Las rondas son las del último dataset más la ronda que agotó la depuración, si la
    agotó una ronda automática (igual que ``depurate`` del dominio).

    Args:
        depurations: Repositorio de depuraciones.
        chart_id: Carta.
        chain: Ascendencia desde el dataset de candidatas.
        final: Depuración que cierra la cadena, o ``None``.

    Returns:
        El destino de las candidatas.
    """
    first = chain[0]
    indices = root_indices(chain)
    dispositions = [RowDisposition.KEPT] * first.data.shape[0]
    annotation_ids: dict[int, str] = {}
    applied: set[str] = set()
    for parent_rows, derived in zip(indices[:-1], chain[1:], strict=True):
        if derived.origin_ref is None:
            continue
        depuration = get_depuration(depurations, first.tenant_id, chart_id, derived.origin_ref)
        _apply(depuration, parent_rows, dispositions, annotation_ids)
        applied.add(depuration.depuration_id)
    rounds = chain[-1].lineage_round
    if final is not None and final.depuration_id not in applied:
        removed = _apply(final, indices[-1], dispositions, annotation_ids)
        rounds += 1 if final.exhausted and removed else 0
    return CandidateOutcome(tuple(dispositions), annotation_ids, rounds)


@dataclass(frozen=True)
class RecalibrationChain:
    """Implementa ``RecalibrationLinks`` para los pasos de la Fase I.

    Attributes:
        recalibration_steps: Pasos de la recalibración por carta.
        recalibrations: Repositorio de recalibraciones.
        versions: Repositorio de versiones (la versión base del informe).
        annotations: Anotaciones (exclusión humana).
        depurations: Repositorio de depuraciones (linaje del informe).
        clock: Reloj.
    """

    recalibration_steps: RecalibrationStepsRegistry
    recalibrations: RecalibrationRepository
    versions: ModelVersionRepository
    annotations: SignalAnnotationRepository
    depurations: DepurationRepository
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

    def bounds(self, session: RecalibrationRecord) -> tuple[int, int]:
        """``(max_rounds, min_rows)`` de la depuración de las filas nuevas.

        Args:
            session: Recalibración.

        Returns:
            Las cotas.
        """
        steps = resolve_recalibration_steps(self.recalibration_steps, session.chart_id)
        return steps.depuration_bounds(session.params)

    def close_insufficient(
        self,
        session: RecalibrationRecord,
        chain: Sequence[DatasetRecord],
        final: DepurationRecord,
    ) -> None:
        """Cierra la recalibración ``succeeded / insufficient`` con su informe (sin versión).

        Args:
            session: Recalibración.
            chain: Ascendencia del dataset depurado.
            final: Depuración agotada (con su resultado).
        """
        steps = resolve_recalibration_steps(self.recalibration_steps, session.chart_id)
        key = (session.tenant_id, session.chart_id, session.model_id)
        active = get_version(self.versions, *key, session.base_version_number)
        outcome = candidate_outcome(self.depurations, session.chart_id, chain, final)
        report = steps.report(
            active.model,
            decision=RecalibrationDecision.INSUFFICIENT,
            forced=session.force_replace,
            n_base=int(active.base_data.shape[0]),
            new_dispositions=outcome.dispositions,
            recalibration_params=session.params,
            depuration_rounds=outcome.rounds,
            depuration_converged=None,
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
