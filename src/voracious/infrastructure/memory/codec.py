"""Codificación de los registros que guardan los repositorios en memoria (mejora M1).

Un repositorio real (Postgres) guarda datos, no objetos de Python: lo que entra se codifica y lo
que sale se decodifica. Los repositorios en memoria pasan por el mismo punto (``RecordCodec``)
para comportarse igual.

- ``ModelRecordCodec``, ``ModelVersionCodec`` y ``RecalibrationRecordCodec`` (vuelta 3.2):
  codifican el registro **entero** como datos (números, textos, booleanos, ``None``, listas y
  diccionarios). El modelo y el informe de la carta se codifican con la propia carta
  (``ControlChart.encode_model`` / ``encode_report``, elegida por ``chart_id``), los arreglos con
  ``encode_array`` (bytes exactos) y las fechas en ISO 8601 con zona horaria. La ida y vuelta es
  exacta en bits.
- ``FitRecordCodec`` y ``LimitsRecordCodec`` (vuelta 3.3): el ajuste y los límites se codifican
  con los pasos de su carta (``Phase1Steps.encode_fit`` / ``encode_limits``), exactos en bits.
- ``ComparisonRecordCodec`` (vuelta 3.4): la comparación se codifica con los pasos de la
  recalibración de su carta (``RecalibrationSteps.encode_comparison``), exacta en bits.
- ``PassthroughCodec``: guarda el registro inmutable tal cual. Se mantiene para los registros
  sin modelo ni informe (monitoreos, observaciones, anotaciones, eventos estructurales,
  datasets, exclusiones y tuberías, que solo
  tienen arreglos, fechas y textos: su codec llega con el adaptador Postgres) y como valor por
  defecto de los repositorios construidos sin cableado (tests).
"""

import copy
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol

from voracious.application.charts import ChartRegistry, resolve_chart
from voracious.application.phase1_steps import Phase1StepsRegistry, resolve_steps
from voracious.application.recalibration_steps import (
    RecalibrationStepsRegistry,
    resolve_recalibration_steps,
)
from voracious.application.records import (
    BaseRowRef,
    BaseRowSource,
    ComparisonRecord,
    ErrorInfo,
    Exclusion,
    ExclusionReason,
    FitRecord,
    JobStatus,
    LifecyclePolicy,
    LimitsRecord,
    ModelProvenance,
    ModelRecord,
    ModelVersion,
    ProposalRequest,
    RecalibrationMode,
    RecalibrationRecord,
    VersionStatus,
)
from voracious.domain.common import InvalidInputError, RecalibrationDecision
from voracious.domain.common.codec import (
    decode_bool_array,
    decode_float_array,
    encode_array,
    read_bool,
    read_int,
    read_mapping,
    read_str,
)

__all__ = [
    "ComparisonRecordCodec",
    "FitRecordCodec",
    "LimitsRecordCodec",
    "ModelRecordCodec",
    "ModelVersionCodec",
    "PassthroughCodec",
    "RecalibrationRecordCodec",
    "RecordCodec",
]


class RecordCodec[R](Protocol):
    """Convierte un registro en lo que se guarda y de vuelta."""

    def encode(self, record: R) -> object:
        """Codifica un registro para guardarlo.

        Args:
            record: Registro.

        Returns:
            La forma guardada.
        """
        ...

    def decode(self, stored: object) -> R:
        """Decodifica un registro guardado.

        Args:
            stored: Forma guardada.

        Returns:
            El registro.
        """
        ...


class PassthroughCodec[R]:
    """Codec identidad: guarda el registro inmutable tal cual (registros sin modelo ni informe).

    Attributes:
        record_type: Tipo del registro; ``decode`` comprueba que lo guardado lo sea.
    """

    def __init__(self, record_type: type[R]) -> None:
        """Construye el codec.

        Args:
            record_type: Tipo del registro.
        """
        self.record_type = record_type

    def encode(self, record: R) -> object:
        """Devuelve el mismo registro.

        Args:
            record: Registro.

        Returns:
            El registro.
        """
        return record

    def decode(self, stored: object) -> R:
        """Devuelve el registro guardado tras comprobar su tipo.

        Args:
            stored: Registro guardado.

        Returns:
            El registro.

        Raises:
            TypeError: Si lo guardado no es del tipo del codec.
        """
        if not isinstance(stored, self.record_type):
            msg = f"se esperaba {self.record_type.__name__}, no {type(stored).__name__}"
            raise TypeError(msg)
        return stored


