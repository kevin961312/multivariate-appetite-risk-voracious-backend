"""Estrategias de T²MRCD por nombre y parámetros como datos (mejora M1, Paso 2b.2).

Los parámetros de la carta (``T2MRCDParams``) y de la recalibración
(``T2MRCDRecalibrationParams``) llevan estrategias (agregación, criterio de fila limpia, medida de
cambio, pruebas formales, regla de decisión), que son objetos invocables. Para persistir un modelo,
una versión o una recalibración sin guardar invocables, la aplicación guarda los parámetros
**codificados**: solo números, textos, booleanos, ``None`` y diccionarios, con cada estrategia por
su nombre estable. ``T2MRCDStrategies`` es el registro ``nombre → objeto`` con el que se
decodifican.

``DEFAULT_STRATEGIES`` solo contiene las estrategias de producción ya decididas
(``docs/metodos/t2mrcd.md``); las pruebas formales de cambio están pendientes de cita y no tienen
ninguna entrada. Los tests registran sus estrategias «SOLO TEST» en una copia
(``dataclasses.replace``), nunca en ``src/``.

El muestreador de réplicas (``bootstrap_oob``) y el estimador (MRCD, ADR 0002) no son parámetros:
los fija la carta, así que no se registran; sus nombres ya quedan en ``BootstrapLimits``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

import numpy as np

from voracious.domain.charts.t2mrcd.aggregation import pooled_quantile
from voracious.domain.charts.t2mrcd.clean import best_subset_criterion
from voracious.domain.charts.t2mrcd.comparison import (
    CovarianceChangeTest,
    DecisionRule,
    MeanChangeTest,
    RelativeChangeMetric,
    any_formal_test_change,
    frobenius_relative_change,
)
from voracious.domain.charts.t2mrcd.params import (
    T2MRCD_MRCD_ALPHA,
    CleanCriterion,
    LimitAggregation,
    T2MRCDBootstrap,
    T2MRCDParams,
)
from voracious.domain.charts.t2mrcd.revalidation import T2MRCDRecalibrationParams
from voracious.domain.common import InvalidInputError
from voracious.domain.estimators.mrcd import MRCDParams, MRCDTarget

__all__ = [
    "BEST_SUBSET_CRITERION_NAME",
    "DEFAULT_STRATEGIES",
    "T2MRCDStrategies",
    "decode_mrcd_params",
    "decode_params",
    "decode_recalibration_params",
    "encode_mrcd_params",
    "encode_params",
    "encode_recalibration_params",
]

BEST_SUBSET_CRITERION_NAME: Final = "best_subset"
"""Nombre estable de ``best_subset_criterion`` (es una función y no tiene atributo ``name``)."""

_BOOTSTRAP_FIELDS: Final = frozenset(
    {
        "n_replicates",
        "seed",
        "alpha_limit",
        "clean_criterion",
        "aggregation",
        "phase2_alpha_limit",
        "phase2_aggregation",
    }
)
_MRCD_FIELDS: Final = frozenset({"alpha", "h", "maxcsteps", "rho", "target", "maxcond"})
_PARAMS_FIELDS: Final = frozenset({"bootstrap", "mrcd", "max_depuration_rounds"})
_RECALIBRATION_FIELDS: Final = frozenset(
    {
        "seed",
        "min_observations",
        "max_depuration_rounds",
        "relative_change_threshold",
        "threshold_decides",
        "relative_change_metric",
        "covariance_test",
        "mean_test",
        "decision_rule",
        "n_test_resamples",
    }
)


@dataclass(frozen=True)
class T2MRCDStrategies:
    """Registro ``nombre → estrategia`` de T²MRCD, una tabla por tipo.

    Attributes:
        clean_criteria: Criterios de fila limpia.
        aggregations: Agregaciones de límites (Fase I y Fase II).
        relative_change_metrics: Medidas del cambio relativo de la dispersión.
        covariance_tests: Pruebas formales de dispersión (vacío en producción: pendientes).
        mean_tests: Pruebas formales de ubicación (vacío en producción: pendientes).
        decision_rules: Reglas de decisión sobre las pruebas formales.
    """

    clean_criteria: Mapping[str, CleanCriterion] = field(
        default_factory=lambda: {BEST_SUBSET_CRITERION_NAME: best_subset_criterion}
    )
    aggregations: Mapping[str, LimitAggregation] = field(
        default_factory=lambda: {pooled_quantile.name: pooled_quantile}
    )
    relative_change_metrics: Mapping[str, RelativeChangeMetric] = field(
        default_factory=lambda: {frobenius_relative_change.name: frobenius_relative_change}
    )
    covariance_tests: Mapping[str, CovarianceChangeTest] = field(default_factory=dict)
    mean_tests: Mapping[str, MeanChangeTest] = field(default_factory=dict)
    decision_rules: Mapping[str, DecisionRule] = field(
        default_factory=lambda: {any_formal_test_change.name: any_formal_test_change}
    )


DEFAULT_STRATEGIES: Final = T2MRCDStrategies()
"""Registro de producción: solo las estrategias decididas (``docs/metodos/t2mrcd.md``)."""


def _resolve[T](table: Mapping[str, T], name: object, field_name: str) -> T:
    """Devuelve la estrategia registrada con ``name``.

    Args:
        table: Tabla del tipo de estrategia.
        name: Nombre leído de los datos.
        field_name: Campo, para el mensaje de error.

    Returns:
        La estrategia.

    Raises:
        InvalidInputError: Si ``name`` no es texto o no está registrado.
    """
    if not isinstance(name, str) or name not in table:
        raise InvalidInputError(
            f"estrategia desconocida en '{field_name}': {name!r}",
            details={
                "field": field_name,
                "reason": "unknown_strategy",
                "name": name if isinstance(name, str) else repr(name),
                "known": sorted(table),
            },
        )
    return table[name]


def _resolve_optional[T](table: Mapping[str, T], name: object, field_name: str) -> T | None:
    """Como ``_resolve``, pero ``None`` (decisión pendiente) se conserva.

    Args:
        table: Tabla del tipo de estrategia.
        name: Nombre leído de los datos, o ``None``.
        field_name: Campo, para el mensaje de error.

    Returns:
        La estrategia o ``None``.
    """
    return None if name is None else _resolve(table, name, field_name)


def _name_of[T](table: Mapping[str, T], strategy: T, field_name: str) -> str:
    """Nombre con el que está registrada una estrategia.

    Args:
        table: Tabla del tipo de estrategia.
        strategy: Estrategia a codificar.
        field_name: Campo, para el mensaje de error.

    Returns:
        Su nombre en el registro.

    Raises:
        InvalidInputError: Si la estrategia no está registrada (no se podría decodificar).
    """
    for name, registered in table.items():
        if registered is strategy or registered == strategy:
            return name
    raise InvalidInputError(
        f"la estrategia de '{field_name}' no está registrada y no se puede persistir",
        details={"field": field_name, "reason": "unregistered_strategy", "known": sorted(table)},
    )


def _name_of_optional[T](table: Mapping[str, T], strategy: T | None, field_name: str) -> str | None:
    """Como ``_name_of``, pero ``None`` (decisión pendiente) se conserva.

    Args:
        table: Tabla del tipo de estrategia.
        strategy: Estrategia o ``None``.
        field_name: Campo, para el mensaje de error.

    Returns:
        Su nombre o ``None``.
    """
    return None if strategy is None else _name_of(table, strategy, field_name)


def _mapping(data: object, field_name: str, allowed: frozenset[str]) -> Mapping[str, object]:
    """Comprueba que ``data`` sea un diccionario con claves conocidas.

    Args:
        data: Valor leído.
        field_name: Campo, para el mensaje de error.
        allowed: Claves admitidas.

    Returns:
        El diccionario.

    Raises:
        InvalidInputError: Si no es un diccionario de claves de texto o tiene claves desconocidas.
    """
    if not isinstance(data, Mapping) or not all(isinstance(k, str) for k in data):
        raise InvalidInputError(
            f"'{field_name}' debe ser un diccionario", details={"field": field_name}
        )
    unknown = sorted(str(k) for k in data if k not in allowed)
    if unknown:
        raise InvalidInputError(
            f"'{field_name}' tiene campos desconocidos: {unknown}",
            details={"field": field_name, "reason": "unknown_fields", "unknown": unknown},
        )
    return data


def _int(value: object, field_name: str) -> int:
    """Entero estricto (sin ``bool`` ni ``float``).

    Args:
        value: Valor leído.
        field_name: Campo.

    Returns:
        El entero.

    Raises:
        InvalidInputError: Si no es entero.
    """
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise InvalidInputError(f"'{field_name}' debe ser entero", details={"field": field_name})
    return int(value)


def _float(value: object, field_name: str) -> float:
    """Número real (se admiten enteros, no ``bool``).

    Args:
        value: Valor leído.
        field_name: Campo.

    Returns:
        El número como ``float``.

    Raises:
        InvalidInputError: Si no es numérico.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        raise InvalidInputError(f"'{field_name}' debe ser numérico", details={"field": field_name})
    return float(value)


