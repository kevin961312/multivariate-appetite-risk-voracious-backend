"""El proceso muere entre escribir una versión y cerrar su trabajo (memoria y Postgres).

Dos trabajos escriben una versión y, en otra escritura, cierran su registro: el ensamblado del
modelo (versión 0, luego el modelo) y la propuesta de una recalibración (versión ``proposed``, luego
la recalibración). Aquí el manejador real corre con un repositorio cuya escritura de cierre «mata
el proceso» (``BaseException`` que ni el caso de uso ni la cola capturan); después se reinicia
(con Postgres, un contenedor nuevo sobre la misma base; en memoria, la recuperación de arranque
sobre el mismo estado) y se comprueba la conciliación de ``RecoverInterruptedJobs``:

- el modelo con versión 0 queda ``succeeded`` con el modelo de esa versión;
- la propuesta huérfana queda ``rejected / job_interrupted``, la recalibración ``failed /
  JOB_INTERRUPTED`` y una recalibración nueva ya no choca con ``PROPOSAL_PENDING``.
"""

import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from support.api import (
    BASE,
    CHART_BASE,
    FAST_PARAMS,
    T0,
    TENANT,
    observations,
    score,
    train,
    upload,
    wait,
)
from support.bits import canonical
from support.solo_test import small_data, solo_test_chart, solo_test_recalibration
from voracious.api.app import create_app
from voracious.application.ports import JobKind, ModelVersionRepository
from voracious.application.records import JobStatus, ModelVersion, VersionStatus
from voracious.application.use_cases import JOB_INTERRUPTED, JOB_INTERRUPTED_NOTE
from voracious.config import Settings
from voracious.container import Container, build_container

TENANT_ID = TENANT["X-Tenant-ID"]
CHART_ID = "t2mrcd"


class _ProcessDied(BaseException):
    """El proceso muere: no es ``Exception``, así que nadie la convierte en ``failed``."""


class _DieOnUpdate:
    """Repositorio que delega todo salvo ``update``, que «mata el proceso»."""

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def update(self, record: object) -> None:
        raise _ProcessDied


class _Backend:
    """Contenedor vigente y forma de «reiniciar» el proceso sobre el mismo estado."""

    def __init__(self, build: Callable[[], Container], *, persistent: bool) -> None:
        self._build = build
        self._persistent = persistent
        self.container = build()

    def restart(self) -> TestClient:
        """Reinicia (Postgres: contenedor nuevo; memoria: el mismo) y devuelve la API.

        Al entrar en el ``with`` del cliente, el ``lifespan`` ejecuta la recuperación de arranque.
        En memoria el estado solo vive en este contenedor, así que se recupera sobre él.
        """
        if self._persistent:
            self.container.shutdown(wait=False)
            self.container = self._build()
        return TestClient(create_app(self.container))

    def close(self) -> None:
        self.container.shutdown(wait=False)


