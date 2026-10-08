"""Rutas de los datasets (``/v1/datasets``): subida JSON o CSV y consulta con linaje.

Mejora M2: ``POST /v1/datasets`` admite ``application/json`` (``{"data": [[...]]}``),
``text/csv`` (cuerpo CSV) y ``multipart/form-data`` (un fichero CSV en la parte ``file``). El
cuerpo se limita a ``VORACIOUS_MAX_UPLOAD_MB`` (``413 PAYLOAD_TOO_LARGE``). Un dataset no
pertenece a ninguna carta: se referencia por su id desde los pasos de cada carta.
"""

from email.message import Message
from email.parser import BytesParser
from email.policy import HTTP
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from voracious.api.deps import get_container
from voracious.api.errors import ApiError
from voracious.api.schemas.common import ErrorResponse
from voracious.api.schemas.datasets import (
    DatasetCreated,
    DatasetInclude,
    DatasetResponse,
    DatasetUploadIn,
)
from voracious.api.tenant import tenant_id
from voracious.container import Container

__all__ = ["MULTIPART_FIELD", "router"]

MULTIPART_FIELD = "file"
"""Nombre de la parte con el CSV en ``multipart/form-data``."""

_MIB = 1024 * 1024

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorResponse} for code in (400, 404, 413, 415, 422)
}

_UPLOAD_BODY: dict[str, object] = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": DatasetUploadIn.model_json_schema()},
            "text/csv": {"schema": {"type": "string"}},
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {MULTIPART_FIELD: {"type": "string", "format": "binary"}},
                    "required": [MULTIPART_FIELD],
                }
            },
        },
    }
}
"""Cuerpo de la subida en OpenAPI (se lee a mano para admitir tres tipos de contenido)."""

router = APIRouter(prefix="/v1/datasets", responses=_ERRORS, tags=["datasets"])

ContainerDep = Annotated[Container, Depends(get_container)]
TenantDep = Annotated[str, Depends(tenant_id)]


async def _body(request: Request, limit: int) -> bytes:
    """Lee el cuerpo sin pasar de ``limit`` bytes.

    Args:
        request: Petición.
        limit: Máximo de bytes.

    Returns:
        El cuerpo.

    Raises:
        ApiError: ``PAYLOAD_TOO_LARGE`` si lo supera.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise ApiError(
            "PAYLOAD_TOO_LARGE",
            "el cuerpo supera el máximo de subida",
            {"max_bytes": limit, "declared_bytes": int(declared)},
        )
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ApiError(
                "PAYLOAD_TOO_LARGE", "el cuerpo supera el máximo de subida", {"max_bytes": limit}
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _text(payload: bytes) -> str:
    """Decodifica un CSV en UTF-8 (con o sin BOM).

    Args:
        payload: Bytes.

    Returns:
        El texto.

    Raises:
        ApiError: ``INVALID_INPUT`` si no es UTF-8.
    """
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(
            "INVALID_INPUT", "el CSV debe estar en UTF-8", {"input": "csv", "reason": "encoding"}
        ) from exc


def _multipart_csv(content_type: str, payload: bytes) -> str:
    """Extrae el CSV de la parte ``file`` de un ``multipart/form-data``.

    Args:
        content_type: Cabecera ``Content-Type`` (con ``boundary``).
        payload: Cuerpo.

    Returns:
        El texto del CSV.

    Raises:
        ApiError: ``INVALID_INPUT`` si no hay una parte ``file``.
    """
    head = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1")
    message = BytesParser(policy=HTTP).parsebytes(head + payload)
    if message.is_multipart():
        for part in message.iter_parts():
            if (
                isinstance(part, Message)
                and part.get_param("name", header="content-disposition") == MULTIPART_FIELD
            ):
                content = part.get_payload(decode=True)
                if isinstance(content, bytes):
                    return _text(content)
    raise ApiError(
        "INVALID_INPUT",
        f"falta la parte '{MULTIPART_FIELD}' con el CSV",
        {"input": MULTIPART_FIELD, "reason": "missing_part"},
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DatasetCreated,
    openapi_extra=_UPLOAD_BODY,
)
async def upload_dataset(request: Request, tenant: TenantDep, c: ContainerDep) -> DatasetCreated:
    """Sube un dataset ``n x p`` (JSON, CSV o multipart) y devuelve su id y su huella.

    Args:
        request: Petición (el cuerpo se lee según su ``Content-Type``).
        tenant: Tenant.
        c: Contenedor.

    Returns:
        ``{dataset_id, n, p, content_hash}``.

    Raises:
        ApiError: ``UNSUPPORTED_MEDIA_TYPE``, ``PAYLOAD_TOO_LARGE`` o ``INVALID_INPUT``.
        RequestValidationError: Si el JSON no cumple el schema.
    """
    content_type = request.headers.get("content-type", "")
    media = content_type.split(";", 1)[0].strip().lower()
    payload = await _body(request, c.settings.max_upload_mb * _MIB)
    upload = c.use_cases.upload_dataset
    if media == "application/json":
        try:
            body = DatasetUploadIn.model_validate_json(payload)
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc
        return DatasetCreated.of(upload.execute(tenant, body.data))
    if media == "text/csv":
        return DatasetCreated.of(upload.execute_csv(tenant, _text(payload)))
    if media == "multipart/form-data":
        return DatasetCreated.of(upload.execute_csv(tenant, _multipart_csv(content_type, payload)))
    raise ApiError(
        "UNSUPPORTED_MEDIA_TYPE",
        "tipo de contenido no admitido (application/json, text/csv o multipart/form-data)",
        {"content_type": media},
    )


@router.get("/{dataset_id}", response_model=DatasetResponse)
def get_dataset(
    dataset_id: str,
    tenant: TenantDep,
    c: ContainerDep,
    include: Annotated[list[DatasetInclude] | None, Query()] = None,
) -> DatasetResponse:
    """Dataset con su linaje (M3: ``data`` y ``rows`` con ``include``).

    Args:
        dataset_id: Dataset.
        tenant: Tenant.
        c: Contenedor.
        include: Partes grandes opcionales.

    Returns:
        El dataset.
    """
    return DatasetResponse.of(c.use_cases.get_dataset.execute(tenant, dataset_id), include or ())
