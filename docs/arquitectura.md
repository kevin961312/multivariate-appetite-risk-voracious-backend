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

## Arquitectura de hoy (Pasos 1 a 3)

Existe todo lo que sigue: `config`, `container`, `api` (rutas por pasos, errores uniformes, tenant), `workers`
(punto de entrada sin lógica), `infrastructure` (cola en hilos por carriles, repositorios en memoria, almacenamiento,
`ProcessPoolTaskMapper`, reloj, ids, logging), `application` (casos de uso, puertos, registros) y el dominio. Siguen
siendo **objetivo** (Paso 4+): Celery, Postgres/TimescaleDB, S3, JWT/OIDC, Docker y CI.

```
 HTTP ─▶ api/ (routers por paso y por carta, schemas, errores, tenant por X-Tenant-ID)
 workers/ (run.handle; Celery después)│
            └────────┬────────────────┘
                     ▼ ambos usan
                container.py (cableado: único lugar que conoce todo)
                     │ construye
                     ▼
          infrastructure/ (InlineJobQueue por carriles, repos en memoria, almacenamiento, pasos por carta, logging)
                     │ implementa los puertos de
                     ▼
          application/ (casos de uso por paso: ajuste, límites, depuración, modelo, tubería, puntuación,
          recalibración, comparación, versión; puertos Protocol)
                     │ usa
                     ▼
          domain/
            ├─ charts/<carta>/       p. ej. t2mrcd: parámetros, estadística, bootstrap, Fase I y Fase II
            ├─ estimators/<estim.>/  p. ej. mrcd: parámetros, adaptador sobre pymrcd, resultado
            └─ common/               ControlChart, TaskMapper, errores, tipos numéricos (sin estadística)
```

Flujo de dependencias: `api | workers` → `container` → `infrastructure` → `application` → `domain`.

## Dominio extensible

Por el [ADR 0004](adr/0004-cartas-y-estimadores-extensibles.md), cada carta y cada estimador es un paquete
independiente con su documento en [`metodos/`](metodos/README.md). Una carta puede usar uno o varios
estimadores; un estimador no conoce las cartas; una carta no importa a otra carta ni un estimador a otro.
`domain/common/` no tiene lógica estadística de ningún método.

Contrato común de una carta: `ControlChart`, un `typing.Protocol` sin estado en `domain/common/chart.py`
(enmienda del [ADR 0004](adr/0004-cartas-y-estimadores-extensibles.md); vive en `common` porque es lo único que
todas las cartas pueden compartir sin importarse entre sí):

- `fit_phase1(x, params, *, mapper: TaskMapper) -> modelo`: ajusta con datos históricos y calcula los límites.
- `validate_phase2_input(model, x_new)`: validación síncrona antes de encolar la Fase II.
- `score_phase2(model, x_new) -> resultado`: puntúa observaciones nuevas y marca señales.
- **Codec de parámetros** (`encode_params`, `decode_params`, `encode_recalibration_params`,
  `decode_recalibration_params`; mejora M1, ADR 0004 enmienda 2b.2): los registros persistidos no pueden guardar
  invocables, así que la carta convierte sus parámetros (con estrategias) en datos y de vuelta. Los protocolos de
  forma de `application/charts.py` fijan lo que el ciclo de vida exige a cualquier carta (resultado con `t2`,
  `signal`, `limit`, `limit_kind`; modelo con `base_mask` y `row_disposition`; informe con `row_disposition`).

**`TaskMapper`** (`domain/common/parallel.py`) es el puerto con el que una carta pide ejecutar tareas
independientes (las réplicas bootstrap de T²MRCD) sin saber cómo: el dominio no puede importar procesos ni hilos
(contrato `domain` limpio). `SerialTaskMapper` es el adaptador en serie; el de procesos
(`ProcessPoolTaskMapper`, `infrastructure/parallel.py`) usa contexto `spawn`, `threadpoolctl` a 1 hilo de BLAS por proceso
y fija `PYMRCD_NUM_THREADS`; su resultado es idéntico en bits al de serie. Crea un pool **por llamada** (spawn caro: deuda). El contexto compartido se entrega una vez y las
tareas llevan solo índice y semilla, de modo que el resultado no depende del número de procesos.

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
| `workers` | `run.handle(JobRequest)`: ejecuta un trabajo con el manejador del contenedor; sin lógica. Punto de entrada de Celery en el futuro. | `application`, `domain`, `container` |
| `config` | `pydantic-settings`, prefijo `VORACIOUS_`. | — |

### Por qué este orden de capas

