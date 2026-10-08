"""Tenant de la petición: cabecera ``X-Tenant-ID`` (sin autenticación real; JWT/OIDC después)."""

import re
from typing import Annotated

from fastapi import Header

from voracious.api.errors import ApiError

__all__ = ["TENANT_HEADER", "TENANT_PATTERN", "TENANT_REQUIRED", "tenant_id"]

TENANT_HEADER = "X-Tenant-ID"
"""Cabecera con el tenant."""

TENANT_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
"""Forma válida de un tenant (se exige coincidencia completa)."""

TENANT_REQUIRED = "TENANT_REQUIRED"
"""Código de error: falta la cabecera o no tiene la forma válida."""


def tenant_id(
    x_tenant_id: Annotated[str | None, Header(alias=TENANT_HEADER)] = None,
) -> str:
    """Dependencia de FastAPI que devuelve el tenant de la petición.

    Args:
        x_tenant_id: Valor de la cabecera.

    Returns:
        El tenant.

    Raises:
        ApiError: ``TENANT_REQUIRED`` si falta o no cumple ``^[A-Za-z0-9_-]{1,64}$``.
    """
    if x_tenant_id is None:
        raise ApiError(
            TENANT_REQUIRED,
            f"falta la cabecera {TENANT_HEADER}",
            {"header": TENANT_HEADER, "reason": "missing"},
        )
    if TENANT_PATTERN.fullmatch(x_tenant_id) is None:
        raise ApiError(
            TENANT_REQUIRED,
            f"la cabecera {TENANT_HEADER} no tiene un tenant válido",
            {"header": TENANT_HEADER, "reason": "invalid"},
        )
    return x_tenant_id
