"""Codificación del modelo y del informe de recalibración de T²MRCD como datos (mejora M1).

El modelo se persiste sin objetos de Python: los parámetros con ``encode_params`` (estrategias por
nombre, ``registry.py``), el ajuste MRCD con ``encode_fit``, cada arreglo con ``encode_array``
(``dtype``, forma y bytes exactos), y ``BootstrapLimits``, ``LimitRegime`` y ``RowDisposition``
por valor. La ida y vuelta es exacta en bits: la Fase II con el modelo decodificado da los mismos
T² y señales. Un campo desconocido o ausente es un error (``InvalidInputError``), y también un
``format_version`` distinto del que entiende este módulo.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from voracious.domain.charts.t2mrcd.bootstrap import BootstrapLimits
from voracious.domain.charts.t2mrcd.comparison import ChangeTestResult, ComparisonResult
from voracious.domain.charts.t2mrcd.model import LimitRegime, T2MRCDModel
from voracious.domain.charts.t2mrcd.registry import (
    DEFAULT_STRATEGIES,
    T2MRCDStrategies,
    decode_params,
    encode_params,
)
from voracious.domain.charts.t2mrcd.revalidation import LimitsSnapshot, T2MRCDRecalibrationReport
from voracious.domain.common import InvalidInputError, RecalibrationDecision, RowDisposition
from voracious.domain.common.codec import (
    decode_bool_array,
    decode_float_array,
    encode_array,
    read_bool,
    read_float,
    read_int,
    read_mapping,
    read_optional_bool,
    read_optional_float,
    read_str,
)
from voracious.domain.estimators.mrcd import decode_fit, encode_fit

__all__ = [
    "MODEL_FORMAT_VERSION",
    "REPORT_FORMAT_VERSION",
    "decode_comparison",
    "decode_limits",
    "decode_model",
    "decode_report",
    "encode_comparison",
    "encode_limits",
    "encode_model",
    "encode_report",
]

MODEL_FORMAT_VERSION: Final = 1
"""Versión del formato del modelo codificado (se comprueba al decodificar)."""

REPORT_FORMAT_VERSION: Final = 1
"""Versión del formato del informe codificado (se comprueba al decodificar)."""

_LIMITS_FIELDS: Final = frozenset(
    {
        "phase1_limit",
        "phase2_limit",
        "n_replicates",
        "seed",
        "spawn_key",
        "n_clean",
        "alpha_limit",
        "phase2_alpha_limit",
        "oob_size_min",
        "oob_size_mean",
        "phase1_mc_error",
        "phase2_mc_error",
        "estimator_name",
        "sampler_name",
    }
)
_MODEL_FIELDS: Final = frozenset(
    {
        "format_version",
        "params",
        "mrcd",
        "n_features",
        "base_mask",
        "row_disposition",
        "clean_mask",
        "limits",
        "limit_regime",
        "historical_t2",
        "historical_outlier",
        "depuration_rounds",
        "depuration_converged",
        "final_depuration_skipped",
        "pymrcd_version",
        "seed",
        "statistic_reference",
    }
)
_TEST_FIELDS: Final = frozenset({"name", "statistic", "p_value", "changed"})
_COMPARISON_FIELDS: Final = frozenset(
    {
        "metric_name",
        "relative_change",
        "threshold",
        "exceeds_threshold",
        "threshold_decides",
        "covariance",
        "mean",
        "decision_rule_name",
        "changed",
    }
)
_SNAPSHOT_FIELDS: Final = frozenset(
    {
        "phase1_limit",
        "phase2_limit",
        "phase1_mc_error",
        "phase2_mc_error",
        "regime",
        "operative_limit",
        "n_base",
    }
)
_REPORT_FIELDS: Final = frozenset(
    {
        "format_version",
        "decision",
        "forced",
        "row_disposition",
        "n_base",
        "n_new",
        "n_excluded_assignable_cause",
        "n_excluded_automatic",
        "n_kept_new",
        "min_observations",
        "depuration_rounds",
        "depuration_converged",
        "comparison",
        "before",
        "after",
        "phase2_exceeds_phase1",
    }
)


def _enum[E: StrEnum](cls: type[E], value: object, field: str) -> E:
    """Enumeración por su valor.

    Args:
        cls: Enumeración.
        value: Valor leído.
        field: Campo, para el mensaje.

    Returns:
        El miembro.

    Raises:
        InvalidInputError: Si el valor no es de la enumeración.
    """
    if isinstance(value, str):
        for member in cls:
            if member.value == value:
                return member
    raise InvalidInputError(
        f"'{field}' no es un valor válido de {cls.__name__}: {value!r}",
        details={"field": field, "reason": "invalid_encoding"},
    )


def _list(value: object, field: str) -> list[object]:
    """Lista (o tupla) leída.

    Args:
        value: Valor leído.
        field: Campo.

    Returns:
        Sus elementos.

    Raises:
        InvalidInputError: Si no es una lista.
    """
    if not isinstance(value, list | tuple):
        raise InvalidInputError(
            f"'{field}' debe ser una lista", details={"field": field, "reason": "invalid_encoding"}
        )
    return list(value)


def _format_version(raw: Mapping[str, object], expected: int, field: str) -> None:
    """Comprueba la versión del formato.

    Args:
        raw: Diccionario leído.
        expected: Versión que entiende este módulo.
        field: Campo, para el mensaje.

    Raises:
        InvalidInputError: Si la versión no coincide.
    """
    version = read_int(raw["format_version"], f"{field}.format_version")
    if version != expected:
        raise InvalidInputError(
            f"'{field}' tiene un formato desconocido: {version}",
            details={"field": f"{field}.format_version", "reason": "unknown_format_version"},
        )


def encode_limits(limits: BootstrapLimits) -> dict[str, object]:
    """Codifica los límites bootstrap por valor.

    Args:
        limits: Límites.

    Returns:
        Diccionario serializable.
    """
    return {
        "phase1_limit": limits.phase1_limit,
        "phase2_limit": limits.phase2_limit,
        "n_replicates": limits.n_replicates,
        "seed": limits.seed,
        "spawn_key": list(limits.spawn_key),
        "n_clean": limits.n_clean,
        "alpha_limit": limits.alpha_limit,
        "phase2_alpha_limit": limits.phase2_alpha_limit,
        "oob_size_min": limits.oob_size_min,
        "oob_size_mean": limits.oob_size_mean,
        "phase1_mc_error": limits.phase1_mc_error,
        "phase2_mc_error": limits.phase2_mc_error,
        "estimator_name": limits.estimator_name,
        "sampler_name": limits.sampler_name,
    }


def decode_limits(data: object, field: str = "limits") -> BootstrapLimits:
    """Decodifica los límites bootstrap (inversa de ``encode_limits``).

    Args:
        data: Límites codificados.
        field: Campo, para los mensajes.

    Returns:
        Los límites.

    Raises:
        InvalidInputError: Campo desconocido, ausente o inválido.
    """
    raw = read_mapping(data, field, _LIMITS_FIELDS)
    return BootstrapLimits(
        phase1_limit=read_float(raw["phase1_limit"], f"{field}.phase1_limit"),
        phase2_limit=read_float(raw["phase2_limit"], f"{field}.phase2_limit"),
        n_replicates=read_int(raw["n_replicates"], f"{field}.n_replicates"),
        seed=read_int(raw["seed"], f"{field}.seed"),
        spawn_key=tuple(
            read_int(k, f"{field}.spawn_key") for k in _list(raw["spawn_key"], f"{field}.spawn_key")
        ),
        n_clean=read_int(raw["n_clean"], f"{field}.n_clean"),
        alpha_limit=read_float(raw["alpha_limit"], f"{field}.alpha_limit"),
        phase2_alpha_limit=read_float(raw["phase2_alpha_limit"], f"{field}.phase2_alpha_limit"),
        oob_size_min=read_int(raw["oob_size_min"], f"{field}.oob_size_min"),
        oob_size_mean=read_float(raw["oob_size_mean"], f"{field}.oob_size_mean"),
        phase1_mc_error=read_optional_float(raw["phase1_mc_error"], f"{field}.phase1_mc_error"),
        phase2_mc_error=read_optional_float(raw["phase2_mc_error"], f"{field}.phase2_mc_error"),
        estimator_name=read_str(raw["estimator_name"], f"{field}.estimator_name"),
        sampler_name=read_str(raw["sampler_name"], f"{field}.sampler_name"),
    )


def _dispositions(value: object, field: str) -> tuple[RowDisposition, ...]:
    """Destinos de fila por valor.

    Args:
        value: Lista de valores.
        field: Campo.

    Returns:
        Los destinos.
    """
    return tuple(_enum(RowDisposition, v, field) for v in _list(value, field))


def encode_model(
    model: T2MRCDModel, strategies: T2MRCDStrategies = DEFAULT_STRATEGIES
) -> dict[str, object]:
    """Codifica un modelo de T²MRCD como datos.

    Args:
        model: Modelo (versión inicial o recalibrada).
        strategies: Registro con el que se nombran las estrategias de los parámetros.

    Returns:
        Diccionario serializable.

    Raises:
        InvalidInputError: Si alguna estrategia de los parámetros no está registrada.
    """
    return {
        "format_version": MODEL_FORMAT_VERSION,
        "params": encode_params(model.params, strategies),
        "mrcd": encode_fit(model.mrcd),
        "n_features": model.n_features,
        "base_mask": encode_array(model.base_mask),
        "row_disposition": [d.value for d in model.row_disposition],
        "clean_mask": encode_array(model.clean_mask),
        "limits": encode_limits(model.limits),
        "limit_regime": model.limit_regime.value,
        "historical_t2": encode_array(model.historical_t2),
        "historical_outlier": encode_array(model.historical_outlier),
        "depuration_rounds": model.depuration_rounds,
        "depuration_converged": model.depuration_converged,
        "final_depuration_skipped": model.final_depuration_skipped,
        "pymrcd_version": model.pymrcd_version,
        "seed": model.seed,
        "statistic_reference": model.statistic_reference,
    }


def decode_model(
    data: Mapping[str, object], strategies: T2MRCDStrategies = DEFAULT_STRATEGIES
) -> T2MRCDModel:
    """Decodifica un modelo de T²MRCD (inversa de ``encode_model``).

    Args:
        data: Modelo codificado.
        strategies: Registro de estrategias de los parámetros.

    Returns:
        El modelo, idéntico en bits al codificado.

    Raises:
        InvalidInputError: Campo desconocido, ausente o inválido, formato desconocido o
            estrategia desconocida.
    """
    raw = read_mapping(data, "model", _MODEL_FIELDS)
    _format_version(raw, MODEL_FORMAT_VERSION, "model")
    params = raw["params"]
    if not isinstance(params, Mapping):
        raise InvalidInputError(
            "'model.params' debe ser un diccionario",
            details={"field": "model.params", "reason": "invalid_encoding"},
        )
    return T2MRCDModel(
        params=decode_params(params, strategies),
        mrcd=decode_fit(raw["mrcd"], "model.mrcd"),
        n_features=read_int(raw["n_features"], "model.n_features"),
        base_mask=decode_bool_array(raw["base_mask"], "model.base_mask"),
        row_disposition=_dispositions(raw["row_disposition"], "model.row_disposition"),
        clean_mask=decode_bool_array(raw["clean_mask"], "model.clean_mask"),
        limits=decode_limits(raw["limits"], "model.limits"),
        limit_regime=_enum(LimitRegime, raw["limit_regime"], "model.limit_regime"),
        historical_t2=decode_float_array(raw["historical_t2"], "model.historical_t2"),
        historical_outlier=decode_bool_array(raw["historical_outlier"], "model.historical_outlier"),
        depuration_rounds=read_int(raw["depuration_rounds"], "model.depuration_rounds"),
        depuration_converged=read_optional_bool(
            raw["depuration_converged"], "model.depuration_converged"
        ),
        final_depuration_skipped=read_bool(
            raw["final_depuration_skipped"], "model.final_depuration_skipped"
        ),
        pymrcd_version=read_str(raw["pymrcd_version"], "model.pymrcd_version"),
        seed=read_int(raw["seed"], "model.seed"),
        statistic_reference=read_str(raw["statistic_reference"], "model.statistic_reference"),
    )


def _encode_test(test: ChangeTestResult) -> dict[str, object]:
    """Codifica el resultado de una prueba de cambio.

    Args:
        test: Resultado.

    Returns:
        Diccionario serializable.
    """
    return {
        "name": test.name,
        "statistic": test.statistic,
        "p_value": test.p_value,
        "changed": test.changed,
    }


def _decode_test(data: object, field: str) -> ChangeTestResult:
    """Decodifica el resultado de una prueba de cambio.

    Args:
        data: Resultado codificado.
        field: Campo.

    Returns:
        El resultado.
    """
    raw = read_mapping(data, field, _TEST_FIELDS)
    return ChangeTestResult(
        name=read_str(raw["name"], f"{field}.name"),
        statistic=read_float(raw["statistic"], f"{field}.statistic"),
        p_value=read_optional_float(raw["p_value"], f"{field}.p_value"),
        changed=read_bool(raw["changed"], f"{field}.changed"),
    )


def _encode_comparison(comparison: ComparisonResult | None) -> dict[str, object] | None:
    """Codifica la comparación de bases.

    Args:
        comparison: Comparación o ``None``.

    Returns:
        Diccionario serializable o ``None``.
    """
    return None if comparison is None else encode_comparison(comparison)


def _decode_comparison(data: object, field: str) -> ComparisonResult | None:
    """Decodifica la comparación de bases.

    Args:
        data: Comparación codificada o ``None``.
        field: Campo.

    Returns:
        La comparación o ``None``.
    """
    if data is None:
        return None
    raw = read_mapping(data, field, _COMPARISON_FIELDS)
    return ComparisonResult(
        metric_name=read_str(raw["metric_name"], f"{field}.metric_name"),
        relative_change=read_float(raw["relative_change"], f"{field}.relative_change"),
        threshold=read_float(raw["threshold"], f"{field}.threshold"),
        exceeds_threshold=read_bool(raw["exceeds_threshold"], f"{field}.exceeds_threshold"),
        threshold_decides=read_bool(raw["threshold_decides"], f"{field}.threshold_decides"),
        covariance=_decode_test(raw["covariance"], f"{field}.covariance"),
        mean=_decode_test(raw["mean"], f"{field}.mean"),
        decision_rule_name=read_str(raw["decision_rule_name"], f"{field}.decision_rule_name"),
        changed=read_bool(raw["changed"], f"{field}.changed"),
    )


def encode_comparison(comparison: ComparisonResult) -> dict[str, object]:
    """Codifica una comparación de bases suelta (paso ``/comparisons``, vuelta 3.4).

    Misma forma que la comparación dentro del informe; sin estadística.

    Args:
        comparison: Comparación.

    Returns:
        Diccionario serializable.
    """
    return {
        "metric_name": comparison.metric_name,
        "relative_change": comparison.relative_change,
        "threshold": comparison.threshold,
        "exceeds_threshold": comparison.exceeds_threshold,
        "threshold_decides": comparison.threshold_decides,
        "covariance": _encode_test(comparison.covariance),
        "mean": _encode_test(comparison.mean),
        "decision_rule_name": comparison.decision_rule_name,
        "changed": comparison.changed,
    }


def decode_comparison(data: object) -> ComparisonResult:
    """Decodifica una comparación de bases suelta (inversa de ``encode_comparison``).

    Args:
        data: Comparación codificada.

    Returns:
        La comparación.

    Raises:
        InvalidInputError: Campo desconocido, ausente o inválido, o ``None``.
    """
    decoded = _decode_comparison(data, "comparison")
    if decoded is None:
        raise InvalidInputError(
            "la comparación codificada no puede ser nula", details={"field": "comparison"}
        )
    return decoded


def _encode_snapshot(snapshot: LimitsSnapshot) -> dict[str, object]:
    """Codifica los límites de una versión (obligatorios: ``before``).

    Simétrico con ``_decode_snapshot``, que tampoco admite ``None``; ``after`` (opcional) pasa
    por ``_encode_optional_snapshot``.

    Args:
        snapshot: Límites.

    Returns:
        Diccionario serializable.
    """
    return {
        "phase1_limit": snapshot.phase1_limit,
        "phase2_limit": snapshot.phase2_limit,
        "phase1_mc_error": snapshot.phase1_mc_error,
        "phase2_mc_error": snapshot.phase2_mc_error,
        "regime": snapshot.regime.value,
        "operative_limit": snapshot.operative_limit,
        "n_base": snapshot.n_base,
    }


def _encode_optional_snapshot(snapshot: LimitsSnapshot | None) -> dict[str, object] | None:
    """Codifica unos límites opcionales (``after``, ``None`` si ``INSUFFICIENT``).

    Args:
        snapshot: Límites o ``None``.

    Returns:
        Diccionario serializable o ``None``.
    """
    return None if snapshot is None else _encode_snapshot(snapshot)


def _decode_snapshot(data: object, field: str) -> LimitsSnapshot:
    """Decodifica los límites de una versión.

    Args:
        data: Límites codificados.
        field: Campo.

    Returns:
        Los límites.
    """
    raw = read_mapping(data, field, _SNAPSHOT_FIELDS)
    return LimitsSnapshot(
        phase1_limit=read_float(raw["phase1_limit"], f"{field}.phase1_limit"),
        phase2_limit=read_float(raw["phase2_limit"], f"{field}.phase2_limit"),
        phase1_mc_error=read_optional_float(raw["phase1_mc_error"], f"{field}.phase1_mc_error"),
        phase2_mc_error=read_optional_float(raw["phase2_mc_error"], f"{field}.phase2_mc_error"),
        regime=_enum(LimitRegime, raw["regime"], f"{field}.regime"),
        operative_limit=read_float(raw["operative_limit"], f"{field}.operative_limit"),
        n_base=read_int(raw["n_base"], f"{field}.n_base"),
    )


def encode_report(report: T2MRCDRecalibrationReport) -> dict[str, object]:
    """Codifica el informe de una recalibración de T²MRCD por valor.

    Args:
        report: Informe.

    Returns:
        Diccionario serializable.
    """
    return {
        "format_version": REPORT_FORMAT_VERSION,
        "decision": report.decision.value,
        "forced": report.forced,
        "row_disposition": [d.value for d in report.row_disposition],
        "n_base": report.n_base,
        "n_new": report.n_new,
        "n_excluded_assignable_cause": report.n_excluded_assignable_cause,
        "n_excluded_automatic": report.n_excluded_automatic,
        "n_kept_new": report.n_kept_new,
        "min_observations": report.min_observations,
        "depuration_rounds": report.depuration_rounds,
        "depuration_converged": report.depuration_converged,
        "comparison": _encode_comparison(report.comparison),
        "before": _encode_snapshot(report.before),
        "after": _encode_optional_snapshot(report.after),
        "phase2_exceeds_phase1": report.phase2_exceeds_phase1,
    }


def decode_report(data: Mapping[str, object]) -> T2MRCDRecalibrationReport:
    """Decodifica el informe de una recalibración (inversa de ``encode_report``).

    Args:
        data: Informe codificado.

    Returns:
        El informe.

    Raises:
        InvalidInputError: Campo desconocido, ausente o inválido, o formato desconocido.
    """
    raw = read_mapping(data, "report", _REPORT_FIELDS)
    _format_version(raw, REPORT_FORMAT_VERSION, "report")
    after = raw["after"]
    return T2MRCDRecalibrationReport(
        decision=_enum(RecalibrationDecision, raw["decision"], "report.decision"),
        forced=read_bool(raw["forced"], "report.forced"),
        row_disposition=_dispositions(raw["row_disposition"], "report.row_disposition"),
        n_base=read_int(raw["n_base"], "report.n_base"),
        n_new=read_int(raw["n_new"], "report.n_new"),
        n_excluded_assignable_cause=read_int(
            raw["n_excluded_assignable_cause"], "report.n_excluded_assignable_cause"
        ),
        n_excluded_automatic=read_int(raw["n_excluded_automatic"], "report.n_excluded_automatic"),
        n_kept_new=read_int(raw["n_kept_new"], "report.n_kept_new"),
        min_observations=read_int(raw["min_observations"], "report.min_observations"),
        depuration_rounds=read_int(raw["depuration_rounds"], "report.depuration_rounds"),
        depuration_converged=read_optional_bool(
            raw["depuration_converged"], "report.depuration_converged"
        ),
        comparison=_decode_comparison(raw["comparison"], "report.comparison"),
        before=_decode_snapshot(raw["before"], "report.before"),
        after=None if after is None else _decode_snapshot(after, "report.after"),
        phase2_exceeds_phase1=read_optional_bool(
            raw["phase2_exceeds_phase1"], "report.phase2_exceeds_phase1"
        ),
    )
