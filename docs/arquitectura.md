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

## Arquitectura de hoy (Pasos 1 a 4.2)

Existe todo lo que sigue: `config`, `container`, `api` (rutas por pasos, errores uniformes, tenant), `workers`
(punto de entrada sin lógica), `cli` (`python -m voracious.cli migrate`, sin lógica), `infrastructure` (cola en hilos
por carriles, repositorios en memoria **o en Postgres**, almacenamiento, `ProcessPoolTaskMapper`, reloj, ids, logging),
`application` (casos de uso, puertos, registros, recuperación al arrancar) y el dominio. Siguen siendo **objetivo**:
Celery, TimescaleDB, S3 y JWT/OIDC con roles y Row-Level Security (Docker y CI existen desde el Paso 4.1; Postgres
desde el 4.2, [ADR 0011](adr/0011-persistencia-en-postgres.md)).

```
 HTTP ─▶ api/ (routers por paso y por carta, schemas, errores, tenant por X-Tenant-ID)
 workers/ (run.handle; Celery después) · cli.py (migrate)│
            └────────┬────────────────┘
                     ▼ ambos usan
                container.py (cableado: único lugar que conoce todo)
                     │ construye
                     ▼
          infrastructure/ (InlineJobQueue por carriles, repos en memoria o Postgres, almacenamiento, pasos por carta, logging)
                     │ implementa los puertos de
                     ▼
          application/ (casos de uso por paso: ajuste, límites, exclusión, modelo, tubería, puntuación,
          recalibración, comparación, versión; puertos Protocol)
                     │ usa
                     ▼
          domain/
            ├─ charts/<carta>/       p. ej. t2mrcd: parámetros, estadística, bootstrap, Fase I y Fase II
            ├─ estimators/<estim.>/  p. ej. mrcd: parámetros, adaptador sobre pymrcd, resultado
            └─ common/               ControlChart, TaskMapper, errores, tipos numéricos (sin estadística)
```

Flujo de dependencias: `api | workers | cli` → `container` → `infrastructure` → `application` → `domain`.

## Despliegue (Pasos 4.1 y 4.2)

Detalle y alternativas en el [ADR 0010](adr/0010-empaquetado-docker-y-ci.md) (imagen, CI) y el
[ADR 0011](adr/0011-persistencia-en-postgres.md) (Postgres, migraciones, backup, recuperación).

- **Compose** (`docker-compose.yml`): cuatro servicios. `postgres` (17, por digest, **sin `ports`**, volumen
  `pgdata`, healthcheck `pg_isready`); `migrate` (ejecuta `python -m voracious.cli migrate` y termina); `api` (un
  solo worker de uvicorn: la cola vive en el proceso y el arranque cierra como interrumpidos los trabajos en curso);
  `backup` (`pg_dump` diario, 7 días, volumen `pgbackups`). La API espera a `postgres` sano y a `migrate` terminado
  con éxito. Raíz de solo lectura con `/tmp` en `tmpfs`, `restart: unless-stopped` y logs rotados.
- **Datasets:** volumen `datasets` montado en `/data` con `VORACIOUS_STORAGE=local` y
  `VORACIOUS_STORAGE_DIR=/data/datasets`; las matrices sobreviven a reinicios y los metadatos están en Postgres.
- **Límites (M7):** `api` 2g / 1.5 CPU / 512 pids; `postgres` 768m / 0.75 CPU / 256 pids; `migrate` 256m / 0.5 CPU;
  `backup` 256m / 0.25 CPU. Pensados para 2 vCPU y 3.7 GiB: con la cola en el proceso la memoria de `api` crece con
  los trabajos en curso y los datasets cargados.
- **Puerto:** `127.0.0.1:8000`, sin exponer a la red; acceso remoto por túnel SSH. La base de datos **nunca** se
  expone.
- **Secretos:** `POSTGRES_PASSWORD` y `VORACIOUS_DATABASE_URL` solo en el `.env` del servidor (no versionado;
  plantilla en `.env.example`). Sin `POSTGRES_PASSWORD` Compose no arranca.