`api` y `workers` son los puntos de entrada y reciben todo ya construido de `container`; `container` es
quien instancia los adaptadores de `infrastructure`; `infrastructure` implementa puertos definidos en
`application`; `application` orquesta `domain`. Una capa solo puede importar las que tiene debajo. El contrato
`layers` refleja el flujo real: con otro orden (p. ej. `api` directamente sobre `application`) no podría
expresar que `container` está en medio. `config` queda fuera del orden (`exhaustive_ignores`) porque la leen
`container` y `infrastructure`, pero no importa nada del proyecto.

### Contratos de `import-linter` vigentes (`pyproject.toml`, `[tool.importlinter]`)

Son 14; la lista numerada y su porqué están en [`CLAUDE.md`](../CLAUDE.md) §2. En resumen:

1. Capas: `api | workers` → `container` → `infrastructure` → `application` → `domain` (exhaustivo).
2. `domain` no importa configuración, `container`, frameworks ni IO; desde el Paso 2 (M1) tampoco
   `multiprocessing`, `concurrent`, `threading`, `socket`, `io`, `pathlib` ni `os`.
3. `application` no importa `config` ni frameworks web/logging.
4. `config` no importa ninguna capa del proyecto.
5. `api` no importa `config` (la recibe de `container`).
6. `api` no importa `infrastructure` (solo a través de `container`).
7. `pymrcd` no importa `voracious`; 8. `pymrcd` solo importa `numpy` y `scipy`.
9. y 10. `independence`: cartas entre sí; estimadores entre sí.
11. `estimators ↛ charts`; 12. `common ↛ charts|estimators`.
13. Solo `domain.estimators.mrcd` importa `pymrcd`.
14. `workers` no importa `infrastructure` ni `config` (solo vía `container`).

Los contratos 5, 6, 13 y 14 llevan `allow_indirect_imports = true`: `api|workers → container → config|infrastructure` y
`charts.t2mrcd → estimators.mrcd → pymrcd` son caminos legítimos y, sin esa opción, import-linter los contaría
como violación; lo que se prohíbe es el import directo.


## Puertos y adaptadores

Los puertos viven en `application/ports.py`, salvo `TaskMapper` (dominio). Los adaptadores «hoy» existen desde el Paso 3;
los de la columna «después» son objetivo (Paso 4+).

| Pieza | Puerto | Adaptador hoy | Adaptador después | Variable |
| --- | --- | --- | --- | --- |
| Ejecución de trabajos | `JobQueue` (recibe `JobRequest`) | `InlineJobQueue`: un `ThreadPoolExecutor` por carril ([ADR 0003](adr/0003-api-asincrona.md)) | `CeleryJobQueue` | `VORACIOUS_JOB_BACKEND=inline` |
| Datasets (linaje, huella) | `DatasetStorage` | `memory` o `LocalDatasetStorage` (`.npy` con hash, M6) | `S3DatasetStorage` | `VORACIOUS_STORAGE`, `VORACIOUS_STORAGE_DIR` |
| Ajustes, límites, depuraciones, tuberías, comparaciones | `FitRepository`, `LimitsRepository`, `DepurationRepository`, `PipelineRepository`, `ComparisonRepository` | en memoria, seguros entre hilos, con `claim` (CAS `queued → running`) | Postgres (TimescaleDB) | `VORACIOUS_REPOSITORY=memory` |
| Modelos y puntuaciones | `ModelRepository`, `MonitoringRepository` | en memoria, con `claim` | Postgres (TimescaleDB) | ídem |
| Ciclo de vida | `ModelVersionRepository` (append-only, CAS de estado, `add_proposal_if_none`), `ObservationRepository`, `SignalAnnotationRepository`, `StructuralEventRepository`, `RecalibrationRepository` (`add_if_none_in_progress`) | en memoria; altas atómicas (D6) | Postgres (TimescaleDB) | ídem |
| Pasos por carta | `Phase1Steps`, `RecalibrationSteps` | `infrastructure/charts/t2mrcd_*.py` | un adaptador por carta nueva | — |
| Reparto de tareas independientes | `TaskMapper` | `SerialTaskMapper` (dominio) o `ProcessPoolTaskMapper` | Celery/Dask | `VORACIOUS_REPLICATE_PROCESSES` |
| Identificadores y reloj | `IdGenerator`, `Clock` | `UuidIdGenerator`, `SystemClock` | — | — |
| Tenant | `TenantContext` | cabecera `X-Tenant-ID` (`400 TENANT_REQUIRED` si falta; sin auth real) | JWT/OIDC | — |

Decisiones de diseño de los puertos y registros:

- **`JobRequest` solo lleva identificadores** (`kind`, `tenant_id`, `scope` = la carta, `resource_id` y, en los
  hijos de un modelo, `model_id`): los datos están en el repositorio y el mensaje sirve para cualquier cola.
- **`JobKind` y carriles** (`lane_of`): `mrcd_fit` → `estimation`; `limits`, `depuration`, `comparison` →
  `calibration`; `model_assembly`, `score`, `version_proposal` → `light`; `pipeline` → `orchestration`. Separarlos
  evita que un bootstrap de minutos bloquee una puntuación (ADR 0003, enmienda). `TRAIN`, `MONITOR` y `RECALIBRATE`
  se retiraron: ya no hay trabajos monolíticos (ADR 0009).
- **Todo `get` exige `tenant_id`** y devuelve `None` si el recurso es de otro tenant: un recurso ajeno es
  indistinguible de uno inexistente.
- **Registros inmutables** con `created_at`, `started_at` y `finished_at` (UTC, de `Clock`); cada transición crea un
  registro nuevo. **Los repositorios guardan datos codificados** (M1: arreglos base64 con dtype y forma, estrictos,
  con `format_version`), no objetos: un adaptador Postgres guardará lo mismo.
- **Atomicidad:** `claim` (CAS `queued → running`), `add_if_none_in_progress` y `add_proposal_if_none` son
  atómicos en los adaptadores en memoria, y su contrato lo es para los futuros.
- **Casos de uso** (`application/use_cases/`): uno o varios por paso (`steps`, `pipelines`, `comparisons`, `proposals`,
  `recalibration_chain`, `monitoring`, `observations`, `recalibration`, `training`, `versions`), `dispatch` que lleva un `JobRequest` a su
  manejador, y los que ejecuta el worker (idempotentes por `claim`).

## Configuración

Solo variables de entorno con prefijo `VORACIOUS_`; la aplicación **no lee `.env`** para que local, CI y
producción se configuren igual (plantilla en `.env.example`).

| Variable | Valores | Default | Efecto |
| --- | --- | --- | --- |
| `VORACIOUS_LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` | Nivel mínimo de los logs JSON (structlog). Un valor inválido falla al arrancar. |
| `VORACIOUS_MRCD_THREADS` | entero ≥ 1, o vacío | vacío | Hilos de la extensión C de `pymrcd` por ajuste MRCD. Solo rendimiento: no cambia ningún resultado ni se guarda en las versiones ([ADR 0006](adr/0006-libreria-pymrcd.md), enmienda 2026-10-07). Vacío: `pymrcd` usa `PYMRCD_NUM_THREADS` o todos los CPU visibles. Cableada en `container`. |
| `VORACIOUS_JOB_BACKEND` | `inline` | `inline` | Adaptador de la cola. |
| `VORACIOUS_REPOSITORY` | `memory` | `memory` | Adaptador de los repositorios. |
| `VORACIOUS_STORAGE` | `memory` \| `local` | `memory` | Almacenamiento de datasets. |
| `VORACIOUS_STORAGE_DIR` | ruta | vacío | Directorio base; obligatorio con `local`. |
| `VORACIOUS_REPLICATE_PROCESSES` | entero ≥ 1, o vacío | vacío (serie) | Procesos para repartir réplicas bootstrap. Solo rendimiento. |
| `VORACIOUS_QUEUE_WORKERS_ESTIMATION` / `_CALIBRATION` / `_LIGHT` / `_ORCHESTRATION` | entero ≥ 1 | 1 / 1 / 4 / 2 | Hilos de cada carril. |
| `VORACIOUS_MAX_UPLOAD_MB` | entero ≥ 1 | 50 | Tamaño máximo del cuerpo de `POST /v1/datasets`; por encima, `413`. |

**Sobresuscripción.** Cada ajuste MRCD usa hilos y el bootstrap puede repartir réplicas en procesos
(`TaskMapper`): procesos × hilos no debe superar los núcleos (se avisa al arrancar). Con réplicas en procesos conviene fijar
`VORACIOUS_MRCD_THREADS` (p. ej. núcleos ÷ procesos); con un solo proceso, dejarla vacía.

## Contrato de la API

Asíncrona ([ADR 0003](adr/0003-api-asincrona.md)), por carta y **por pasos independientes encadenables por
id** ([ADR 0009](adr/0009-api-por-pasos-encadenables.md)); rutas y códigos definitivos en la enmienda del Paso 3
del [ADR 0005](adr/0005-api-fase-i-fase-ii.md). `<c>` = `/v1/charts/t2mrcd`:

