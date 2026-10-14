"""Regresión en bits: ``fit_phase1``/``recalibrate`` siguen dando las huellas versionadas.

Las huellas (``tests/fixtures/t2mrcd_composition_hashes.json``) se regeneraron al quitar la
comparación de bases (decisión del dueño, 2026-10-14: cambian el informe y los parámetros de los
casos; los modelos de los 9 casos conservan sus bits) y al fijar la cita de la estadística T²
(``STATISTIC_REFERENCE``), en la plataforma de referencia; los bytes de un ajuste pueden variar
con otra BLAS/LAPACK o CPU, así que fuera de ella el test se salta (con motivo).

Las huellas **solo del modelo** (``tests/fixtures/t2mrcd_model_hashes.json``, sin informe ni cita)
son la línea base de ``c7f896b`` y **no** se regeneran cuando cambian solo la cita o el formato del
informe: si dejan de coincidir, cambió el modelo.
"""

import json
import platform

import pytest

from support.composition_hashes import (
    FIXTURE,
    MODEL_FIXTURE,
    REFERENCE_PLATFORM,
    compute_hashes,
    compute_model_hashes,
)

_ON_REFERENCE = (platform.system(), platform.machine()) == REFERENCE_PLATFORM


@pytest.mark.skipif(
    not _ON_REFERENCE,
    reason=f"huellas en bits de la plataforma de referencia {REFERENCE_PLATFORM} (BLAS/CPU)",
)
def test_fit_phase1_and_recalibrate_keep_their_versioned_hashes() -> None:
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert tuple(stored["platform"]) == REFERENCE_PLATFORM
    assert compute_hashes() == stored["hashes"]


def test_fixture_covers_every_composition_case() -> None:
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(stored["hashes"]) == 9
    assert all(len(h) == 64 for h in stored["hashes"].values())


@pytest.mark.skipif(
    not _ON_REFERENCE,
    reason=f"huellas en bits de la plataforma de referencia {REFERENCE_PLATFORM} (BLAS/CPU)",
)
def test_models_keep_their_c7f896b_hashes_without_report_or_citation() -> None:
    stored = json.loads(MODEL_FIXTURE.read_text(encoding="utf-8"))
    assert tuple(stored["platform"]) == REFERENCE_PLATFORM
    assert compute_model_hashes() == stored["hashes"]


def test_model_fixture_covers_every_composition_case() -> None:
    stored = json.loads(MODEL_FIXTURE.read_text(encoding="utf-8"))
    assert stored["baseline_commit"] == "c7f896b"
    assert len(stored["hashes"]) == 9
    for key, value in stored["hashes"].items():
        digest = value if key.startswith("phase1/") else value[1]
        assert len(digest) == 64
