"""Carta T²MRCD: la carta por defecto, con MRCD como estimador (``docs/metodos/t2mrcd.md``).

Solo importa ``domain.common`` y ``domain.estimators.mrcd`` (contratos de import-linter).
"""

from voracious.domain.charts.t2mrcd.aggregation import (
    QUANTILE_METHOD,
    mean_of_replicate_quantiles,
)
from voracious.domain.charts.t2mrcd.bootstrap import (
    BOOTSTRAP_LIMIT_NOT_FINITE,
    BOOTSTRAP_REPLICATE_FAILED,
    BootstrapLimits,
    ReplicateContext,
    ReplicateOutcome,
    ReplicateTask,
    calibrate_limits,
    replicate_tasks,
    run_replicate,
)
from voracious.domain.charts.t2mrcd.chart import (
    CHART_ID,
    STATISTIC_REFERENCE,
    T2MRCD_CLEAN_CRITERION_INVALID,
    T2MRCD_DECISION_PENDING,
    T2MRCD_NO_CLEAN_OBSERVATIONS,
    T2MRCDChart,
)
from voracious.domain.charts.t2mrcd.clean import best_subset_criterion
from voracious.domain.charts.t2mrcd.model import T2MRCDModel, T2MRCDMonitoring
from voracious.domain.charts.t2mrcd.params import (
    DEFAULT_ALPHA_LIMIT,
    DEFAULT_N_REPLICATES,
    T2MRCD_MRCD_ALPHA,
    CleanCriterion,
    LimitAggregation,
    T2MRCDBootstrap,
    T2MRCDParams,
)
from voracious.domain.charts.t2mrcd.statistic import t2

__all__ = [
    "BOOTSTRAP_LIMIT_NOT_FINITE",
    "BOOTSTRAP_REPLICATE_FAILED",
    "CHART_ID",
    "DEFAULT_ALPHA_LIMIT",
    "DEFAULT_N_REPLICATES",
    "QUANTILE_METHOD",
    "STATISTIC_REFERENCE",
    "T2MRCD_CLEAN_CRITERION_INVALID",
    "T2MRCD_DECISION_PENDING",
    "T2MRCD_MRCD_ALPHA",
    "T2MRCD_NO_CLEAN_OBSERVATIONS",
    "BootstrapLimits",
    "CleanCriterion",
    "LimitAggregation",
    "ReplicateContext",
    "ReplicateOutcome",
    "ReplicateTask",
    "T2MRCDBootstrap",
    "T2MRCDChart",
    "T2MRCDModel",
    "T2MRCDMonitoring",
    "T2MRCDParams",
    "best_subset_criterion",
    "calibrate_limits",
    "mean_of_replicate_quantiles",
    "replicate_tasks",
    "run_replicate",
    "t2",
]