# --- piezas comunes ------------------------------------------------------------------------------


def _enum[E: StrEnum](cls: type[E], value: object, field: str) -> E:
    """Enumeración por su valor.

    Args:
        cls: Enumeración.
        value: Valor guardado.
        field: Campo, para el mensaje.

    Returns:
        El miembro.

    Raises:
        InvalidInputError: Si el valor no es de la enumeración.
    """
    text = read_str(value, field)
    for member in cls:
        if member.value == text:
            return member
    raise InvalidInputError(
        f"'{field}' no es un valor de {cls.__name__}: {text!r}",
        details={"field": field, "reason": "invalid_encoding"},
    )


def _optional_str(value: object, field: str) -> str | None:
    """Texto o ``None``.

    Args:
        value: Valor guardado.
        field: Campo.

    Returns:
        El texto o ``None``.
    """
    return None if value is None else read_str(value, field)


def _optional_int(value: object, field: str) -> int | None:
    """Entero o ``None``.

    Args:
        value: Valor guardado.
        field: Campo.

    Returns:
        El entero o ``None``.
    """
    return None if value is None else read_int(value, field)


def _encode_time(value: datetime | None) -> str | None:
    """Fecha en ISO 8601 (con zona horaria si la tiene).

    Args:
        value: Fecha o ``None``.

    Returns:
        El texto o ``None``.
    """
    return None if value is None else value.isoformat()


def _time(value: object, field: str) -> datetime:
    """Fecha ISO 8601 guardada.

    Args:
        value: Texto guardado.
        field: Campo.

    Returns:
        La fecha.

    Raises:
        InvalidInputError: Si no es una fecha ISO 8601.
    """
    text = read_str(value, field)
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise InvalidInputError(
            f"'{field}' no es una fecha ISO 8601",
            details={"field": field, "reason": "invalid_encoding"},
        ) from exc


def _optional_time(value: object, field: str) -> datetime | None:
    """Fecha o ``None``.

    Args:
        value: Texto guardado o ``None``.
        field: Campo.

    Returns:
        La fecha o ``None``.
    """
    return None if value is None else _time(value, field)


def _data(value: Mapping[str, object]) -> dict[str, object]:
    """Copia profunda de un diccionario de datos (parámetros, detalles de error).

    Args:
        value: Diccionario.

    Returns:
        La copia (lo guardado no comparte objetos mutables con el registro).
    """
    return copy.deepcopy(dict(value))


def _mapping_data(value: object, field: str) -> dict[str, object]:
    """Diccionario de datos guardado (copia profunda).

    Args:
        value: Valor guardado.
        field: Campo.

    Returns:
        La copia.

    Raises:
        InvalidInputError: Si no es un diccionario de claves de texto.
    """
    if not isinstance(value, Mapping) or not all(isinstance(k, str) for k in value):
        raise InvalidInputError(
            f"'{field}' debe ser un diccionario",
            details={"field": field, "reason": "invalid_encoding"},
        )
    return _data(value)


_ERROR_FIELDS: Final = frozenset({"code", "message", "details"})


def _encode_error(error: ErrorInfo | None) -> dict[str, object] | None:
    """Codifica el error de un trabajo.

    Args:
        error: Error o ``None``.

    Returns:
        Diccionario o ``None``.
    """
    if error is None:
        return None
    return {"code": error.code, "message": error.message, "details": _data(error.details)}


def _decode_error(value: object, field: str = "error") -> ErrorInfo | None:
    """Decodifica el error de un trabajo.

    Args:
        value: Error guardado o ``None``.
        field: Campo.

    Returns:
        El error o ``None``.
    """
    if value is None:
        return None
    raw = read_mapping(value, field, _ERROR_FIELDS)
    return ErrorInfo(
        code=read_str(raw["code"], f"{field}.code"),
        message=read_str(raw["message"], f"{field}.message"),
        details=_mapping_data(raw["details"], f"{field}.details"),
    )


def _chart_data(value: object, field: str) -> Mapping[str, object]:
    """Modelo o informe codificado por la carta.

    Args:
        value: Valor guardado.
        field: Campo.

    Returns:
        El diccionario.

    Raises:
        InvalidInputError: Si no es un diccionario.
    """
    if not isinstance(value, Mapping):
        raise InvalidInputError(
            f"'{field}' debe ser un diccionario",
            details={"field": field, "reason": "invalid_encoding"},
        )
    return value


