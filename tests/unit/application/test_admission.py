"""Cupo por tenant de trabajos de cómputo activos (M1 del paso E): la regla y los casos de uso.

Cuentan los ajustes y límites sueltos y las tuberías ``queued`` o ``running``; los pasos de una
tubería ni se comprueban ni se cuentan. La comprobación va tras las validaciones síncronas y no
guarda ni encola nada al rechazar.
"""

from dataclasses import replace
from datetime import timedelta

import pytest

from support import records as rec
from support.app import CHART, OTHER_TENANT, T0, TENANT, App, hours, score, trained_model
from support.solo_test import fast_params, small_data
from voracious.application.errors import (
    DatasetNotFoundError,
    FitNotFoundError,
    TooManyJobsError,
)
from voracious.application.records import (
    AssignableCause,
    JobStatus,
    PipelineKind,
    RecalibrationMode,
)
from voracious.application.use_cases import JOB_INTERRUPTED, RecoverInterruptedJobs
from voracious.application.use_cases.admission import JobAdmission
from voracious.domain.charts.t2mrcd import T2MRCDChart, T2MRCDRecalibrationParams
from voracious.infrastructure.memory import (
    InMemoryFitRepository,
    InMemoryLimitsRepository,
    InMemoryPipelineRepository,
)

N = 30
END = T0 + timedelta(hours=N - 1)
RECALIBRATION = T2MRCDRecalibrationParams(seed=11, min_observations=10)


def _admission(max_active: int) -> JobAdmission:
    return JobAdmission(
        InMemoryFitRepository(),
        InMemoryLimitsRepository(),
        InMemoryPipelineRepository(),
        max_active,
    )


def _app(max_active: int) -> App:
    return App(charts={CHART: T2MRCDChart()}, max_active_jobs=max_active)


def _dataset(app: App, tenant: str = TENANT) -> str:
    return app.upload().execute(tenant, small_data(40, 4, seed=3)).dataset_id


def _full(app: App, *, active: int) -> None:
    """Comprueba que el cupo del tenant está lleno con ``active`` trabajos activos."""
    with pytest.raises(TooManyJobsError) as info:
        app.admission.check(TENANT)
    assert info.value.details == {"max_active_jobs": app.max_active_jobs, "active_jobs": active}


# --- la regla ------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, True])
def test_max_active_must_be_a_positive_integer(bad: int) -> None:
    with pytest.raises(ValueError, match="max_active"):
        _admission(bad)


def test_counts_standalone_steps_and_every_pipeline_of_the_tenant() -> None:
    admission = _admission(10)
    admission.fits.add(rec.fit(rid="f1"))
    admission.fits.add(rec.fit(rid="f2", status=JobStatus.RUNNING))
    admission.fits.add(replace(rec.fit(rid="f3"), pipeline_id="p1"))  # hijo de una tubería
    admission.fits.add(rec.fit(rid="f4", status=JobStatus.SUCCEEDED))
    admission.limits.add(rec.limits(rid="l1"))
    admission.limits.add(replace(rec.limits(rid="l2", status=JobStatus.RUNNING), pipeline_id="p1"))
    admission.limits.add(rec.limits(rid="l3", status=JobStatus.FAILED))
    admission.pipelines.add(rec.pipeline(rid="p1", status=JobStatus.RUNNING))
    admission.pipelines.add(replace(rec.pipeline(rid="p2"), kind=PipelineKind.RECALIBRATION))
    admission.pipelines.add(rec.pipeline(rid="p3", status=JobStatus.SUCCEEDED))
    admission.fits.add(rec.fit(tenant="otro", rid="f1"))
    assert admission.active_jobs("t") == 5  # f1, f2, l1, p1 y p2
    assert admission.active_jobs("otro") == 1
    assert admission.active_jobs("nadie") == 0


def test_check_rejects_from_the_quota_on_with_a_fixed_message() -> None:
    admission = _admission(2)
    admission.fits.add(rec.fit(rid="f1"))
    admission.check("t")  # 1 < 2
    admission.pipelines.add(rec.pipeline(rid="p1"))
    with pytest.raises(TooManyJobsError) as info:
        admission.check("t")
    error = info.value
    assert error.code == "TOO_MANY_JOBS"
    assert error.message == TooManyJobsError.MESSAGE
    assert error.details == {"max_active_jobs": 2, "active_jobs": 2}
    admission.check("otro")  # otro tenant: su propio cupo


# --- ajustes y límites sueltos -------------------------------------------------------------------


def test_second_standalone_fit_is_rejected_until_the_first_finishes() -> None:
    app = _app(1)
    dataset_id = _dataset(app)
    app.request_fit().execute(TENANT, CHART, dataset_id, None)
    jobs, ids = list(app.queue.jobs), app.ids.count
    with pytest.raises(TooManyJobsError) as info:
        app.request_fit().execute(TENANT, CHART, dataset_id, None)
    assert info.value.details == {"max_active_jobs": 1, "active_jobs": 1}
    assert app.queue.jobs == jobs  # nada encolado
    assert len(app.fits.list_unfinished()) == 1  # nada guardado
    assert app.ids.count == ids  # ni un id reservado
    # Las validaciones síncronas van antes que el cupo.
    with pytest.raises(DatasetNotFoundError):
        app.request_fit().execute(TENANT, CHART, "nada", None)
    # Otro tenant no se ve afectado.
    app.request_fit().execute(OTHER_TENANT, CHART, _dataset(app, OTHER_TENANT), None)
    app.run_all()
    assert app.admission.active_jobs(TENANT) == 0
    app.request_fit().execute(TENANT, CHART, dataset_id, None)  # admitido de nuevo