- **Perfil 2 vCPU** (`.env.example`, comentado): `VORACIOUS_REPLICATE_PROCESSES=2`, `VORACIOUS_MRCD_THREADS=1`,
  carriles `ESTIMATION=1`, `CALIBRATION=1`, `LIGHT=2`, `ORCHESTRATION=1`. Procesos × hilos MRCD no supera los
  núcleos. Solo rendimiento: no cambia ningún resultado.
- **Tiempos medidos (2026-10-09, servidor 2 vCPU, 200×300, B = 100, 2 procesos × 1 hilo):** una calibración
  bootstrap 5,5 min; Fase I completa de una sola pasada ≈ 6 min (estimado a partir de la calibración medida);
  memoria pico 245 MB, dentro del `mem_limit` de 2g. Con la cascada de depuración antigua: 18,3 min sin converger
  (200 → 36 filas en 6 rondas; ver [`metodos/t2mrcd.md`](metodos/t2mrcd.md)). Siguen sin medirse la
  recalibración completa y el caso p > n.

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
| `cli` | `python -m voracious.cli migrate`: traduce la orden a `container.run_migrations`; sin lógica. | `container` |
| `config` | `pydantic-settings`, prefijo `VORACIOUS_`. | — |

### Por qué este orden de capas

`api`, `workers` y `cli` son los puntos de entrada y reciben todo ya construido de `container`; `container` es
quien instancia los adaptadores de `infrastructure`; `infrastructure` implementa puertos definidos en
`application`; `application` orquesta `domain`. Una capa solo puede importar las que tiene debajo. El contrato
`layers` refleja el flujo real: con otro orden (p. ej. `api` directamente sobre `application`) no podría
expresar que `container` está en medio. `config` queda fuera del orden (`exhaustive_ignores`) porque la leen
`container` y `infrastructure`, pero no importa nada del proyecto.

### Contratos de `import-linter` vigentes (`pyproject.toml`, `[tool.importlinter]`)

Son 16; la lista numerada y su porqué están en [`CLAUDE.md`](../CLAUDE.md) §2. En resumen:

1. Capas: `api | workers | cli` → `container` → `infrastructure` → `application` → `domain` (exhaustivo).
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
15. `api` no importa el driver de Postgres (`psycopg`, `psycopg_pool`); 16. `cli` no importa `infrastructure` ni
    `config` (solo vía `container`).

Además, `psycopg` y `psycopg_pool` están prohibidos en `domain` (2), `application` (3) y `pymrcd` (8): el driver
solo vive en `infrastructure/postgres`.

Los contratos 5, 6, 13, 14, 15 y 16 llevan `allow_indirect_imports = true`: `api|workers|cli → container → config|infrastructure` y
`charts.t2mrcd → estimators.mrcd → pymrcd` son caminos legítimos y, sin esa opción, import-linter los contaría
como violación; lo que se prohíbe es el import directo.


## Puertos y adaptadores

Los puertos viven en `application/ports.py`, salvo `TaskMapper` (dominio). Los adaptadores «hoy» existen desde el Paso 3 (Postgres, desde el 4.2);
los de la columna «después» son objetivo.

