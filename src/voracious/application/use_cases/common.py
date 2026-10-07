"""Piezas compartidas por los casos de uso: búsquedas con su error y ``INTERNAL_ERROR``."""

from voracious.application.errors import (
    ModelNotFoundError,
    ModelNotReadyError,
    VersionNotFoundError,
)
from voracious.application.lifecycle import active_version
from voracious.application.ports import ModelRepository, ModelVersionRepository
from voracious.application.records import JobStatus, ModelRecord, ModelVersion

__all__ = ["INTERNAL_ERROR", "get_model", "get_version", "ready_model", "require_active_version"]

INTERNAL_ERROR = "INTERNAL_ERROR"
"""Código de un fallo inesperado (no ``DomainError``); el detalle va al log, no al registro."""


def get_model(models: ModelRepository, tenant_id: str, chart_id: str, model_id: str) -> ModelRecord:
    """Busca un modelo o lanza ``ModelNotFoundError``.

    Args:
        models: Repositorio.
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo.

    Returns:
        El registro.

    Raises:
        ModelNotFoundError: Si no existe para esa clave.
    """
    record = models.get(tenant_id, chart_id, model_id)
    if record is None:
        raise ModelNotFoundError(
            f"el modelo '{model_id}' no existe", details={"model_id": model_id}
        )
    return record


def ready_model(
    models: ModelRepository, tenant_id: str, chart_id: str, model_id: str
) -> ModelRecord:
    """Devuelve un modelo ``succeeded`` del tenant y la carta.

    Args:
        models: Repositorio de modelos.
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo.

    Returns:
        El registro del modelo.

    Raises:
        ModelNotFoundError: Si no existe para ese tenant y esa carta.
        ModelNotReadyError: Si existe pero no está en ``succeeded``.
    """
    record = get_model(models, tenant_id, chart_id, model_id)
    if record.status is not JobStatus.SUCCEEDED:
        raise ModelNotReadyError(
            f"el modelo '{model_id}' no está listo",
            details={"model_id": model_id, "status": str(record.status)},
        )
    return record


def get_version(
    versions: ModelVersionRepository, tenant_id: str, chart_id: str, model_id: str, number: int
) -> ModelVersion:
    """Busca una versión o lanza ``VersionNotFoundError``.

    Args:
        versions: Repositorio de versiones.
        tenant_id: Tenant.
        chart_id: Carta.
        model_id: Modelo.
        number: Número de versión.

    Returns:
        La versión.

    Raises:
        VersionNotFoundError: Si no existe para esa clave.
    """
    version = versions.get(tenant_id, chart_id, model_id, number)
    if version is None:
        raise VersionNotFoundError(
            f"la versión {number} del modelo '{model_id}' no existe",
            details={"model_id": model_id, "version": number},
        )
    return version


def require_active_version(versions: list[ModelVersion], model_id: str) -> ModelVersion:
    """Devuelve la versión vigente o lanza ``ModelNotReadyError`` si el modelo no tiene ninguna.

    Args:
        versions: Versiones del modelo.
        model_id: Modelo, para el mensaje.

    Returns:
        La versión vigente.

    Raises:
        ModelNotReadyError: Si no hay versión vigente.
    """
    active = active_version(versions)
    if active is None:
        raise ModelNotReadyError(
            f"el modelo '{model_id}' no tiene versión vigente",
            details={"model_id": model_id, "reason": "no_active_version"},
        )
    return active
