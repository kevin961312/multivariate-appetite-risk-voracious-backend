"""Casos fijos de Fase I y de recalibración de T²MRCD para las pruebas de equivalencia en bits.

Los usa ``tests/unit/domain/charts/t2mrcd/test_composition.py`` (composición paso a paso frente a
``fit_phase1``/``recalibrate``) y sirvieron para capturar la instantánea previa al refactor de la
vuelta 3.2. Parámetros: los de producción con B reducido (``fast_params``) y, en la recalibración,
las pruebas de permutación «SOLO TEST».
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from support.solo_test import fast_params, solo_test_recalibration
from voracious.domain.charts.t2mrcd import T2MRCDParams, T2MRCDRecalibrationParams

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Phase1Case:
    """Entrada de un caso de Fase I."""

    x: FloatArray
    params: T2MRCDParams
    excluded: npt.NDArray[np.bool_] | None = None


@dataclass(frozen=True)
class RecalibrationCase:
    """Entrada de un caso de recalibración (sobre el modelo de ``active_case``)."""

    x_new: FloatArray
    params: T2MRCDRecalibrationParams
    force_replace: bool = False
    assignable_cause: npt.NDArray[np.bool_] | None = None


def contaminated(seed: int = 100) -> FloatArray:
    """60 x 3 normal con 10 filas desplazadas: la depuración quita filas en dos rondas."""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(60, 3))
    x[:6] += rng.normal(scale=1.0, size=(6, 3)) + 4.0
    x[6:10] += 2.5
    return x


def phase1_cases() -> dict[str, Phase1Case]:
    """Casos de Fase I: n > p, p > n, contaminado, exclusión humana y rondas agotadas."""
    human = np.zeros(60, dtype=np.bool_)
    human[[0, 1, 2, 30]] = True
    return {
        "n_gt_p": Phase1Case(np.random.default_rng(3).normal(size=(40, 4)), fast_params()),
        "p_gt_n": Phase1Case(np.random.default_rng(5).normal(size=(15, 20)), fast_params()),
        "contaminated": Phase1Case(contaminated(), fast_params()),
        "human_exclusion": Phase1Case(contaminated(), fast_params(seed=8), human),
        "max_rounds": Phase1Case(contaminated(), fast_params(max_depuration_rounds=1)),
    }


def active_case() -> Phase1Case:
    """Fase I del modelo vigente de las recalibraciones (80 x 3 normal)."""
    return Phase1Case(np.random.default_rng(20).normal(size=(80, 3)), fast_params())


def _insufficient_after_depuration() -> FloatArray:
    """30 x 3 con 7 filas muy desplazadas: empieza con 30 >= 25 filas, la depuración quita las 7 y
    quedan 23 < ``min_observations`` dentro del bucle (``INSUFFICIENT`` tras una ronda)."""
    x = np.random.default_rng(22).normal(size=(30, 3))
    x[:7] += 9.0
    return x


def recalibration_cases() -> dict[str, RecalibrationCase]:
    """Casos de recalibración: EXTEND, REPLACE, INSUFFICIENT (de entrada y dentro del bucle de
    depuración) y reemplazo forzado."""
    rng = np.random.default_rng(21)
    in_control = rng.normal(size=(60, 3))
    in_control[4] += 6.0
    shifted = rng.normal(size=(60, 3)) + 3.0
    human = np.zeros(60, dtype=np.bool_)
    human[[1, 2]] = True
    return {
        "extend": RecalibrationCase(in_control, solo_test_recalibration(), assignable_cause=human),
        "replace": RecalibrationCase(shifted, solo_test_recalibration(seed=12)),
        "insufficient": RecalibrationCase(rng.normal(size=(10, 3)), solo_test_recalibration()),
        "insufficient_in_loop": RecalibrationCase(
            _insufficient_after_depuration(), solo_test_recalibration(seed=14)
        ),
        "forced": RecalibrationCase(
            in_control, T2MRCDRecalibrationParams(seed=13), force_replace=True
        ),
    }
