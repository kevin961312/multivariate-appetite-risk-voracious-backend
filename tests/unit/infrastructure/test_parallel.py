"""``ProcessPoolTaskMapper`` con procesos ``spawn`` reales (T6, lento: unos segundos)."""

import numpy as np
import pytest

from support.mappers import ProcessPoolTaskMapper, boom_task
from support.solo_test import fast_params, small_data
from voracious.domain.charts.t2mrcd import T2MRCDChart
from voracious.domain.common import SerialTaskMapper


def test_fit_phase1_in_processes_is_bit_identical_to_serial() -> None:
    chart = T2MRCDChart()
    x = small_data(40, 4, seed=5)
    serial = chart.fit_phase1(x, fast_params(), mapper=SerialTaskMapper())
    parallel = chart.fit_phase1(x, fast_params(), mapper=ProcessPoolTaskMapper(2, mrcd_threads=1))
    assert serial.limits.phase1_limit == parallel.limits.phase1_limit
    assert serial.limits.phase2_limit == parallel.limits.phase2_limit
    assert serial.historical_t2.tobytes() == parallel.historical_t2.tobytes()
    assert np.array_equal(serial.base_mask, parallel.base_mask)


def test_exception_in_a_process_propagates() -> None:
    with pytest.raises(ValueError, match="tarea 3"):
        ProcessPoolTaskMapper(2).map(boom_task, None, list(range(6)))


def test_order_and_edge_cases() -> None:
    assert ProcessPoolTaskMapper(2).map(boom_task, None, [0, 1, 2]) == [0, 1, 2]
    assert ProcessPoolTaskMapper(2).map(boom_task, None, []) == []
    with pytest.raises(ValueError, match="max_workers"):
        ProcessPoolTaskMapper(0)
    with pytest.raises(ValueError, match="mrcd_threads"):
        ProcessPoolTaskMapper(1, mrcd_threads=0)
