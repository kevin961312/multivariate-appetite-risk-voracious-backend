"""Huellas sha256 de ``fit_phase1``/``recalibrate`` en los casos de ``composition_cases.py``.

Protegen contra regresiones futuras en bits: la huella es el sha256 de ``repr(canonical(...))``
(``support.bits``). Los bytes dependen de la plataforma de referencia (BLAS/LAPACK y CPU), así que
el fixture declara su plataforma y el test se salta fuera de ella.

Regenerar (solo si un cambio **intencionado** altera los bits, y anotándolo en el informe)::

    uv run python tests/support/composition_hashes.py
"""

import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy as np

if __package__ in {None, ""}:  # ejecución directa como script
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from support.bits import canonical
from support.composition_cases import active_case, phase1_cases, recalibration_cases
from voracious.domain.charts.t2mrcd import T2MRCDChart
from voracious.domain.common import SerialTaskMapper

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "t2mrcd_composition_hashes.json"
"""Fixture versionado con las huellas."""

REFERENCE_PLATFORM = ("Darwin", "arm64")
"""Plataforma (``platform.system()``, ``platform.machine()``) en la que se generaron."""


def fingerprint(value: object) -> str:
    """Huella sha256 de la forma canónica en bits de ``value``."""
    return hashlib.sha256(repr(canonical(value)).encode()).hexdigest()


def compute_hashes() -> dict[str, str]:
    """Huellas de los 4 casos de Fase I y de los 5 de recalibración."""
    chart, mapper = T2MRCDChart(), SerialTaskMapper()
    out: dict[str, str] = {}
    for name, case in sorted(phase1_cases().items()):
        model = chart.fit_phase1(case.x, case.params, mapper=mapper, excluded=case.excluded)
        out[f"phase1/{name}"] = fingerprint(model)
    active = active_case()
    model = chart.fit_phase1(active.x, active.params, mapper=mapper)
    base = active.x[model.base_mask]
    for name, rcase in sorted(recalibration_cases().items()):
        outcome = chart.recalibrate(
            model,
            base,
            rcase.x_new,
            assignable_cause=rcase.assignable_cause,
            force_replace=rcase.force_replace,
            params=rcase.params,
            mapper=mapper,
        )
        out[f"recalibration/{name}"] = fingerprint(
            (outcome.decision, outcome.model, outcome.report)
        )
    return out


def main() -> None:
    """Escribe el fixture con las huellas actuales y la plataforma."""
    payload = {
        "platform": list(REFERENCE_PLATFORM),
        "generated_on": [platform.system(), platform.machine()],
        "numpy": np.__version__,
        "hashes": compute_hashes(),
    }
    FIXTURE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
