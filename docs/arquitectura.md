# Arquitectura

## Por qué hexagonal

El producto vale por el estimador (MRCD) y la carta T²MRCD; eso no debe depender de cómo se recibe una
petición, dónde se guarda un resultado ni quién ejecuta el cálculo. El objetivo es distribuido, pero hoy se
construye lo mínimo. Con puertos y adaptadores, cada pieza distribuida entra como **un adaptador nuevo y una
variable de configuración**, sin tocar `domain/` ni `application/`. Ver [ADR 0001](adr/0001-hexagonal.md).

## Arquitectura objetivo (no se construye todavía)

```
 clientes ──HTTPS──▶ API FastAPI (multi-tenant, JWT/OIDC)
                         │ encola
                         ▼
                   Celery + Redis ──▶ workers MRCD (paralelo por portafolio)
                                          │        └─▶ Dask/Spark para lotes masivos
                                          ▼
                     PostgreSQL/TimescaleDB (series y resultados)
                     S3 (data lake de entradas)
                     Kubernetes con autoescalado
```

## Arquitectura de hoy (cascarón)

```
 HTTP ─▶ api/ (routers, schemas, errores, tenant por X-Tenant-ID)
            │ usa casos de uso vía container.py
            ▼
         application/ (SubmitAnalysis, GetAnalysis, puertos Protocol)
            │                         ▲ implementan los puertos
            ▼                         │
         domain/ (MRCD, MRCDParams,   infrastructure/ (InlineJobQueue,
                  T², errores)          InMemoryAnalysisRepository, LocalDatasetStorage)
```

## Capas

| Capa | Responsabilidad | Depende de |
| --- | --- | --- |
| `domain` | Estimador MRCD, parámetros, resultados, estadística T², errores de dominio. Puro: numpy/scipy. | nada del proyecto |
| `application` | Casos de uso y puertos (`typing.Protocol`). Orquesta, no sabe de HTTP ni de BD. | `domain` |
| `infrastructure` | Adaptadores que implementan los puertos. | `application`, `domain` |
| `api` | FastAPI: app factory, routers, schemas Pydantic, dependencias, mapeo de errores. | `application`, `domain`, `container` |
| `workers` | (vacío) Punto de entrada de Celery en el futuro. | `application`, `domain`, `container` |
| `config` | `pydantic-settings`, prefijo `VORACIOUS_`. | — |
| `container` | Cableado: elige adaptadores según `config`. Único lugar que conoce todo. | todas |

Los contratos se verifican con `import-linter` (configurado en `pyproject.toml` desde el Paso 1).

## Puertos y adaptadores

| Pieza | Puerto | Adaptador hoy | Adaptador después | Variable |
| --- | --- | --- | --- | --- |
| Ejecución de análisis | `JobQueue` | `InlineJobQueue` (mismo proceso) | `CeleryJobQueue` | `VORACIOUS_JOB_BACKEND=inline` |
| Persistencia de análisis | `AnalysisRepository` | `InMemoryAnalysisRepository` | `PostgresAnalysisRepository` (TimescaleDB) | `VORACIOUS_REPOSITORY=memory` |
| Datos de entrada | `DatasetStorage` | `LocalDatasetStorage` | `S3DatasetStorage` | `VORACIOUS_STORAGE=local` |
| Tenant | `TenantContext` | cabecera `X-Tenant-ID` (sin auth real) | JWT/OIDC | — |

## Contrato de la API

Asíncrona desde el día uno ([ADR 0003](adr/0003-api-asincrona.md)):

- `POST /v1/analyses` — matriz n×p (JSON o CSV) + `MRCDParams` opcionales → `202 {analysis_id}`.
- `GET /v1/analyses/{id}` — `{status: queued | running | succeeded | failed, ...}`.
- Errores con formato uniforme `{code, message, details}`.
- Toda ruta de negocio exige tenant; un tenant nunca ve análisis de otro.
- `GET /health` (vivo) y `GET /ready` (listo para tráfico).

Mientras `MRCD.fit` no exista, todo análisis termina en `failed` con código `MRCD_NOT_IMPLEMENTED`.
