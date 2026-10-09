"""Pasos de la Fase I de T²MRCD bajo ``/v1/charts/t2mrcd`` (vuelta 3.3, ADR 0005 enmendado).

APIs independientes y encadenables por id, cada una con su trabajo asíncrono y su carril:
(opcional) ``/exclusions`` (exclusión humana) → ``/fits`` (MRCD bajo la carta, ``alpha`` 0.75
por defecto) → ``/limits`` → ``/models`` (solo referencias). Sin depuración automática iterativa
(decisión del dueño, 2026-10-09). ``/pipelines/phase1`` encadena los mismos pasos (orquestación
pura). Cada ``POST`` responde ``202`` con el id y se consulta con ``GET``. Solo traducen HTTP ↔
casos de uso.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from voracious.api.deps import get_container
from voracious.api.schemas.common import AcceptedJob, ErrorResponse
from voracious.api.schemas.t2mrcd_phase1 import (
    ExclusionInclude,
    ExclusionRequest,
    ExclusionResponse,
    FitInclude,
    FitRequest,
    FitResponse,
    LimitsInclude,
    LimitsRequest,
    LimitsResponse,
    ModelFromRefsRequest,
    Phase1PipelineRequest,
    PipelineResponse,
)
from voracious.api.tenant import tenant_id
from voracious.container import Container
from voracious.domain.charts.t2mrcd import CHART_ID

__all__ = ["router"]

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorResponse} for code in (400, 404, 409, 422)
}

router = APIRouter(prefix=f"/v1/charts/{CHART_ID}", responses=_ERRORS)

ContainerDep = Annotated[Container, Depends(get_container)]
TenantDep = Annotated[str, Depends(tenant_id)]


@router.post(
    "/fits",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedJob,
    tags=["t2mrcd-phase1"],
)
def request_fit(body: FitRequest, tenant: TenantDep, c: ContainerDep) -> AcceptedJob:
    """Valida el dataset y encola su ajuste MRCD (carril ``estimation``).

    Args:
        body: Dataset y parámetros de MRCD.
        tenant: Tenant.
        c: Contenedor.

    Returns:
        El ``id`` del ajuste, ``queued``.
    """
    mrcd = None if body.mrcd is None else body.mrcd.to_domain()
    return AcceptedJob(id=c.use_cases.request_fit.execute(tenant, CHART_ID, body.dataset_id, mrcd))


@router.get("/fits/{fit_id}", response_model=FitResponse, tags=["t2mrcd-phase1"])
def get_fit(
    fit_id: str,
    tenant: TenantDep,
    c: ContainerDep,
    include: Annotated[list[FitInclude] | None, Query()] = None,
) -> FitResponse:
    """Estado del ajuste (M3: ``center`` y ``cov`` con ``include=covariance``).

    Args:
        fit_id: Ajuste.
        tenant: Tenant.
        c: Contenedor.
        include: Partes grandes opcionales.

    Returns:
        El ajuste.
    """
    record = c.use_cases.get_fit.execute(tenant, CHART_ID, fit_id)
    return FitResponse.of(record, include or ())


@router.post(
    "/limits",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedJob,
    tags=["t2mrcd-phase1"],
)
def request_limits(body: LimitsRequest, tenant: TenantDep, c: ContainerDep) -> AcceptedJob:
    """Valida el ajuste y encola la calibración de límites (carril ``calibration``).

    Con ``recalibration_id`` (filas nuevas o base ampliada de una recalibración) los parámetros
    se heredan de la versión base y la operación es ``new_rows`` o ``extension``; sin él,
    ``params`` es obligatorio. Las decisiones pendientes responden ``422`` aquí, antes de encolar.

    Args:
        body: Ajuste y parámetros de la carta (o la recalibración).
        tenant: Tenant.
        c: Contenedor.

    Returns:
        El ``id`` de los límites, ``queued``.
    """
    params = None if body.params is None else body.params.to_domain()
    return AcceptedJob(
        id=c.use_cases.request_limits.execute(
            tenant, CHART_ID, body.fit_id, params, recalibration_id=body.recalibration_id
        )
    )


@router.get("/limits/{limits_id}", response_model=LimitsResponse, tags=["t2mrcd-phase1"])
def get_limits(
    limits_id: str,
    tenant: TenantDep,
    c: ContainerDep,
    include: Annotated[list[LimitsInclude] | None, Query()] = None,
) -> LimitsResponse:
    """Estado de la calibración (M3: ``clean_rows`` con ``include``).

    Args:
        limits_id: Límites.
        tenant: Tenant.
        c: Contenedor.
        include: Partes grandes opcionales.

    Returns:
        Los límites.
    """
    record = c.use_cases.get_limits.execute(tenant, CHART_ID, limits_id)
    return LimitsResponse.of(record, include or ())


@router.post(
    "/exclusions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedJob,
    tags=["t2mrcd-phase1"],
)
def request_exclusion(body: ExclusionRequest, tenant: TenantDep, c: ContainerDep) -> AcceptedJob:
    """Valida y encola una exclusión humana (sin ajuste; carril ``light``).

    ``{dataset_id, assignable_cause}`` sobre el dataset subido (Fase I). Sobre las candidatas de
    una recalibración las filas salen de las anotaciones: se pide con ``{dataset_id}`` solo.

    Args:
        body: Dataset y filas con causa asignable.
        tenant: Tenant.
        c: Contenedor.

    Returns:
        El ``id`` de la exclusión, ``queued``.
    """
    return AcceptedJob(
        id=c.use_cases.request_exclusion.execute(
            tenant,
            CHART_ID,
            body.dataset_id,
            [a.to_record() for a in body.assignable_cause],
        )
    )


@router.get("/exclusions/{exclusion_id}", response_model=ExclusionResponse, tags=["t2mrcd-phase1"])
def get_exclusion(
    exclusion_id: str,
    tenant: TenantDep,
    c: ContainerDep,
    include: Annotated[list[ExclusionInclude] | None, Query()] = None,
) -> ExclusionResponse:
    """Estado de la exclusión (M3: destino por fila con ``include=row_disposition``).

    Args:
        exclusion_id: Exclusión.
        tenant: Tenant.
        c: Contenedor.
        include: Partes grandes opcionales.

    Returns:
        La exclusión.
    """
    record = c.use_cases.get_exclusion.execute(tenant, CHART_ID, exclusion_id)
    return ExclusionResponse.of(record, include or ())


@router.post(
    "/models",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedJob,
    tags=["t2mrcd-models"],
)
def request_model(body: ModelFromRefsRequest, tenant: TenantDep, c: ContainerDep) -> AcceptedJob:
    """Encola el ensamblado del modelo a partir de referencias (sin datos ni cómputo nuevo).

    Args:
        body: ``{fit_id, limits_id}`` y política.
        tenant: Tenant.
        c: Contenedor.

    Returns:
        El ``id`` del modelo, ``queued``.
    """
    policy = None if body.lifecycle_policy is None else body.lifecycle_policy.to_domain()
    return AcceptedJob(
        id=c.use_cases.request_model.execute(
            tenant,
            CHART_ID,
            fit_id=body.fit_id,
            limits_id=body.limits_id,
            lifecycle_policy=policy,
        )
    )


@router.post(
    "/pipelines/phase1",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedJob,
    tags=["t2mrcd-pipelines"],
)
def request_pipeline(
    body: Phase1PipelineRequest, tenant: TenantDep, c: ContainerDep
) -> AcceptedJob:
    """Encola la Fase I completa por pasos (orquestación de ``/fits`` … ``/models``).

    Args:
        body: Dataset, parámetros, exclusión humana y política.
        tenant: Tenant.
        c: Contenedor.

    Returns:
        El ``id`` de la tubería, ``queued``.
    """
    policy = None if body.lifecycle_policy is None else body.lifecycle_policy.to_domain()
    return AcceptedJob(
        id=c.use_cases.request_pipeline.execute(
            tenant,
            CHART_ID,
            body.dataset_id,
            body.params.to_domain(),
            [a.to_record() for a in body.assignable_cause],
            policy,
        )
    )


@router.get(
    "/pipelines/{pipeline_id}",
    response_model=PipelineResponse,
    tags=["t2mrcd-pipelines"],
)
@router.get(
    "/pipelines/phase1/{pipeline_id}",
    response_model=PipelineResponse,
    tags=["t2mrcd-pipelines"],
)
def get_pipeline(pipeline_id: str, tenant: TenantDep, c: ContainerDep) -> PipelineResponse:
    """Estado de una tubería (Fase I o recalibración), sus pasos y el modelo resultante.

    ``/pipelines/{id}`` sirve para ambos tipos (``kind``); ``/pipelines/phase1/{id}`` se
    mantiene como alias.

    Args:
        pipeline_id: Tubería.
        tenant: Tenant.
        c: Contenedor.

    Returns:
        La tubería.
    """
    return PipelineResponse.of(c.use_cases.get_pipeline.execute(tenant, CHART_ID, pipeline_id))
