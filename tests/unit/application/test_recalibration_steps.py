"""Recalibración por pasos en la aplicación (T22, T23): sesión, extensión, propuesta y tubería."""

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from support.app import CHART, T0, TENANT, App, hours, lifecycle_app, score, trained_model
from support.memory import InMemoryRecalibrationRepository
from support.solo_test import small_data
from voracious.application.errors import (
    DatasetNotFoundError,
    RecalibrationMismatchError,
    RecalibrationNotFoundError,
    RecalibrationNotInProgressError,
    VersionInputsMismatchError,
)
from voracious.application.ports import JobKind, JobRequest
from voracious.application.records import (
    DatasetSource,
    JobStatus,
    ProposalRequest,
    RecalibrationMode,
    RecalibrationRecord,
    VersionStatus,
)
from voracious.application.use_cases import RequestFit, RequestLimits
from voracious.domain.charts.t2mrcd import T2MRCDChart, T2MRCDRecalibrationParams
from voracious.domain.common import InvalidInputError, RecalibrationDecision
from voracious.infrastructure.charts import T2MRCDRecalibrationSteps

N = 30
END = T0 + timedelta(hours=N - 1)


def _scored_app(app: App | None = None) -> tuple[App, str]:
    app = app if app is not None else lifecycle_app()
    model_id = trained_model(app)
    x = small_data(N, 4, seed=50)
    x[[3, 7]] += 8.0
    score(app, model_id, x, hours(N))
    return app, model_id


def _open(app: App, model_id: str, **kwargs: object) -> RecalibrationRecord:
    args: dict[str, object] = {
        "range_from": T0,
        "range_to": END,
        "params": T2MRCDRecalibrationParams(seed=11, min_observations=10),
        "mode": RecalibrationMode.STEPWISE,
    }
    args.update(kwargs)
    rid = app.request_recalibration().execute(TENANT, CHART, model_id, **args)
    return app.get_recalibration().execute(TENANT, CHART, model_id, rid)


def _new_rows(app: App, session: RecalibrationRecord) -> tuple[str, str]:
    """Ajusta y calibra las candidatas (sin anotaciones, sin exclusión): ``(fit, limits)``."""
    assert session.candidates_dataset_id is not None
    fit_id = app.request_fit().execute(TENANT, CHART, session.candidates_dataset_id, None)
    app.run_all()
    limits_id = app.request_limits().execute(
        TENANT, CHART, fit_id, None, recalibration_id=session.recalibration_id
    )
    app.run_all()
    return fit_id, limits_id


def _force(app: App, session: RecalibrationRecord, force_replace: bool) -> None:
    """Cambia ``force_replace`` de la sesión guardada (para cruzar pasos de las dos ramas)."""
    key = (TENANT, CHART, session.model_id, session.recalibration_id)
    app.recalibrations.records[key] = replace(
        app.recalibrations.records[key], force_replace=force_replace
    )


def test_stepwise_session_freezes_candidates_and_enqueues_nothing() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id)
    assert app.queue.jobs == []
    assert session.status is JobStatus.RUNNING
    assert session.mode is RecalibrationMode.STEPWISE
    assert session.pipeline_id is None
    assert len(session.candidate_ids) == N
    assert session.already_in_base_ids == ()
    bootstrap = session.inherited_params["bootstrap"]
    assert isinstance(bootstrap, dict)
    assert bootstrap["seed"] == 11
    assert session.candidates_dataset_id is not None
    dataset = app.datasets.get(TENANT, session.candidates_dataset_id)
    assert dataset is not None
    assert dataset.source is DatasetSource.RECALIBRATION_CANDIDATES
    assert dataset.origin_ref == session.recalibration_id
    observed = [app.observations.get(TENANT, CHART, model_id, oid) for oid in session.candidate_ids]
    values = np.array([o.values for o in observed if o is not None])
    assert dataset.data.tobytes() == values.tobytes()


def app_fit(app: App, session: RecalibrationRecord) -> str:
    """Ajuste del dataset de candidatas (ya ejecutado)."""
    assert session.candidates_dataset_id is not None
    fit_id = app.request_fit().execute(TENANT, CHART, session.candidates_dataset_id, None)
    app.run_all()
    return fit_id


def _extension(app: App, session: RecalibrationRecord, dataset_id: str | None = None) -> str:
    """Construye la extensión de la sesión (sin anotaciones: las candidatas)."""
    kept = dataset_id if dataset_id is not None else session.candidates_dataset_id
    assert kept is not None
    return app.request_extension().execute(
        TENANT, CHART, session.model_id, session.recalibration_id, dataset_id=kept
    )