# --- ModelRecord ---------------------------------------------------------------------------------

_MODEL_RECORD_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "model_id",
        "status",
        "params",
        "training_data",
        "created_at",
        "started_at",
        "finished_at",
        "model",
        "error",
        "lifecycle_policy",
        "provenance",
        "pipeline_id",
    }
)
_PROVENANCE_FIELDS: Final = frozenset({"root_dataset_id", "fit_id", "limits_id", "exclusion_id"})
_POLICY_FIELDS: Final = frozenset({"revalidate_every_months", "revalidate_every_observations"})


def _encode_provenance(provenance: ModelProvenance | None) -> dict[str, object] | None:
    """Codifica la procedencia de un modelo.

    Args:
        provenance: Procedencia o ``None``.

    Returns:
        Diccionario o ``None``.
    """
    if provenance is None:
        return None
    return {
        "root_dataset_id": provenance.root_dataset_id,
        "fit_id": provenance.fit_id,
        "limits_id": provenance.limits_id,
        "exclusion_id": provenance.exclusion_id,
    }


def _decode_provenance(value: object) -> ModelProvenance | None:
    """Decodifica la procedencia de un modelo.

    Args:
        value: Procedencia guardada o ``None``.

    Returns:
        La procedencia o ``None``.
    """
    if value is None:
        return None
    raw = read_mapping(value, "provenance", _PROVENANCE_FIELDS)
    return ModelProvenance(
        root_dataset_id=read_str(raw["root_dataset_id"], "provenance.root_dataset_id"),
        fit_id=read_str(raw["fit_id"], "provenance.fit_id"),
        limits_id=read_str(raw["limits_id"], "provenance.limits_id"),
        exclusion_id=_optional_str(raw["exclusion_id"], "provenance.exclusion_id"),
    )


class ModelRecordCodec:
    """Codec de ``ModelRecord``: registro entero como datos; el modelo, con su carta.

    Attributes:
        charts: Cartas por ``chart_id`` (codifican y decodifican su modelo).
    """

    def __init__(self, charts: ChartRegistry) -> None:
        """Construye el codec.

        Args:
            charts: Registro de cartas.
        """
        self.charts = charts

    def encode(self, record: ModelRecord) -> object:
        """Codifica el registro.

        Args:
            record: Registro.

        Returns:
            Diccionario serializable.

        Raises:
            UnknownChartError: Si la carta del registro no está registrada.
        """
        chart = resolve_chart(self.charts, record.chart_id)
        policy = record.lifecycle_policy
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "model_id": record.model_id,
            "status": record.status.value,
            "params": _data(record.params),
            "training_data": encode_array(record.training_data),
            "created_at": _encode_time(record.created_at),
            "started_at": _encode_time(record.started_at),
            "finished_at": _encode_time(record.finished_at),
            "model": None if record.model is None else chart.encode_model(record.model),
            "error": _encode_error(record.error),
            "lifecycle_policy": {
                "revalidate_every_months": policy.revalidate_every_months,
                "revalidate_every_observations": policy.revalidate_every_observations,
            },
            "provenance": _encode_provenance(record.provenance),
            "pipeline_id": record.pipeline_id,
        }

    def decode(self, stored: object) -> ModelRecord:
        """Decodifica el registro.

        Args:
            stored: Diccionario guardado.

        Returns:
            El registro.

        Raises:
            InvalidInputError: Si lo guardado no es un registro codificado válido.
            UnknownChartError: Si la carta del registro no está registrada.
        """
        raw = read_mapping(stored, "model_record", _MODEL_RECORD_FIELDS)
        chart_id = read_str(raw["chart_id"], "chart_id")
        chart = resolve_chart(self.charts, chart_id)
        policy = read_mapping(raw["lifecycle_policy"], "lifecycle_policy", _POLICY_FIELDS)
        model = raw["model"]
        return ModelRecord(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=chart_id,
            model_id=read_str(raw["model_id"], "model_id"),
            status=_enum(JobStatus, raw["status"], "status"),
            params=_mapping_data(raw["params"], "params"),
            training_data=decode_float_array(raw["training_data"], "training_data"),
            created_at=_time(raw["created_at"], "created_at"),
            started_at=_optional_time(raw["started_at"], "started_at"),
            finished_at=_optional_time(raw["finished_at"], "finished_at"),
            model=None if model is None else chart.decode_model(_chart_data(model, "model")),
            error=_decode_error(raw["error"]),
            lifecycle_policy=LifecyclePolicy(
                revalidate_every_months=_optional_int(
                    policy["revalidate_every_months"], "lifecycle_policy.revalidate_every_months"
                ),
                revalidate_every_observations=_optional_int(
                    policy["revalidate_every_observations"],
                    "lifecycle_policy.revalidate_every_observations",
                ),
            ),
            provenance=_decode_provenance(raw["provenance"]),
            pipeline_id=_optional_str(raw["pipeline_id"], "pipeline_id"),
        )


