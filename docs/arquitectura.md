# Arquitectura

## Por qué hexagonal

El producto vale por los métodos estadísticos (hoy el estimador MRCD y la carta T²MRCD); eso no debe depender
de cómo se recibe una petición, dónde se guarda un resultado ni quién ejecuta el cálculo. El objetivo es
distribuido, pero hoy se construye lo mínimo. Con puertos y adaptadores, cada pieza distribuida entra como
**un adaptador nuevo y una variable de configuración**, sin tocar `domain/` ni `application/`.
Ver [ADR 0001](adr/0001-hexagonal.md).

## Arquitectura objetivo (no se construye todavía)

```
 clientes ──HTTPS──▶ API FastAPI (multi-tenant, JWT/OIDC)
                         │ encola
                         ▼
                   Celery + Redis ──▶ workers (Fase I y Fase II, paralelo por portafolio)
                                          │        └─▶ Dask/Spark para lotes masivos
                                          ▼
                     PostgreSQL/TimescaleDB (series, modelos y monitoreos)
                     S3 (data lake de entradas)
                     Kubernetes con autoescalado
```

## Arquitectura de hoy y del Paso 2 en adelante

Existe hoy (Paso 1): `config`, `container`, `api` con `/health` y `/ready`, logging en `infrastructure`.
Lo demás es **objetivo** de los Pasos 2 y 3.

```
 HTTP ─▶ api/ (routers por carta, schemas, errores, tenant por X-Tenant-ID)
 workers/ (futuro: Celery)            │
            └────────┬────────────────┘
                     ▼ ambos usan
                container.py (cableado: único lugar que conoce todo)
                     │ construye
                     ▼
          infrastructure/ (InlineJobQueue, repos en memoria, almacenamiento local, logging)
                     │ implementa los puertos de
                     ▼
          application/ (TrainModel, GetModel, MonitorObservations, GetMonitoring; puertos Protocol)
                     │ usa
                     ▼
          domain/
            ├─ charts/<carta>/       p. ej. t2mrcd: parámetros, estadística, Fase I y Fase II
            ├─ estimators/<estim.>/  p. ej. mrcd: parámetros, ajuste, resultado
            └─ common/               tipos de resultado, errores, utilidades numéricas puras
```

Flujo de dependencias: `api | workers` → `container` → `infrastructure` → `application` → `domain`.

## Dominio extensible

Por el [ADR 0004](adr/0004-cartas-y-estimadores-extensibles.md), cada carta y cada estimador es un paquete
independiente con su documento en [`metodos/`](metodos/README.md). Una carta puede usar uno o varios
estimadores; un estimador no conoce las cartas; una carta no importa a otra carta ni un estimador a otro.
`domain/common/` no tiene lógica estadística de ningún método.

Contrato común de una carta (`typing.Protocol` sin estado; **objetivo del Paso 2**, ubicación exacta por decidir,
ver [`ESTADO.md`](ESTADO.md)):

- `fit_phase1(X, params) -> PhaseIModel`: ajusta con datos históricos y calcula los límites.
- `score_phase2(model, X_new) -> PhaseIIResult`: puntúa observaciones nuevas y marca señales.

`application` e `infrastructure` trabajan contra este contrato; añadir una carta no las modifica, solo se
registra en `container.py`.

## Capas

| Capa | Responsabilidad | Depende de |
| --- | --- | --- |
| `domain` | Cartas, estimadores, parámetros, resultados, errores de dominio. Puro: numpy/scipy. | nada del proyecto |
| `application` | Casos de uso y puertos (`typing.Protocol`). Orquesta, no sabe de HTTP ni de BD. | `domain` |
| `infrastructure` | Adaptadores que implementan los puertos (y logging). | `application`, `domain` |
| `container` | Cableado: elige adaptadores según `config`. Único lugar que conoce todo. | todas |
| `api` | FastAPI: app factory, routers, schemas Pydantic, dependencias, mapeo de errores. | `application`, `domain`, `container` |
| `workers` | (vacío) Punto de entrada de Celery en el futuro. | `application`, `domain`, `container` |
| `config` | `pydantic-settings`, prefijo `VORACIOUS_`. | — |

### Por qué este orden de capas

`api` y `workers` son los puntos de entrada y reciben todo ya construido de `container`; `container` es
quien instancia los adaptadores de `infrastructure`; `infrastructure` implementa puertos definidos en
`application`; `application` orquesta `domain`. Una capa solo puede importar las que tiene debajo. El contrato
`layers` refleja el flujo real: con otro orden (p. ej. `api` directamente sobre `application`) no podría
expresar que `container` está en medio. `config` queda fuera del orden (`exhaustive_ignores`) porque la leen
`container` y `infrastructure`, pero no importa nada del proyecto.

