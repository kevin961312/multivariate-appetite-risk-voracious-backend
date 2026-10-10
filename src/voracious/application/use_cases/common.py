"""Piezas compartidas por los casos de uso: búsquedas con su error y ``INTERNAL_ERROR``."""

from collections.abc import Sequence

from voracious.application.errors import (
    ModelNotFoundError,
    ModelNotReadyError,
    VariablesMismatchError,
    VersionNotFoundError,
)
from voracious.application.lifecycle import active_version
from voracious.application.ports import ModelRepository, ModelVersionRepository
from voracious.application.records import JobStatus, ModelRecord, ModelVersion

__all__ = [
    "INTERNAL_ERROR",
    "JOB_INTERRUPTED",
    "check_variables",
    "get_model",
    "get_version",
    "ready_model",
    "require_active_version",
]

INTERNAL_ERROR = "INTERNAL_ERROR"
"""Código de un fallo inesperado (no ``DomainError``); el detalle va al log, no al registro."""

JOB_INTERRUPTED = "JOB_INTERRUPTED"
"""Código de un trabajo que estaba ``queued`` o ``running`` cuando el proceso se reinició (la cola
vive en el proceso y se pierde): ``RecoverInterruptedJobs`` lo cierra ``failed`` al arrancar."""


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


def check_variables(
    model: ModelRecord, p: int, variables: Sequence[str] | None, *, source: str
) -> None:
    """Comprueba que las columnas de una entrada sean las variables del modelo (Paso 4.2).

    Si el modelo tiene nombres (los del dataset raíz), la entrada debe tener ``p`` igual a su
    número y, si trae nombres, los mismos en el mismo orden. Si la entrada trae nombres, deben ser
    uno por columna. Sin nombres en ningún lado no hay nada que comprobar (el número lo valida la
    carta).

    Args:
        model: Modelo.
        p: Columnas de la entrada.
        variables: Nombres que trae la entrada, o ``None``.
        source: Entrada, para ``details`` (``scores``, ``recalibration``).

    Raises:
        VariablesMismatchError: Si el número o los nombres no coinciden.
    """
    names = None if variables is None else tuple(str(v).strip() for v in variables)
    if names is not None and len(names) != p:
        raise VariablesMismatchError(
            "'variables' debe tener un nombre por columna",
            details={"input": source, "columns": p, "names": len(names)},
        )
    expected = model.variables
    if expected is None:
        return
    if len(expected) != p:
        raise VariablesMismatchError(
            f"el modelo tiene {len(expected)} variables y la entrada {p}",
            details={"input": source, "expected": list(expected), "columns": p},
        )
    if names is not None and names != expected:
        raise VariablesMismatchError(
            "las variables no son las del modelo (mismos nombres y en el mismo orden)",
            details={"input": source, "expected": list(expected), "received": list(names)},
        )
