from collections.abc import Callable, Sequence

import numpy as np
import pytest

from support.mappers import ProcessPoolTaskMapper, ReversedTaskMapper
from support.samplers import EmptyNewSampler
from support.solo_test import small_data
from voracious.domain.charts.t2mrcd import (
    BOOTSTRAP_LIMIT_NOT_FINITE,
    BOOTSTRAP_OOB_EMPTY,
    BOOTSTRAP_REPLICATE_FAILED,
    DEFAULT_ALPHA_LIMIT,
    DEFAULT_PHASE2_ALPHA_LIMIT,
    BootstrapLimits,
    PooledQuantile,
    ReplicateContext,
    bootstrap_oob_sampler,
    calibrate_limits,
    pooled_quantile,
    replicate_tasks,
    run_replicate,
)
from voracious.domain.common import EstimationError, SerialTaskMapper, TaskMapper
from voracious.domain.estimators.mrcd import (
    MRCD_FIT_FAILED,
    MRCDEstimator,
    MRCDParams,
    fit_mrcd,
)

ESTIMATOR = MRCDEstimator(MRCDParams())


def _calibrate(
    x: np.ndarray, mapper: TaskMapper, seed: int = 11, b: int = 5, sampler: object = None
) -> BootstrapLimits:
    return calibrate_limits(
        x,
        estimator=ESTIMATOR,
        sampler=bootstrap_oob_sampler if sampler is None else sampler,
        n_replicates=b,
        seed=seed,
        alpha=DEFAULT_ALPHA_LIMIT,
        phase2_alpha=DEFAULT_PHASE2_ALPHA_LIMIT,
        aggregation=pooled_quantile,
        phase2_aggregation=pooled_quantile,
        mapper=mapper,
    )


def test_seeds_use_fixed_slots_of_seed_sequence() -> None:
    tasks = replicate_tasks(5, 3)
    assert [t.index for t in tasks] == [0, 1, 2]
    # Réplica i = hijo (0, i) de la calibración; con clave k, hijo k + (0, i).
    for task, i in zip(tasks, range(3), strict=True):
        assert task.seed.entropy == 5
        assert task.seed.spawn_key == (0, i)
    keyed = replicate_tasks(5, 2, spawn_key=(1, 4))
    assert [t.seed.spawn_key for t in keyed] == [(1, 4, 0, 0), (1, 4, 0, 1)]
    # Cambiar B no desplaza las semillas de las réplicas existentes.
    assert replicate_tasks(5, 10)[2].seed.spawn_key == tasks[2].seed.spawn_key


def test_replicate_fits_on_the_sample_and_scores_sample_and_oob() -> None:
    x = small_data()
    task = replicate_tasks(3, 1)[0]
    context = ReplicateContext(x_clean=x, estimator=ESTIMATOR, sampler=bootstrap_oob_sampler)
    out = run_replicate(context, task)
    assert out.failure is None
    # Mismos índices que el muestreador con la misma semilla: con reemplazo, tamaño n_clean.
    idx = np.random.default_rng(task.seed).integers(0, x.shape[0], size=x.shape[0])
    assert np.unique(idx).size < x.shape[0]
    oob = np.setdiff1d(np.arange(x.shape[0]), idx)
    fit = fit_mrcd(x[idx], MRCDParams())
    assert np.array_equal(out.t2_in, fit.mah)
    # Fase II: T² de las filas que no entraron, con el ajuste de la muestra (no el de la base).
    assert np.array_equal(out.t2_oob, fit.distances(x[oob]))
    assert out.t2_oob.shape == (oob.size,)
    assert not np.allclose(out.t2_oob, fit_mrcd(x, MRCDParams()).distances(x[oob]))


def test_bootstrap_oob_sampler() -> None:
    x = np.arange(20.0).reshape(10, 2)
    sample, oob = bootstrap_oob_sampler.sample(x, np.random.default_rng(1))
    assert bootstrap_oob_sampler.name == "bootstrap_oob"
    assert sample.shape == (10, 2)
    used = {int(r[0]) for r in sample}
    assert {int(r[0]) for r in oob} == set(range(0, 20, 2)) - used
    assert np.all(np.diff(oob[:, 0]) > 0)  # en orden de fila


