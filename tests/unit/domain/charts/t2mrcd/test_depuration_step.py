"""``depuration_step``: una ronda de la depuración automática, pura (vuelta 3.2, T14)."""

from dataclasses import dataclass

import numpy as np

from voracious.domain.charts.t2mrcd import DepurationStep, depurate, depuration_step


@dataclass(frozen=True)
class _Stage:
    """Ronda falsa: T² = primera columna."""

    limit: float

    @property
    def phase1_limit(self) -> float:
        return self.limit

    def t2(self, x: np.ndarray) -> np.ndarray:
        return x[:, 0]


def _step(
    x: np.ndarray, kept: np.ndarray, round_index: int, *, max_rounds: int = 5, min_rows: int = 1
) -> DepurationStep:
    rows = np.flatnonzero(kept).astype(np.int64)
    return depuration_step(
        _Stage(5.0), x[rows], rows, kept, round_index, max_rounds=max_rounds, min_rows=min_rows
    )


def test_converges_when_no_row_is_above_the_limit() -> None:
    x = np.array([[1.0], [2.0], [9.0]])
    kept = np.array([True, True, False])
    step = _step(x, kept, 2)
    assert step.converged
    assert step.final
    assert not step.exhausted
    assert step.kept.tolist() == [True, True, False]
    assert not step.excluded_automatic_now.any()
    assert step.above_t2.tolist() == [False, False]
    assert step.kept is not kept


def test_removes_every_row_above_the_limit_and_continues() -> None:
    x = np.array([[1.0], [9.0], [2.0], [8.0], [3.0]])
    kept = np.array([True, True, True, True, False])
    step = _step(x, kept, 0)
    assert not step.converged
    assert not step.final
    assert step.above_t2.tolist() == [False, True, False, True]
    assert step.kept.tolist() == [True, False, True, False, False]
    assert step.excluded_automatic_now.tolist() == [False, True, False, True, False]
    assert kept.tolist() == [True, True, True, True, False]  # no muta la entrada


def test_round_limit_reached_keeps_the_rows_and_ends_without_converging() -> None:
    x = np.array([[1.0], [9.0]])
    kept = np.ones(2, dtype=np.bool_)
    step = _step(x, kept, 3, max_rounds=3)
    assert step.final
    assert not step.converged
    assert not step.exhausted
    assert step.kept.all()
    assert not step.excluded_automatic_now.any()
    assert step.above_t2.tolist() == [False, True]


def test_below_min_rows_after_removing_is_exhausted() -> None:
    x = np.array([[1.0], [9.0], [8.0]])
    step = _step(x, np.ones(3, dtype=np.bool_), 0, min_rows=2)
    assert step.final
    assert step.exhausted
    assert not step.converged
    assert step.kept.tolist() == [True, False, False]
    # Con min_rows = 1 la misma ronda sigue.
    assert not _step(x, np.ones(3, dtype=np.bool_), 0, min_rows=1).final


def test_depurate_is_the_loop_of_depuration_step() -> None:
    x = np.array([[1.0], [9.0], [2.0], [8.0], [6.0], [3.0]])
    kept = np.ones(6, dtype=np.bool_)
    seen: list[int] = []

    def fit_round(x_rows: np.ndarray, rows: np.ndarray, r: int) -> _Stage:
        seen.append(r)
        # El límite baja en cada ronda: la ronda 1 vuelve a quitar filas.
        return _Stage(7.0 - 1.5 * r)

    result = depurate(x, kept, fit_round=fit_round, max_rounds=5, min_rows=1)
    assert seen == [0, 1, 2]
    assert result.rounds == 2
    assert result.converged
    assert result.kept.tolist() == [True, False, True, False, False, True]
    assert result.excluded_automatic.tolist() == [False, True, False, True, True, False]