| Pieza | Puerto | Adaptador hoy | Adaptador después | Variable |
| --- | --- | --- | --- | --- |
| Ejecución de trabajos | `JobQueue` (recibe `JobRequest`) | `InlineJobQueue`: un `ThreadPoolExecutor` por carril ([ADR 0003](adr/0003-api-asincrona.md)) | `CeleryJobQueue` | `VORACIOUS_JOB_BACKEND=inline` |
| Datasets (linaje, huella) | `DatasetStorage` | `memory` o `LocalDatasetStorage` (`.npy` con hash, M6; con Postgres, metadatos y fechas en la base) | `S3DatasetStorage` | `VORACIOUS_STORAGE`, `VORACIOUS_STORAGE_DIR` |
| Ajustes, límites, exclusiones, tuberías, comparaciones | `FitRepository`, `LimitsRepository`, `ExclusionRepository`, `PipelineRepository`, `ComparisonRepository` | `memory` (seguros entre hilos) o **Postgres** (`infrastructure/postgres/`, [ADR 0011](adr/0011-persistencia-en-postgres.md)); ambos con `claim` (CAS `queued → running`) | Postgres con TimescaleDB (sin fecha) | `VORACIOUS_REPOSITORY=memory\|postgres`, `VORACIOUS_DATABASE_URL` |
| Modelos y puntuaciones | `ModelRepository`, `MonitoringRepository` | `memory` o Postgres, con `claim` | ídem | ídem |
| Ciclo de vida | `ModelVersionRepository` (append-only, CAS de estado, `add_proposal_if_none`), `ObservationRepository`, `SignalAnnotationRepository`, `StructuralEventRepository`, `RecalibrationRepository` (`add_if_none_in_progress`) | `memory` o Postgres; altas atómicas (D6) con índices únicos parciales | ídem | ídem |
| Pasos por carta | `Phase1Steps`, `RecalibrationSteps` | `infrastructure/charts/t2mrcd_*.py` | un adaptador por carta nueva | — |
| Reparto de tareas independientes | `TaskMapper` | `SerialTaskMapper` (dominio) o `ProcessPoolTaskMapper` | Celery/Dask | `VORACIOUS_REPLICATE_PROCESSES` |
| Recuperación al arrancar | `RecoverInterruptedJobs` (caso de uso sobre los puertos de repositorio) | `lifespan` de la API: `failed / JOB_INTERRUPTED` | cola distribuida | — |
| Identificadores y reloj | `IdGenerator`, `Clock` | `UuidIdGenerator`, `SystemClock` | — | — |
| Tenant | `TenantContext` | cabecera `X-Tenant-ID` (`400 TENANT_REQUIRED` si falta; sin auth real) | JWT/OIDC | — |

Decisiones de diseño de los puertos y registros:

- **`JobRequest` solo lleva identificadores** (`kind`, `tenant_id`, `scope` = la carta, `resource_id` y, en los
  hijos de un modelo, `model_id`): los datos están en el repositorio y el mensaje sirve para cualquier cola.
- **`JobKind` y carriles** (`lane_of`): `mrcd_fit` → `estimation`; `limits`, `comparison` →
  `calibration`; `exclusion`, `model_assembly`, `score`, `version_proposal` → `light`; `pipeline` → `orchestration`. Separarlos
  evita que un bootstrap de minutos bloquee una puntuación (ADR 0003, enmienda). `TRAIN`, `MONITOR` y `RECALIBRATE`
  se retiraron: ya no hay trabajos monolíticos (ADR 0009).
- **Todo `get` exige `tenant_id`** y devuelve `None` si el recurso es de otro tenant: un recurso ajeno es
  indistinguible de uno inexistente.
- **Registros inmutables** con `created_at`, `started_at` y `finished_at` (UTC, de `Clock`); cada transición crea un
  registro nuevo. **Los repositorios guardan datos codificados** (M1: arreglos base64 con dtype y forma, estrictos,
  con `format_version`), no objetos: el adaptador Postgres guarda ese mismo JSON en `payload TEXT`.
- **Atomicidad:** `claim` (CAS `queued → running`), `add_if_none_in_progress` y `add_proposal_if_none` son
  atómicos en el adaptador en memoria (cerrojos) y en el de Postgres (`UPDATE … RETURNING`, índices únicos parciales con
  `ON CONFLICT DO NOTHING`, `SELECT … FOR UPDATE`); ambos pasan la misma suite de contrato.
- **Casos de uso** (`application/use_cases/`): uno o varios por paso (`steps`, `pipelines`, `comparisons`, `proposals`,
  `recalibration_chain`, `monitoring`, `observations`, `recalibration`, `training`, `versions`), `dispatch` que lleva un `JobRequest` a su
  manejador, y los que ejecuta el worker (idempotentes por `claim`).

