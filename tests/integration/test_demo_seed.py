"""``scripts/demo_seed.py`` contra la app en proceso, por HTTP real (uvicorn en un hilo).

La demo usa los defaults de producción de la carta (B = 100) sobre 150 x 8: tarda unos segundos.
"""

import importlib.util
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import uvicorn

from voracious.api.app import create_app
from voracious.config import Settings
from voracious.container import Container, build_container

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo_seed.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_seed", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_seed"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def served() -> Iterator[tuple[str, Container]]:
    container = build_container(Settings())
    server = uvicorn.Server(
        uvicorn.Config(create_app(container), host="127.0.0.1", port=0, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn no arrancó"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", container
    finally:
        server.should_exit = True
        thread.join(timeout=30)


def test_demo_seed_runs_end_to_end(
    served: tuple[str, Container], capsys: pytest.CaptureFixture[str]
) -> None:
    base_url, container = served
    demo = _load()
    assert demo.main(["--base-url", base_url, "--tenant", "demo", "--poll", "0.05"]) == 0
    out = capsys.readouterr().out
    assert "DATOS SIMULADOS" in out
    model_id = next(line.split()[-1] for line in out.splitlines() if line.startswith("model_id"))
    model = container.use_cases.get_model.execute("demo", "t2mrcd", model_id)
    assert model.variables == tuple(f"var_{j}" for j in range(1, 9))
    assert model.training_data.shape == (150, 8)
    assert model.observed_at is not None
    assert model.observed_at[0].isoformat().startswith("2026-01-01")
    boot = model.params["bootstrap"]  # defaults de producción de la carta
    assert boot["n_replicates"] == 100
    assert (boot["alpha_limit"], boot["phase2_alpha_limit"]) == (0.005, 0.005)
    assert (boot["aggregation"], boot["phase2_aggregation"]) == (
        "pooled_quantile",
        "pooled_quantile",
    )
    assert model.params["mrcd"]["alpha"] == 0.75
    observations = container.use_cases.list_observations.execute("demo", "t2mrcd", model_id)
    assert len(observations) == 20
    signals = [o for o in observations if o.observation.signal]
    assert signals, "la demo debe producir señales"
    assert any(o.annotation is not None and o.annotation.assignable_cause for o in signals)
    assert min(o.observation.observed_at for o in observations) > max(model.observed_at)


def test_demo_seed_reports_an_unreachable_api(capsys: pytest.CaptureFixture[str]) -> None:
    demo = _load()
    assert demo.main(["--base-url", "http://127.0.0.1:1", "--timeout", "1"]) == 1
    assert "la demo falló" in capsys.readouterr().err
