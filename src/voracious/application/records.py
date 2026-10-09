"""Registros persistentes del ciclo de vida de una carta, comunes a todas las cartas.

Datasets, pasos encadenables de la Fase I (exclusiones, ajustes, límites y tuberías; vuelta 3.3
del Paso 3), modelos (Fase I), monitoreos (Fase II), versiones, observaciones, anotaciones,
eventos estructurales y recalibraciones (ADR 0005, ADR 0008). Los registros son inmutables; cada
transición de estado crea uno nuevo con ``dataclasses.replace`` y se guarda con ``update`` (o, en
las versiones, con el comparar-y-cambiar de ``ModelVersionRepository``). El modelo y los informes
de cada carta se guardan como ``object``: solo la carta los interpreta. Los parámetros se guardan
**codificados** como datos (``ControlChart.encode_params``, mejora M1). Todas las fechas son UTC
con zona horaria.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from voracious.domain.common import (
    BoolVector,
    FloatMatrix,
    FloatVector,
    InvalidInputError,
    RecalibrationDecision,
    RowDisposition,
)

__all__ = [
    "AssignableCause",
    "BaseRowRef",
    "BaseRowSource",
    "ComparisonRecord",
    "DatasetRecord",
    "DatasetSource",
    "ErrorInfo",
    "Exclusion",
    "ExclusionReason",
    "ExclusionRecord",
    "FitRecord",
    "IndexVector",
    "JobStatus",
    "LifecyclePolicy",
    "LimitsRecord",
    "ModelProvenance",
    "ModelRecord",
    "ModelVersion",
    "MonitoringRecord",
    "MonitoringSummary",
    "ObservationRecord",
    "PipelineKind",
    "PipelineRecord",
    "PipelineStep",
    "ProposalRequest",
    "RecalibrationMode",
    "RecalibrationRecord",
    "SignalAnnotation",
    "StructuralEvent",
    "VersionStatus",
]

IndexVector = npt.NDArray[np.int64]
"""Índices de fila (base 0)."""

DEFAULT_REVALIDATE_EVERY_MONTHS = 6
"""Revalidación periódica por defecto: documento de diseño del dueño (2026-10-07), sin cita."""


class JobStatus(StrEnum):
    """Estado de un trabajo asíncrono (ADR 0003, ADR 0005)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    """Cancelado por una persona (hoy solo una recalibración paso a paso sin propuesta pedida)."""


