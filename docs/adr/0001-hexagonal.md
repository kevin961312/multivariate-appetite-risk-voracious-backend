# ADR 0001 — Arquitectura hexagonal (puertos y adaptadores)

- **Estado:** Aceptado
- **Fecha:** 2026-10-06

## Contexto

Voracious apunta a una arquitectura distribuida (Celery + Redis, TimescaleDB, S3, Kubernetes, multi-tenant),
pero hoy solo se necesita un cascarón que pruebe el cableado completo. Si el dominio o los casos de uso se
acoplan a FastAPI, a una cola o a una base concreta, cada salto de escala obliga a reescribir el núcleo, que es
justamente la parte más cara de validar (fidelidad a `rrcov`).

## Decisión

- Capas `domain` → `application` → (`infrastructure`, `api`), con dependencias solo hacia dentro.
- `application/ports.py` define los puertos como `typing.Protocol`: `JobQueue`, `AnalysisRepository`,
  `DatasetStorage`, `TenantContext`.
- Hoy se implementan adaptadores mínimos (`InlineJobQueue`, `InMemoryAnalysisRepository`,
  `LocalDatasetStorage`, tenant por cabecera). `container.py` los elige por variables `VORACIOUS_*`.
- La dirección de dependencias se verifica con `import-linter` en la compuerta, no por convención.

## Consecuencias

- Añadir Celery, TimescaleDB o S3 = un adaptador nuevo + una variable; dominio y casos de uso no cambian.
- Los casos de uso se prueban con dobles en memoria, sin red ni BD.
- Coste: algo más de indirección (protocolos, contenedor) que un FastAPI monolítico.

## Alternativas descartadas

- **FastAPI monolítico con lógica en los routers:** rápido hoy, pero acopla el estimador a HTTP y obliga a
  reescribir al introducir workers.
- **Construir ya Celery/Postgres:** infraestructura sin uso real todavía; retrasa el cascarón y añade
  superficie de fallo.

## Enmienda 2026-10-20 (seguridad mínima): `TenantContext` nunca existió

Por qué: la lista de puertos de la «Decisión» nombra `TenantContext`, pero ese puerto no llegó a crearse; el tenant
era una dependencia de FastAPI (`api/tenant.py`) que pasaba un `str` a los casos de uso. No se reescribe el texto
original: el puerto real es **`TokenVerifier`** (`application/ports.py`, `verify(token) -> Principal`), cuyo
adaptador es `JwtTokenVerifier` en `infrastructure/auth/` y cuyo tipo `Principal` (sujeto, tenant, roles,
caducidad, `jti`) vive en `application/auth.py`. El tenant de todo caso de uso sale de `Principal.tenant_id`.
Decisiones y alternativas en el [ADR 0012](0012-seguridad-minima-sops-jwt.md).