def test_standalone_limits_take_a_slot_and_are_checked() -> None:
    app = _app(1)
    fit_id = app.request_fit().execute(TENANT, CHART, _dataset(app), None)
    app.run_all()
    app.request_limits().execute(TENANT, CHART, fit_id, fast_params())
    _full(app, active=1)
    with pytest.raises(TooManyJobsError):
        app.request_limits().execute(TENANT, CHART, fit_id, fast_params())
    with pytest.raises(TooManyJobsError):
        app.request_fit().execute(TENANT, CHART, _dataset(app), None)
    with pytest.raises(FitNotFoundError):  # validación antes que el cupo
        app.request_limits().execute(TENANT, CHART, "nada", fast_params())
    app.run_all()
    app.request_limits().execute(TENANT, CHART, fit_id, fast_params())


def test_exclusions_assemblies_and_scores_are_not_limited() -> None:
    app = _app(1)
    model_id = trained_model(app)
    fit_id = app.request_fit().execute(TENANT, CHART, _dataset(app), None)
    app.run_all()
    limits_id = app.request_limits().execute(TENANT, CHART, fit_id, fast_params())
    app.run_all()
    app.request_fit().execute(TENANT, CHART, _dataset(app), None)  # cupo lleno
    _full(app, active=1)
    assert app.request_model().execute(TENANT, CHART, fit_id=fit_id, limits_id=limits_id)
    cause = (AssignableCause(row=0, cause="x"),)
    assert app.request_exclusion().execute(TENANT, CHART, _dataset(app), cause)
    x = small_data(3, 4, seed=1)
    assert app.monitor().execute(TENANT, CHART, model_id, x, hours(3, T0 + timedelta(days=30)))
    _full(app, active=1)  # ninguno de los tres ocupa hueco


# --- tuberías ------------------------------------------------------------------------------------


def test_pipeline_takes_one_slot_and_its_steps_are_never_checked() -> None:
    app = _app(1)
    dataset_id = _dataset(app)
    pipeline_id = app.request_pipeline().execute(TENANT, CHART, dataset_id, fast_params())
    with pytest.raises(TooManyJobsError):
        app.request_pipeline().execute(TENANT, CHART, dataset_id, fast_params())
    with pytest.raises(TooManyJobsError):
        app.request_fit().execute(TENANT, CHART, dataset_id, None)
    app.run(app.queue.jobs.pop(0))  # la tubería arranca y crea su ajuste
    child = app.fits.list_unfinished()
    assert [f.pipeline_id for f in child] == [pipeline_id]
    _full(app, active=1)  # la tubería con su hijo en curso cuenta 1
    app.run_all()
    record = app.get_pipeline().execute(TENANT, CHART, pipeline_id)
    assert record.status is JobStatus.SUCCEEDED, record.error  # con el cupo lleno, termina
    assert app.admission.active_jobs(TENANT) == 0
    app.request_pipeline().execute(TENANT, CHART, dataset_id, fast_params())


def _scored(app: App) -> str:
    model_id = trained_model(app)
    x = small_data(N, 4, seed=50)
    x[[3, 7]] += 8.0
    score(app, model_id, x, hours(N))
    return model_id


def _recalibrate(app: App, model_id: str, **kwargs: object) -> str:
    args: dict[str, object] = {"range_from": T0, "range_to": END, "params": RECALIBRATION}
    args.update(kwargs)
    return app.request_recalibration().execute(TENANT, CHART, model_id, **args)


def test_recalibration_pipeline_is_checked_and_stepwise_sessions_are_not() -> None:
    app = _app(1)
    model_id = _scored(app)
    app.request_fit().execute(TENANT, CHART, _dataset(app), None)  # cupo lleno
    jobs, ids = list(app.queue.jobs), app.ids.count
    with pytest.raises(TooManyJobsError):
        _recalibrate(app, model_id)
    assert app.recalibrations.list(TENANT, CHART, model_id) == []  # nada guardado
    assert (app.queue.jobs, app.ids.count) == (jobs, ids)  # ni encolado ni dataset de candidatas
    rid = _recalibrate(app, model_id, mode=RecalibrationMode.STEPWISE, force_replace=True)
    session = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert session.candidates_dataset_id is not None
    with pytest.raises(TooManyJobsError):  # sus pasos sueltos sí cuentan
        app.request_fit().execute(TENANT, CHART, session.candidates_dataset_id, None)
    app.run_all()
    app.request_fit().execute(TENANT, CHART, session.candidates_dataset_id, None)


def test_recalibration_pipeline_takes_one_slot_and_finishes() -> None:
    app = _app(1)
    model_id = _scored(app)
    rid = _recalibrate(app, model_id)
    _full(app, active=1)
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.SUCCEEDED, record.error
    assert app.admission.active_jobs(TENANT) == 0


# --- recuperación --------------------------------------------------------------------------------


def test_recovery_frees_the_slots() -> None:
    app = _app(2)
    dataset_id = _dataset(app)
    fit_id = app.request_fit().execute(TENANT, CHART, dataset_id, None)
    pipeline_id = app.request_pipeline().execute(TENANT, CHART, dataset_id, fast_params())
    _full(app, active=2)
    RecoverInterruptedJobs(
        app.fits,
        app.limits,
        app.exclusions,
        app.pipelines,
        app.models,
        app.monitorings,
        app.recalibrations,
        app.versions,
        app.clock,
    ).execute()
    fit = app.get_fit().execute(TENANT, CHART, fit_id)
    pipeline = app.get_pipeline().execute(TENANT, CHART, pipeline_id)
    for record in (fit, pipeline):
        assert record.status is JobStatus.FAILED
        assert record.error is not None
        assert record.error.code == JOB_INTERRUPTED
    assert app.admission.active_jobs(TENANT) == 0
    app.request_fit().execute(TENANT, CHART, dataset_id, None)
