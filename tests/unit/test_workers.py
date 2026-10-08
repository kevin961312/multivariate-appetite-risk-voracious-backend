import pytest

import voracious.workers.run as run
from voracious.application.errors import FitNotFoundError
from voracious.application.ports import JobKind, JobRequest
from voracious.config import Settings
from voracious.container import build_container

JOB = JobRequest(JobKind.MRCD_FIT, "t", "t2mrcd", "nope")


def test_handle_uses_the_given_container() -> None:
    container = build_container(Settings())
    try:
        with pytest.raises(FitNotFoundError):
            run.handle(JOB, container)
    finally:
        container.shutdown()


def test_handle_builds_the_process_container_once(monkeypatch: pytest.MonkeyPatch) -> None:
    run._default_container.cache_clear()
    with pytest.raises(FitNotFoundError):
        run.handle(JOB)
    assert run._default_container() is run._default_container()
    run._default_container().shutdown()
    run._default_container.cache_clear()