def _bool(value: object, field_name: str) -> bool:
    """Booleano estricto.

    Args:
        value: Valor leído.
        field_name: Campo.

    Returns:
        El booleano.

    Raises:
        InvalidInputError: Si no es booleano.
    """
    if not isinstance(value, bool):
        raise InvalidInputError(f"'{field_name}' debe ser booleano", details={"field": field_name})
    return value


def _encode_mrcd(params: MRCDParams) -> dict[str, object]:
    """Codifica los parámetros de MRCD (ya son datos).

    Args:
        params: Parámetros de MRCD.

    Returns:
        Diccionario con los seis campos.
    """
    return {
        "alpha": params.alpha,
        "h": params.h,
        "maxcsteps": params.maxcsteps,
        "rho": params.rho,
        "target": params.target,
        "maxcond": params.maxcond,
    }


def _decode_mrcd(data: object) -> MRCDParams:
    """Decodifica los parámetros de MRCD; un campo ausente toma el default de la carta.

    El default de la carta es ``MRCDParams(alpha=T2MRCD_MRCD_ALPHA)`` (``T2MRCDParams``); los
    demás defaults son los de ``rrcov`` citados en ``MRCDParams``.

    Args:
        data: Diccionario de MRCD.

    Returns:
        Los parámetros.

    Raises:
        InvalidInputError: Si un campo tiene un tipo inválido.
    """
    raw = _mapping(data, "mrcd", _MRCD_FIELDS)
    base = MRCDParams(alpha=T2MRCD_MRCD_ALPHA)
    target: MRCDTarget = base.target
    if "target" in raw:
        if raw["target"] == "identity":
            target = "identity"
        elif raw["target"] == "equicorrelation":
            target = "equicorrelation"
        else:
            raise InvalidInputError(
                "'mrcd.target' debe ser 'identity' o 'equicorrelation'",
                details={"field": "mrcd.target"},
            )
    h, rho = raw.get("h", base.h), raw.get("rho", base.rho)
    return MRCDParams(
        alpha=_float(raw["alpha"], "mrcd.alpha") if "alpha" in raw else base.alpha,
        h=None if h is None else _int(h, "mrcd.h"),
        maxcsteps=_int(raw["maxcsteps"], "mrcd.maxcsteps")
        if "maxcsteps" in raw
        else base.maxcsteps,
        rho=None if rho is None else _float(rho, "mrcd.rho"),
        target=target,
        maxcond=_float(raw["maxcond"], "mrcd.maxcond") if "maxcond" in raw else base.maxcond,
    )


