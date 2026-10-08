"""Apoyo de los tests HTTP: cabeceras de tenant, sondeo de trabajos y escenarios mínimos."""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import numpy.typing as npt
from fastapi.testclient import TestClient

from support.solo_test import small_data

TENANT = {"X-Tenant-ID": "tenant-a"}
OTHER = {"X-Tenant-ID": "tenant-b"}
CHART_BASE = "/v1/charts/t2mrcd"
BASE = f"{CHART_BASE}/models"
DATASETS = "/v1/datasets"
T0 = datetime(2026, 3, 1, tzinfo=UTC)
FAST_PARAMS: dict[str, Any] = {"bootstrap": {"seed": 7, "n_replicates": 5}}
"""B reducido por velocidad (SOLO TEST); el resto, defaults de la carta."""


def wait(client: TestClient, url: str, timeout: float = 120.0) -> dict[str, Any]:
    """Sondea ``url`` hasta que el trabajo termine y devuelve el cuerpo."""
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(url, headers=TENANT)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        if body["status"] in {"succeeded", "failed"}:
            return body
        assert time.monotonic() < deadline, f"el trabajo no terminó: {body}"
        time.sleep(0.02)


def upload(client: TestClient, data: npt.ArrayLike, headers: dict[str, str] = TENANT) -> str:
    """Sube un dataset JSON y devuelve su id."""
    response = client.post(DATASETS, headers=headers, json={"data": np.asarray(data).tolist()})
    assert response.status_code == 201, response.text
    return str(response.json()["dataset_id"])


def run_pipeline(
    client: TestClient, dataset_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Lanza la tubería de Fase I sobre un dataset y espera a que termine."""
    payload = {"dataset_id": dataset_id, "params": FAST_PARAMS, **(body or {})}
    response = client.post(f"{CHART_BASE}/pipelines/phase1", headers=TENANT, json=payload)
    assert response.status_code == 202, response.text
    return wait(client, f"{CHART_BASE}/pipelines/phase1/{response.json()['id']}")


def train(client: TestClient, seed: int = 3, body: dict[str, Any] | None = None) -> str:
    """Entrena un modelo pequeño (40 x 4) por la tubería y espera a que termine bien."""
    pipeline = run_pipeline(client, upload(client, small_data(40, 4, seed=seed)), body)
    assert pipeline["status"] == "succeeded", pipeline
    model_id = str(pipeline["model_id"])
    assert wait(client, f"{BASE}/{model_id}")["status"] == "succeeded"
    return model_id


def observations(
    n: int, seed: int = 50, shifted: tuple[int, ...] = (3, 7), start: datetime = T0
) -> list[dict[str, Any]]:
    """``n`` observaciones horarias desde ``start``; las filas ``shifted`` desplazadas (señales)."""
    x = small_data(n, 4, seed=seed)
    x[[i for i in shifted if i < n]] += 8.0
    return [
        {"observed_at": (start + timedelta(hours=i)).isoformat(), "values": row}
        for i, row in enumerate(np.asarray(x).tolist())
    ]


def score(client: TestClient, model_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Puntúa un lote y espera a que termine bien."""
    response = client.post(
        f"{BASE}/{model_id}/scores",
        headers=TENANT,
        json={"observations": rows, "batch_label": "b1"},
    )
    assert response.status_code == 202, response.text
    body = wait(client, f"{BASE}/{model_id}/scores/{response.json()['id']}")
    assert body["status"] == "succeeded", body
    return body