## Persistencia (Paso 4.2)

Decisiones y alternativas en el [ADR 0011](adr/0011-persistencia-en-postgres.md). Migración
`infrastructure/postgres/migrations/0001_initial.sql`; se aplica con `python -m voracious.cli migrate`.

**Convenciones de toda tabla de registros.** Lleva `tenant_id` (y toda lectura filtra por él), `seq BIGSERIAL`
(orden de inserción), `payload TEXT` (el JSON exacto del codec: no JSONB, que rechaza `NaN`/`±Inf` y pierde `-0`) y
`format_version`. Las demás columnas son **copias** del payload para filtrar, ordenar e imponer invariantes; **se lee
siempre del payload**. Estados de trabajo: `queued | running | succeeded | failed | cancelled` (`CHECK`); los de una
versión: `proposed | active | superseded | rejected`. Las tablas de trabajos llevan un índice parcial `*_unfinished`
(`WHERE status IN ('queued','running')`) que usa la recuperación al arrancar.

```mermaid
erDiagram
    tenants ||--o{ datasets : "FK"
    datasets ||--o{ dataset_rows : "FK"
    tenants ||--o{ fits : "FK"
    tenants ||--o{ limits : "FK"
    tenants ||--o{ exclusions : "FK"
    tenants ||--o{ pipelines : "FK"
    tenants ||--o{ models : "FK"
    tenants ||--o{ model_versions : "FK"
    model_versions ||--o{ version_base_rows : "FK"
    tenants ||--o{ scores : "FK"
    tenants ||--o{ observations : "FK"
    tenants ||--o{ signal_annotations : "FK"
    tenants ||--o{ structural_events : "FK"
    tenants ||--o{ recalibrations : "FK"
    tenants ||--o{ comparisons : "FK"
    datasets ||..o{ fits : "dataset_id (lógica)"
    fits ||..o{ limits : "fit_id (lógica)"
    datasets ||..o{ exclusions : "dataset_id (lógica)"
    datasets ||..o{ pipelines : "dataset_id (lógica)"
    pipelines ||..o| models : "pipeline_id (lógica)"
    models ||..o{ model_versions : "model_id (lógica)"
    models ||..o{ scores : "model_id (lógica)"
    scores ||..o{ observations : "score_id (lógica)"
    observations ||..o{ signal_annotations : "observation_id (lógica)"
    models ||..o{ structural_events : "model_id (lógica)"
    models ||..o{ recalibrations : "model_id (lógica)"
    recalibrations ||..o{ comparisons : "recalibration_id (lógica)"
    recalibrations ||..o{ model_versions : "recalibration_id (lógica)"
    tenants { text tenant_id PK }
    datasets { text tenant_id PK "PK (tenant_id, dataset_id)" }
    dataset_rows { int row_index PK "PK (tenant_id, dataset_id, row_index)" }
    model_versions { int number PK "PK (tenant_id, chart_id, model_id, number)" }
    version_base_rows { int row_index PK "PK (..., number, row_index)" }
```

Las referencias «lógicas» no son claves foráneas: el vínculo lo valida la aplicación (los pasos se encadenan por id,
ADR 0009) y así un recurso puede referirse a otro del mismo tenant sin acoplar el orden de inserción.