### Contratos de `import-linter` vigentes (`pyproject.toml`, `[tool.importlinter]`)

1. Capas: `api | workers` → `container` → `infrastructure` → `application` → `domain` (exhaustivo).
2. `domain` no importa configuración, `container`, frameworks ni IO (FastAPI, Starlette, Pydantic,
   pydantic-settings, structlog, httpx, uvicorn).
3. `application` no importa `config` ni frameworks web/logging.
4. `config` no importa ninguna capa del proyecto.
5. `api` no importa `config` (la recibe de `container`).
6. `api` no importa `infrastructure` (solo a través de `container`).

Los contratos 5 y 6 llevan `allow_indirect_imports = true`: `api → container → config|infrastructure` es el
camino legítimo y, sin esa opción, import-linter lo contaría como violación; lo que se prohíbe es el import
directo.

**Anunciados para el Paso 2:** contratos `independence` (cartas entre sí; estimadores entre sí) y `forbidden`
`estimators ↛ charts` y `common ↛ charts|estimators`. **Deuda:** `workers ↛ infrastructure|config` (Paso 3).

## Puertos y adaptadores

Los nombres de los puertos de persistencia son **orientativos y se fijan en el Paso 2**.

| Pieza | Puerto | Adaptador hoy | Adaptador después | Variable |
| --- | --- | --- | --- | --- |
| Ejecución de Fase I y Fase II | `JobQueue` | `InlineJobQueue` (mismo proceso) | `CeleryJobQueue` | `VORACIOUS_JOB_BACKEND=inline` |
| Persistencia de modelos (Fase I) | `ModelRepository` | en memoria | Postgres (TimescaleDB) | `VORACIOUS_REPOSITORY=memory` |
| Persistencia de monitoreos (Fase II) | `MonitoringRepository` | en memoria | Postgres (TimescaleDB) | `VORACIOUS_REPOSITORY=memory` |
| Datos de entrada | `DatasetStorage` | `LocalDatasetStorage` | `S3DatasetStorage` | `VORACIOUS_STORAGE=local` |
| Tenant | `TenantContext` | cabecera `X-Tenant-ID` (sin auth real) | JWT/OIDC | — |

Las variables de esta tabla son **objetivo**; hoy solo existe `VORACIOUS_LOG_LEVEL`.

## Configuración

Solo variables de entorno con prefijo `VORACIOUS_`; la aplicación **no lee `.env`** para que local, CI y
producción se configuren igual (plantilla en `.env.example`).

| Variable | Valores | Default | Efecto |
| --- | --- | --- | --- |
| `VORACIOUS_LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` | Nivel mínimo de los logs JSON (structlog). Un valor inválido falla al arrancar. |

## Contrato de la API

Asíncrona desde el día uno ([ADR 0003](adr/0003-api-asincrona.md)) y organizada por carta con Fase I y
Fase II ([ADR 0005](adr/0005-api-fase-i-fase-ii.md)). **Objetivo del Paso 3**; `<carta>` es p. ej. `t2mrcd`:

| Fase | Ruta | Respuesta |
| --- | --- | --- |
| I | `POST /v1/charts/<carta>/models` (n×p en JSON o CSV + parámetros) | `202 {model_id}` |
| I | `GET /v1/charts/<carta>/models/{model_id}` | `queued \| running \| succeeded \| failed`; si `succeeded`, el modelo |
| II | `POST /v1/charts/<carta>/models/{model_id}/monitorings` | `202 {monitoring_id}` |
| II | `GET /v1/charts/<carta>/models/{model_id}/monitorings/{monitoring_id}` | estado; si `succeeded`, estadístico y señales |

- Fase II exige un modelo `succeeded`, del mismo tenant y de la misma carta: `409` si no está listo o falló,
  `404` si no existe o es de otro tenant.
- Errores con formato uniforme `{code, message, details}`.
- Toda ruta de negocio exige tenant; un tenant nunca ve recursos de otro.
- Mientras `MRCD.fit` no exista, la Fase I de T²MRCD termina en `failed` con `MRCD_NOT_IMPLEMENTED`.

### Salud (existe desde el Paso 1)

- `GET /health` es **liveness**: el proceso responde. No comprueba dependencias, para que un fallo de una
  dependencia externa no haga que el orquestador reinicie un proceso sano.
- `GET /ready` es **readiness**: el proceso puede recibir tráfico. `checks` va vacío porque aún no hay
  dependencias externas; irán entrando con cada adaptador (BD, Redis, S3).
- **Decisión abierta:** código HTTP de `/ready` cuando un check falle (típicamente `503`; no está decidido).