# --- ModelVersion --------------------------------------------------------------------------------

_VERSION_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "model_id",
        "number",
        "status",
        "model",
        "base_data",
        "base_hash",
        "base_refs",
        "exclusions",
        "decision",
        "justification",
        "created_at",
        "report",
        "recalibration_id",
        "structural_event_id",
        "previous_number",
        "effective_from",
        "approved_at",
        "rejected_at",
        "decided_by",
        "decision_note",
    }
)
_REF_FIELDS: Final = frozenset({"source", "ref"})
_EXCLUSION_FIELDS: Final = frozenset({"ref", "reason", "annotation_id"})


def _encode_ref(ref: BaseRowRef) -> dict[str, object]:
    """Codifica la referencia a una fila de la base.

    Args:
        ref: Referencia.

    Returns:
        Diccionario.
    """
    return {"source": ref.source.value, "ref": ref.ref}


def _decode_ref(value: object, field: str) -> BaseRowRef:
    """Decodifica la referencia a una fila de la base.

    Args:
        value: Referencia guardada.
        field: Campo.

    Returns:
        La referencia.
    """
    raw = read_mapping(value, field, _REF_FIELDS)
    return BaseRowRef(
        source=_enum(BaseRowSource, raw["source"], f"{field}.source"),
        ref=read_str(raw["ref"], f"{field}.ref"),
    )


