"""Recuperación al arrancar: los trabajos interrumpidos por un reinicio terminan ``failed``.

La cola (``InlineJobQueue``) vive en el proceso: si el proceso se reinicia, lo que estaba
``queued`` o ``running`` no lo va a ejecutar nadie. Con repositorios persistentes (Postgres) esos
registros sobrevivirían para siempre «en curso» y bloquearían, p. ej., una recalibración nueva
(D6). ``RecoverInterruptedJobs`` los cierra ``failed / JOB_INTERRUPTED`` al arrancar, antes de
aceptar tráfico; el cliente los vuelve a pedir.

Excepción: una recalibración **paso a paso** abierta (``stepwise``, ``running``, sin propuesta en
curso) no es un trabajo de la cola, sino una sesión que espera pasos del cliente; se respeta. Si
tenía la propuesta pedida (``queued`` o ``running``), ese trabajo sí se perdió y la sesión se
cierra ``failed``.

Conciliación de versiones. Dos trabajos escriben una versión y después, en otra escritura, cierran
su registro; un reinicio entre ambas deja una versión sin su cierre:

- **Ensamblado de un modelo** (versión 0 ``active`` escrita, modelo aún ``running``): la versión 0
  es el modelo ya ensamblado, así que el modelo se completa ``succeeded`` con el modelo de esa
  versión y su instante. Rechazarla no cabe: ``rejected`` es de propuestas y ``superseded`` de
  versiones sustituidas por otra aprobada (ADR 0008).
- **Propuesta de una recalibración** (versión ``proposed`` escrita, recalibración aún en curso): la
  recalibración se cierra ``failed / JOB_INTERRUPTED`` y su versión ``proposed`` pasa a
  ``rejected`` con la nota ``job_interrupted`` (comparar-y-cambiar del repositorio). Así no queda
  una propuesta huérfana que bloquee recalibraciones nuevas (``PROPOSAL_PENDING``) ni que pueda
  aprobarse sin que su recalibración haya terminado bien.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace

from voracious.application.ports import (
    Clock,
    ComparisonRepository,
    ExclusionRepository,
    FitRepository,
    LimitsRepository,
    ModelRepository,
    ModelVersionRepository,
    MonitoringRepository,
    PipelineRepository,
    RecalibrationRepository,
    VersionDecision,
    VersionStatusChange,
)
from voracious.application.records import (
    ErrorInfo,
    JobStatus,
    ModelRecord,
    RecalibrationMode,
    RecalibrationRecord,
    VersionStatus,
)
from voracious.application.use_cases.common import JOB_INTERRUPTED

__all__ = ["JOB_INTERRUPTED_NOTE", "RecoverInterruptedJobs", "is_open_session"]

_IN_PROGRESS = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})

JOB_INTERRUPTED_NOTE = "job_interrupted"
"""Nota de una versión propuesta rechazada porque su recalibración se interrumpió."""


def _interrupted(status: JobStatus) -> ErrorInfo:
    """Error de un trabajo interrumpido por un reinicio.

    Args:
        status: Estado en que estaba.

    Returns:
        El error ``JOB_INTERRUPTED``.
    """
    return ErrorInfo(
        JOB_INTERRUPTED,
        "el trabajo se interrumpió al reiniciarse el servicio; vuelve a pedirlo",
        {"previous_status": status.value},
    )


def is_open_session(record: RecalibrationRecord) -> bool:
    """Indica si una recalibración es una sesión paso a paso abierta (no un trabajo perdido).

    Args:
        record: Recalibración.

    Returns:
        ``True`` si es ``stepwise``, está ``running`` y no tiene una propuesta en curso.
    """
    return (
        record.mode is RecalibrationMode.STEPWISE
        and record.status is JobStatus.RUNNING
        and (record.proposal is None or record.proposal.status not in _IN_PROGRESS)
    )


@dataclass(frozen=True)
class RecoverInterruptedJobs:
    """Cierra ``failed / JOB_INTERRUPTED`` los trabajos que un reinicio dejó en curso.

    Se ejecuta una vez al arrancar el proceso (``lifespan`` de la API), con **un** worker de
    uvicorn: no hay otro proceso con trabajos en curso sobre los mismos repositorios.

    Attributes:
        fits: Ajustes.
        limits: Límites.
        exclusions: Exclusiones.
        pipelines: Tuberías.
        models: Modelos.
        monitorings: Puntuaciones.
        recalibrations: Recalibraciones.
        comparisons: Comparaciones.
        versions: Versiones (conciliación de la versión 0 y de las propuestas huérfanas).
        clock: Reloj.
    """

    fits: FitRepository
    limits: LimitsRepository
    exclusions: ExclusionRepository
    pipelines: PipelineRepository
    models: ModelRepository
    monitorings: MonitoringRepository
    recalibrations: RecalibrationRepository
    comparisons: ComparisonRepository
    versions: ModelVersionRepository
    clock: Clock

    def execute(self) -> Mapping[str, int]:
        """Cierra los trabajos interrumpidos.

        Returns:
            Cuántos registros se cerraron de cada tipo (``fits``, ``limits``…); ``versions``
            cuenta las versiones conciliadas (versión 0 adoptada o propuesta rechazada).
        """
        now = self.clock.now()
        failed = JobStatus.FAILED
        counts = dict.fromkeys(
            (
                "fits",
                "limits",
                "exclusions",
                "pipelines",
                "models",
                "scores",
                "recalibrations",
                "comparisons",
                "versions",
            ),
            0,
        )
        for fit in self.fits.list_unfinished():
            self.fits.update(
                replace(fit, status=failed, finished_at=now, error=_interrupted(fit.status))
            )
            counts["fits"] += 1
        for lim in self.limits.list_unfinished():
            self.limits.update(
                replace(lim, status=failed, finished_at=now, error=_interrupted(lim.status))
            )
            counts["limits"] += 1
        for exc in self.exclusions.list_unfinished():
            self.exclusions.update(
                replace(exc, status=failed, finished_at=now, error=_interrupted(exc.status))
            )
            counts["exclusions"] += 1
        for pipe in self.pipelines.list_unfinished():
            self.pipelines.update(
                replace(pipe, status=failed, finished_at=now, error=_interrupted(pipe.status))
            )
            counts["pipelines"] += 1
        for model in self.models.list_unfinished():
            adopted = self._adopt_initial_version(model)
            if adopted is None:
                adopted = replace(
                    model, status=failed, finished_at=now, error=_interrupted(model.status)
                )
            else:
                counts["versions"] += 1
            self.models.update(adopted)
            counts["models"] += 1
        for mon in self.monitorings.list_unfinished():
            self.monitorings.update(
                replace(mon, status=failed, finished_at=now, error=_interrupted(mon.status))
            )
            counts["scores"] += 1
        for comp in self.comparisons.list_unfinished():
            self.comparisons.update(
                replace(comp, status=failed, finished_at=now, error=_interrupted(comp.status))
            )
            counts["comparisons"] += 1
        for recal in self.recalibrations.list_unfinished():
            if is_open_session(recal):
                continue
            proposal = recal.proposal
            if proposal is not None and proposal.status in _IN_PROGRESS:
                proposal = replace(proposal, status=failed)
            counts["versions"] += self._reject_orphan_proposals(recal)
            self.recalibrations.update(
                replace(
                    recal,
                    status=failed,
                    finished_at=now,
                    error=_interrupted(recal.status),
                    proposal=proposal,
                )
            )
            counts["recalibrations"] += 1
        return counts

    def _adopt_initial_version(self, model: ModelRecord) -> ModelRecord | None:
        """Completa un modelo cuya versión 0 se escribió antes de cerrarlo.

        Args:
            model: Modelo en curso.

        Returns:
            El modelo ``succeeded`` con el modelo y el instante de su versión 0, o ``None`` si
            no tiene versión 0 (el trabajo no llegó a escribirla).
        """
        initial = self.versions.get(model.tenant_id, model.chart_id, model.model_id, 0)
        if initial is None:
            return None
        return replace(
            model,
            status=JobStatus.SUCCEEDED,
            finished_at=initial.created_at,
            model=initial.model,
            error=None,
        )

    def _reject_orphan_proposals(self, recal: RecalibrationRecord) -> int:
        """Rechaza las versiones ``proposed`` de una recalibración que no terminó bien.

        Args:
            recal: Recalibración interrumpida.

        Returns:
            Cuántas versiones se rechazaron.
        """
        key = (recal.tenant_id, recal.chart_id, recal.model_id)
        decision = VersionDecision(
            decided_at=self.clock.now(), decided_by=None, note=JOB_INTERRUPTED_NOTE
        )
        rejected = 0
        for version in self.versions.list(*key):
            if (
                version.recalibration_id == recal.recalibration_id
                and version.status is VersionStatus.PROPOSED
            ):
                change = VersionStatusChange(
                    *key,
                    version.number,
                    VersionStatus.PROPOSED,
                    VersionStatus.REJECTED,
                    decision,
                )
                rejected += int(self.versions.apply_status_changes([change]))
        return rejected
