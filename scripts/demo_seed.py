"""Siembra una demo de Voracious por HTTP con DATOS SIMULADOS (Paso 4.2).

    uv run python scripts/demo_seed.py --base-url http://127.0.0.1:8000 --tenant demo

Qué hace, solo hablando con la API (no importa nada de ``voracious``):

1. Genera un histórico SIMULADO de 150 x 8 (AR(1) con semilla fija), con fechas diarias desde
   2026-01-01 y variables ``var_1`` … ``var_8``, y lo sube (``POST /v1/datasets``).
2. Corre la Fase I por la tubería (``/pipelines/phase1``) con los defaults de producción de la
   carta (solo se fija la semilla del bootstrap, que es obligatoria) y espera al modelo.
3. Puntúa 20 observaciones nuevas, también simuladas y con fechas posteriores; algunas están
   desplazadas a propósito para que haya señales.
4. Anota una señal con causa asignable e imprime los identificadores.

Los datos son simulados: no representan ningún portafolio real. Solo usa la biblioteca estándar y
numpy.
"""

import argparse
import http.client
import json
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import numpy as np

SEED = 20260101
"""Semilla de la simulación y del bootstrap (fija: la demo es reproducible)."""

N_HISTORY = 150
N_NEW = 20
P = 8
PHI = 0.5
"""Coeficiente AR(1) de cada variable (simulación, no es un parámetro del método)."""

START = datetime(2026, 1, 1, tzinfo=UTC)
SHIFTED_ROWS = (12, 15, 18)
"""Observaciones nuevas desplazadas a propósito (señales esperadas)."""

SHIFT = 6.0
"""Desplazamiento de esas filas, en desviaciones típicas de la innovación."""

CHART = "/v1/charts/t2mrcd"

Json = dict[str, Any] | list[Any]
"""Cuerpo JSON de una respuesta."""


class ApiError(RuntimeError):
    """La API respondió con un error."""


class Api:
    """Cliente HTTP mínimo (``urllib``) con la cabecera de tenant.

    Attributes:
        base_url: URL base de la API.
        tenant: Tenant (``X-Tenant-ID``).
        timeout: Segundos máximos por petición.
    """

    def __init__(self, base_url: str, tenant: str, timeout: float = 30.0) -> None:
        """Construye el cliente.

        Args:
            base_url: URL base de la API (``http`` o ``https``).
            tenant: Tenant.
            timeout: Segundos máximos por petición.
        """
        self.base_url = base_url.rstrip("/")
        self.tenant = tenant
        self.timeout = timeout

    def call(self, method: str, path: str, body: object | None = None) -> Json:
        """Hace una petición JSON y devuelve el cuerpo de la respuesta."""
        url = urlsplit(self.base_url)
        kind = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        conn = kind(url.netloc, timeout=self.timeout)
        data = None if body is None else json.dumps(body).encode("utf-8")
        try:
            conn.request(
                method,
                f"{url.path}{path}",
                body=data,
                headers={"X-Tenant-ID": self.tenant, "Content-Type": "application/json"},
            )
            response = conn.getresponse()
            text = response.read().decode("utf-8", errors="replace")
        finally:
            conn.close()
        if response.status >= 400:
            msg = f"{method} {path} -> {response.status}: {text}"
            raise ApiError(msg)
        return json.loads(text)

    def wait(self, path: str, limit: float, poll: float) -> dict[str, Any]:
        """Sondea un trabajo hasta que termine; falla si no termina bien."""
        deadline = time.monotonic() + limit
        while True:
            body: dict[str, Any] = self.call("GET", path)
            if body["status"] == "succeeded":
                return body
            if body["status"] in {"failed", "cancelled"}:
                msg = f"{path} terminó {body['status']}: {body.get('error')}"
                raise ApiError(msg)
            if time.monotonic() > deadline:
                msg = f"{path} no terminó en {limit} s"
                raise ApiError(msg)
            time.sleep(poll)


