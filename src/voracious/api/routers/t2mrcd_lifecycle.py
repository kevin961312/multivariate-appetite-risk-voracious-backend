"""Rutas del ciclo de vida de la carta T²MRCD bajo ``/v1/charts/t2mrcd/models`` (ADR 0005, 0008).

Solo traducen HTTP ↔ casos de uso: ninguna lógica estadística ni de ciclo de vida. Los pasos de
cómputo responden ``202`` con el identificador y se consultan con ``GET`` (estado
``queued | running | succeeded | failed``); los comandos sin cómputo responden ``201``/``200``.
La recalibración paso a paso (vuelta 3.4) abre su sesión con ``201`` y se encadena por id con
``/exclusions``, ``…/recalibrations/{id}/extension`` (salvo reemplazo), ``/fits``, ``/limits`` y
``…/versions``.
``POST /models`` (solo referencias) está en ``t2mrcd_phase1.py`` con el resto de los pasos de la
Fase I; aquí queda la consulta del modelo y su ciclo de vida.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from voracious.api.auth import Decider, Operator, Reader
from voracious.api.deps import get_container
from voracious.api.schemas.common import AcceptedJob, ErrorResponse
from voracious.api.schemas.t2mrcd import (
    AnnotationOut,
    AnnotationRequest,
    ApproveRequest,
    ChartStatusOut,
    ModelInclude,
    ModelResponse,
    ObservationOut,
    RecalibrationInclude,
    RecalibrationRequest,
    RecalibrationResponse,
    RejectRequest,
    ScoreRequest,
    ScoreResponse,
    StructuralEventOut,
    StructuralEventRequest,
    VersionDetail,
    VersionInclude,
    VersionSummary,
)
from voracious.api.schemas.t2mrcd_recalibration import (
    ExtensionOut,
    ExtensionRequest,
    StepwiseRecalibrationOut,
    VersionProposalRequest,
)
from voracious.application.records import RecalibrationMode
from voracious.container import Container
from voracious.domain.charts.t2mrcd import CHART_ID

__all__ = ["router"]

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}

router = APIRouter(prefix=f"/v1/charts/{CHART_ID}/models", responses=_ERRORS)

ContainerDep = Annotated[Container, Depends(get_container)]


@router.get("/{model_id}", response_model=ModelResponse, tags=["t2mrcd-models"])
def get_model(
    model_id: str,
    principal: Reader,
    c: ContainerDep,
    include: Annotated[list[ModelInclude] | None, Query()] = None,
) -> ModelResponse:
    """Estado del modelo y, si terminó bien, el modelo (M3: matrices con ``include``).

    Args:
        model_id: Modelo.
        principal: Quien llama (lectura: analyst, approver o admin); da el tenant.
        c: Contenedor.
        include: Partes grandes opcionales.

    Returns:
        El modelo.
    """
    record = c.use_cases.get_model.execute(principal.tenant_id, CHART_ID, model_id)
    return ModelResponse.of(record, include or ())


@router.get("/{model_id}/status", response_model=ChartStatusOut, tags=["t2mrcd-models"])
def get_status(model_id: str, principal: Reader, c: ContainerDep) -> ChartStatusOut:
    """Estado de la carta por precedencia y sus avisos.

    Args:
        model_id: Modelo.
        principal: Quien llama (lectura: analyst, approver o admin); da el tenant.
        c: Contenedor.

    Returns:
        El estado.
    """
    return ChartStatusOut.of(c.use_cases.status.execute(principal.tenant_id, CHART_ID, model_id))


@router.post(
    "/{model_id}/scores",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedJob,
    tags=["t2mrcd-scores"],
)
def score(model_id: str, body: ScoreRequest, principal: Operator, c: ContainerDep) -> AcceptedJob:
    """Valida y encola la puntuación de un lote (Fase II).

    Args:
        model_id: Modelo.
        body: Observaciones con fecha.
        principal: Quien llama (operación: analyst o admin); da el tenant.
        c: Contenedor.

    Returns:
        El ``id`` de la puntuación, ``queued``.
    """
    score_id = c.use_cases.monitor.execute(
        principal.tenant_id,
        CHART_ID,
        model_id,
        [o.values for o in body.observations],
        [o.observed_at for o in body.observations],
        body.batch_label,
        body.variables,
    )
    return AcceptedJob(id=score_id)


@router.get("/{model_id}/scores/{score_id}", response_model=ScoreResponse, tags=["t2mrcd-scores"])
def get_score(model_id: str, score_id: str, principal: Reader, c: ContainerDep) -> ScoreResponse:
    """Estado de una puntuación.

    Args:
        model_id: Modelo.
        score_id: Puntuación.
        principal: Quien llama (lectura: analyst, approver o admin); da el tenant.
        c: Contenedor.

    Returns:
        La puntuación.
    """
    return ScoreResponse.of(
        c.use_cases.get_monitoring.execute(principal.tenant_id, CHART_ID, model_id, score_id)
    )


@router.get(
    "/{model_id}/observations", response_model=list[ObservationOut], tags=["t2mrcd-observations"]
)
def list_observations(
    model_id: str,
    principal: Reader,
    c: ContainerDep,
    observed_from: Annotated[datetime | None, Query(alias="from")] = None,
    observed_to: Annotated[datetime | None, Query(alias="to")] = None,
    signals_only: bool = False,
) -> list[ObservationOut]:
    """Observaciones registradas en un rango (inclusivo) con su anotación vigente.

    Args:
        model_id: Modelo.
        principal: Quien llama (lectura: analyst, approver o admin); da el tenant.
        c: Contenedor.
        observed_from: Inicio (con zona horaria).
        observed_to: Fin (con zona horaria).
        signals_only: Solo señales.

    Returns:
        Las observaciones.
    """
    rows = c.use_cases.list_observations.execute(
        principal.tenant_id,
        CHART_ID,
        model_id,
        observed_from=observed_from,
        observed_to=observed_to,
        signals_only=signals_only,
    )
    return [ObservationOut.of(r.observation, r.annotation) for r in rows]


@router.post(
    "/{model_id}/observations/{observation_id}/annotations",
    status_code=status.HTTP_201_CREATED,
    response_model=AnnotationOut,
    tags=["t2mrcd-observations"],
)
def annotate(
    model_id: str,
    observation_id: str,
    body: AnnotationRequest,
    principal: Operator,
    c: ContainerDep,
) -> AnnotationOut:
    """Añade una anotación a una señal (append-only; vale la más reciente).

    Args:
        model_id: Modelo.
        observation_id: Observación con señal.
        body: Anotación.
        principal: Quien llama (operación: analyst o admin); da el tenant y el
            actor (``sub``).
        c: Contenedor.

    Returns:
        La anotación.
    """
    annotation = c.use_cases.annotate.execute(
        principal.tenant_id,
        CHART_ID,
        model_id,
        observation_id,
        assignable_cause=body.assignable_cause,
        cause=body.cause,
        action=body.action,
        actor=principal.subject,
    )
    return AnnotationOut.of(annotation)


@router.post(
    "/{model_id}/structural-events",
    status_code=status.HTTP_201_CREATED,
    response_model=StructuralEventOut,
    tags=["t2mrcd-observations"],
)
def register_event(
    model_id: str, body: StructuralEventRequest, principal: Operator, c: ContainerDep
) -> StructuralEventOut:
    """Registra un evento estructural («requiere nueva base»).

    Args:
        model_id: Modelo.
        body: Evento.
        principal: Quien llama (operación: analyst o admin); da el tenant y el
            actor (``sub``).
        c: Contenedor.

    Returns:
        El evento.
    """
    event = c.use_cases.register_event.execute(
        principal.tenant_id,
        CHART_ID,
        model_id,
        occurred_at=body.occurred_at,
        description=body.description,
        actor=principal.subject,
    )
    return StructuralEventOut.of(event)


@router.get(
    "/{model_id}/structural-events",
    response_model=list[StructuralEventOut],
    tags=["t2mrcd-observations"],
)
def list_events(model_id: str, principal: Reader, c: ContainerDep) -> list[StructuralEventOut]:
    """Eventos estructurales del modelo.

    Args:
        model_id: Modelo.
        principal: Quien llama (lectura: analyst, approver o admin); da el tenant.
        c: Contenedor.

    Returns:
        Los eventos.
    """
    events = c.use_cases.list_events.execute(principal.tenant_id, CHART_ID, model_id)
    return [StructuralEventOut.of(e) for e in events]


@router.get("/{model_id}/versions", response_model=list[VersionSummary], tags=["t2mrcd-versions"])
def list_versions(model_id: str, principal: Reader, c: ContainerDep) -> list[VersionSummary]:
    """Versiones del modelo (resumen, sin modelo ni base).

    Args:
        model_id: Modelo.
        principal: Quien llama (lectura: analyst, approver o admin); da el tenant.
        c: Contenedor.

    Returns:
        Las versiones.
    """
    versions = c.use_cases.list_versions.execute(principal.tenant_id, CHART_ID, model_id)
    return [VersionSummary.of(v) for v in versions]


@router.get("/{model_id}/versions/{number}", response_model=VersionDetail, tags=["t2mrcd-versions"])
def get_version(
    model_id: str,
    number: int,
    principal: Reader,
    c: ContainerDep,
    include: Annotated[list[VersionInclude] | None, Query()] = None,
) -> VersionDetail:
    """Detalle de una versión (M3: base y matrices con ``include``).

    Args:
        model_id: Modelo.
        number: Versión.
        principal: Quien llama (lectura: analyst, approver o admin); da el tenant.
        c: Contenedor.
        include: Partes grandes opcionales.

    Returns:
        La versión.
    """
    version = c.use_cases.get_version.execute(principal.tenant_id, CHART_ID, model_id, number)
    return VersionDetail.detail(version, include or ())


@router.post(
    "/{model_id}/versions/{number}/approve",
    response_model=VersionSummary,
    tags=["t2mrcd-versions"],
)
def approve(
    model_id: str,
    number: int,
    principal: Decider,
    c: ContainerDep,
    body: ApproveRequest | None = None,
) -> VersionSummary:
    """Aprueba una propuesta (``effective_from`` no retroactivo).

    Args:
        model_id: Modelo.
        number: Versión propuesta.
        principal: Quien llama (decisión: approver o admin); da el tenant y el
            actor (``sub``).
        c: Contenedor.
        body: Datos de la aprobación (opcional).

    Returns:
        La versión aprobada.
    """
    data = body if body is not None else ApproveRequest()
    version = c.use_cases.approve.execute(
        principal.tenant_id,
        CHART_ID,
        model_id,
        number,
        effective_from=data.effective_from,
        note=data.note,
        actor=principal.subject,
    )
    return VersionSummary.of(version)


@router.post(
    "/{model_id}/versions/{number}/reject",
    response_model=VersionSummary,
    tags=["t2mrcd-versions"],
)
def reject(
    model_id: str,
    number: int,
    principal: Decider,
    c: ContainerDep,
    body: RejectRequest | None = None,
) -> VersionSummary:
    """Rechaza una propuesta.

    Args:
        model_id: Modelo.
        number: Versión propuesta.
        principal: Quien llama (decisión: approver o admin); da el tenant y el
            actor (``sub``).
        c: Contenedor.
        body: Datos del rechazo (opcional).

    Returns:
        La versión rechazada.
    """
    data = body if body is not None else RejectRequest()
    version = c.use_cases.reject.execute(
        principal.tenant_id, CHART_ID, model_id, number, note=data.note, actor=principal.subject
    )
    return VersionSummary.of(version)


@router.post(
    "/{model_id}/recalibrations",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedJob | StepwiseRecalibrationOut,
    responses={status.HTTP_201_CREATED: {"model": StepwiseRecalibrationOut}},
    tags=["t2mrcd-recalibrations"],
)
def request_recalibration(
    model_id: str,
    body: RecalibrationRequest,
    principal: Operator,
    c: ContainerDep,
    response: Response,
) -> AcceptedJob | StepwiseRecalibrationOut:
    """Valida y abre una recalibración: tubería (``202``) o paso a paso (``201``).

    Args:
        model_id: Modelo.
        body: Rango, parámetros, reemplazo forzado y modo.
        principal: Quien llama (operación: analyst o admin); da el tenant y el
            actor (``sub``).
        c: Contenedor.
        response: Respuesta (fija ``201`` en modo ``stepwise``).

    Returns:
        ``202 {id}`` (tubería, ``queued``) o ``201 {recalibration_id, candidates_dataset_id}``.
    """
    mode = RecalibrationMode(body.mode)
    recalibration_id = c.use_cases.request_recalibration.execute(
        principal.tenant_id,
        CHART_ID,
        model_id,
        range_from=body.range_from,
        range_to=body.range_to,
        params=body.params.to_domain(),
        force_replace=body.force_replace,
        actor=principal.subject,
        mode=mode,
    )
    if mode is RecalibrationMode.PIPELINE:
        return AcceptedJob(id=recalibration_id)
    record = c.use_cases.get_recalibration.execute(
        principal.tenant_id, CHART_ID, model_id, recalibration_id
    )
    response.status_code = status.HTTP_201_CREATED
    return StepwiseRecalibrationOut(
        recalibration_id=recalibration_id,
        candidates_dataset_id=record.candidates_dataset_id or "",
    )


@router.get(
    "/{model_id}/recalibrations/{recalibration_id}",
    response_model=RecalibrationResponse,
    tags=["t2mrcd-recalibrations"],
)
def get_recalibration(
    model_id: str,
    recalibration_id: str,
    principal: Reader,
    c: ContainerDep,
    include: Annotated[list[RecalibrationInclude] | None, Query()] = None,
) -> RecalibrationResponse:
    """Estado de una recalibración y, si terminó bien, su informe y la versión propuesta.

    Args:
        model_id: Modelo.
        recalibration_id: Recalibración.
        principal: Quien llama (lectura: analyst, approver o admin); da el tenant.
        c: Contenedor.
        include: Partes grandes opcionales.

    Returns:
        La recalibración.
    """
    record = c.use_cases.get_recalibration.execute(
        principal.tenant_id, CHART_ID, model_id, recalibration_id
    )
    return RecalibrationResponse.of(record, include or ())


@router.post(
    "/{model_id}/recalibrations/{recalibration_id}/extension",
    status_code=status.HTTP_201_CREATED,
    response_model=ExtensionOut,
    tags=["t2mrcd-recalibrations"],
)
def request_extension(
    model_id: str,
    recalibration_id: str,
    body: ExtensionRequest,
    principal: Operator,
    c: ContainerDep,
) -> ExtensionOut:
    """Construye (síncrono) el dataset de extensión: base vigente + filas nuevas conservadas.

    Solo en una recalibración que amplía la base (por defecto); con reemplazo
    (``force_replace`` o evento estructural) responde ``422 INVALID_INPUT``. Repetirla con el mismo
    ``dataset_id`` devuelve la misma extensión.

    Args:
        model_id: Modelo.
        recalibration_id: Recalibración en curso.
        body: Filas nuevas conservadas (candidatas o salida de su exclusión humana).
        principal: Quien llama (operación: analyst o admin); da el tenant.
        c: Contenedor.

    Returns:
        El dataset de extensión y sus filas.
    """
    extension_id = c.use_cases.request_extension.execute(
        principal.tenant_id, CHART_ID, model_id, recalibration_id, dataset_id=body.dataset_id
    )
    total = c.use_cases.get_dataset.execute(principal.tenant_id, extension_id).dataset.data.shape[0]
    kept = c.use_cases.get_dataset.execute(principal.tenant_id, body.dataset_id).dataset.data.shape[
        0
    ]
    return ExtensionOut(dataset_id=extension_id, n_base=int(total - kept), n_kept_new=int(kept))


@router.post(
    "/{model_id}/versions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedJob,
    tags=["t2mrcd-versions"],
)
def request_version(
    model_id: str, body: VersionProposalRequest, principal: Operator, c: ContainerDep
) -> AcceptedJob:
    """Valida y encola la propuesta de versión de una recalibración (carril ``light``).

    El trabajo es la recalibración: se consulta con ``GET …/recalibrations/{id}`` (al terminar,
    ``proposed_version``).

    Args:
        model_id: Modelo.
        body: Recalibración, ajuste y límites.
        principal: Quien llama (operación: analyst o admin); da el tenant.
        c: Contenedor.

    Returns:
        El ``id`` de la recalibración, ``queued``.
    """
    recalibration_id = c.use_cases.request_version_proposal.execute(
        principal.tenant_id,
        CHART_ID,
        model_id,
        body.recalibration_id,
        fit_id=body.fit_id,
        limits_id=body.limits_id,
    )
    return AcceptedJob(id=recalibration_id)


@router.post(
    "/{model_id}/recalibrations/{recalibration_id}/cancel",
    response_model=RecalibrationResponse,
    tags=["t2mrcd-recalibrations"],
)
def cancel_recalibration(
    model_id: str, recalibration_id: str, principal: Operator, c: ContainerDep
) -> RecalibrationResponse:
    """Cancela una sesión paso a paso ``running`` sin propuesta pedida (libera D6).

    Args:
        model_id: Modelo.
        recalibration_id: Recalibración.
        principal: Quien llama (operación: analyst o admin); da el tenant.
        c: Contenedor.

    Returns:
        La recalibración ``cancelled``.
    """
    record = c.use_cases.cancel_recalibration.execute(
        principal.tenant_id, CHART_ID, model_id, recalibration_id
    )
    return RecalibrationResponse.of(record, ())
