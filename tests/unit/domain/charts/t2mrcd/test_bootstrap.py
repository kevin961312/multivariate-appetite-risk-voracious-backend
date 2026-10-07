from collections.abc import Callable, Sequence

import numpy as np
import pytest

from support.mappers import ProcessPoolTaskMapper, ReversedTaskMapper
from support.solo_test import small_data
from voracious.domain.charts.t2mrcd import (
    BOOTSTRAP_LIMIT_NOT_FINITE,
    BOOTSTRAP_REPLICATE_FAILED,
    DEFAULT_ALPHA_LIMIT,
    ReplicateContext,
    calibrate_limits,
    mean_of_replicate_quantiles,
    replicate_tasks,
    run_replicate,
)
from voracious.domain.common import EstimationError, SerialTaskMapper, TaskMapper
from voracious.domain.estimators.mrcd import MRCD_FIT_FAILED, MRCDParams, fit_mrcd


def _calibrate(x: np.ndarray, mapper: TaskMapper, seed: int = 11, b: int = 5) -> object:
    return calibrate_limits(
        x,
        mrcd=MRCDParams(),
        n_replicates=b,
        seed=seed,
        alpha=DEFAULT_ALPHA_LIMIT,
        aggregation=mean_of_replicate_quantiles,
        mapper=mapper,
    )


def test_seeds_come_from_seed_sequence_spawn() -> None:
    tasks = replicate_tasks(5, 3)
    assert [t.index for t in tasks] == [0, 1, 2]
    expected = np.random.SeedSequence(5).spawn(3)
    for task, child in zip(tasks, expected, strict=True):
        assert task.seed.entropy == child.entropy
        assert task.seed.spawn_key == child.spawn_key


def test_replicate_resamples_with_replacement_and_scores_the_sample() -> None:
    x = small_data()
    task = replicate_tasks(3, 1)[0]
    out = run_replicate(ReplicateContext(x_clean=x, mrcd=MRCDParams()), task)
    assert out.failure is None
    # Misma semilla => mismos índices: con reemplazo, tamaño n_clean.
    idx = np.random.default_rng(task.seed).integers(0, x.shape[0], size=x.shape[0])
    assert np.unique(idx).size < x.shape[0]
    fit = fit_mrcd(x[idx], MRCDParams())
    assert out.t2.shape == (x.shape[0],)
    assert np.array_equal(out.t2, fit.mah)


def test_limits_do_not_depend_on_execution_order() -> None:
    x = small_data()
    reversed_mapper = ReversedTaskMapper()
    serial = _calibrate(x, SerialTaskMapper())
    backwards = _calibrate(x, reversed_mapper)
    assert reversed_mapper.executed == [4, 3, 2, 1, 0]
    assert serial == backwards
    assert serial != _calibrate(x, SerialTaskMapper(), seed=12)


def test_run_replicate_under_real_process_pool() -> None:
    x = small_data()
    serial = _calibrate(x, SerialTaskMapper())
    pooled = _calibrate(x, ProcessPoolTaskMapper(max_workers=2))
    assert pooled == serial


def test_replicate_failure_fails_whole_phase1() -> None:
    # Fallo real de MRCD (columna constante), sin espías: falla toda réplica; se informa la 0
    # aunque el mapper las ejecute al revés.
    x = small_data()
    x[:, 1] = 2.0
    with pytest.raises(EstimationError) as info:
        _calibrate(x, ReversedTaskMapper())
    err = info.value
    assert err.code == BOOTSTRAP_REPLICATE_FAILED
    assert err.details["replicate_index"] == 0
    assert err.details["error_code"] == MRCD_FIT_FAILED
    assert err.details["error_message"]
    details = err.details["error_details"]
    assert isinstance(details, dict)
    assert "r_message" in details


def test_failure_outcome_is_returned_not_raised() -> None:
    x = small_data()
    x[:, 0] = 1.0
    out = run_replicate(ReplicateContext(x_clean=x, mrcd=MRCDParams()), replicate_tasks(1, 1)[0])
    assert out.failure is not None
    assert out.failure.code == MRCD_FIT_FAILED
    assert out.t2.size == 0


def test_non_finite_limit_is_an_error() -> None:
    with pytest.raises(EstimationError) as info:
        calibrate_limits(
            small_data(),
            mrcd=MRCDParams(),
            n_replicates=2,
            seed=1,
            alpha=DEFAULT_ALPHA_LIMIT,
            aggregation=lambda t2s, alpha: float("nan"),
            mapper=SerialTaskMapper(),
        )
    assert info.value.code == BOOTSTRAP_LIMIT_NOT_FINITE
    assert info.value.details == {"limit": "nan"}


class _DroppingMapper:
    def map[C, T, R](self, fn: Callable[[C, T], R], context: C, tasks: Sequence[T]) -> list[R]:
        return [fn(context, t) for t in tasks[:-1]]


def test_mapper_must_return_one_outcome_per_replicate() -> None:
    with pytest.raises(RuntimeError, match="una salida por réplica"):
        _calibrate(small_data(), _DroppingMapper(), b=2)