def _extended(app: App, session: RecalibrationRecord) -> tuple[str, str, str]:
    """Extensión, ajuste y límites de la base ampliada: ``(extension, fit, limits)``."""
    extension_id = _extension(app, session)
    fit_id = app.request_fit().execute(TENANT, CHART, extension_id, None)
    app.run_all()
    limits_id = app.request_limits().execute(
        TENANT, CHART, fit_id, None, recalibration_id=session.recalibration_id
    )
    app.run_all()
    return extension_id, fit_id, limits_id


def test_job_runners_reject_other_kinds_and_unknown_resources() -> None:
    app, model_id = _scored_app()
    with pytest.raises(ValueError, match="version_proposal"):
        app.run_version_proposal().execute(JobRequest(JobKind.MRCD_FIT, TENANT, CHART, "x"))
    job = JobRequest(JobKind.VERSION_PROPOSAL, TENANT, CHART, "x", model_id)
    with pytest.raises(RecalibrationNotFoundError):
        app.run_version_proposal().execute(job)
    session = _open(app, model_id)
    idle = JobRequest(JobKind.VERSION_PROPOSAL, TENANT, CHART, session.recalibration_id, model_id)
    app.run_version_proposal().execute(idle)  # sin propuesta pedida: no hace nada
    assert (
        app.get_recalibration().execute(TENANT, CHART, model_id, session.recalibration_id).status
        is JobStatus.RUNNING
    )


def test_extension_stacks_the_base_and_the_kept_rows_once() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id)
    extension_id = _extension(app, session)
    dataset = app.datasets.get(TENANT, extension_id)
    assert dataset is not None
    assert dataset.source is DatasetSource.RECALIBRATION_EXTENSION
    assert dataset.origin_ref == session.recalibration_id
    v0 = app.get_version().execute(TENANT, CHART, model_id, 0)
    candidates = app.datasets.get(TENANT, session.candidates_dataset_id or "")
    assert candidates is not None
    stacked = np.vstack([v0.base_data, candidates.data])
    assert dataset.data.tobytes() == stacked.tobytes()
    stored = app.get_recalibration().execute(TENANT, CHART, model_id, session.recalibration_id)
    assert (stored.kept_dataset_id, stored.extension_dataset_id) == (
        session.candidates_dataset_id,
        extension_id,
    )
    # Idempotente con el mismo dataset: la misma extensión, sin crear otra.
    before = app.ids.count
    assert _extension(app, session) == extension_id
    assert app.ids.count == before


def test_extension_rejects_what_is_not_its_kept_rows() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id)
    rid = session.recalibration_id
    foreign = app.upload().execute(TENANT, small_data(N, 4, seed=9))
    with pytest.raises(RecalibrationMismatchError) as mismatch:
        _extension(app, session, foreign.dataset_id)
    assert mismatch.value.details["reason"] == "not_kept_rows_of_recalibration"
    with pytest.raises(DatasetNotFoundError):
        _extension(app, session, "nada")
    extension_id = _extension(app, session)
    # Ya construida: otra base no se acepta (ni la propia extensión como filas conservadas).
    with pytest.raises(RecalibrationMismatchError):
        _extension(app, session, extension_id)
    other = app.upload().execute(TENANT, small_data(N, 4, seed=10))
    with pytest.raises(RecalibrationMismatchError):
        _extension(app, session, other.dataset_id)
    with pytest.raises(RecalibrationNotFoundError):
        app.request_extension().execute(
            TENANT, CHART, model_id, "nada", dataset_id=session.candidates_dataset_id or ""
        )
    app.recalibrations.cancel(TENANT, CHART, model_id, rid, app.clock.now())
    with pytest.raises(RecalibrationNotInProgressError):
        _extension(app, session)


def test_extension_built_with_other_rows_is_rejected() -> None:
    app, model_id = _scored_app()
    ids = [
        o.observation_id
        for o in app.observations.list(TENANT, CHART, model_id)
        if np.abs(o.values).max() > 5
    ]
    app.annotate().execute(TENANT, CHART, model_id, ids[0], assignable_cause=True)
    session = _open(app, model_id)
    assert session.candidates_dataset_id is not None
    with pytest.raises(InvalidInputError) as human:
        _extension(app, session)
    assert human.value.details["reason"] == "human_exclusion_required"
    exclusion_id = app.request_exclusion().execute(TENANT, CHART, session.candidates_dataset_id)
    app.run_all()
    exclusion = app.get_exclusion().execute(TENANT, CHART, exclusion_id)
    assert exclusion.output_dataset_id is not None
    extension_id = _extension(app, session, exclusion.output_dataset_id)
    assert _extension(app, session, exclusion.output_dataset_id) == extension_id
    key = (TENANT, CHART, model_id, session.recalibration_id)
    stored = app.recalibrations.records[key]
    app.recalibrations.records[key] = replace(stored, kept_dataset_id="otra")
    with pytest.raises(InvalidInputError) as built:
        _extension(app, session, exclusion.output_dataset_id)
    assert built.value.details["reason"] == "extension_already_built"