def encode_mrcd_params(params: MRCDParams) -> dict[str, object]:
    """Codifica los parámetros de MRCD de la carta (ajuste suelto ``/fits``, vuelta 3.3).

    Args:
        params: Parámetros de MRCD.

    Returns:
        Diccionario con los seis campos (el mismo que ``encode_params(...)["mrcd"]``).
    """
    return _encode_mrcd(params)


def decode_mrcd_params(data: object) -> MRCDParams:
    """Decodifica los parámetros de MRCD; un campo ausente toma el default de la carta.

    Args:
        data: Diccionario de MRCD.

    Returns:
        Los parámetros.

    Raises:
        InvalidInputError: Si un campo es desconocido o tiene un tipo inválido.
    """
    return _decode_mrcd(data)


def encode_params(
    params: T2MRCDParams, strategies: T2MRCDStrategies = DEFAULT_STRATEGIES
) -> dict[str, object]:
    """Codifica los parámetros de la carta como datos (estrategias por nombre).

    Args:
        params: Parámetros de la carta.
        strategies: Registro con el que se buscan los nombres.

    Returns:
        Diccionario serializable (números, textos, ``None`` y diccionarios).

    Raises:
        InvalidInputError: Si alguna estrategia no está registrada.
    """
    boot = params.bootstrap
    return {
        "bootstrap": {
            "n_replicates": boot.n_replicates,
            "seed": boot.seed,
            "alpha_limit": boot.alpha_limit,
            "clean_criterion": _name_of(
                strategies.clean_criteria, boot.clean_criterion, "bootstrap.clean_criterion"
            ),
            "aggregation": _name_of_optional(
                strategies.aggregations, boot.aggregation, "bootstrap.aggregation"
            ),
            "phase2_alpha_limit": boot.phase2_alpha_limit,
            "phase2_aggregation": _name_of_optional(
                strategies.aggregations, boot.phase2_aggregation, "bootstrap.phase2_aggregation"
            ),
        },
        "mrcd": _encode_mrcd(params.mrcd),
        "max_depuration_rounds": params.max_depuration_rounds,
    }


