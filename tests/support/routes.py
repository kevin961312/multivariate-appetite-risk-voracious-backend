"""Instantánea de las rutas de la API y matriz de roles esperada (caja negra, D7)."""

from voracious.application.auth import Role

READ = frozenset({Role.ANALYST, Role.APPROVER, Role.ADMIN})
"""Lectura: todos los ``GET`` de negocio."""
OPERATE = frozenset({Role.ANALYST, Role.ADMIN})
"""Operación: subir datos, pasos de cómputo, puntuar, anotar, eventos, recalibrar y proponer."""
DECIDE = frozenset({Role.APPROVER, Role.ADMIN})
"""Decisión: aprobar y rechazar versiones."""
PUBLIC: frozenset[Role] = frozenset()
"""Rutas sin token."""

M = "/v1/charts/t2mrcd/models/{model_id}"

ROUTE_ROLES: dict[tuple[str, str], frozenset[Role]] = {
    ("GET", "/health"): PUBLIC,
    ("GET", "/ready"): PUBLIC,
    ("POST", "/v1/datasets"): OPERATE,
    ("GET", "/v1/datasets/{dataset_id}"): READ,
    ("POST", "/v1/charts/t2mrcd/fits"): OPERATE,
    ("GET", "/v1/charts/t2mrcd/fits/{fit_id}"): READ,
    ("POST", "/v1/charts/t2mrcd/limits"): OPERATE,
    ("GET", "/v1/charts/t2mrcd/limits/{limits_id}"): READ,
    ("POST", "/v1/charts/t2mrcd/exclusions"): OPERATE,
    ("GET", "/v1/charts/t2mrcd/exclusions/{exclusion_id}"): READ,
    ("POST", "/v1/charts/t2mrcd/pipelines/phase1"): OPERATE,
    ("GET", "/v1/charts/t2mrcd/pipelines/phase1/{pipeline_id}"): READ,
    ("GET", "/v1/charts/t2mrcd/pipelines/{pipeline_id}"): READ,
    ("POST", "/v1/charts/t2mrcd/models"): OPERATE,
    ("GET", M): READ,
    ("GET", f"{M}/status"): READ,
    ("POST", f"{M}/scores"): OPERATE,
    ("GET", f"{M}/scores/{{score_id}}"): READ,
    ("GET", f"{M}/observations"): READ,
    ("POST", f"{M}/observations/{{observation_id}}/annotations"): OPERATE,
    ("POST", f"{M}/structural-events"): OPERATE,
    ("GET", f"{M}/structural-events"): READ,
    ("GET", f"{M}/versions"): READ,
    ("GET", f"{M}/versions/{{number}}"): READ,
    ("POST", f"{M}/versions/{{number}}/approve"): DECIDE,
    ("POST", f"{M}/versions/{{number}}/reject"): DECIDE,
    ("POST", f"{M}/recalibrations"): OPERATE,
    ("GET", f"{M}/recalibrations/{{recalibration_id}}"): READ,
    ("POST", f"{M}/recalibrations/{{recalibration_id}}/extension"): OPERATE,
    ("POST", f"{M}/versions"): OPERATE,
    ("POST", f"{M}/recalibrations/{{recalibration_id}}/cancel"): OPERATE,
}
"""Roles que permiten cada ruta (vacío = pública)."""

EXPECTED_ROUTES = sorted(ROUTE_ROLES)
"""Instantánea de las rutas de la API (método, plantilla)."""
