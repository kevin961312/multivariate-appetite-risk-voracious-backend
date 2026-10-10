"""La API sobre Postgres real (Paso 4.2): mismos bits que en memoria, persistencia y ``/ready``.

- La cadena HTTP de Fase I, una puntuación y una recalibración dan, sobre Postgres, exactamente
  los mismos bits que sobre memoria (modelo, versión 0, T² de cada observación, versión propuesta
  e informe).
- Lo creado sigue ahí tras reconstruir el contenedor (otro proceso sobre la misma base).
- Al arrancar, lo que un reinicio dejó en curso termina ``failed / JOB_INTERRUPTED``.
- ``/ready`` comprueba la base (``503`` si no responde); ``/health`` no depende de ella.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from support.api import BASE, DATASETS, T0, TENANT, observations, score, train, wait
from support.bits import canonical
from support.solo_test import solo_test_chart, solo_test_recalibration
from voracious.api.app import create_app
from voracious.application.records import JobStatus
from voracious.application.use_cases import JOB_INTERRUPTED
from voracious.config import Settings
from voracious.container import Container, build_container
from voracious.infrastructure.memory import ModelRecordCodec
from voracious.infrastructure.postgres import PostgresModelRepository, create_pool

TENANT_ID = TENANT["X-Tenant-ID"]
CHART_ID = "t2mrcd"
N = 30


def _postgres(url: str, storage: Path) -> Container:
    settings = Settings(
        repository="postgres",
        database_url=url,
        database_pool_size=4,
        storage="local",
        storage_dir=storage,
    )
    return build_container(settings, charts={CHART_ID: solo_test_chart()})


@pytest.fixture
def pg_container(pg_url: str, tmp_path: Path) -> Iterator[Container]:
    built = _postgres(pg_url, tmp_path / "datasets")
    yield built
    built.shutdown()


def _flow(container: Container) -> dict[str, Any]:
    """Fase I por HTTP, puntuación, anotación y recalibración; devuelve sus bits."""
    uc = container.use_cases
    with TestClient(create_app(container)) as client:
        model_id = train(client)
        done = score(client, model_id, observations(N))
        ids = list(done["result"]["observation_ids"])
        response = client.post(
            f"{BASE}/{model_id}/observations/{ids[3]}/annotations",
            headers=TENANT,
            json={"assignable_cause": True, "cause": "error de carga"},
        )
        assert response.status_code == 201, response.text
        rid = uc.request_recalibration.execute(
            TENANT_ID,
            CHART_ID,
            model_id,
            range_from=T0,
            range_to=T0 + timedelta(hours=N - 1),
            params=solo_test_recalibration(seed=11, min_observations=10),
        )
        recal = wait(client, f"{BASE}/{model_id}/recalibrations/{rid}")
        assert recal["status"] == "succeeded", recal
        model = uc.get_model.execute(TENANT_ID, CHART_ID, model_id)
        v0 = uc.get_version.execute(TENANT_ID, CHART_ID, model_id, 0)
        proposed = uc.get_version.execute(TENANT_ID, CHART_ID, model_id, recal["proposed_version"])
        scored = uc.list_observations.execute(TENANT_ID, CHART_ID, model_id)
        return {
            "model": canonical(model.model),
            "training": canonical(model.training_data),
            "params": canonical(model.params),
            "v0": canonical((v0.model, v0.base_data, v0.base_hash)),
            "t2": [canonical((o.observation.t2, o.observation.limit)) for o in scored],
            "outcome": recal["outcome"],
            "proposed": canonical(
                (proposed.model, proposed.report, proposed.base_data, proposed.base_hash)
            ),
        }


def test_postgres_gives_the_same_bits_as_memory(pg_container: Container) -> None:
    memory = build_container(Settings(), charts={CHART_ID: solo_test_chart()})
    try:
        expected = _flow(memory)
    finally:
        memory.shutdown()
    got = _flow(pg_container)
    assert got["outcome"] == expected["outcome"] == "extend"
    for key in expected:
        assert got[key] == expected[key], key


def test_model_survives_rebuilding_the_container(pg_url: str, tmp_path: Path) -> None:
    first = _postgres(pg_url, tmp_path / "datasets")
    try:
        with TestClient(create_app(first)) as client:
            model_id = train(client)
            before = client.get(f"{BASE}/{model_id}", headers=TENANT).json()
            versions = client.get(f"{BASE}/{model_id}/versions", headers=TENANT).json()
    finally:
        first.shutdown()
    second = _postgres(pg_url, tmp_path / "datasets")
    try:
        with TestClient(create_app(second)) as client:
            after = client.get(f"{BASE}/{model_id}", headers=TENANT)
            assert after.status_code == 200, after.text
            assert after.json() == before
            assert client.get(f"{BASE}/{model_id}/versions", headers=TENANT).json() == versions
            root = before["provenance"]["root_dataset_id"]
            dataset = client.get(f"{DATASETS}/{root}", headers=TENANT)
            assert dataset.status_code == 200, dataset.text
            other = client.get(f"{BASE}/{model_id}", headers={"X-Tenant-ID": "tenant-b"})
            assert other.status_code == 404
    finally:
        second.shutdown()


def test_startup_fails_interrupted_jobs(pg_url: str, tmp_path: Path) -> None:
    container = _postgres(pg_url, tmp_path / "datasets")
    try:
        with TestClient(create_app(container)) as client:
            model_id = train(client)
            queued = container.use_cases.get_model.execute(TENANT_ID, CHART_ID, model_id)
    finally:
        container.shutdown()
    # Un modelo «en curso» como el que dejaría un reinicio a mitad del trabajo.
    pool = create_pool(pg_url, 1)
    try:
        repo = PostgresModelRepository(pool, ModelRecordCodec(container.charts))
        repo.add(replace(queued, model_id="interrumpido", status=JobStatus.RUNNING, model=None))
    finally:
        pool.close()
    restarted = _postgres(pg_url, tmp_path / "datasets")
    try:
        with TestClient(create_app(restarted)) as client:  # el lifespan recupera al arrancar
            body = client.get(f"{BASE}/interrumpido", headers=TENANT).json()
            assert body["status"] == "failed"
            assert body["error"]["code"] == JOB_INTERRUPTED
            assert client.get(f"{BASE}/{model_id}", headers=TENANT).json()["status"] == "succeeded"
    finally:
        restarted.shutdown()


def test_ready_checks_database_and_storage(pg_container: Container) -> None:
    client = TestClient(create_app(pg_container))
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "storage": "ok"}}


def test_ready_is_503_when_the_database_is_down(tmp_path: Path) -> None:
    down = _postgres("postgresql://nadie:nada@127.0.0.1:1/ninguna", tmp_path / "datasets")
    try:
        client = TestClient(create_app(down))
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "checks": {"database": "fail", "storage": "ok"},
        }
        assert client.get("/health").status_code == 200  # la vida no depende de la base
        assert "nada@" not in repr(down.settings)  # la URL no se muestra
    finally:
        down.shutdown(wait=False)
