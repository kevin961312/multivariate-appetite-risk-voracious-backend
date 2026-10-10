"""``RecoverInterruptedJobs`` con los repositorios en memoria (la de Postgres en test_postgres)."""

from dataclasses import replace

from support import records as rec
from support.bits import canonical
from support.memory import FixedClock
from voracious.application.records import (
    JobStatus,
    ProposalRequest,
    RecalibrationMode,
    VersionStatus,
)
from voracious.application.use_cases import (
    JOB_INTERRUPTED,
    JOB_INTERRUPTED_NOTE,
    RecoverInterruptedJobs,
)
from voracious.application.use_cases.recovery import is_open_session
from voracious.infrastructure.memory import (
    InMemoryComparisonRepository,
    InMemoryExclusionRepository,
    InMemoryFitRepository,
    InMemoryLimitsRepository,
    InMemoryModelRepository,
    InMemoryModelVersionRepository,
    InMemoryMonitoringRepository,
    InMemoryPipelineRepository,
    InMemoryRecalibrationRepository,
    ModelVersionCodec,
)


def test_recovery_in_memory() -> None:
    fits, limits = InMemoryFitRepository(), InMemoryLimitsRepository()
    exclusions, pipelines = InMemoryExclusionRepository(), InMemoryPipelineRepository()
    models, monitorings = InMemoryModelRepository(), InMemoryMonitoringRepository()
    recalibrations, comparisons = InMemoryRecalibrationRepository(), InMemoryComparisonRepository()
    models.add(rec.model())
    pipelines.add(rec.pipeline(status=JobStatus.SUCCEEDED))
    stepwise = RecalibrationMode.STEPWISE
    open_ = rec.recalibration(rid="open", status=JobStatus.RUNNING, mode=stepwise)
    done_proposal = replace(
        rec.recalibration(tenant="t2", status=JobStatus.RUNNING, mode=stepwise),
        proposal=ProposalRequest("f", "l", None, JobStatus.FAILED, rec.T),
    )
    recalibrations.add(open_)
    recalibrations.add(done_proposal)
    assert is_open_session(open_)
    assert is_open_session(done_proposal)
    clock = FixedClock(rec.T)
    versions = InMemoryModelVersionRepository(ModelVersionCodec(rec.CHARTS))
    counts = RecoverInterruptedJobs(
        fits,
        limits,
        exclusions,
        pipelines,
        models,
        monitorings,
        recalibrations,
        comparisons,
        versions,
        clock,
    ).execute()
    assert (counts["models"], counts["recalibrations"], counts["pipelines"]) == (1, 0, 0)
    model = models.get("t", "c", "m")
    assert model is not None
    assert model.error is not None
    assert (model.status, model.error.code, model.finished_at) == (
        JobStatus.FAILED,
        JOB_INTERRUPTED,
        rec.T,
    )


def _recovery(
    models: InMemoryModelRepository,
    recalibrations: InMemoryRecalibrationRepository,
    versions: InMemoryModelVersionRepository,
) -> RecoverInterruptedJobs:
    return RecoverInterruptedJobs(
        InMemoryFitRepository(),
        InMemoryLimitsRepository(),
        InMemoryExclusionRepository(),
        InMemoryPipelineRepository(),
        models,
        InMemoryMonitoringRepository(),
        recalibrations,
        InMemoryComparisonRepository(),
        versions,
        FixedClock(rec.T),
    )


def test_model_with_initial_version_is_completed_not_failed() -> None:
    """Versión 0 escrita y modelo sin cerrar: el modelo se completa con ella."""
    models, versions = (
        InMemoryModelRepository(),
        InMemoryModelVersionRepository(ModelVersionCodec(rec.CHARTS)),
    )
    models.add(rec.model(status=JobStatus.RUNNING))
    v0 = rec.version()
    versions.add(v0)
    counts = _recovery(models, InMemoryRecalibrationRepository(), versions).execute()
    assert (counts["models"], counts["versions"]) == (1, 1)
    model = models.get("t", "c", "m")
    assert model is not None
    assert (model.status, model.error, model.finished_at) == (
        JobStatus.SUCCEEDED,
        None,
        v0.created_at,
    )
    assert canonical(model.model) == canonical(v0.model)
    kept = versions.get("t", "c", "m", 0)
    assert kept is not None
    assert kept.status is VersionStatus.ACTIVE  # la versión 0 no cambia


def test_orphan_proposal_of_interrupted_recalibration_is_rejected() -> None:
    """Versión propuesta escrita y recalibración sin cerrar: la propuesta se rechaza."""
    models, recalibrations = InMemoryModelRepository(), InMemoryRecalibrationRepository()
    versions = InMemoryModelVersionRepository(ModelVersionCodec(rec.CHARTS))
    models.add(rec.model(status=JobStatus.SUCCEEDED))
    versions.add(rec.version())
    asked = replace(
        rec.recalibration(status=JobStatus.RUNNING, mode=RecalibrationMode.STEPWISE),
        proposal=ProposalRequest("f", "l", None, JobStatus.RUNNING, rec.T),
    )
    recalibrations.add(asked)
    proposed = rec.version(number=1, status=VersionStatus.PROPOSED)
    versions.add(replace(proposed, recalibration_id="r"))
    versions.add(replace(proposed, number=2, recalibration_id="otra"))
    counts = _recovery(models, recalibrations, versions).execute()
    assert (counts["recalibrations"], counts["versions"]) == (1, 1)
    orphan = versions.get("t", "c", "m", 1)
    assert orphan is not None
    assert (orphan.status, orphan.decision_note, orphan.rejected_at, orphan.decided_by) == (
        VersionStatus.REJECTED,
        JOB_INTERRUPTED_NOTE,
        rec.T,
        None,
    )
    statuses = [v.status for v in versions.list("t", "c", "m")]
    # la de otra recalibración y la versión 0 quedan intactas
    assert statuses == [VersionStatus.ACTIVE, VersionStatus.REJECTED, VersionStatus.PROPOSED]