| Paso | Rutas | Respuesta |
| --- | --- | --- |
| Dataset | `POST /v1/datasets`, `GET /v1/datasets/{id}` | `201`; JSON, CSV o multipart |
| Fase I | `POST/GET <c>/fits`, `<c>/limits`, `<c>/depurations`; `POST <c>/models` (solo referencias) | `202 {id, status:"queued"}` + `GET` |
| Orquestación | `POST <c>/pipelines/phase1`, `GET <c>/pipelines/{id}` | `202`; encadena los pasos anteriores |
| Fase II | `POST <c>/models/{id}/scores`, `GET …/scores/{id}` | `202` + `GET` |
| Ciclo de vida | `…/observations`, `…/annotations` (POST), `…/structural-events`, `…/recalibrations` (+ `cancel`), `…/comparisons`, `…/versions` (+ `approve`, `reject`), `…/status` | ver ADR 0005 |

- Estados `queued | running | succeeded | failed`. Un fallo de dominio **de un trabajo** queda en el registro y el
  `GET` responde `200`; los errores **síncronos** usan el formato `{code, message, details}` y los estados de
  `CODE_TO_STATUS` (`api/errors.py`).
- Toda ruta de negocio exige `X-Tenant-ID` (`400 TENANT_REQUIRED`); un tenant nunca ve recursos de otro.
- `?include=` (M3) pide las matrices grandes de modelos, versiones y recalibraciones; por defecto no se envían.
- Con los defaults de T²MRCD la Fase I se ejecuta completa; si un campo decisivo se pasa como `None`, el rechazo es
  síncrono (`T2MRCD_DECISION_PENDING` con `details.pending`). Fase I y Fase II tienen límites distintos que
  comparten réplicas (ADR 0007).

### Ciclo de vida de la carta (implementado: dominio 2b.1, aplicación 2b.2, rutas y adaptadores Paso 3)

Decidido en el [ADR 0008](adr/0008-ciclo-de-vida-de-la-carta.md): el backend posee versiones, observaciones,
anotaciones, eventos estructurales, propuesta/aprobación y avisos; el front solo muestra y pide. Endpoints
definitivos en el [ADR 0005](adr/0005-api-fase-i-fase-ii.md) (enmienda del Paso 3). Flujo:

```
 Fase I (v0, límites I y II) ─▶ vigilancia con límite de Fase I (provisional y fijo)
        │                                  │ registra cada observación (fecha, lote, T², límite, versión)
        │                                  ▼ anota señales
        │                        recalibración a petición (202) ─▶ versión propuesta + reporte antes/después
        │                                                            │ aprobar (effective_from no retroactivo) / rechazar
        ▼                                                            ▼
   evento estructural ─▶ «requiere nueva base»            versión vigente (límite de Fase II)
```

**Estado de la carta** (`GET …/status`), el primero que aplique, por precedencia:

1. `requires_new_base`: hay un evento estructural sin base nueva posterior; se sigue vigilando con la versión vigente.
2. `proposal_pending`: hay una propuesta sin aprobar ni rechazar.
3. `revalidation_due`: venció la revalidación periódica (6 meses u N observaciones).
4. `startup` (vigilando con v0) o `active` (con una versión recalibrada vigente).

Las versiones son inmutables y append-only; solo cambia su estado (`proposed | active | superseded | rejected`),
con comparar-y-cambiar (CAS) que lleva los datos de la decisión, para impedir dos aprobaciones concurrentes. Cada
observación se puntúa con la versión vigente en su fecha. `effective_from` por defecto es el instante de la
aprobación y debe ser posterior a la última observación puntuada y al `effective_from` vigente. La revalidación
cuenta meses desde `approved_at` de la vigente (v0: fin de la Fase I) y observaciones puntuadas con ella
(`count_scored_with`); se evalúa al consultar, sin tareas programadas. Cada versión guarda `base_hash` (SHA-256 de
la base) y su `justification` (`initial_fit`, `structural_event`, `forced_replace`, `change_detected`,
`no_change_detected`). Detalle en el ADR 0008, enmienda 2b.2.

### Salud (existe desde el Paso 1)

- `GET /health` es **liveness**: el proceso responde. No comprueba dependencias, para que un fallo de una
  dependencia externa no haga que el orquestador reinicie un proceso sano.
- `GET /ready` es **readiness**: el proceso puede recibir tráfico. `checks` va vacío (deuda: no comprueba cola ni almacenamiento); irán entrando con cada adaptador (BD, Redis, S3).
- **Decisión abierta:** código HTTP de `/ready` cuando un check falle (típicamente `503`; no está decidido).
