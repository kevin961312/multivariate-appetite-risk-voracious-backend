"""Regresión en bits: ``fit_phase1``/``recalibrate`` siguen dando las huellas versionadas.

Las huellas (``tests/fixtures/t2mrcd_composition_hashes.json``) se generaron con el código de la
vuelta 3.2 en la plataforma de referencia; los bytes de un ajuste pueden variar con otra
BLAS/LAPACK o CPU, así que fuera de ella el test se salta (con motivo).
"""

import json
import platform

import pytest

from support.composition_hashes import FIXTURE, REFERENCE_PLATFORM, compute_hashes

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
    assert len(stored["hashes"]) == 10
    assert all(len(h) == 64 for h in stored["hashes"].values())