def _items(value: object, field: str) -> list[object]:
    """Lista guardada.

    Args:
        value: Valor guardado.
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


class ModelVersionCodec:
    """Codec de ``ModelVersion``: versión entera como datos; modelo e informe, con su carta.

    Attributes:
        charts: Cartas por ``chart_id``.
    """

    def __init__(self, charts: ChartRegistry) -> None:
        """Construye el codec.

        Args:
            charts: Registro de cartas.
        """
        self.charts = charts

    def encode(self, record: ModelVersion) -> object:
        """Codifica la versión.

        Args:
            record: Versión.

        Returns:
            Diccionario serializable.

        Raises:
            UnknownChartError: Si la carta de la versión no está registrada.
        """
        chart = resolve_chart(self.charts, record.chart_id)
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "model_id": record.model_id,
            "number": record.number,
            "status": record.status.value,
            "model": chart.encode_model(record.model),
            "base_data": encode_array(record.base_data),
            "base_hash": record.base_hash,
            "base_refs": [_encode_ref(r) for r in record.base_refs],
            "exclusions": [
                {
                    "ref": _encode_ref(e.ref),
                    "reason": e.reason.value,
                    "annotation_id": e.annotation_id,
                }
                for e in record.exclusions
            ],
            "decision": record.decision.value,
            "justification": record.justification,
            "created_at": _encode_time(record.created_at),
            "report": None if record.report is None else chart.encode_report(record.report),
            "recalibration_id": record.recalibration_id,
            "structural_event_id": record.structural_event_id,
            "previous_number": record.previous_number,
            "effective_from": _encode_time(record.effective_from),
            "approved_at": _encode_time(record.approved_at),
            "rejected_at": _encode_time(record.rejected_at),
            "decided_by": record.decided_by,
            "decision_note": record.decision_note,
        }

    def decode(self, stored: object) -> ModelVersion:
        """Decodifica la versión.

        Args:
            stored: Diccionario guardado.

        Returns:
            La versión.

        Raises:
            InvalidInputError: Si lo guardado no es una versión codificada válida.
            UnknownChartError: Si la carta de la versión no está registrada.
        """
        raw = read_mapping(stored, "model_version", _VERSION_FIELDS)
        chart_id = read_str(raw["chart_id"], "chart_id")
        chart = resolve_chart(self.charts, chart_id)
        report = raw["report"]
        exclusions = []
        for i, item in enumerate(_items(raw["exclusions"], "exclusions")):
            ex = read_mapping(item, f"exclusions[{i}]", _EXCLUSION_FIELDS)
            exclusions.append(
                Exclusion(
                    ref=_decode_ref(ex["ref"], f"exclusions[{i}].ref"),
                    reason=_enum(ExclusionReason, ex["reason"], f"exclusions[{i}].reason"),
                    annotation_id=_optional_str(
                        ex["annotation_id"], f"exclusions[{i}].annotation_id"
                    ),
                )
            )
        return ModelVersion(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=chart_id,
            model_id=read_str(raw["model_id"], "model_id"),
            number=read_int(raw["number"], "number"),
            status=_enum(VersionStatus, raw["status"], "status"),
            model=chart.decode_model(_chart_data(raw["model"], "model")),
            base_data=decode_float_array(raw["base_data"], "base_data"),
            base_hash=read_str(raw["base_hash"], "base_hash"),
            base_refs=tuple(
                _decode_ref(r, f"base_refs[{i}]")
                for i, r in enumerate(_items(raw["base_refs"], "base_refs"))
            ),
            exclusions=tuple(exclusions),
            decision=_enum(RecalibrationDecision, raw["decision"], "decision"),
            justification=read_str(raw["justification"], "justification"),
            created_at=_time(raw["created_at"], "created_at"),
            report=None if report is None else chart.decode_report(_chart_data(report, "report")),
            recalibration_id=_optional_str(raw["recalibration_id"], "recalibration_id"),
            structural_event_id=_optional_str(raw["structural_event_id"], "structural_event_id"),
            previous_number=_optional_int(raw["previous_number"], "previous_number"),
            effective_from=_optional_time(raw["effective_from"], "effective_from"),
            approved_at=_optional_time(raw["approved_at"], "approved_at"),
            rejected_at=_optional_time(raw["rejected_at"], "rejected_at"),
            decided_by=_optional_str(raw["decided_by"], "decided_by"),
            decision_note=_optional_str(raw["decision_note"], "decision_note"),
        )


# --- RecalibrationRecord -------------------------------------------------------------------------

_RECALIBRATION_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "model_id",
        "recalibration_id",
        "status",
        "range_from",
        "range_to",
        "params",
        "force_replace",
        "base_version_number",
        "structural_event_id",
        "created_at",
        "actor",
        "started_at",
        "finished_at",
        "outcome",
        "report",
        "proposed_version",
        "error",
        "mode",
        "inherited_params",
        "candidate_ids",
        "already_in_base_ids",
        "candidates_dataset_id",
        "pipeline_id",
        "proposal",
    }
)

_PROPOSAL_FIELDS: Final = frozenset(
    {"fit_id", "limits_id", "comparison_id", "status", "requested_at"}
)


def _encode_proposal(proposal: ProposalRequest | None) -> dict[str, object] | None:
    """Codifica la petición de propuesta de una recalibración.

    Args:
        proposal: Petición o ``None``.

    Returns:
        Diccionario o ``None``.
    """
    if proposal is None:
        return None
    return {
        "fit_id": proposal.fit_id,
        "limits_id": proposal.limits_id,
        "comparison_id": proposal.comparison_id,
        "status": proposal.status.value,
        "requested_at": _encode_time(proposal.requested_at),
    }


def _decode_proposal(value: object) -> ProposalRequest | None:
    """Decodifica la petición de propuesta.

    Args:
        value: Petición guardada o ``None``.

    Returns:
        La petición o ``None``.
    """
    if value is None:
        return None
    raw = read_mapping(value, "proposal", _PROPOSAL_FIELDS)
    return ProposalRequest(
        fit_id=read_str(raw["fit_id"], "proposal.fit_id"),
        limits_id=read_str(raw["limits_id"], "proposal.limits_id"),
        comparison_id=_optional_str(raw["comparison_id"], "proposal.comparison_id"),
        status=_enum(JobStatus, raw["status"], "proposal.status"),
        requested_at=_time(raw["requested_at"], "proposal.requested_at"),
    )


def _strings(value: object, field: str) -> tuple[str, ...]:
    """Lista de textos guardada.

    Args:
        value: Valor guardado.
        field: Campo.

    Returns:
        Los textos.
    """
    return tuple(read_str(v, f"{field}[{i}]") for i, v in enumerate(_items(value, field)))


class RecalibrationRecordCodec:
    """Codec de ``RecalibrationRecord``: registro entero como datos; el informe, con su carta.

    Attributes:
        charts: Cartas por ``chart_id``.
    """

    def __init__(self, charts: ChartRegistry) -> None:
        """Construye el codec.

        Args:
            charts: Registro de cartas.
        """
        self.charts = charts

    def encode(self, record: RecalibrationRecord) -> object:
        """Codifica el registro.

        Args:
            record: Registro.

        Returns:
            Diccionario serializable.

        Raises:
            UnknownChartError: Si la carta del registro no está registrada.
        """
        chart = resolve_chart(self.charts, record.chart_id)
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "model_id": record.model_id,
            "recalibration_id": record.recalibration_id,
            "status": record.status.value,
            "range_from": _encode_time(record.range_from),
            "range_to": _encode_time(record.range_to),
            "params": _data(record.params),
            "force_replace": record.force_replace,
            "base_version_number": record.base_version_number,
            "structural_event_id": record.structural_event_id,
            "created_at": _encode_time(record.created_at),
            "actor": record.actor,
            "started_at": _encode_time(record.started_at),
            "finished_at": _encode_time(record.finished_at),
            "outcome": None if record.outcome is None else record.outcome.value,
            "report": None if record.report is None else chart.encode_report(record.report),
            "proposed_version": record.proposed_version,
            "error": _encode_error(record.error),
            "mode": record.mode.value,
            "inherited_params": _data(record.inherited_params),
            "candidate_ids": list(record.candidate_ids),
            "already_in_base_ids": list(record.already_in_base_ids),
            "candidates_dataset_id": record.candidates_dataset_id,
            "pipeline_id": record.pipeline_id,
            "proposal": _encode_proposal(record.proposal),
        }

    def decode(self, stored: object) -> RecalibrationRecord:
        """Decodifica el registro.

        Args:
            stored: Diccionario guardado.

        Returns:
            El registro.

        Raises:
            InvalidInputError: Si lo guardado no es un registro codificado válido.
            UnknownChartError: Si la carta del registro no está registrada.
        """
        raw = read_mapping(stored, "recalibration_record", _RECALIBRATION_FIELDS)
        chart_id = read_str(raw["chart_id"], "chart_id")
        chart = resolve_chart(self.charts, chart_id)
        outcome, report = raw["outcome"], raw["report"]
        return RecalibrationRecord(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=chart_id,
            model_id=read_str(raw["model_id"], "model_id"),
            recalibration_id=read_str(raw["recalibration_id"], "recalibration_id"),
            status=_enum(JobStatus, raw["status"], "status"),
            range_from=_time(raw["range_from"], "range_from"),
            range_to=_time(raw["range_to"], "range_to"),
            params=_mapping_data(raw["params"], "params"),
            force_replace=read_bool(raw["force_replace"], "force_replace"),
            base_version_number=read_int(raw["base_version_number"], "base_version_number"),
            structural_event_id=_optional_str(raw["structural_event_id"], "structural_event_id"),
            created_at=_time(raw["created_at"], "created_at"),
            actor=_optional_str(raw["actor"], "actor"),
            started_at=_optional_time(raw["started_at"], "started_at"),
            finished_at=_optional_time(raw["finished_at"], "finished_at"),
            outcome=None if outcome is None else _enum(RecalibrationDecision, outcome, "outcome"),
            report=None if report is None else chart.decode_report(_chart_data(report, "report")),
            proposed_version=_optional_int(raw["proposed_version"], "proposed_version"),
            error=_decode_error(raw["error"]),
            mode=_enum(RecalibrationMode, raw["mode"], "mode"),
            inherited_params=_mapping_data(raw["inherited_params"], "inherited_params"),
            candidate_ids=_strings(raw["candidate_ids"], "candidate_ids"),
            already_in_base_ids=_strings(raw["already_in_base_ids"], "already_in_base_ids"),
            candidates_dataset_id=_optional_str(
                raw["candidates_dataset_id"], "candidates_dataset_id"
            ),
            pipeline_id=_optional_str(raw["pipeline_id"], "pipeline_id"),
            proposal=_decode_proposal(raw["proposal"]),
        )


# --- FitRecord y LimitsRecord (vuelta 3.3) -------------------------------------------------------

_FIT_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "fit_id",
        "dataset_id",
        "status",
        "params",
        "created_at",
        "started_at",
        "finished_at",
        "result",
        "error",
        "pipeline_id",
    }
)


class FitRecordCodec:
    """Codec de ``FitRecord``: registro entero como datos; el ajuste, con los pasos de su carta.

    Attributes:
        steps: Pasos de Fase I por ``chart_id``.
    """

    def __init__(self, steps: Phase1StepsRegistry) -> None:
        """Construye el codec.

        Args:
            steps: Registro de pasos.
        """
        self.steps = steps

    def encode(self, record: FitRecord) -> object:
        """Codifica el registro.

        Args:
            record: Registro.

        Returns:
            Diccionario serializable.
        """
        steps = resolve_steps(self.steps, record.chart_id)
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "fit_id": record.fit_id,
            "dataset_id": record.dataset_id,
            "status": record.status.value,
            "params": _data(record.params),
            "created_at": _encode_time(record.created_at),
            "started_at": _encode_time(record.started_at),
            "finished_at": _encode_time(record.finished_at),
            "result": None if record.result is None else steps.encode_fit(record.result),
            "error": _encode_error(record.error),
            "pipeline_id": record.pipeline_id,
        }

    def decode(self, stored: object) -> FitRecord:
        """Decodifica el registro.

        Args:
            stored: Diccionario guardado.

        Returns:
            El registro.
        """
        raw = read_mapping(stored, "fit_record", _FIT_FIELDS)
        chart_id = read_str(raw["chart_id"], "chart_id")
        steps = resolve_steps(self.steps, chart_id)
        result = raw["result"]
        return FitRecord(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=chart_id,
            fit_id=read_str(raw["fit_id"], "fit_id"),
            dataset_id=read_str(raw["dataset_id"], "dataset_id"),
            status=_enum(JobStatus, raw["status"], "status"),
            params=_mapping_data(raw["params"], "params"),
            created_at=_time(raw["created_at"], "created_at"),
            started_at=_optional_time(raw["started_at"], "started_at"),
            finished_at=_optional_time(raw["finished_at"], "finished_at"),
            result=None if result is None else steps.decode_fit(_chart_data(result, "result")),
            error=_decode_error(raw["error"]),
            pipeline_id=_optional_str(raw["pipeline_id"], "pipeline_id"),
        )


_LIMITS_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "limits_id",
        "fit_id",
        "status",
        "params",
        "seed",
        "stage_kind",
        "spawn_key",
        "created_at",
        "recalibration_id",
        "started_at",
        "finished_at",
        "result",
        "clean_rows",
        "error",
        "pipeline_id",
    }
)


class LimitsRecordCodec:
    """Codec de ``LimitsRecord``: registro entero como datos; los límites, con su carta.

    Attributes:
        steps: Pasos de Fase I por ``chart_id``.
    """

    def __init__(self, steps: Phase1StepsRegistry) -> None:
        """Construye el codec.

        Args:
            steps: Registro de pasos.
        """
        self.steps = steps

    def encode(self, record: LimitsRecord) -> object:
        """Codifica el registro.

        Args:
            record: Registro.

        Returns:
            Diccionario serializable.
        """
        steps = resolve_steps(self.steps, record.chart_id)
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "limits_id": record.limits_id,
            "fit_id": record.fit_id,
            "status": record.status.value,
            "params": _data(record.params),
            "seed": record.seed,
            "stage_kind": record.stage_kind,
            "spawn_key": list(record.spawn_key),
            "created_at": _encode_time(record.created_at),
            "recalibration_id": record.recalibration_id,
            "started_at": _encode_time(record.started_at),
            "finished_at": _encode_time(record.finished_at),
            "result": None if record.result is None else steps.encode_limits(record.result),
            "clean_rows": None if record.clean_rows is None else encode_array(record.clean_rows),
            "error": _encode_error(record.error),
            "pipeline_id": record.pipeline_id,
        }

    def decode(self, stored: object) -> LimitsRecord:
        """Decodifica el registro.

        Args:
            stored: Diccionario guardado.

        Returns:
            El registro.
        """
        raw = read_mapping(stored, "limits_record", _LIMITS_FIELDS)
        chart_id = read_str(raw["chart_id"], "chart_id")
        steps = resolve_steps(self.steps, chart_id)
        result, clean = raw["result"], raw["clean_rows"]
        return LimitsRecord(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=chart_id,
            limits_id=read_str(raw["limits_id"], "limits_id"),
            fit_id=read_str(raw["fit_id"], "fit_id"),
            status=_enum(JobStatus, raw["status"], "status"),
            params=_mapping_data(raw["params"], "params"),
            seed=read_int(raw["seed"], "seed"),
            stage_kind=read_str(raw["stage_kind"], "stage_kind"),
            spawn_key=tuple(
                read_int(v, f"spawn_key[{i}]")
                for i, v in enumerate(_items(raw["spawn_key"], "spawn_key"))
            ),
            created_at=_time(raw["created_at"], "created_at"),
            recalibration_id=_optional_str(raw["recalibration_id"], "recalibration_id"),
            started_at=_optional_time(raw["started_at"], "started_at"),
            finished_at=_optional_time(raw["finished_at"], "finished_at"),
            result=None if result is None else steps.decode_limits(_chart_data(result, "result")),
            clean_rows=None if clean is None else decode_bool_array(clean, "clean_rows"),
            error=_decode_error(raw["error"]),
            pipeline_id=_optional_str(raw["pipeline_id"], "pipeline_id"),
        )


# --- ComparisonRecord (vuelta 3.4) ---------------------------------------------------------------

_COMPARISON_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "model_id",
        "comparison_id",
        "recalibration_id",
        "fit_id",
        "limits_id",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "result",
        "decision",
        "extension_dataset_id",
        "error",
        "pipeline_id",
    }
)


class ComparisonRecordCodec:
    """Codec de ``ComparisonRecord``: registro entero como datos; la comparación, con su carta.

    Attributes:
        steps: Pasos de la recalibración por ``chart_id``.
    """

    def __init__(self, steps: RecalibrationStepsRegistry) -> None:
        """Construye el codec.

        Args:
            steps: Registro de pasos de la recalibración.
        """
        self.steps = steps

    def encode(self, record: ComparisonRecord) -> object:
        """Codifica el registro.

        Args:
            record: Registro.

        Returns:
            Diccionario serializable.
        """
        steps = resolve_recalibration_steps(self.steps, record.chart_id)
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "model_id": record.model_id,
            "comparison_id": record.comparison_id,
            "recalibration_id": record.recalibration_id,
            "fit_id": record.fit_id,
            "limits_id": record.limits_id,
            "status": record.status.value,
            "created_at": _encode_time(record.created_at),
            "started_at": _encode_time(record.started_at),
            "finished_at": _encode_time(record.finished_at),
            "result": None if record.result is None else steps.encode_comparison(record.result),
            "decision": None if record.decision is None else record.decision.value,
            "extension_dataset_id": record.extension_dataset_id,
            "error": _encode_error(record.error),
            "pipeline_id": record.pipeline_id,
        }

    def decode(self, stored: object) -> ComparisonRecord:
        """Decodifica el registro.

        Args:
            stored: Diccionario guardado.

        Returns:
            El registro.
        """
        raw = read_mapping(stored, "comparison_record", _COMPARISON_FIELDS)
        chart_id = read_str(raw["chart_id"], "chart_id")
        steps = resolve_recalibration_steps(self.steps, chart_id)
        result, decision = raw["result"], raw["decision"]
        return ComparisonRecord(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=chart_id,
            model_id=read_str(raw["model_id"], "model_id"),
            comparison_id=read_str(raw["comparison_id"], "comparison_id"),
            recalibration_id=read_str(raw["recalibration_id"], "recalibration_id"),
            fit_id=read_str(raw["fit_id"], "fit_id"),
            limits_id=read_str(raw["limits_id"], "limits_id"),
            status=_enum(JobStatus, raw["status"], "status"),
            created_at=_time(raw["created_at"], "created_at"),
            started_at=_optional_time(raw["started_at"], "started_at"),
            finished_at=_optional_time(raw["finished_at"], "finished_at"),
            result=None
            if result is None
            else steps.decode_comparison(_chart_data(result, "result")),
            decision=None
            if decision is None
            else _enum(RecalibrationDecision, decision, "decision"),
            extension_dataset_id=_optional_str(raw["extension_dataset_id"], "extension_dataset_id"),
            error=_decode_error(raw["error"]),
            pipeline_id=_optional_str(raw["pipeline_id"], "pipeline_id"),
        )
