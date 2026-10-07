"""Endpoints de vida (``/health``) y disponibilidad (``/ready``)."""

from fastapi import APIRouter

from voracious.api.schemas import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Indica que el proceso está vivo.

    Returns:
        Estado ``ok``.
    """
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
def ready() -> ReadyResponse:
    """Indica que el proceso puede recibir tráfico.

    Hoy no hay dependencias externas, por lo que ``checks`` va vacío.

    Returns:
        Estado ``ready`` con el resultado de cada comprobación.
    """
    return ReadyResponse(status="ready", checks={})