def test_forced_replace_has_no_extension() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id, force_replace=True)
    with pytest.raises(InvalidInputError) as info:
        _extension(app, session)
    assert info.value.details["reason"] == "forced_replace_has_no_extension"


def test_concurrent_extension_returns_the_winner_or_fails() -> None:
    class _Late(InMemoryRecalibrationRepository):
        """``set_extension`` pierde la carrera: otra petición ya fijó ``winner``."""

        winner: tuple[str, str] | None = None

        def set_extension(
            self,
            tenant_id: str,
            chart_id: str,
            model_id: str,
            recalibration_id: str,
            *,
            kept_dataset_id: str,
            extension_dataset_id: str,
        ) -> RecalibrationRecord | None:
            key = (tenant_id, chart_id, model_id, recalibration_id)
            if self.winner is not None:
                kept, extension = self.winner
                self.records[key] = replace(
                    self.records[key], kept_dataset_id=kept, extension_dataset_id=extension
                )
            return None

    repo = _Late()
    app, model_id = _scored_app(App(charts={CHART: T2MRCDChart()}, recalibrations=repo))
    session = _open(app, model_id)
    with pytest.raises(RecalibrationNotInProgressError) as lost:
        _extension(app, session)
    assert lost.value.details["reason"] == "concurrent_request"
    repo.winner = (session.candidates_dataset_id or "", "ganadora")
    assert _extension(app, session) == "ganadora"


def test_steps_follow_the_operation_of_the_session() -> None:
    """M3: sin reemplazo no se ajustan las filas nuevas sueltas; con él no hay extensión."""
    app, model_id = _scored_app()
    session = _open(app, model_id)
    assert session.candidates_dataset_id is not None
    with pytest.raises(InvalidInputError) as fit_new_rows:
        app.request_fit().execute(TENANT, CHART, session.candidates_dataset_id, None)
    assert fit_new_rows.value.details["reason"] == "new_rows_require_replace"
    extension_id = _extension(app, session)
    fit_id = app.request_fit().execute(TENANT, CHART, extension_id, None)
    app.run_all()
    _force(app, session, True)
    with pytest.raises(InvalidInputError) as limits_ext:
        app.request_limits().execute(
            TENANT, CHART, fit_id, None, recalibration_id=session.recalibration_id
        )
    assert limits_ext.value.details["reason"] == "extension_requires_extend"
    with pytest.raises(InvalidInputError) as fit_ext:
        app.request_fit().execute(TENANT, CHART, extension_id, None)
    assert fit_ext.value.details["reason"] == "extension_requires_extend"

    forced_app, forced_model = _scored_app()
    forced = _open(forced_app, forced_model, force_replace=True)
    fit_new = app_fit(forced_app, forced)
    _force(forced_app, forced, False)
    with pytest.raises(InvalidInputError) as limits_new:
        forced_app.request_limits().execute(
            TENANT, CHART, fit_new, None, recalibration_id=forced.recalibration_id
        )
    assert limits_new.value.details["reason"] == "new_rows_require_replace"


def test_proposal_needs_the_steps_of_its_decision() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id, force_replace=True)
    rid = session.recalibration_id
    new_fit, new_limits = _new_rows(app, session)

    def propose(fit_id: str, limits_id: str) -> str:
        return app.request_version_proposal().execute(
            TENANT, CHART, model_id, rid, fit_id=fit_id, limits_id=limits_id
        )

    _force(app, session, False)
    with pytest.raises(VersionInputsMismatchError) as missing:
        propose(new_fit, new_limits)
    assert missing.value.details["reason"] == "extension_required"
    extension_id, ext_fit, ext_limits = _extended(app, session)
    with pytest.raises(VersionInputsMismatchError) as not_extension:
        propose(new_fit, new_limits)
    assert not_extension.value.details == {
        "reason": "extend_uses_extension_dataset",
        "extension_dataset_id": extension_id,
    }
    _force(app, session, True)
    with pytest.raises(VersionInputsMismatchError) as not_new_rows:
        propose(ext_fit, ext_limits)
    assert not_new_rows.value.details == {"reason": "replace_uses_new_rows", "fit_id": ext_fit}
    _force(app, session, False)
    propose(ext_fit, ext_limits)
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.SUCCEEDED
    assert record.outcome is RecalibrationDecision.EXTEND
    version = app.get_version().execute(TENANT, CHART, model_id, 1)
    assert version.justification == "default_extend"
    assert version.status is VersionStatus.PROPOSED
    assert version.base_data.tobytes() == app.datasets.get(TENANT, extension_id).data.tobytes()