@dataclass(frozen=True)
class ErrorInfo:
    """Error de un trabajo ``failed``, sin trazas.

    Attributes:
        code: Código estable (p. ej. ``T2MRCD_DECISION_PENDING``).
        message: Mensaje legible.
        details: Datos adicionales serializables.
    """

    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LifecyclePolicy:
    """Política de revalidación periódica de la carta (ADR 0008, punto 7).

    Se evalúa al consultar el estado de la carta (con ``Clock``), sin tareas programadas.

    Attributes:
        revalidate_every_months: Meses desde la aprobación de la versión vigente tras los que se
            avisa (6 por defecto, documento del dueño); ``None`` desactiva el criterio.
        revalidate_every_observations: Observaciones puntuadas con la versión vigente tras las
            que se avisa; ``None`` (por defecto) desactiva el criterio.
    """

    revalidate_every_months: int | None = DEFAULT_REVALIDATE_EVERY_MONTHS
    revalidate_every_observations: int | None = None

    def __post_init__(self) -> None:
        """Valida que cada criterio sea ``None`` o un entero ``>= 1``.

        Raises:
            InvalidInputError: Si un criterio no es ``None`` ni un entero ``>= 1``.
        """
        for name, value in (
            ("revalidate_every_months", self.revalidate_every_months),
            ("revalidate_every_observations", self.revalidate_every_observations),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise InvalidInputError(
                    f"'{name}' debe ser None o un entero >= 1",
                    details={"field": f"lifecycle_policy.{name}"},
                )


@dataclass(frozen=True, eq=False)
class ModelRecord:
    """Modelo de Fase I de un tenant: la carta del portafolio, de la que cuelgan sus versiones.

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta (``t2mrcd``…).
        model_id: Identificador del modelo.
        status: Estado del trabajo.
        params: Parámetros de la carta codificados como datos (``encode_params``).
        training_data: Histórico ``n x p`` con el que se ajusta.
        created_at: Instante de creación (UTC).
        started_at: Instante en que pasó a ``running`` (UTC).
        finished_at: Instante en que terminó (UTC).
        model: Modelo de la carta si ``succeeded`` (el de la versión 0).
        error: Error si ``failed``.
        lifecycle_policy: Política de revalidación periódica.
        provenance: Recursos de los que se ensambló (vuelta 3.3): dataset raíz, exclusión humana,
            ajuste y límites; ``None`` en un modelo sin cadena de pasos.
        pipeline_id: Tubería que lo pidió, si la hay (al terminar se la avisa).
    """

    tenant_id: str
    chart_id: str
    model_id: str
    status: JobStatus
    params: Mapping[str, object]
    training_data: FloatMatrix
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    model: object | None = None
    error: ErrorInfo | None = None
    lifecycle_policy: LifecyclePolicy = field(default_factory=LifecyclePolicy)
    provenance: "ModelProvenance | None" = None
    pipeline_id: str | None = None


@dataclass(frozen=True)
class ModelProvenance:
    """De qué recursos se ensambló un modelo (la cadena de Fase I por pasos).

    Attributes:
        root_dataset_id: Dataset raíz (el histórico subido): ``training_data`` del modelo.
        fit_id: Ajuste final.
        limits_id: Límites finales.
        exclusion_id: Exclusión humana de la que sale el dataset del ajuste, o ``None`` si se
            ajustó el dataset raíz.
    """

    root_dataset_id: str
    fit_id: str
    limits_id: str
    exclusion_id: str | None = None


class DatasetSource(StrEnum):
    """Origen de un dataset."""

    UPLOAD = "upload"
    """Subido por el cliente (raíz de una Fase I)."""

    EXCLUSION_OUTPUT = "exclusion_output"
    """Filas conservadas por una exclusión humana (``parent[rows]``)."""

    RECALIBRATION_CANDIDATES = "recalibration_candidates"
    """Observaciones candidatas de una recalibración (raíz de sus pasos; vuelta 3.4)."""

    RECALIBRATION_EXTENSION = "recalibration_extension"
    """Base ampliada de una recalibración (``vstack(base, nuevas)``; vuelta 3.4)."""


@dataclass(frozen=True, eq=False)
class DatasetRecord:
    """Matriz ``n x p`` inmutable de un tenant, con su linaje.

    Attributes:
        tenant_id: Tenant propietario.
        dataset_id: Identificador.
        data: Matriz ``n x p`` ``float64`` contigua.
        content_hash: Huella del contenido (``base_content_hash``).
        source: Origen.
        created_at: Instante de creación (UTC).
        parent_id: Dataset del que deriva (``None`` en una raíz).
        rows: Índices de sus filas en ``parent_id`` (``data == parent.data[rows]``); ``None`` en
            una raíz.
        origin_ref: Recurso que lo creó (la exclusión o la recalibración), si lo hay.
    """

    tenant_id: str
    dataset_id: str
    data: FloatMatrix
    content_hash: str
    source: DatasetSource
    created_at: datetime
    parent_id: str | None = None
    rows: IndexVector | None = None
    origin_ref: str | None = None


@dataclass(frozen=True, eq=False)
class FitRecord:
    """Ajuste del estimador de una carta sobre un dataset (``/fits``).

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta bajo la que se ajusta.
        fit_id: Identificador.
        dataset_id: Dataset ajustado.
        status: Estado del trabajo.
        params: Parámetros del estimador codificados como datos.
        created_at: Instante de creación (UTC).
        started_at: Instante en que pasó a ``running`` (UTC).
        finished_at: Instante en que terminó (UTC).
        result: Ajuste del estimador si ``succeeded``.
        error: Error si ``failed``.
        pipeline_id: Tubería que lo pidió, si la hay.
    """

    tenant_id: str
    chart_id: str
    fit_id: str
    dataset_id: str
    status: JobStatus
    params: Mapping[str, object]
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: object | None = None
    error: ErrorInfo | None = None
    pipeline_id: str | None = None


@dataclass(frozen=True, eq=False)
class LimitsRecord:
    """Calibración de límites sobre un ajuste (``/limits``).

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        limits_id: Identificador.
        fit_id: Ajuste calibrado.
        status: Estado del trabajo.
        params: Parámetros de la carta codificados como datos.
        seed: Semilla raíz de la calibración.
        stage_kind: Operación (``phase1``, ``new_rows`` o ``extension``), deducida del dataset;
            nunca la elige el cliente.
        spawn_key: Hueco de semilla de la operación (``stage_spawn_key``).
        created_at: Instante de creación (UTC).
        recalibration_id: Recalibración de la que forma parte, si la hay (vuelta 3.4).
        started_at: Instante en que pasó a ``running`` (UTC).
        finished_at: Instante en que terminó (UTC).
        result: Límites de la carta si ``succeeded``.
        clean_rows: Filas limpias del ajuste (máscara sobre las filas del dataset) si
            ``succeeded``.
        error: Error si ``failed``.
        pipeline_id: Tubería que lo pidió, si la hay.
    """

    tenant_id: str
    chart_id: str
    limits_id: str
    fit_id: str
    status: JobStatus
    params: Mapping[str, object]
    seed: int
    stage_kind: str
    spawn_key: tuple[int, ...]
    created_at: datetime
    recalibration_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: object | None = None
    clean_rows: BoolVector | None = None
    error: ErrorInfo | None = None
    pipeline_id: str | None = None


@dataclass(frozen=True)
class AssignableCause:
    """Fila excluida por una persona (causa asignable confirmada).

    Attributes:
        row: Índice de la fila en el dataset del ajuste (base 0).
        cause: Cuál fue la causa.
        annotation_id: Anotación de la que sale la exclusión (al recalibrar, la exclusión humana
            se toma de las anotaciones con causa asignable confirmada; ``None`` en la Fase I).
    """

    row: int
    cause: str | None = None
    annotation_id: str | None = None


@dataclass(frozen=True, eq=False)
class ExclusionRecord:
    """Exclusión humana de las filas de un dataset con causa asignable (``/exclusions``).

    Referencia el dataset, sin ajuste: se aplica antes de ajustar nada, como en ``fit_phase1``.
    En la Fase I la piden las filas del cliente; sobre las candidatas de una recalibración, las
    anotaciones con causa asignable confirmada.

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        exclusion_id: Identificador.
        dataset_id: Dataset de entrada.
        status: Estado del trabajo.
        assignable_cause: Filas excluidas por una persona.
        created_at: Instante de creación (UTC).
        started_at: Instante en que pasó a ``running`` (UTC).
        finished_at: Instante en que terminó (UTC).
        result: Destino de cada fila del dataset si ``succeeded``.
        insufficient: ``True`` si, en una recalibración, quedan menos filas que
            ``min_observations`` (la recalibración termina ``insufficient`` y no hay dataset de
            salida); ``False`` si no; ``None`` mientras no termine.
        output_dataset_id: Dataset derivado con las filas conservadas.
        error: Error si ``failed``.
        pipeline_id: Tubería que lo pidió, si la hay.
    """

    tenant_id: str
    chart_id: str
    exclusion_id: str
    dataset_id: str
    status: JobStatus
    assignable_cause: tuple[AssignableCause, ...]
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: tuple[RowDisposition, ...] | None = None
    insufficient: bool | None = None
    output_dataset_id: str | None = None
    error: ErrorInfo | None = None
    pipeline_id: str | None = None


class PipelineKind(StrEnum):
    """Tipo de tubería."""

    PHASE1 = "phase1"
    """Fase I completa: exclusión humana (si la hay), ajuste, límites y modelo."""

    RECALIBRATION = "recalibration"
    """Recalibración completa (modo ``pipeline``): exclusión humana de las filas nuevas, ajuste,
    límites, comparación, extensión y propuesta de versión (vuelta 3.4)."""


@dataclass(frozen=True)
class PipelineStep:
    """Paso de una tubería: el recurso que creó.

    Attributes:
        kind: ``exclusion``, ``fit``, ``limits``, ``model``, ``comparison`` o ``version``.
        resource_id: Identificador del recurso.
    """

    kind: str
    resource_id: str


@dataclass(frozen=True, eq=False)
class PipelineRecord:
    """Orquestación de pasos encadenados: solo referencias, sin cómputo.

    ``PHASE1`` (``/pipelines/phase1``) o ``RECALIBRATION`` (recalibración en modo ``pipeline``).

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        pipeline_id: Identificador.
        kind: Tipo de tubería.
        status: Estado.
        dataset_id: Dataset raíz (en una recalibración, el de candidatas).
        params: Parámetros de la carta codificados (en una recalibración, los heredados).
        assignable_cause: Filas del dataset raíz excluidas por una persona (en una
            recalibración, vacía: la exclusión humana sale de las anotaciones).
        lifecycle_policy: Política del modelo resultante.
        created_at: Instante de creación (UTC).
        steps: Recursos creados, en orden.
        started_at: Instante en que pasó a ``running`` (UTC).
        finished_at: Instante en que terminó (UTC).
        model_id: Modelo resultante si ``succeeded`` (Fase I) o modelo recalibrado, fijado al
            crearla (recalibración).
        error: Error si ``failed`` (el del paso que falló, con ``details.step``).
        recalibration_id: Recalibración que orquesta (solo ``RECALIBRATION``).
    """

    tenant_id: str
    chart_id: str
    pipeline_id: str
    kind: PipelineKind
    status: JobStatus
    dataset_id: str
    params: Mapping[str, object]
    assignable_cause: tuple[AssignableCause, ...]
    lifecycle_policy: LifecyclePolicy
    created_at: datetime
    steps: tuple[PipelineStep, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None
    model_id: str | None = None
    error: ErrorInfo | None = None
    recalibration_id: str | None = None


@dataclass(frozen=True)
class MonitoringSummary:
    """Resultado de un monitoreo ``succeeded``: las observaciones registradas.

    Attributes:
        observation_ids: Observaciones registradas, en el orden de las filas del lote.
        version_numbers: Versión con la que se puntuó cada fila (mismo orden).
        n_signals: Filas con señal.
    """

    observation_ids: tuple[str, ...]
    version_numbers: tuple[int, ...]
    n_signals: int


@dataclass(frozen=True, eq=False)
class MonitoringRecord:
    """Monitoreo de Fase II contra un modelo.

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        model_id: Modelo contra el que se puntúa.
        monitoring_id: Identificador del monitoreo.
        status: Estado del trabajo.
        observations: Observaciones nuevas ``m x p``.
        observed_at: Fecha de cada fila (UTC), longitud ``m``.
        created_at: Instante de creación (UTC).
        batch_label: Etiqueta opcional del lote.
        started_at: Instante en que pasó a ``running`` (UTC).
        finished_at: Instante en que terminó (UTC).
        result: Observaciones registradas si ``succeeded``.
        error: Error si ``failed``.
    """

    tenant_id: str
    chart_id: str
    model_id: str
    monitoring_id: str
    status: JobStatus
    observations: FloatMatrix
    observed_at: tuple[datetime, ...]
    created_at: datetime
    batch_label: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: MonitoringSummary | None = None
    error: ErrorInfo | None = None


class VersionStatus(StrEnum):
    """Estado de una versión del modelo (lo único mutable de una versión, ADR 0008)."""

    PROPOSED = "proposed"
    """Propuesta por una recalibración; no rige hasta aprobarse."""

    ACTIVE = "active"
    """Vigente: la última versión aprobada."""

    SUPERSEDED = "superseded"
    """Aprobada y sustituida por otra posterior; sigue rigiendo las fechas anteriores."""

    REJECTED = "rejected"
    """Propuesta rechazada (por una persona o por un evento estructural)."""


class BaseRowSource(StrEnum):
    """Origen de una fila de la base de una versión."""

    TRAINING = "training"
    """Fila del histórico de Fase I; ``ref`` es su índice (base 0) en ``training_data``."""

    OBSERVATION = "observation"
    """Observación de Fase II; ``ref`` es su ``observation_id``."""


@dataclass(frozen=True)
class BaseRowRef:
    """Referencia a una fila de la base de una versión.

    Attributes:
        source: Origen de la fila.
        ref: Índice del histórico (como texto) u ``observation_id``.
    """

    source: BaseRowSource
    ref: str


class ExclusionReason(StrEnum):
    """Por qué una fila candidata no entró en la base de una versión."""

    ASSIGNABLE_CAUSE = "assignable_cause"
    """Excluida por una persona: anotación con causa asignable confirmada."""

    ALREADY_IN_BASE = "already_in_base"
    """Ya formaba parte de la base de la versión vigente (no se vuelve a pasar como nueva)."""


@dataclass(frozen=True)
class Exclusion:
    """Fila excluida de la base de una versión.

    Attributes:
        ref: Fila excluida.
        reason: Motivo.
        annotation_id: Anotación que la excluyó (solo ``ASSIGNABLE_CAUSE``).
    """

    ref: BaseRowRef
    reason: ExclusionReason
    annotation_id: str | None = None


@dataclass(frozen=True, eq=False)
class ModelVersion:
    """Versión inmutable del modelo de una carta (ADR 0008).

    Solo ``status`` y los campos de la decisión (``effective_from``, ``approved_at``,
    ``rejected_at``, ``decided_by`` y ``decision_note``) cambian, y solo por el comparar-y-cambiar
    de ``ModelVersionRepository``; el contenido (modelo, base, informe) no se modifica nunca.

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        model_id: Carta del portafolio de la que cuelga la versión.
        number: Número de versión (0 = Fase I inicial).
        status: Estado.
        model: Modelo de la carta de esta versión.
        base_data: Base ``n x p`` con la que se ajustó (copia propia).
        base_hash: Huella del contenido de ``base_data`` (``base_content_hash``).
        base_refs: Origen de cada fila de ``base_data``, en el mismo orden.
        exclusions: Filas candidatas que no entraron en la base.
        decision: ``initial``, ``extend`` o ``replace``.
        justification: Por qué se tomó la decisión (``initial_fit``, ``structural_event``,
            ``forced_replace``, ``change_detected`` o ``no_change_detected``).
        report: Informe de la recalibración (antes/después), ``None`` en la versión 0.
        recalibration_id: Recalibración que la propuso.
        structural_event_id: Evento estructural que resuelve, si lo hay.
        previous_number: Versión vigente cuando se propuso.
        created_at: Instante de creación (UTC).
        effective_from: Desde cuándo rige (UTC); ``None`` = desde el origen (versión 0).
        approved_at: Instante de aprobación (UTC).
        rejected_at: Instante de rechazo (UTC).
        decided_by: Quién aprobó o rechazó.
        decision_note: Nota de la decisión (``structural_event`` si la rechazó un evento).
    """

    tenant_id: str
    chart_id: str
    model_id: str
    number: int
    status: VersionStatus
    model: object
    base_data: FloatMatrix
    base_hash: str
    base_refs: tuple[BaseRowRef, ...]
    exclusions: tuple[Exclusion, ...]
    decision: RecalibrationDecision
    justification: str
    created_at: datetime
    report: object | None = None
    recalibration_id: str | None = None
    structural_event_id: str | None = None
    previous_number: int | None = None
    effective_from: datetime | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str | None = None


@dataclass(frozen=True, eq=False)
class ObservationRecord:
    """Observación de Fase II puntuada y registrada (ADR 0008, punto 3).

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        model_id: Carta del portafolio.
        observation_id: Identificador de la observación.
        monitoring_id: Monitoreo que la registró.
        batch_label: Etiqueta del lote.
        observed_at: Fecha de la observación (UTC).
        values: Valores de las ``p`` variables.
        t2: Estadístico de la carta.
        limit: Límite con el que se evaluó.
        limit_kind: Régimen de ese límite (``phase1_provisional`` o ``phase2`` en T²MRCD).
        version_number: Versión con la que se puntuó (la vigente en ``observed_at``).
        signal: ``True`` si superó el límite.
        recorded_at: Instante del registro (UTC).
    """

    tenant_id: str
    chart_id: str
    model_id: str
    observation_id: str
    monitoring_id: str
    batch_label: str | None
    observed_at: datetime
    values: FloatVector
    t2: float
    limit: float
    limit_kind: str
    version_number: int
    signal: bool
    recorded_at: datetime


@dataclass(frozen=True)
class SignalAnnotation:
    """Anotación de una observación con señal (Q12). Solo se añaden; vale la más reciente.

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        model_id: Carta del portafolio.
        annotation_id: Identificador de la anotación.
        observation_id: Observación anotada.
        assignable_cause: ``True`` si se confirmó una causa asignable (la excluye al recalibrar).
        cause: Cuál fue la causa.
        action: Acción tomada.
        actor: Quién anotó.
        created_at: Instante de la anotación (UTC).
    """

    tenant_id: str
    chart_id: str
    model_id: str
    annotation_id: str
    observation_id: str
    assignable_cause: bool
    cause: str | None
    action: str | None
    actor: str | None
    created_at: datetime


@dataclass(frozen=True)
class StructuralEvent:
    """Evento estructural del proceso: marca «requiere nueva base» (ADR 0008, punto 6).

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        model_id: Carta del portafolio.
        event_id: Identificador del evento.
        occurred_at: Cuándo ocurrió (UTC).
        description: Descripción.
        actor: Quién lo registró.
        registered_at: Instante del registro (UTC).
    """

    tenant_id: str
    chart_id: str
    model_id: str
    event_id: str
    occurred_at: datetime
    description: str
    actor: str | None
    registered_at: datetime


class RecalibrationMode(StrEnum):
    """Cómo se ejecuta una recalibración (vuelta 3.4)."""

    PIPELINE = "pipeline"
    """Todo junto: una tubería encadena los pasos (orquestación pura)."""

    STEPWISE = "stepwise"
    """Paso a paso: el cliente pide cada paso por su API y los encadena por id."""


@dataclass(frozen=True)
class ProposalRequest:
    """Pasos con los que se pidió la versión propuesta de una recalibración (``/versions``).

    Attributes:
        fit_id: Ajuste final (filas nuevas en REPLACE; base ampliada en EXTEND).
        limits_id: Límites de ese ajuste.
        comparison_id: Comparación de bases (``None`` en un reemplazo forzado).
        status: Estado del trabajo de la propuesta.
        requested_at: Instante de la petición (UTC).
    """

    fit_id: str
    limits_id: str
    comparison_id: str | None
    status: JobStatus
    requested_at: datetime


@dataclass(frozen=True, eq=False)
class RecalibrationRecord:
    """Trabajo de recalibración a petición (ADR 0008, punto 4).

    Es también la **sesión** de la recalibración por pasos (vuelta 3.4): fija al pedirla las
    observaciones candidatas (en orden), las que ya estaban en la base y los parámetros de la
    carta heredados de la versión base con la semilla de la recalibración (Q8). Mientras está
    ``running`` admite pasos; termina al proponer la versión, al quedar ``insufficient`` o al
    fallar.

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        model_id: Carta del portafolio.
        recalibration_id: Identificador.
        status: Estado del trabajo.
        range_from: Inicio del rango de fechas de las observaciones (UTC, inclusivo).
        range_to: Fin del rango (UTC, inclusivo).
        params: Parámetros de la recalibración codificados como datos.
        force_replace: Reemplazo forzado (por una persona o por un evento estructural).
        base_version_number: Versión vigente (la base) al pedirla.
        structural_event_id: Evento estructural que resuelve, si lo hay.
        created_at: Instante de creación (UTC).
        actor: Quién la pidió.
        started_at: Instante en que pasó a ``running`` (UTC).
        finished_at: Instante en que terminó (UTC).
        outcome: Decisión de la carta si ``succeeded`` (``insufficient`` sin versión).
        report: Informe de la carta si ``succeeded``.
        proposed_version: Número de la versión creada, si se creó.
        error: Error si ``failed``.
        mode: ``pipeline`` o ``stepwise``.
        inherited_params: Parámetros de la carta heredados de la versión base con la semilla de
            la recalibración, codificados (los usan los límites de la recalibración).
        candidate_ids: Observaciones candidatas (las nuevas del rango), en orden: fila ``i`` del
            dataset de candidatas.
        already_in_base_ids: Observaciones del rango que ya estaban en la base vigente.
        candidates_dataset_id: Dataset ``recalibration_candidates``.
        pipeline_id: Tubería que la orquesta (modo ``pipeline``).
        proposal: Petición de la versión propuesta, si se hizo.
    """

    tenant_id: str
    chart_id: str
    model_id: str
    recalibration_id: str
    status: JobStatus
    range_from: datetime
    range_to: datetime
    params: Mapping[str, object]
    force_replace: bool
    base_version_number: int
    structural_event_id: str | None
    created_at: datetime
    actor: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    outcome: RecalibrationDecision | None = None
    report: object | None = None
    proposed_version: int | None = None
    error: ErrorInfo | None = None
    mode: RecalibrationMode = RecalibrationMode.PIPELINE
    inherited_params: Mapping[str, object] = field(default_factory=dict)
    candidate_ids: tuple[str, ...] = ()
    already_in_base_ids: tuple[str, ...] = ()
    candidates_dataset_id: str | None = None
    pipeline_id: str | None = None
    proposal: ProposalRequest | None = None


@dataclass(frozen=True, eq=False)
class ComparisonRecord:
    """Comparación de la base vigente con las filas nuevas conservadas (``/comparisons``).

    Attributes:
        tenant_id: Tenant propietario.
        chart_id: Carta.
        model_id: Modelo recalibrado.
        comparison_id: Identificador.
        recalibration_id: Recalibración a la que pertenece.
        fit_id: Ajuste de las filas nuevas conservadas (``μ₁``, ``S₁``).
        limits_id: Límites de ese ajuste (operación ``new_rows``).
        status: Estado del trabajo.
        created_at: Instante de creación (UTC).
        started_at: Instante en que pasó a ``running`` (UTC).
        finished_at: Instante en que terminó (UTC).
        result: Comparación de la carta si ``succeeded``.
        decision: ``extend`` o ``replace`` si ``succeeded``.
        extension_dataset_id: Dataset ``recalibration_extension`` (base + nuevas) si ``extend``.
        error: Error si ``failed``.
        pipeline_id: Tubería que la pidió, si la hay.
    """

    tenant_id: str
    chart_id: str
    model_id: str
    comparison_id: str
    recalibration_id: str
    fit_id: str
    limits_id: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: object | None = None
    decision: RecalibrationDecision | None = None
    extension_dataset_id: str | None = None
    error: ErrorInfo | None = None
    pipeline_id: str | None = None