def _decode_bootstrap(data: object, strategies: T2MRCDStrategies) -> T2MRCDBootstrap:
    """Decodifica el bootstrap; un campo ausente toma el default de ``T2MRCDBootstrap``.

    Args:
        data: Diccionario del bootstrap.
        strategies: Registro de estrategias.

    Returns:
        La configuración del bootstrap.

    Raises:
        InvalidInputError: Si falta ``seed``, un campo es inválido o una estrategia es
            desconocida.
    """
    raw = _mapping(data, "bootstrap", _BOOTSTRAP_FIELDS)
    if "seed" not in raw:
        raise InvalidInputError(
            "'bootstrap.seed' es obligatoria", details={"field": "bootstrap.seed"}
        )
    default = T2MRCDBootstrap(seed=_int(raw["seed"], "bootstrap.seed"))
    return T2MRCDBootstrap(
        n_replicates=_int(raw["n_replicates"], "bootstrap.n_replicates")
        if "n_replicates" in raw
        else default.n_replicates,
        seed=default.seed,
        alpha_limit=_float(raw["alpha_limit"], "bootstrap.alpha_limit")
        if "alpha_limit" in raw
        else default.alpha_limit,
        clean_criterion=_resolve(
            strategies.clean_criteria, raw["clean_criterion"], "bootstrap.clean_criterion"
        )
        if "clean_criterion" in raw
        else default.clean_criterion,
        aggregation=_resolve_optional(
            strategies.aggregations, raw["aggregation"], "bootstrap.aggregation"
        )
        if "aggregation" in raw
        else default.aggregation,
        phase2_alpha_limit=_float(raw["phase2_alpha_limit"], "bootstrap.phase2_alpha_limit")
        if "phase2_alpha_limit" in raw
        else default.phase2_alpha_limit,
        phase2_aggregation=_resolve_optional(
            strategies.aggregations, raw["phase2_aggregation"], "bootstrap.phase2_aggregation"
        )
        if "phase2_aggregation" in raw
        else default.phase2_aggregation,
    )


def decode_params(
    data: Mapping[str, object], strategies: T2MRCDStrategies = DEFAULT_STRATEGIES
) -> T2MRCDParams:
    """Decodifica los parámetros de la carta (inversa de ``encode_params``).

    Un campo ausente toma el default de la dataclass correspondiente (citados en ``params.py``);
    ``bootstrap.seed`` es obligatoria. Un campo desconocido es un error.

    Args:
        data: Parámetros codificados.
        strategies: Registro de estrategias.

    Returns:
        Los parámetros.

    Raises:
        InvalidInputError: Campo desconocido o inválido, o estrategia desconocida
            (``details["reason"] == "unknown_strategy"``).
    """
    raw = _mapping(data, "params", _PARAMS_FIELDS)
    if "bootstrap" not in raw:
        raise InvalidInputError("'bootstrap' es obligatorio", details={"field": "bootstrap"})
    bootstrap = _decode_bootstrap(raw["bootstrap"], strategies)
    default = T2MRCDParams(bootstrap=bootstrap)
    return T2MRCDParams(
        bootstrap=bootstrap,
        mrcd=_decode_mrcd(raw["mrcd"]) if "mrcd" in raw else default.mrcd,
        max_depuration_rounds=_int(raw["max_depuration_rounds"], "max_depuration_rounds")
        if "max_depuration_rounds" in raw
        else default.max_depuration_rounds,
    )