@pytest.fixture(params=["memory", "postgres"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[_Backend]:
    charts = {CHART_ID: solo_test_chart()}
    if request.param == "memory":
        built = _Backend(lambda: build_container(Settings(), charts=charts), persistent=False)
    else:
        url = request.getfixturevalue("pg_url")
        settings = Settings(
            repository="postgres",
            database_url=url,
            database_pool_size=4,
            storage="local",
            storage_dir=tmp_path / "datasets",
        )
        built = _Backend(lambda: build_container(settings, charts=charts), persistent=True)
    yield built
    built.close()


def _crash_on_close(
    container: Container, kind: JobKind, repo: str
) -> tuple[Any, Callable[[], None]]:
    """Sustituye el manejador ``kind`` por uno cuyo repositorio ``repo`` muere al cerrar.

    Returns:
        El trabajo original (``Run…Job``), para leer sus repositorios, y cómo restaurarlo (el
        proceso reiniciado vuelve a tener el manejador sano).
    """
    handlers = cast(dict[JobKind, Callable[..., None]], container.handlers)
    original = handlers[kind]
    job = cast(Any, original).__self__
    handlers[kind] = replace(job, **{repo: _DieOnUpdate(getattr(job, repo))}).execute

    def restore() -> None:
        handlers[kind] = original

    return job, restore


def _until(found: Callable[[], ModelVersion | None]) -> ModelVersion:
    deadline = time.monotonic() + 120.0
    while (version := found()) is None:
        assert time.monotonic() < deadline, "la versión no llegó a escribirse"
        time.sleep(0.02)
    return version


def test_model_whose_initial_version_was_written_is_completed(backend: _Backend) -> None:
    job, restore = _crash_on_close(backend.container, JobKind.MODEL_ASSEMBLY, "models")
    versions: ModelVersionRepository = job.versions
    # Sin ``with``: sin lifespan, la cola sigue viva hasta el «reinicio».
    client = TestClient(create_app(backend.container))
    payload = {"dataset_id": upload(client, small_data(40, 4, seed=3)), "params": FAST_PARAMS}
    response = client.post(f"{CHART_BASE}/pipelines/phase1", headers=TENANT, json=payload)
    assert response.status_code == 202, response.text

    def initial() -> ModelVersion | None:
        running = [m for m in job.models.list_unfinished() if m.status is JobStatus.RUNNING]
        if not running:
            return None
        return versions.get(TENANT_ID, CHART_ID, running[0].model_id, 0)

    v0 = _until(initial)
    restore()
    with backend.restart() as client:
        body = client.get(f"{BASE}/{v0.model_id}", headers=TENANT).json()
        assert body["status"] == "succeeded", body
        assert body["error"] is None
        model = backend.container.use_cases.get_model.execute(TENANT_ID, CHART_ID, v0.model_id)
        assert canonical(model.model) == canonical(v0.model)
        assert model.finished_at == v0.created_at
        listed = client.get(f"{BASE}/{v0.model_id}/versions", headers=TENANT)
        assert listed.status_code == 200, listed.text
        assert [v["status"] for v in listed.json()] == ["active"]


def test_orphan_proposal_is_rejected_and_unblocks_recalibration(backend: _Backend) -> None:
    uc = backend.container.use_cases
    # Sin ``with``: sin lifespan, la cola sigue viva hasta el «reinicio».
    client = TestClient(create_app(backend.container))
    model_id = train(client)
    score(client, model_id, observations(30))
    job, restore = _crash_on_close(backend.container, JobKind.VERSION_PROPOSAL, "recalibrations")
    versions: ModelVersionRepository = job.versions

    def recalibrate() -> str:
        return uc.request_recalibration.execute(
            TENANT_ID,
            CHART_ID,
            model_id,
            range_from=T0,
            range_to=T0 + timedelta(hours=29),
            params=solo_test_recalibration(seed=11, min_observations=10),
        )

    rid = recalibrate()

    def proposed() -> ModelVersion | None:
        found = versions.list(TENANT_ID, CHART_ID, model_id)
        return next((v for v in found if v.status is VersionStatus.PROPOSED), None)

    orphan = _until(proposed)
    assert orphan.recalibration_id == rid
    restore()
    with backend.restart() as client:
        uc = backend.container.use_cases
        recal = client.get(f"{BASE}/{model_id}/recalibrations/{rid}", headers=TENANT).json()
        assert recal["status"] == "failed", recal
        assert recal["error"]["code"] == JOB_INTERRUPTED
        rejected = uc.get_version.execute(TENANT_ID, CHART_ID, model_id, orphan.number)
        assert (rejected.status, rejected.decision_note, rejected.decided_by) == (
            VersionStatus.REJECTED,
            JOB_INTERRUPTED_NOTE,
            None,
        )
        assert rejected.rejected_at is not None
        assert uc.get_version.execute(TENANT_ID, CHART_ID, model_id, 0).status is (
            VersionStatus.ACTIVE
        )
        again = recalibrate()  # ya no hay propuesta pendiente que la bloquee
        done = wait(client, f"{BASE}/{model_id}/recalibrations/{again}")
        assert done["status"] == "succeeded", done
        assert done["proposed_version"] == orphan.number + 1
