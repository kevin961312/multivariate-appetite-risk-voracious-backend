"""``InlineJobQueue``: carriles independientes, sin bloquear al encolar y apagado ordenado (T5)."""

import threading
from collections.abc import Iterator

import pytest
import structlog
from structlog.testing import capture_logs

from voracious.application.ports import JobKind, JobLane, JobRequest
from voracious.infrastructure.jobs import InlineJobQueue

LANES = dict.fromkeys(JobLane, 1)


def _job(kind: JobKind, resource: str = "r") -> JobRequest:
    model = "m" if kind in {JobKind.SCORE, JobKind.COMPARISON, JobKind.VERSION_PROPOSAL} else None
    return JobRequest(kind, "t", "c", resource, model)


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()


def test_blocked_calibration_does_not_block_light_lane() -> None:
    release = threading.Event()
    calibration_started = threading.Event()
    scored = threading.Event()

    def calibrate(job: JobRequest) -> None:
        calibration_started.set()
        release.wait(timeout=10)

    queue = InlineJobQueue(
        {JobKind.LIMITS: calibrate, JobKind.SCORE: lambda j: scored.set()}, LANES
    )
    try:
        queue.enqueue(_job(JobKind.LIMITS))
        assert calibration_started.wait(timeout=5)
        queue.enqueue(_job(JobKind.SCORE))
        assert scored.wait(timeout=5)
        assert not release.is_set()
    finally:
        release.set()
        queue.shutdown()


def test_enqueue_returns_before_the_job_finishes() -> None:
    release = threading.Event()
    done = threading.Event()

    def slow(job: JobRequest) -> None:
        release.wait(timeout=10)
        done.set()

    queue = InlineJobQueue({JobKind.MRCD_FIT: slow}, LANES)
    queue.enqueue(_job(JobKind.MRCD_FIT))
    assert not done.is_set()
    release.set()
    queue.shutdown(wait=True)
    assert done.is_set()


def test_handler_exception_is_logged_and_queue_keeps_working() -> None:
    ran = threading.Event()

    def boom(job: JobRequest) -> None:
        raise RuntimeError("fallo")

    queue = InlineJobQueue({JobKind.MRCD_FIT: boom, JobKind.SCORE: lambda j: ran.set()}, LANES)
    with capture_logs() as logs:
        queue.enqueue(_job(JobKind.MRCD_FIT, "ajuste-1"))
        queue.enqueue(_job(JobKind.SCORE))
        queue.shutdown(wait=True)
    assert ran.is_set()
    failed = [e for e in logs if e["event"] == "job_failed"]
    assert len(failed) == 1
    assert failed[0]["resource_id"] == "ajuste-1"
    assert failed[0]["kind"] == "mrcd_fit"


def test_unknown_kind_and_closed_queue_fail_on_enqueue() -> None:
    queue = InlineJobQueue({}, LANES)
    with pytest.raises(ValueError, match="manejador"):
        queue.enqueue(_job(JobKind.MRCD_FIT))
    queue = InlineJobQueue({JobKind.MRCD_FIT: lambda j: None}, LANES)
    queue.shutdown(wait=False)
    with pytest.raises(RuntimeError):
        queue.enqueue(_job(JobKind.MRCD_FIT))


def test_lane_configuration_is_validated() -> None:
    with pytest.raises(ValueError, match="carriles"):
        InlineJobQueue({}, {JobLane.LIGHT: 1})
    with pytest.raises(ValueError, match="al menos un hilo"):
        InlineJobQueue({}, {**LANES, JobLane.LIGHT: 0})
