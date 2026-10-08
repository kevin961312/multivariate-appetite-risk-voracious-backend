"""``JobRequest`` por tipo, carriles de la cola y D6 atómico en los casos de uso (T1, T2)."""

import threading
from dataclasses import replace
from datetime import timedelta

import pytest

from support.app import CHART, T0, TENANT, App, hours, lifecycle_app, score, trained_model
from support.memory import InMemoryRecalibrationRepository
from support.solo_test import fixed_tests_recalibration, small_data
from voracious.application.errors import RecalibrationInProgressError
from voracious.application.ports import JobKind, JobLane, JobRequest, lane_of
from voracious.application.records import JobStatus, RecalibrationRecord, VersionStatus

REQUIRED = {JobKind.SCORE, JobKind.VERSION_PROPOSAL, JobKind.COMPARISON}


def test_every_kind_has_a_lane() -> None:
    assert {lane_of(k) for k in JobKind} == set(JobLane)
    assert lane_of(JobKind.MRCD_FIT) is JobLane.ESTIMATION
    assert lane_of(JobKind.LIMITS) is JobLane.CALIBRATION
    assert lane_of(JobKind.SCORE) is JobLane.LIGHT
    assert lane_of(JobKind.PIPELINE) is JobLane.ORCHESTRATION


@pytest.mark.parametrize("kind", list(JobKind))
def test_model_id_rule_per_kind(kind: JobKind) -> None:
    if kind in REQUIRED:
        assert JobRequest(kind, "t", "c", "r", "m").model_id == "m"
        with pytest.raises(ValueError, match="obligatorio"):
            JobRequest(kind, "t", "c", "r")
    else:
        assert JobRequest(kind, "t", "c", "r").resource_id == "r"
        with pytest.raises(ValueError, match="no se admite"):
            JobRequest(kind, "t", "c", "r", "m")


@pytest.mark.parametrize("field", ["tenant_id", "scope", "resource_id"])
def test_identifiers_cannot_be_empty(field: str) -> None:
    args = {"tenant_id": "t", "scope": "c", "resource_id": "r", field: ""}
    with pytest.raises(ValueError, match=field):
        JobRequest(JobKind.MRCD_FIT, **args)


class _GatedRecalibrations(InMemoryRecalibrationRepository):
    """Las dos primeras llamadas a ``list`` (la comprobación previa de cada petición) esperan a
    la otra: ambas peticiones ven «ninguna en curso» antes de que ninguna guarde."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Barrier(2)
        self.calls = 0
        self.lock = threading.Lock()

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[RecalibrationRecord]:
        rows = super().list(tenant_id, chart_id, model_id)
        with self.lock:
            self.calls += 1
            gated = self.calls <= 2
        if gated:
            self.gate.wait(timeout=10)
        return rows


def _scored_app() -> tuple[App, str]:
    app = lifecycle_app()
    model_id = trained_model(app)
    score(app, model_id, small_data(30, 4, seed=50), hours(30))
    return app, model_id


def test_concurrent_recalibration_requests_one_wins() -> None:
    app, model_id = _scored_app()
    app.recalibrations = _GatedRecalibrations()
    use_case = app.request_recalibration()
    outcomes: list[object] = []

    def request() -> None:
        try:
            outcomes.append(
                use_case.execute(
                    TENANT,
                    CHART,
                    model_id,
                    range_from=T0,
                    range_to=T0 + timedelta(hours=29),
                    params=fixed_tests_recalibration(min_observations=10),
                )
            )
        except RecalibrationInProgressError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=request) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    errors = [o for o in outcomes if isinstance(o, RecalibrationInProgressError)]
    assert len(errors) == 1
    assert errors[0].details == {"reason": "concurrent_request"}
    assert len([j for j in app.queue.jobs if j.kind is JobKind.PIPELINE]) == 1


def test_recalibration_job_fails_if_a_proposal_appeared() -> None:
    app, model_id = _scored_app()
    rid = app.request_recalibration().execute(
        TENANT,
        CHART,
        model_id,
        range_from=T0,
        range_to=T0 + timedelta(hours=29),
        params=fixed_tests_recalibration(min_observations=10),
    )
    v0 = app.versions.list(TENANT, CHART, model_id)[0]
    app.versions.add(replace(v0, number=7, status=VersionStatus.PROPOSED))
    app.run_all()
    record = app.get_recalibration().execute(TENANT, CHART, model_id, rid)
    assert record.status is JobStatus.FAILED
    assert record.error is not None
    assert record.error.code == "PROPOSAL_PENDING"
    assert record.error.details == {"version": 7, "step": "version", "step_id": rid}