| Tabla | Clave primaria | Índices y restricciones que importan | Para qué |
| --- | --- | --- | --- |
| `tenants` | `tenant_id` | — | Se crea al primer uso del tenant; ancla de las FK. |
| `datasets` | `(tenant_id, dataset_id)` | `datasets_parent (tenant_id, parent_id)`; `variables TEXT[]`, `content_hash`, `n_rows`, `n_cols` | Metadatos y linaje; la matriz está en `.npy`. |
| `dataset_rows` | `(tenant_id, dataset_id, row_index)` | `dataset_rows_observed (…, observed_at)`; FK a `datasets`; `external_ref` reservada (`NULL`) | Fecha de cada fila. Solo trazabilidad. |
| `fits` | `(tenant_id, chart_id, fit_id)` | `fits_unfinished (seq)` parcial | Ajuste MRCD (paso de Fase I). |
| `limits` | `(tenant_id, chart_id, limits_id)` | `limits_unfinished` parcial; `fit_id`, `recalibration_id` | Límites bootstrap. |
| `exclusions` | `(tenant_id, chart_id, exclusion_id)` | `exclusions_unfinished` parcial | Exclusión humana de filas. |
| `pipelines` | `(tenant_id, chart_id, pipeline_id)` | `pipelines_unfinished` parcial; `kind`, `n_steps`, `model_id` | Orquestación encadenada. |
| `models` | `(tenant_id, chart_id, model_id)` | `models_unfinished` parcial; `root_dataset_id` | Modelo ensamblado (versión 0 incluida). |
| `model_versions` | `(tenant_id, chart_id, model_id, number)` | **`model_versions_one_proposal`**: único parcial `WHERE status='proposed'` (D6); `effective_from`; append-only salvo estado/decisión (CAS con `FOR UPDATE`) | Versiones inmutables del ciclo de vida. |
| `version_base_rows` | `(…, number, row_index)` | FK a `model_versions`; `source`, `ref`, `observed_at` | Origen y fecha de cada fila de la base de una versión. Append-only. |
| `scores` | `(tenant_id, chart_id, model_id, score_id)` | `scores_unfinished` parcial; `batch_label` | Lote de Fase II (trabajo). |
| `observations` | `(tenant_id, chart_id, model_id, observation_id)` | `observations_by_date (…, observed_at, seq)`, `observations_signals` parcial `WHERE signal`, `observations_by_version`; `observed_values FLOAT8[]`, `t2`, `limit_used`, `limit_kind`, `version_number`, `signal` | Registro de cada observación puntuada. Append-only. Es la materia prima de la recalibración. |
| `signal_annotations` | `(…, annotation_id)` | `signal_annotations_by_observation (…, observation_id, seq)` | Vale la de mayor `seq` por observación. Append-only. |
| `structural_events` | `(…, event_id)` | `structural_events_by_date (…, occurred_at, registered_at, seq)` | Eventos que exigen nueva base. Append-only. |
| `recalibrations` | `(…, recalibration_id)` | **`recalibrations_one_in_progress`**: único parcial `WHERE status IN ('queued','running')` (D6); `recalibrations_by_id` | Una recalibración en curso por modelo. |
| `comparisons` | `(…, comparison_id)` | `comparisons_unfinished` parcial; `recalibration_id` | Comparación S/μ de la recalibración. |
| `schema_migrations` | `version` | `checksum` SHA-256, `applied_at` | La crea el ejecutor, no la migración. |

**Fechas y nombres de variables.** Pedido del dueño para trazabilidad y para recalibrar con datos de enero a
septiembre más los nuevos. Un dataset puede traer el nombre de cada columna y la fecha de cada fila: JSON con
`variables` y `observed_at` (con zona horaria; se guardan en UTC); CSV con cabecera y `?date_column=` (por defecto
`observed_at`). Se heredan al **modelo**, a la **versión 0** (cada fila de su base queda fechada en
`version_base_rows`), a la salida de una **exclusión**, a las **candidatas** de una recalibración y a la **extensión**.
Si el modelo tiene nombres, una puntuación o recalibración con otros número u orden responde `422
VARIABLES_MISMATCH`. Nada de esto entra en ninguna estadística: un test compara el modelo en bits con y sin ellos.

