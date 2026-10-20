"""Cupo por tenant de trabajos de cómputo activos por HTTP (M1 del paso E): ``429 TOO_MANY_JOBS``.

Con ``VORACIOUS_MAX_ACTIVE_JOBS_PER_TENANT=1`` y una carta cuyo ajuste espera a una barrera (el
trabajo queda en curso mientras el test lo necesite): el segundo ``POST`` de cómputo del tenant da
``429`` en el formato uniforme; una tubería con su hijo en curso cuenta 1 y termina aunque el cupo
esté lleno; al terminar se admite de nuevo; otro tenant no se ve afectado. La recuperación al
arrancar (``JOB_INTERRUPTED``) libera los huecos: ``tests/unit/application/test_admission.py``.
"""

import threading
import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from support.api import (
    BASE,
    CHART_BASE,
    FAST_PARAMS,
    OTHER,
    T0,
    TENANT,
    observations,
    score,
    train,
    upload,
    wait,
)
from support.auth import auth_settings
from support.solo_test import small_data
from voracious.api.app import create_app
from voracious.application.errors import TooManyJobsError
from voracious.container import build_container
from voracious.domain.charts.t2mrcd import T2MRCDChart
from voracious.domain.estimators.mrcd import MRCDFit

FITS = f"{CHART_BASE}/fits"
PIPELINES = f"{CHART_BASE}/pipelines/phase1"
END = (T0 + timedelta(hours=29)).isoformat()


def _gated_chart(gate: threading.Event) -> T2MRCDChart:
    """T²MRCD cuyo ajuste del estimador espera a ``gate`` (deja el trabajo en curso)."""

    class _Gated(T2MRCDChart):
        def fit_estimator(self, *args: object, **kwargs: object) -> MRCDFit:
            assert gate.wait(timeout=60)
            return super().fit_estimator(*args, **kwargs)

    return _Gated()


@pytest.fixture
def gate() -> threading.Event:
    """Barrera de los ajustes, abierta al empezar."""
    event = threading.Event()
    event.set()
    return event


@pytest.fixture
def client(gate: threading.Event) -> Iterator[TestClient]:
    container = build_container(
        auth_settings(max_active_jobs_per_tenant=1), charts={"t2mrcd": _gated_chart(gate)}
    )
    with TestClient(create_app(container)) as test_client:
        try:
            yield test_client
        finally:
            gate.set()  # antes del cierre de la app, que espera a los trabajos en curso


def _accepted(response: httpx2.Response) -> str:
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def _too_many(response: httpx2.Response, active: int = 1) -> None:
    assert response.status_code == 429, response.text
    body: dict[str, Any] = response.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == "TOO_MANY_JOBS"
    assert body["message"] == TooManyJobsError.MESSAGE
    assert body["details"] == {"max_active_jobs": 1, "active_jobs": active}


def _fit(client: TestClient, dataset_id: str, headers: dict[str, str] = TENANT) -> httpx2.Response:
    return client.post(FITS, headers=headers, json={"dataset_id": dataset_id})


def _pipeline(client: TestClient, dataset_id: str) -> httpx2.Response:
    return client.post(
        PIPELINES, headers=TENANT, json={"dataset_id": dataset_id, "params": FAST_PARAMS}
    )


def test_second_fit_is_429_until_the_first_finishes(
    client: TestClient, gate: threading.Event
) -> None:
    dataset = upload(client, small_data(40, 4))
    gate.clear()
    first = _accepted(_fit(client, dataset))
    _too_many(_fit(client, dataset))
    _too_many(_pipeline(client, dataset))
    # Una validación síncrona se informa antes que el cupo.
    missing = _fit(client, "nada")
    assert (missing.status_code, missing.json()["code"]) == (404, "DATASET_NOT_FOUND")
    # Otro tenant tiene su propio cupo.
    other = _accepted(_fit(client, upload(client, small_data(40, 4), headers=OTHER), OTHER))
    gate.set()
    assert wait(client, f"{FITS}/{first}")["status"] == "succeeded"
    again = _accepted(_fit(client, dataset))
    assert wait(client, f"{FITS}/{again}")["status"] == "succeeded"
    response = client.get(f"{FITS}/{other}", headers=OTHER)
    assert response.status_code == 200, response.text


def test_pipeline_with_its_step_in_progress_counts_one_and_finishes(
    client: TestClient, gate: threading.Event
) -> None:
    dataset = upload(client, small_data(40, 4))
    gate.clear()
    pipeline = _accepted(_pipeline(client, dataset))
    url = f"{PIPELINES}/{pipeline}"
    deadline = time.monotonic() + 60
    while not (steps := client.get(url, headers=TENANT).json()["steps"]):
        assert time.monotonic() < deadline, "la tubería no creó su ajuste"
        time.sleep(0.01)  # hasta que la tubería cree su ajuste (retenido en la barrera)
    assert [s["kind"] for s in steps] == ["fit"]
    _too_many(_fit(client, dataset))  # tubería + su ajuste: 1, no 2
    _too_many(_pipeline(client, dataset))
    gate.set()
    done = wait(client, url)
    assert done["status"] == "succeeded", done  # sus pasos nunca pasan por el cupo
    _accepted(_fit(client, dataset))


def test_recalibration_pipeline_is_429_and_stepwise_session_is_not(
    client: TestClient, gate: threading.Event
) -> None:
    model_id = train(client)
    score(client, model_id, observations(30))
    gate.clear()
    held = _accepted(_fit(client, upload(client, small_data(40, 4))))
    url = f"{BASE}/{model_id}/recalibrations"
    body: dict[str, Any] = {
        "range_from": T0.isoformat(),
        "range_to": END,
        "params": {"seed": 11, "min_observations": 20},
        "force_replace": True,
    }
    _too_many(client.post(url, headers=TENANT, json=body))
    session = client.post(url, headers=TENANT, json={**body, "mode": "stepwise"})
    assert session.status_code == 201, session.text
    candidates = session.json()["candidates_dataset_id"]
    _too_many(_fit(client, candidates))  # sus pasos sueltos sí cuentan
    gate.set()
    assert wait(client, f"{FITS}/{held}")["status"] == "succeeded"
    _accepted(_fit(client, candidates))
