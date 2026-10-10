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
- Paso 4.2 (Postgres): ``ExclusionRecordCodec``, ``PipelineRecordCodec``,
  ``MonitoringRecordCodec``, ``ObservationRecordCodec``, ``SignalAnnotationCodec`` y
  ``StructuralEventCodec`` (registros sin objetos de carta) y ``encode_dataset_meta`` /
  ``decode_dataset_meta`` (los metadatos de un dataset; la matriz la guarda su almacén). Con ellos
  todo registro tiene forma de datos y Postgres guarda ese JSON tal cual (``TEXT``).
- ``PassthroughCodec``: guarda el registro inmutable tal cual; valor por defecto de los
  repositorios en memoria construidos sin cableado (tests).
"""

import copy
from collections.abc import Mapping, Sequence
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
    AssignableCause,
    BaseRowRef,
    BaseRowSource,
    ComparisonRecord,
    DatasetRecord,
    DatasetSource,
    ErrorInfo,
    Exclusion,
    ExclusionReason,
    ExclusionRecord,
    FitRecord,
    JobStatus,
    LifecyclePolicy,
    LimitsRecord,
    ModelProvenance,
    ModelRecord,
    ModelVersion,
    MonitoringRecord,
    MonitoringSummary,
    ObservationRecord,
    PipelineKind,
    PipelineRecord,
    PipelineStep,
    ProposalRequest,
    RecalibrationMode,
    RecalibrationRecord,
    SignalAnnotation,
    StructuralEvent,
    VersionStatus,
)
from voracious.domain.common import (
    FloatMatrix,
    InvalidInputError,
    RecalibrationDecision,
    RowDisposition,
)
from voracious.domain.common.codec import (
    decode_bool_array,
    decode_float_array,
    decode_int_array,
    encode_array,
    read_bool,
    read_int,
    read_mapping,
    read_str,
)

__all__ = [
    "ComparisonRecordCodec",
    "ExclusionRecordCodec",
    "FitRecordCodec",
    "LimitsRecordCodec",
    "ModelRecordCodec",
    "ModelVersionCodec",
    "MonitoringRecordCodec",
    "ObservationRecordCodec",
    "PassthroughCodec",
    "PipelineRecordCodec",
    "RecalibrationRecordCodec",
    "RecordCodec",
    "SignalAnnotationCodec",
    "StructuralEventCodec",
    "decode_dataset_meta",
    "encode_dataset_meta",
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


def _encode_times(values: Sequence[datetime] | None) -> list[str] | None:
    """Fechas en ISO 8601, o ``None``.

    Args:
        values: Fechas o ``None``.

    Returns:
        Los textos o ``None``.
    """
    return None if values is None else [v.isoformat() for v in values]


def _optional_times(value: object, field: str) -> tuple[datetime, ...] | None:
    """Lista de fechas guardada, o ``None``.

    Args:
        value: Valor guardado.
        field: Campo.

    Returns:
        Las fechas o ``None``.
    """
    if value is None:
        return None
    return tuple(_time(v, f"{field}[{i}]") for i, v in enumerate(_items(value, field)))


def _encode_strings(values: Sequence[str] | None) -> list[str] | None:
    """Lista de textos, o ``None``.

    Args:
        values: Textos o ``None``.

    Returns:
        La lista o ``None``.
    """
    return None if values is None else list(values)


def _optional_strings(value: object, field: str) -> tuple[str, ...] | None:
    """Lista de textos guardada, o ``None``.

    Args:
        value: Valor guardado.
        field: Campo.

    Returns:
        Los textos o ``None``.
    """
    return None if value is None else _strings(value, field)


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
        "variables",
        "observed_at",
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
            "variables": _encode_strings(record.variables),
            "observed_at": _encode_times(record.observed_at),
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
            variables=_optional_strings(raw["variables"], "variables"),
            observed_at=_optional_times(raw["observed_at"], "observed_at"),
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
_REF_FIELDS: Final = frozenset({"source", "ref", "observed_at"})
_EXCLUSION_FIELDS: Final = frozenset({"ref", "reason", "annotation_id"})


def _encode_ref(ref: BaseRowRef) -> dict[str, object]:
    """Codifica la referencia a una fila de la base.

    Args:
        ref: Referencia.

    Returns:
        Diccionario.
    """
    return {
        "source": ref.source.value,
        "ref": ref.ref,
        "observed_at": _encode_time(ref.observed_at),
    }


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
        observed_at=_optional_time(raw["observed_at"], f"{field}.observed_at"),
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


# --- registros sin objetos de carta (Paso 4.2: los guarda Postgres) ------------------------------

_DATASET_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "dataset_id",
        "content_hash",
        "shape",
        "source",
        "created_at",
        "parent_id",
        "rows",
        "origin_ref",
        "variables",
        "observed_at",
    }
)


def encode_dataset_meta(record: DatasetRecord) -> dict[str, object]:
    """Metadatos de un dataset como datos: todo menos la matriz (que guarda el almacén).

    Args:
        record: Dataset.

    Returns:
        Diccionario serializable (con la forma ``[n, p]`` para comprobar la matriz al leer).
    """
    return {
        "tenant_id": record.tenant_id,
        "dataset_id": record.dataset_id,
        "content_hash": record.content_hash,
        "shape": [int(d) for d in record.data.shape],
        "source": record.source.value,
        "created_at": _encode_time(record.created_at),
        "parent_id": record.parent_id,
        "rows": None if record.rows is None else encode_array(record.rows),
        "origin_ref": record.origin_ref,
        "variables": _encode_strings(record.variables),
        "observed_at": _encode_times(record.observed_at),
    }


def decode_dataset_meta(stored: object, data: FloatMatrix) -> DatasetRecord:
    """Dataset a partir de sus metadatos y de su matriz.

    Args:
        stored: Metadatos guardados (``encode_dataset_meta``).
        data: Matriz ya leída y comprobada contra la huella.

    Returns:
        El dataset.

    Raises:
        InvalidInputError: Si los metadatos no son válidos o la forma no coincide con la matriz.
    """
    raw = read_mapping(stored, "dataset", _DATASET_FIELDS)
    shape = tuple(read_int(d, "shape") for d in _items(raw["shape"], "shape"))
    if shape != data.shape:
        raise InvalidInputError(
            "la matriz del dataset no tiene la forma de sus metadatos",
            details={"field": "shape", "reason": "invalid_encoding"},
        )
    rows = raw["rows"]
    return DatasetRecord(
        tenant_id=read_str(raw["tenant_id"], "tenant_id"),
        dataset_id=read_str(raw["dataset_id"], "dataset_id"),
        data=data,
        content_hash=read_str(raw["content_hash"], "content_hash"),
        source=_enum(DatasetSource, raw["source"], "source"),
        created_at=_time(raw["created_at"], "created_at"),
        parent_id=_optional_str(raw["parent_id"], "parent_id"),
        rows=None if rows is None else decode_int_array(rows, "rows"),
        origin_ref=_optional_str(raw["origin_ref"], "origin_ref"),
        variables=_optional_strings(raw["variables"], "variables"),
        observed_at=_optional_times(raw["observed_at"], "observed_at"),
    )


_CAUSE_FIELDS: Final = frozenset({"row", "cause", "annotation_id"})


def _encode_causes(causes: Sequence[AssignableCause]) -> list[dict[str, object]]:
    """Codifica las filas con causa asignable.

    Args:
        causes: Filas.

    Returns:
        La lista.
    """
    return [{"row": c.row, "cause": c.cause, "annotation_id": c.annotation_id} for c in causes]


def _decode_causes(value: object, field: str) -> tuple[AssignableCause, ...]:
    """Decodifica las filas con causa asignable.

    Args:
        value: Lista guardada.
        field: Campo.

    Returns:
        Las filas.
    """
    out = []
    for i, item in enumerate(_items(value, field)):
        raw = read_mapping(item, f"{field}[{i}]", _CAUSE_FIELDS)
        out.append(
            AssignableCause(
                row=read_int(raw["row"], f"{field}[{i}].row"),
                cause=_optional_str(raw["cause"], f"{field}[{i}].cause"),
                annotation_id=_optional_str(raw["annotation_id"], f"{field}[{i}].annotation_id"),
            )
        )
    return tuple(out)


def _encode_policy(policy: LifecyclePolicy) -> dict[str, object]:
    """Codifica la política de revalidación.

    Args:
        policy: Política.

    Returns:
        Diccionario.
    """
    return {
        "revalidate_every_months": policy.revalidate_every_months,
        "revalidate_every_observations": policy.revalidate_every_observations,
    }


def _decode_policy(value: object, field: str) -> LifecyclePolicy:
    """Decodifica la política de revalidación.

    Args:
        value: Diccionario guardado.
        field: Campo.

    Returns:
        La política.
    """
    raw = read_mapping(value, field, _POLICY_FIELDS)
    return LifecyclePolicy(
        revalidate_every_months=_optional_int(
            raw["revalidate_every_months"], f"{field}.revalidate_every_months"
        ),
        revalidate_every_observations=_optional_int(
            raw["revalidate_every_observations"], f"{field}.revalidate_every_observations"
        ),
    )


_EXCLUSION_RECORD_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "exclusion_id",
        "dataset_id",
        "status",
        "assignable_cause",
        "created_at",
        "started_at",
        "finished_at",
        "result",
        "insufficient",
        "output_dataset_id",
        "error",
        "pipeline_id",
    }
)


class ExclusionRecordCodec:
    """Codec de ``ExclusionRecord`` (registro entero como datos)."""

    def encode(self, record: ExclusionRecord) -> object:
        """Codifica el registro.

        Args:
            record: Registro.

        Returns:
            Diccionario serializable.
        """
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "exclusion_id": record.exclusion_id,
            "dataset_id": record.dataset_id,
            "status": record.status.value,
            "assignable_cause": _encode_causes(record.assignable_cause),
            "created_at": _encode_time(record.created_at),
            "started_at": _encode_time(record.started_at),
            "finished_at": _encode_time(record.finished_at),
            "result": None if record.result is None else [d.value for d in record.result],
            "insufficient": record.insufficient,
            "output_dataset_id": record.output_dataset_id,
            "error": _encode_error(record.error),
            "pipeline_id": record.pipeline_id,
        }

    def decode(self, stored: object) -> ExclusionRecord:
        """Decodifica el registro.

        Args:
            stored: Diccionario guardado.

        Returns:
            El registro.
        """
        raw = read_mapping(stored, "exclusion_record", _EXCLUSION_RECORD_FIELDS)
        result = raw["result"]
        insufficient = raw["insufficient"]
        return ExclusionRecord(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=read_str(raw["chart_id"], "chart_id"),
            exclusion_id=read_str(raw["exclusion_id"], "exclusion_id"),
            dataset_id=read_str(raw["dataset_id"], "dataset_id"),
            status=_enum(JobStatus, raw["status"], "status"),
            assignable_cause=_decode_causes(raw["assignable_cause"], "assignable_cause"),
            created_at=_time(raw["created_at"], "created_at"),
            started_at=_optional_time(raw["started_at"], "started_at"),
            finished_at=_optional_time(raw["finished_at"], "finished_at"),
            result=None
            if result is None
            else tuple(
                _enum(RowDisposition, v, f"result[{i}]")
                for i, v in enumerate(_items(result, "result"))
            ),
            insufficient=None if insufficient is None else read_bool(insufficient, "insufficient"),
            output_dataset_id=_optional_str(raw["output_dataset_id"], "output_dataset_id"),
            error=_decode_error(raw["error"]),
            pipeline_id=_optional_str(raw["pipeline_id"], "pipeline_id"),
        )


_PIPELINE_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "pipeline_id",
        "kind",
        "status",
        "dataset_id",
        "params",
        "assignable_cause",
        "lifecycle_policy",
        "created_at",
        "steps",
        "started_at",
        "finished_at",
        "model_id",
        "error",
        "recalibration_id",
    }
)
_STEP_FIELDS: Final = frozenset({"kind", "resource_id"})


class PipelineRecordCodec:
    """Codec de ``PipelineRecord`` (registro entero como datos)."""

    def encode(self, record: PipelineRecord) -> object:
        """Codifica el registro.

        Args:
            record: Registro.

        Returns:
            Diccionario serializable.
        """
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "pipeline_id": record.pipeline_id,
            "kind": record.kind.value,
            "status": record.status.value,
            "dataset_id": record.dataset_id,
            "params": _data(record.params),
            "assignable_cause": _encode_causes(record.assignable_cause),
            "lifecycle_policy": _encode_policy(record.lifecycle_policy),
            "created_at": _encode_time(record.created_at),
            "steps": [{"kind": st.kind, "resource_id": st.resource_id} for st in record.steps],
            "started_at": _encode_time(record.started_at),
            "finished_at": _encode_time(record.finished_at),
            "model_id": record.model_id,
            "error": _encode_error(record.error),
            "recalibration_id": record.recalibration_id,
        }

    def decode(self, stored: object) -> PipelineRecord:
        """Decodifica el registro.

        Args:
            stored: Diccionario guardado.

        Returns:
            El registro.
        """
        raw = read_mapping(stored, "pipeline_record", _PIPELINE_FIELDS)
        steps = []
        for i, item in enumerate(_items(raw["steps"], "steps")):
            st = read_mapping(item, f"steps[{i}]", _STEP_FIELDS)
            steps.append(
                PipelineStep(
                    kind=read_str(st["kind"], f"steps[{i}].kind"),
                    resource_id=read_str(st["resource_id"], f"steps[{i}].resource_id"),
                )
            )
        return PipelineRecord(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=read_str(raw["chart_id"], "chart_id"),
            pipeline_id=read_str(raw["pipeline_id"], "pipeline_id"),
            kind=_enum(PipelineKind, raw["kind"], "kind"),
            status=_enum(JobStatus, raw["status"], "status"),
            dataset_id=read_str(raw["dataset_id"], "dataset_id"),
            params=_mapping_data(raw["params"], "params"),
            assignable_cause=_decode_causes(raw["assignable_cause"], "assignable_cause"),
            lifecycle_policy=_decode_policy(raw["lifecycle_policy"], "lifecycle_policy"),
            created_at=_time(raw["created_at"], "created_at"),
            steps=tuple(steps),
            started_at=_optional_time(raw["started_at"], "started_at"),
            finished_at=_optional_time(raw["finished_at"], "finished_at"),
            model_id=_optional_str(raw["model_id"], "model_id"),
            error=_decode_error(raw["error"]),
            recalibration_id=_optional_str(raw["recalibration_id"], "recalibration_id"),
        )


_MONITORING_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "model_id",
        "monitoring_id",
        "status",
        "observations",
        "observed_at",
        "created_at",
        "batch_label",
        "started_at",
        "finished_at",
        "result",
        "error",
    }
)
_SUMMARY_FIELDS: Final = frozenset({"observation_ids", "version_numbers", "n_signals"})


class MonitoringRecordCodec:
    """Codec de ``MonitoringRecord`` (registro entero como datos, matriz exacta en bits)."""

    def encode(self, record: MonitoringRecord) -> object:
        """Codifica el registro.

        Args:
            record: Registro.

        Returns:
            Diccionario serializable.
        """
        result = record.result
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "model_id": record.model_id,
            "monitoring_id": record.monitoring_id,
            "status": record.status.value,
            "observations": encode_array(record.observations),
            "observed_at": _encode_times(record.observed_at),
            "created_at": _encode_time(record.created_at),
            "batch_label": record.batch_label,
            "started_at": _encode_time(record.started_at),
            "finished_at": _encode_time(record.finished_at),
            "result": None
            if result is None
            else {
                "observation_ids": list(result.observation_ids),
                "version_numbers": list(result.version_numbers),
                "n_signals": result.n_signals,
            },
            "error": _encode_error(record.error),
        }

    def decode(self, stored: object) -> MonitoringRecord:
        """Decodifica el registro.

        Args:
            stored: Diccionario guardado.

        Returns:
            El registro.
        """
        raw = read_mapping(stored, "monitoring_record", _MONITORING_FIELDS)
        result = raw["result"]
        summary = None
        if result is not None:
            res = read_mapping(result, "result", _SUMMARY_FIELDS)
            summary = MonitoringSummary(
                observation_ids=_strings(res["observation_ids"], "result.observation_ids"),
                version_numbers=tuple(
                    read_int(v, f"result.version_numbers[{i}]")
                    for i, v in enumerate(_items(res["version_numbers"], "result.version_numbers"))
                ),
                n_signals=read_int(res["n_signals"], "result.n_signals"),
            )
        return MonitoringRecord(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=read_str(raw["chart_id"], "chart_id"),
            model_id=read_str(raw["model_id"], "model_id"),
            monitoring_id=read_str(raw["monitoring_id"], "monitoring_id"),
            status=_enum(JobStatus, raw["status"], "status"),
            observations=decode_float_array(raw["observations"], "observations"),
            observed_at=_optional_times(raw["observed_at"], "observed_at") or (),
            created_at=_time(raw["created_at"], "created_at"),
            batch_label=_optional_str(raw["batch_label"], "batch_label"),
            started_at=_optional_time(raw["started_at"], "started_at"),
            finished_at=_optional_time(raw["finished_at"], "finished_at"),
            result=summary,
            error=_decode_error(raw["error"]),
        )


_OBSERVATION_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "model_id",
        "observation_id",
        "monitoring_id",
        "batch_label",
        "observed_at",
        "values",
        "t2",
        "limit",
        "limit_kind",
        "version_number",
        "signal",
        "recorded_at",
    }
)


class ObservationRecordCodec:
    """Codec de ``ObservationRecord``: los valores y los reales, exactos en bits.

    ``t2`` y ``limit`` se guardan con ``float.hex`` (también ``nan``, ``inf`` y ``-0.0``) para
    que la forma guardada sea JSON estricto y la ida y vuelta exacta.
    """

    def encode(self, record: ObservationRecord) -> object:
        """Codifica la observación.

        Args:
            record: Observación.

        Returns:
            Diccionario serializable.
        """
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "model_id": record.model_id,
            "observation_id": record.observation_id,
            "monitoring_id": record.monitoring_id,
            "batch_label": record.batch_label,
            "observed_at": _encode_time(record.observed_at),
            "values": encode_array(record.values),
            "t2": float(record.t2).hex(),
            "limit": float(record.limit).hex(),
            "limit_kind": record.limit_kind,
            "version_number": record.version_number,
            "signal": bool(record.signal),
            "recorded_at": _encode_time(record.recorded_at),
        }

    def decode(self, stored: object) -> ObservationRecord:
        """Decodifica la observación.

        Args:
            stored: Diccionario guardado.

        Returns:
            La observación.
        """
        raw = read_mapping(stored, "observation_record", _OBSERVATION_FIELDS)
        return ObservationRecord(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=read_str(raw["chart_id"], "chart_id"),
            model_id=read_str(raw["model_id"], "model_id"),
            observation_id=read_str(raw["observation_id"], "observation_id"),
            monitoring_id=read_str(raw["monitoring_id"], "monitoring_id"),
            batch_label=_optional_str(raw["batch_label"], "batch_label"),
            observed_at=_time(raw["observed_at"], "observed_at"),
            values=decode_float_array(raw["values"], "values"),
            t2=_hex_float(raw["t2"], "t2"),
            limit=_hex_float(raw["limit"], "limit"),
            limit_kind=read_str(raw["limit_kind"], "limit_kind"),
            version_number=read_int(raw["version_number"], "version_number"),
            signal=read_bool(raw["signal"], "signal"),
            recorded_at=_time(raw["recorded_at"], "recorded_at"),
        )


def _hex_float(value: object, field: str) -> float:
    """Real guardado con ``float.hex``.

    Args:
        value: Texto guardado.
        field: Campo.

    Returns:
        El real, idéntico en bits.

    Raises:
        InvalidInputError: Si no es un real hexadecimal.
    """
    text = read_str(value, field)
    try:
        return float.fromhex(text)
    except ValueError as exc:
        raise InvalidInputError(
            f"'{field}' no es un real hexadecimal",
            details={"field": field, "reason": "invalid_encoding"},
        ) from exc


_ANNOTATION_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "model_id",
        "annotation_id",
        "observation_id",
        "assignable_cause",
        "cause",
        "action",
        "actor",
        "created_at",
    }
)


class SignalAnnotationCodec:
    """Codec de ``SignalAnnotation``."""

    def encode(self, record: SignalAnnotation) -> object:
        """Codifica la anotación.

        Args:
            record: Anotación.

        Returns:
            Diccionario serializable.
        """
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "model_id": record.model_id,
            "annotation_id": record.annotation_id,
            "observation_id": record.observation_id,
            "assignable_cause": record.assignable_cause,
            "cause": record.cause,
            "action": record.action,
            "actor": record.actor,
            "created_at": _encode_time(record.created_at),
        }

    def decode(self, stored: object) -> SignalAnnotation:
        """Decodifica la anotación.

        Args:
            stored: Diccionario guardado.

        Returns:
            La anotación.
        """
        raw = read_mapping(stored, "signal_annotation", _ANNOTATION_FIELDS)
        return SignalAnnotation(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=read_str(raw["chart_id"], "chart_id"),
            model_id=read_str(raw["model_id"], "model_id"),
            annotation_id=read_str(raw["annotation_id"], "annotation_id"),
            observation_id=read_str(raw["observation_id"], "observation_id"),
            assignable_cause=read_bool(raw["assignable_cause"], "assignable_cause"),
            cause=_optional_str(raw["cause"], "cause"),
            action=_optional_str(raw["action"], "action"),
            actor=_optional_str(raw["actor"], "actor"),
            created_at=_time(raw["created_at"], "created_at"),
        )


_EVENT_FIELDS: Final = frozenset(
    {
        "tenant_id",
        "chart_id",
        "model_id",
        "event_id",
        "occurred_at",
        "description",
        "actor",
        "registered_at",
    }
)


class StructuralEventCodec:
    """Codec de ``StructuralEvent``."""

    def encode(self, record: StructuralEvent) -> object:
        """Codifica el evento.

        Args:
            record: Evento.

        Returns:
            Diccionario serializable.
        """
        return {
            "tenant_id": record.tenant_id,
            "chart_id": record.chart_id,
            "model_id": record.model_id,
            "event_id": record.event_id,
            "occurred_at": _encode_time(record.occurred_at),
            "description": record.description,
            "actor": record.actor,
            "registered_at": _encode_time(record.registered_at),
        }

    def decode(self, stored: object) -> StructuralEvent:
        """Decodifica el evento.

        Args:
            stored: Diccionario guardado.

        Returns:
            El evento.
        """
        raw = read_mapping(stored, "structural_event", _EVENT_FIELDS)
        return StructuralEvent(
            tenant_id=read_str(raw["tenant_id"], "tenant_id"),
            chart_id=read_str(raw["chart_id"], "chart_id"),
            model_id=read_str(raw["model_id"], "model_id"),
            event_id=read_str(raw["event_id"], "event_id"),
            occurred_at=_time(raw["occurred_at"], "occurred_at"),
            description=read_str(raw["description"], "description"),
            actor=_optional_str(raw["actor"], "actor"),
            registered_at=_time(raw["registered_at"], "registered_at"),
        )
