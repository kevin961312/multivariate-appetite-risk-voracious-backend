"""``scripts/demo_seed.py`` contra la app en proceso, por HTTP real (uvicorn en un hilo).

La demo usa los defaults de producción de la carta (B = 100) sobre 150 x 8: tarda unos segundos.
Llama con un token del tenant ``demo`` y rol ``analyst`` (el tenant ya no va en una cabecera).
"""

import importlib.util
import io
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
import uvicorn

from support.auth import auth_settings, token
from voracious.api.app import create_app
from voracious.application.auth import Role
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
    container = build_container(auth_settings())
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
    served: tuple[str, Container],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url, container = served
    demo = _load()
    secret = token("demo", roles=(Role.ANALYST,), subject="demo-seed")
    monkeypatch.setenv("VORACIOUS_API_TOKEN", secret)
    assert demo.main(["--base-url", base_url, "--poll", "0.05"]) == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "DATOS SIMULADOS" in out
    for part in secret.split("."):  # el token no se imprime, ni a trozos
        assert part not in out
        assert part not in captured.err
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
    assert {o.annotation.actor for o in signals if o.annotation is not None} == {"demo-seed"}
    assert min(o.observation.observed_at for o in observations) > max(model.observed_at)


def test_demo_seed_reports_an_unreachable_api(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    demo = _load()
    monkeypatch.setenv("VORACIOUS_API_TOKEN", "x.y.z")
    assert demo.main(["--base-url", "http://127.0.0.1:1", "--timeout", "1"]) == 1
    assert "la demo falló" in capsys.readouterr().err


def test_demo_seed_without_a_token_stops_with_a_clear_message(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    demo = _load()
    monkeypatch.delenv("VORACIOUS_API_TOKEN", raising=False)
    assert demo.main(["--base-url", "http://127.0.0.1:1"]) == 1
    err = capsys.readouterr().err
    assert "falta el token" in err
    assert "VORACIOUS_API_TOKEN" in err
    assert demo.main(["--token-file", "/no/existe/token.txt"]) == 1
    assert "no se puede leer --token-file" in capsys.readouterr().err


def test_demo_seed_reads_the_token_from_a_file_or_stdin(
    served: tuple[str, Container],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El token llega por fichero o por la entrada estándar y viaja como ``Bearer``."""
    base_url, _ = served
    demo = _load()
    secret = token("demo", roles=(Role.APPROVER,))
    path = tmp_path / "token.txt"
    path.write_text(f"{secret}\n", encoding="utf-8")
    assert demo.read_token(str(path)) == secret
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"  {secret}\n"))
    assert demo.read_token("-") == secret
    api = demo.Api(base_url, secret)
    assert secret not in repr(api)
    with pytest.raises(demo.ApiError, match="403"):  # approver no puede subir datos
        api.call("POST", "/v1/datasets", {"data": [[1.0]]})