def test_proposal_job_fails_if_a_proposal_appeared_and_concurrent_request_loses() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id, force_replace=True)
    fit_id, limits_id = _new_rows(app, session)
    rid = session.recalibration_id
    app.request_version_proposal().execute(
        TENANT, CHART, model_id, rid, fit_id=fit_id, limits_id=limits_id
    )
    v0 = app.versions.list(TENANT, CHART, model_id)[0]
    app.versions.add(replace(v0, number=7, status=VersionStatus.PROPOSED))
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert (record.error.code, record.error.details) == ("PROPOSAL_PENDING", {"version": 7})
    assert record.proposal is not None
    assert record.proposal.status is JobStatus.FAILED

    class _Busy(InMemoryRecalibrationRepository):
        def request_proposal(
            self,
            tenant_id: str,
            chart_id: str,
            model_id: str,
            recalibration_id: str,
            proposal: ProposalRequest,
        ) -> RecalibrationRecord | None:
            return None

    busy = App(charts={CHART: T2MRCDChart()}, recalibrations=_Busy())
    busy, other = _scored_app(busy)
    opened = _open(busy, other, force_replace=True)
    fit_id, limits_id = _new_rows(busy, opened)
    with pytest.raises(RecalibrationNotInProgressError) as info:
        busy.request_version_proposal().execute(
            TENANT, CHART, other, opened.recalibration_id, fit_id=fit_id, limits_id=limits_id
        )
    assert info.value.details["reason"] == "concurrent_request"


def test_pipeline_step_failure_fails_the_recalibration() -> None:
    app, model_id = _scored_app()
    rid = app.request_recalibration().execute(
        TENANT,
        CHART,
        model_id,
        range_from=T0,
        range_to=END,
        params=T2MRCDRecalibrationParams(seed=11, min_observations=10),
    )
    key = (TENANT, CHART, model_id, rid)
    stored = app.recalibrations.records[key]
    inherited = dict(stored.inherited_params)
    bootstrap = inherited["bootstrap"]
    assert isinstance(bootstrap, dict)
    inherited["bootstrap"] = {**bootstrap, "aggregation": None}
    app.recalibrations.records[key] = replace(stored, inherited_params=inherited)
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == "T2MRCD_DECISION_PENDING"
    assert record.error.details["step"] == "limits"
    assert record.pipeline_id is not None
    pipeline = app.get_pipeline().execute(TENANT, CHART, record.pipeline_id)
    assert pipeline.status is JobStatus.FAILED
    with pytest.raises(ValueError, match="no es de Fase I"):
        app.run_phase1().execute(JobRequest(JobKind.PIPELINE, TENANT, CHART, record.pipeline_id))


def test_recalibration_datasets_need_the_links() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id, force_replace=True)
    fit_id = app_fit(app, session)
    unwired = RequestLimits(
        app.steps,
        app.datasets,
        app.fits,
        app.limits,
        app.queue,
        app.ids,
        app.clock,
    )
    with pytest.raises(RecalibrationMismatchError) as info:
        unwired.execute(TENANT, CHART, fit_id, None, recalibration_id=session.recalibration_id)
    assert info.value.details == {"reason": "not_wired"}
    with pytest.raises(RecalibrationMismatchError):
        app.request_limits().execute(TENANT, CHART, fit_id, None)


def test_fit_on_recalibration_datasets_needs_the_links() -> None:
    app, model_id = _scored_app()
    session = _open(app, model_id, force_replace=True)
    unwired = RequestFit(app.steps, app.datasets, app.fits, app.queue, app.ids, app.clock)
    with pytest.raises(RecalibrationMismatchError) as info:
        unwired.execute(TENANT, CHART, session.candidates_dataset_id or "", None)
    assert info.value.details == {"reason": "not_wired"}


def test_adapter_rejects_foreign_values() -> None:
    steps = T2MRCDRecalibrationSteps(T2MRCDChart())
    with pytest.raises(TypeError):
        steps.inherited_params(object(), {"seed": 1})
    with pytest.raises(TypeError):
        steps.report(
            object(),
            decision=RecalibrationDecision.INSUFFICIENT,
            n_base=1,
            new_dispositions=(),
            recalibration_params={"seed": 1},
            model=None,
        )
    assert steps.decide(n_kept=1, recalibration_params={"seed": 1}, force_replace=False) is (
        RecalibrationDecision.INSUFFICIENT
    )
