"""Endpoints de vida (``/health``) y disponibilidad (``/ready``)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from voracious.api.deps import get_container
from voracious.api.schemas import HealthResponse, ReadyResponse
from voracious.container import Container

router = APIRouter(tags=["health"])

ContainerDep = Annotated[Container, Depends(get_container)]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Indica que el proceso está vivo (sin consultar ninguna dependencia).

    Returns:
        Estado ``ok``.
    """
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
def ready(c: ContainerDep) -> ReadyResponse | JSONResponse:
    """Indica si el proceso puede recibir tráfico: comprueba cada dependencia externa.

    Con ``VORACIOUS_REPOSITORY=postgres``, ``database`` (``SELECT 1`` con tiempo máximo corto);
    con ``VORACIOUS_STORAGE=local``, ``storage`` (directorio escribible).

    Args:
        c: Contenedor.

    Returns:
        ``200`` con ``ready``, o ``503`` con ``not_ready`` y qué comprobación falló.
    """
    checks = {name: "ok" if ok else "fail" for name, ok in c.check_readiness().items()}
    if all(v == "ok" for v in checks.values()):
        return ReadyResponse.model_validate({"status": "ready", "checks": checks})
    body = ReadyResponse.model_validate({"status": "not_ready", "checks": checks})
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body.model_dump())