**Recalibración = recalcular todo.** MRCD no admite una actualización incremental (el subconjunto `best`, ρ y los
C-steps dependen de todas las filas), y las cartas autoiniciadas de Quesenberry y Hawkins valen para estimadores
clásicos, no para MRCD. Por eso recalibrar reajusta MRCD y recalibra los límites sobre una base nueva
(ADR 0008). Ejemplo: base inicial del 1-ene al 30-sep de 2026; en noviembre se recalibra y las observaciones de
octubre y noviembre, guardadas en `observations` con su fecha, son las candidatas que se unen a la base. Guardar
cada observación con su fecha y valores es lo que hace posible ese flujo tras un reinicio.

**Recuperación tras un reinicio.** `RecoverInterruptedJobs` (en el `lifespan` de la API) cierra `failed /
JOB_INTERRUPTED` lo que quedó `queued` o `running`, salvo las sesiones `stepwise` abiertas sin propuesta en curso.
Por eso hay un solo worker de uvicorn.

## Configuración

Solo variables de entorno con prefijo `VORACIOUS_`; la aplicación **no lee `.env`** para que local, CI y
producción se configuren igual (plantilla en `.env.example`).

| Variable | Valores | Default | Efecto |
| --- | --- | --- | --- |
| `VORACIOUS_LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` | Nivel mínimo de los logs JSON (structlog). Un valor inválido falla al arrancar. |
| `VORACIOUS_MRCD_THREADS` | entero ≥ 1, o vacío | vacío | Hilos de la extensión C de `pymrcd` por ajuste MRCD. Solo rendimiento: no cambia ningún resultado ni se guarda en las versiones ([ADR 0006](adr/0006-libreria-pymrcd.md), enmienda 2026-10-07). Vacío: `pymrcd` usa `PYMRCD_NUM_THREADS` o todos los CPU visibles. Cableada en `container`. |
| `VORACIOUS_JOB_BACKEND` | `inline` | `inline` | Adaptador de la cola. |
| `VORACIOUS_REPOSITORY` | `memory` \| `postgres` | `memory` | Adaptador de los repositorios. `postgres` exige `VORACIOUS_DATABASE_URL` y `VORACIOUS_STORAGE=local`; si no, `ConfigurationError` al arrancar. |
| `VORACIOUS_DATABASE_URL` | `postgresql://usuario:contraseña@host:5432/base` | vacío | **Secreto** (`SecretStr`: no sale en `repr` ni en logs). Contraseña en codificación URL. Obligatoria con `postgres`. |
| `VORACIOUS_DATABASE_POOL_SIZE` | entero ≥ 1 | 10 | Conexiones máximas del pool. Solo rendimiento. |
| `POSTGRES_USER` / `POSTGRES_DB` / `POSTGRES_PASSWORD` | texto | `voracious` / `voracious` / **obligatoria** | No son de la aplicación: los lee Compose para los servicios `postgres` y `backup`. |
| `VORACIOUS_TEST_DATABASE_URL` | URL de un Postgres de prueba | vacío | Solo pruebas y compuerta; sin ella la compuerta levanta uno con Docker (`compose.test.yaml`). |
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
| Fase I | `POST/GET <c>/fits`, `<c>/limits`, `<c>/exclusions`; `POST <c>/models` (solo referencias) | `202 {id, status:"queued"}` + `GET` |
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

### Salud (Paso 1; checks reales desde el 4.2)

- `GET /health` es **liveness**: el proceso responde. No comprueba dependencias, para que un fallo de una
  dependencia externa no haga que el orquestador reinicie un proceso sano.
- `GET /ready` es **readiness**: el proceso puede recibir tráfico. Con `repository=postgres` comprueba `database`
  (`SELECT 1`, máximo 2 s) y con `storage=local` comprueba `storage` (directorio escribible). Todo bien: `200
  {status: ready, checks}`; si algo falla: **`503 {status: not_ready, checks}`** con el check en `fail`. Decisión
  cerrada en el [ADR 0011](adr/0011-persistencia-en-postgres.md). Con todo en memoria `checks` va vacío.
- La cola no tiene check (vive en el proceso): deuda hasta la cola distribuida (Redis).