def simulate(seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    """Histórico y observaciones nuevas SIMULADOS: AR(1) con innovaciones correlacionadas.

    Args:
        seed: Semilla.

    Returns:
        ``(histórico 150 x 8, nuevas 20 x 8)``; las nuevas continúan el mismo proceso y las filas
        ``SHIFTED_ROWS`` llevan un desplazamiento.
    """
    rng = np.random.default_rng(seed)
    corr = 0.3 + 0.7 * np.eye(P)
    chol = np.linalg.cholesky(corr)
    total = N_HISTORY + N_NEW
    x = np.zeros((total, P))
    state = np.zeros(P)
    for t in range(total):
        state = PHI * state + chol @ rng.standard_normal(P)
        x[t] = state
    new = x[N_HISTORY:].copy()
    new[list(SHIFTED_ROWS)] += SHIFT
    return x[:N_HISTORY], new


def _dates(start: datetime, n: int) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def run(api: Api, *, limit: float = 600.0, poll: float = 1.0) -> dict[str, Any]:
    """Siembra la demo y devuelve los identificadores creados.

    Args:
        api: Cliente.
        limit: Segundos máximos de espera por trabajo.
        poll: Segundos entre sondeos.

    Returns:
        ``dataset_id``, ``pipeline_id``, ``model_id``, ``score_id``, ``observation_ids``,
        ``signal_ids`` y ``annotation_id`` (``None`` si no hubo ninguna señal).
    """
    history, new = simulate()
    variables = [f"var_{j + 1}" for j in range(P)]
    dataset = api.call(
        "POST",
        "/v1/datasets",
        {
            "data": history.tolist(),
            "variables": variables,
            "observed_at": _dates(START, N_HISTORY),
        },
    )
    pipeline = api.call(
        "POST",
        f"{CHART}/pipelines/phase1",
        {"dataset_id": dataset["dataset_id"], "params": {"bootstrap": {"seed": SEED}}},
    )
    done = api.wait(f"{CHART}/pipelines/phase1/{pipeline['id']}", limit, poll)
    model_id = done["model_id"]
    api.wait(f"{CHART}/models/{model_id}", limit, poll)
    rows = [
        {"observed_at": when, "values": values}
        for when, values in zip(
            _dates(START + timedelta(days=N_HISTORY), N_NEW), new.tolist(), strict=True
        )
    ]
    score = api.call(
        "POST",
        f"{CHART}/models/{model_id}/scores",
        {"observations": rows, "batch_label": "demo", "variables": variables},
    )
    scored = api.wait(f"{CHART}/models/{model_id}/scores/{score['id']}", limit, poll)
    signals = api.call("GET", f"{CHART}/models/{model_id}/observations?signals_only=true")
    annotation_id = None
    if signals:
        note = api.call(
            "POST",
            f"{CHART}/models/{model_id}/observations/{signals[0]['id']}/annotations",
            {
                "assignable_cause": True,
                "cause": "error de carga simulado (demo)",
                "action": "se corrigió la fuente (demo)",
                "actor": "demo_seed",
            },
        )
        annotation_id = note["id"]
    return {
        "dataset_id": dataset["dataset_id"],
        "pipeline_id": pipeline["id"],
        "model_id": model_id,
        "score_id": score["id"],
        "observation_ids": scored["result"]["observation_ids"],
        "signal_ids": [s["id"] for s in signals],
        "annotation_id": annotation_id,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada.

    Args:
        argv: Argumentos (sin el programa).

    Returns:
        0 si fue bien; 1 si la API falló.
    """
    parser = argparse.ArgumentParser(description="Siembra una demo de Voracious (datos simulados).")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--timeout", type=float, default=600.0, help="espera máxima por trabajo")
    parser.add_argument("--poll", type=float, default=1.0, help="segundos entre sondeos")
    args = parser.parse_args(argv)
    out = sys.stdout
    out.write("=== DATOS SIMULADOS: demo de Voracious, no es un portafolio real ===\n")
    try:
        ids = run(Api(args.base_url, args.tenant), limit=args.timeout, poll=args.poll)
    except (ApiError, OSError) as exc:
        sys.stderr.write(f"la demo falló: {exc}\n")
        return 1
    out.write(f"tenant:        {args.tenant}\n")
    for key in ("dataset_id", "pipeline_id", "model_id", "score_id", "annotation_id"):
        out.write(f"{key + ':':<15}{ids[key]}\n")
    out.write(f"señales:       {len(ids['signal_ids'])} de {len(ids['observation_ids'])}\n")
    out.write("=== fin (datos simulados) ===\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