def test_limits_record_provenance() -> None:
    x = small_data()
    limits = _calibrate(x, SerialTaskMapper())
    assert limits.n_replicates == 5
    assert limits.seed == 11
    assert limits.spawn_key == ()
    assert limits.n_clean == 40
    assert limits.alpha_limit == DEFAULT_ALPHA_LIMIT
    assert limits.phase2_alpha_limit == DEFAULT_PHASE2_ALPHA_LIMIT
    assert limits.estimator_name == "mrcd"
    assert limits.sampler_name == "bootstrap_oob"
    context = ReplicateContext(x_clean=x, estimator=ESTIMATOR, sampler=bootstrap_oob_sampler)
    outcomes = [run_replicate(context, t) for t in replicate_tasks(11, 5)]
    assert limits.phase1_limit == pooled_quantile([o.t2_in for o in outcomes], 0.005)
    assert limits.phase2_limit == pooled_quantile([o.t2_oob for o in outcomes], 0.005)
    sizes = [o.t2_oob.size for o in outcomes]
    assert limits.oob_size_min == min(sizes)
    assert limits.oob_size_mean == pytest.approx(np.mean(sizes))
    # M6: error Monte Carlo con su propio hueco de semilla, (1, 0) y (1, 1).
    assert limits.phase1_mc_error == pooled_quantile.mc_error(
        [o.t2_in for o in outcomes], 0.005, np.random.SeedSequence(11, spawn_key=(1, 0))
    )
    assert limits.phase2_mc_error == pooled_quantile.mc_error(
        [o.t2_oob for o in outcomes], 0.005, np.random.SeedSequence(11, spawn_key=(1, 1))
    )
    assert limits.phase1_mc_error > 0.0
    assert limits.phase2_mc_error > 0.0
    assert limits.phase2_exceeds_phase1 == (limits.phase2_limit > limits.phase1_limit)


def test_mc_error_is_not_available_with_one_replicate() -> None:
    # Con B = 1 el error Monte Carlo no está disponible (None), no es 0.
    limits = _calibrate(small_data(), SerialTaskMapper(), b=1)
    assert limits.phase1_mc_error is None
    assert limits.phase2_mc_error is None


def test_limits_do_not_depend_on_execution_order() -> None:
    # (h) reproducibilidad: en serie, en orden inverso y en procesos reales.
    x = small_data()
    reversed_mapper = ReversedTaskMapper()
    serial = _calibrate(x, SerialTaskMapper())
    backwards = _calibrate(x, reversed_mapper)
    assert reversed_mapper.executed == [4, 3, 2, 1, 0]
    assert serial == backwards
    assert serial != _calibrate(x, SerialTaskMapper(), seed=12)


def test_run_replicate_under_real_process_pool() -> None:
    x = small_data()
    assert _calibrate(x, ProcessPoolTaskMapper(max_workers=2)) == _calibrate(x, SerialTaskMapper())


def test_replicate_failure_fails_whole_calibration() -> None:
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
    details = err.details["error_details"]
    assert isinstance(details, dict)
    assert "r_message" in details


def test_failure_outcome_is_returned_not_raised() -> None:
    x = small_data()
    x[:, 0] = 1.0
    context = ReplicateContext(x_clean=x, estimator=ESTIMATOR, sampler=bootstrap_oob_sampler)
    out = run_replicate(context, replicate_tasks(1, 1)[0])
    assert out.failure is not None
    assert out.failure.code == MRCD_FIT_FAILED
    assert out.t2_in.size == 0
    assert out.t2_oob.size == 0


def test_empty_oob_fails_without_discarding(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(MRCDEstimator, "fit", lambda self, x: calls.append(x))
    with pytest.raises(EstimationError) as info:
        _calibrate(small_data(), SerialTaskMapper(), sampler=EmptyNewSampler())
    assert info.value.code == BOOTSTRAP_OOB_EMPTY
    assert info.value.details["replicate_index"] == 0
    assert info.value.details["error_code"] == BOOTSTRAP_OOB_EMPTY
    assert calls == []  # se comprueba antes de ajustar


def test_single_clean_row_has_empty_oob() -> None:
    # Con el muestreador de producción y una sola fila limpia nunca queda out-of-bag.
    with pytest.raises(EstimationError) as info:
        _calibrate(small_data(1, 4), SerialTaskMapper(), b=2)
    assert info.value.code == BOOTSTRAP_OOB_EMPTY


class _NanAggregation(PooledQuantile):
    def __call__(self, t2_by_replicate: Sequence[np.ndarray], alpha: float) -> float:
        return float("nan")


@pytest.mark.parametrize("phase", ["phase1", "phase2"])
def test_non_finite_limit_is_an_error(phase: str) -> None:
    nan = _NanAggregation()
    with pytest.raises(EstimationError) as info:
        calibrate_limits(
            small_data(),
            estimator=ESTIMATOR,
            sampler=bootstrap_oob_sampler,
            n_replicates=2,
            seed=1,
            alpha=DEFAULT_ALPHA_LIMIT,
            phase2_alpha=DEFAULT_PHASE2_ALPHA_LIMIT,
            aggregation=nan if phase == "phase1" else pooled_quantile,
            phase2_aggregation=nan if phase == "phase2" else pooled_quantile,
            mapper=SerialTaskMapper(),
        )
    assert info.value.code == BOOTSTRAP_LIMIT_NOT_FINITE
    assert info.value.details == {"limit": "nan", "phase": phase}


class _DroppingMapper:
    def map[C, T, R](self, fn: Callable[[C, T], R], context: C, tasks: Sequence[T]) -> list[R]:
        return [fn(context, t) for t in tasks[:-1]]


def test_mapper_must_return_one_outcome_per_replicate() -> None:
    with pytest.raises(RuntimeError, match="una salida por réplica"):
        _calibrate(small_data(), _DroppingMapper(), b=2)