def encode_recalibration_params(
    params: T2MRCDRecalibrationParams, strategies: T2MRCDStrategies = DEFAULT_STRATEGIES
) -> dict[str, object]:
    """Codifica los parámetros de la recalibración como datos (estrategias por nombre).

    Args:
        params: Parámetros de la recalibración.
        strategies: Registro con el que se buscan los nombres.

    Returns:
        Diccionario serializable.

    Raises:
        InvalidInputError: Si alguna estrategia no está registrada.
    """
    return {
        "seed": params.seed,
        "min_observations": params.min_observations,
        "max_depuration_rounds": params.max_depuration_rounds,
        "relative_change_threshold": params.relative_change_threshold,
        "threshold_decides": params.threshold_decides,
        "relative_change_metric": _name_of(
            strategies.relative_change_metrics,
            params.relative_change_metric,
            "recalibration.relative_change_metric",
        ),
        "covariance_test": _name_of_optional(
            strategies.covariance_tests, params.covariance_test, "recalibration.covariance_test"
        ),
        "mean_test": _name_of_optional(
            strategies.mean_tests, params.mean_test, "recalibration.mean_test"
        ),
        "decision_rule": _name_of(
            strategies.decision_rules, params.decision_rule, "recalibration.decision_rule"
        ),
        "n_test_resamples": params.n_test_resamples,
    }


def decode_recalibration_params(
    data: Mapping[str, object], strategies: T2MRCDStrategies = DEFAULT_STRATEGIES
) -> T2MRCDRecalibrationParams:
    """Decodifica los parámetros de la recalibración (inversa de ``encode_recalibration_params``).

    Un campo ausente toma el default de ``T2MRCDRecalibrationParams`` (citados en
    ``revalidation.py``); ``seed`` es obligatoria.

    Args:
        data: Parámetros codificados.
        strategies: Registro de estrategias.

    Returns:
        Los parámetros.

    Raises:
        InvalidInputError: Campo desconocido o inválido, o estrategia desconocida.
    """
    raw = _mapping(data, "recalibration", _RECALIBRATION_FIELDS)
    if "seed" not in raw:
        raise InvalidInputError(
            "'recalibration.seed' es obligatoria", details={"field": "recalibration.seed"}
        )
    default = T2MRCDRecalibrationParams(seed=_int(raw["seed"], "recalibration.seed"))
    n_test_resamples = raw.get("n_test_resamples", default.n_test_resamples)
    return T2MRCDRecalibrationParams(
        seed=default.seed,
        min_observations=_int(raw["min_observations"], "recalibration.min_observations")
        if "min_observations" in raw
        else default.min_observations,
        max_depuration_rounds=_int(
            raw["max_depuration_rounds"], "recalibration.max_depuration_rounds"
        )
        if "max_depuration_rounds" in raw
        else default.max_depuration_rounds,
        relative_change_threshold=_float(
            raw["relative_change_threshold"], "recalibration.relative_change_threshold"
        )
        if "relative_change_threshold" in raw
        else default.relative_change_threshold,
        threshold_decides=_bool(raw["threshold_decides"], "recalibration.threshold_decides")
        if "threshold_decides" in raw
        else default.threshold_decides,
        relative_change_metric=_resolve(
            strategies.relative_change_metrics,
            raw["relative_change_metric"],
            "recalibration.relative_change_metric",
        )
        if "relative_change_metric" in raw
        else default.relative_change_metric,
        covariance_test=_resolve_optional(
            strategies.covariance_tests, raw["covariance_test"], "recalibration.covariance_test"
        )
        if "covariance_test" in raw
        else default.covariance_test,
        mean_test=_resolve_optional(
            strategies.mean_tests, raw["mean_test"], "recalibration.mean_test"
        )
        if "mean_test" in raw
        else default.mean_test,
        decision_rule=_resolve(
            strategies.decision_rules, raw["decision_rule"], "recalibration.decision_rule"
        )
        if "decision_rule" in raw
        else default.decision_rule,
        n_test_resamples=None
        if n_test_resamples is None
        else _int(n_test_resamples, "recalibration.n_test_resamples"),
    )
