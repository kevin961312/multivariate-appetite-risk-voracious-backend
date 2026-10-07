import numpy as np
import pytest

from voracious.domain.charts.t2mrcd import (
    DEFAULT_ALPHA_LIMIT,
    DEFAULT_N_REPLICATES,
    T2MRCD_MRCD_ALPHA,
    T2MRCDBootstrap,
    T2MRCDParams,
    best_subset_criterion,
    mean_of_replicate_quantiles,
)
from voracious.domain.common import InvalidInputError
from voracious.domain.estimators.mrcd import MRCDParams


def test_production_defaults_and_nothing_pending() -> None:
    boot = T2MRCDBootstrap(seed=1)
    assert boot.n_replicates == DEFAULT_N_REPLICATES == 100  # dueño (P3), Heng, Shen y Lange
    assert boot.alpha_limit == DEFAULT_ALPHA_LIMIT == 0.005  # dueño 2026-10-07 (P4)
    assert boot.clean_criterion is best_subset_criterion  # dueño 2026-10-07 (P2)
    assert boot.aggregation is mean_of_replicate_quantiles  # dueño 2026-10-07 (P4, opción b)
    assert boot.pending_fields() == []
    assert T2MRCDBootstrap(seed=1, aggregation=None).pending_fields() == ["bootstrap.aggregation"]
    params = T2MRCDParams(bootstrap=boot)
    assert params.mrcd.alpha == T2MRCD_MRCD_ALPHA == 0.75  # dueño 2026-10-07 (P2)
    assert params.mrcd == MRCDParams(alpha=0.75)
    # El adaptador conserva el default de rrcov; solo cambia el de la carta.
    assert MRCDParams().alpha == 0.5


def test_seed_is_mandatory() -> None:
    with pytest.raises(TypeError):
        T2MRCDBootstrap(**{})


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"seed": 1, "n_replicates": 0}, "bootstrap.n_replicates"),
        ({"seed": 1, "n_replicates": True}, "bootstrap.n_replicates"),
        ({"seed": 1, "n_replicates": 2.5}, "bootstrap.n_replicates"),
        ({"seed": 1, "n_replicates": 3.0}, "bootstrap.n_replicates"),
        ({"seed": 1, "n_replicates": "3"}, "bootstrap.n_replicates"),
        ({"seed": 1.0}, "bootstrap.seed"),
        ({"seed": True}, "bootstrap.seed"),
        ({"seed": -1}, "bootstrap.seed"),
        ({"seed": False}, "bootstrap.seed"),
        ({"seed": 1, "alpha_limit": 0.0}, "bootstrap.alpha_limit"),
        ({"seed": 1, "alpha_limit": 1.0}, "bootstrap.alpha_limit"),
    ],
)
def test_invalid_bootstrap_values(kwargs: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidInputError) as info:
        T2MRCDBootstrap(**kwargs)
    assert info.value.details["field"] == field


def test_numpy_integers_are_accepted() -> None:
    boot = T2MRCDBootstrap(seed=np.int64(3), n_replicates=np.int32(4))  # enteros de numpy
    assert boot.n_replicates == 4
    assert boot.seed == 3
