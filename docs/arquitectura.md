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

Existe hoy (Pasos 1 y 2): `config`, `container`, `api` con `/health` y `/ready`, logging en `infrastructure`, el
dominio (`common`, `estimators/mrcd`, `charts/t2mrcd`) y `application` (casos de uso, puertos y registros).
Siguen siendo **objetivo del Paso 3**: los adaptadores de `infrastructure` (cola, repositorios, `TaskMapper` con
procesos), el cableado en `container`, `workers` y las rutas de la API.

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
(`ProcessPoolTaskMapper`) irá en `infrastructure` (Paso 3). El contexto compartido se entrega una vez y las
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

Son 13; la lista numerada y su porqué están en [`CLAUDE.md`](../CLAUDE.md) §2. En resumen:

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

Los contratos 5, 6 y 13 llevan `allow_indirect_imports = true`: `api → container → config|infrastructure` y
`charts.t2mrcd → estimators.mrcd → pymrcd` son caminos legítimos y, sin esa opción, import-linter los contaría
como violación; lo que se prohíbe es el import directo.

**Deuda:** `workers ↛ infrastructure|config` (Paso 3, cuando `workers` tenga contenido).

## Puertos y adaptadores

Los puertos están fijados (Paso 2) y viven en `application/ports.py`, salvo `TaskMapper` (dominio). Los
adaptadores de la columna «hoy» son **objetivo del Paso 3**.

| Pieza | Puerto | Adaptador hoy | Adaptador después | Variable |
| --- | --- | --- | --- | --- |
| Ejecución de Fase I y Fase II | `JobQueue` (recibe `JobRequest`) | `InlineJobQueue` (mismo proceso) | `CeleryJobQueue` | `VORACIOUS_JOB_BACKEND=inline` |
| Persistencia de modelos (Fase I) | `ModelRepository` | en memoria | Postgres (TimescaleDB) | `VORACIOUS_REPOSITORY=memory` |
| Persistencia de monitoreos (Fase II) | `MonitoringRepository` | en memoria | Postgres (TimescaleDB) | `VORACIOUS_REPOSITORY=memory` |
| Reparto de tareas independientes | `TaskMapper` | `SerialTaskMapper` (dominio); procesos en el Paso 3 | `ProcessPoolTaskMapper`, luego Celery/Dask | _por definir_ |
| Identificadores y reloj | `IdGenerator`, `Clock` | _Paso 3_ | — | — |
| Datos de entrada | `DatasetStorage` | `LocalDatasetStorage` | `S3DatasetStorage` | `VORACIOUS_STORAGE=local` |
| Versiones, observaciones, anotaciones, eventos estructurales y recalibraciones (puertos **definidos** en 2b.2) | `ModelVersionRepository` (append-only, CAS de estado), `ObservationRepository`, `SignalAnnotationRepository`, `StructuralEventRepository`, `RecalibrationRepository` | en memoria solo en `tests/support/`; reales en el Paso 3 | Postgres (TimescaleDB) | `VORACIOUS_REPOSITORY=memory` |
| Tenant | `TenantContext` | cabecera `X-Tenant-ID` (sin auth real) | JWT/OIDC | — |

Decisiones de diseño de los puertos y registros:

- **`JobRequest` solo lleva identificadores** (`kind`, `tenant_id`, `chart_id`, `model_id`, `monitoring_id`): los
  datos están en el repositorio y el mensaje sirve para cualquier cola (Celery incluido).
- **Todo `get` exige `tenant_id`** y devuelve `None` si el recurso es de otro tenant: un recurso ajeno es
  indistinguible de uno inexistente, y el aislamiento no depende de que el llamador se acuerde de comprobarlo.
- **Registros inmutables** (`ModelRecord`, `MonitoringRecord`) con `created_at`, `started_at` y `finished_at`
  (UTC, de `Clock`); cada transición crea un registro nuevo (`dataclasses.replace`) que se guarda con `update`.
  El modelo y el resultado de la carta se guardan como `object`: solo la carta los interpreta.
- **Casos de uso** (`application/use_cases/`): `TrainModel`, `GetModel`, `MonitorObservations`, `GetMonitoring`
  (los que usa la API) y `RunTrainingJob`, `RunMonitoringJob` (los que ejecuta el worker; idempotentes).

Las variables de esta tabla son **objetivo**; hoy solo existe `VORACIOUS_LOG_LEVEL`.

## Configuración

Solo variables de entorno con prefijo `VORACIOUS_`; la aplicación **no lee `.env`** para que local, CI y
producción se configuren igual (plantilla en `.env.example`).

| Variable | Valores | Default | Efecto |
| --- | --- | --- | --- |
| `VORACIOUS_LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` | Nivel mínimo de los logs JSON (structlog). Un valor inválido falla al arrancar. |
| `VORACIOUS_MRCD_THREADS` | entero ≥ 1, o vacío | vacío (= no definida) | Hilos de la extensión C de `pymrcd` por ajuste MRCD. Solo rendimiento: no cambia ningún resultado ni se guarda en las versiones de la carta ([ADR 0006](adr/0006-libreria-pymrcd.md), enmienda 2026-10-07). Vacío: `pymrcd` usa `PYMRCD_NUM_THREADS` o todos los CPU visibles. **Existe en `Settings` pero aún no está cableada** en `container` (Paso 3). |

**Sobresuscripción.** Cada ajuste MRCD usa hilos y el bootstrap puede repartir réplicas en procesos
(`TaskMapper`): procesos × hilos no debe superar los núcleos. Con réplicas en procesos conviene fijar
`VORACIOUS_MRCD_THREADS` (p. ej. núcleos ÷ procesos); con un solo proceso, dejarla vacía.

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
- Con los defaults de T²MRCD (P2–P6 cerradas) la Fase I se ejecuta completa; si un campo decisivo se pasa como
  `None`, termina en `failed` con `T2MRCD_DECISION_PENDING` y `details.pending`. Fase I y Fase II tienen límites distintos que comparten réplicas (ADR 0007, enmienda del Paso 2b). Catálogo completo de códigos en la enmienda del
  [ADR 0005](adr/0005-api-fase-i-fase-ii.md).

### Ciclo de vida de la carta (casos de uso en 2b.2; rutas y adaptadores en el Paso 3)

Decidido en el [ADR 0008](adr/0008-ciclo-de-vida-de-la-carta.md): el backend posee versiones, observaciones,
anotaciones, eventos estructurales, propuesta/aprobación y avisos; el front solo muestra y pide. Endpoints
previstos en el [ADR 0005](adr/0005-api-fase-i-fase-ii.md) (enmienda 2026-10-07). Flujo:

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
- `GET /ready` es **readiness**: el proceso puede recibir tráfico. `checks` va vacío porque aún no hay
  dependencias externas; irán entrando con cada adaptador (BD, Redis, S3).
- **Decisión abierta:** código HTTP de `/ready` cuando un check falle (típicamente `503`; no está decidido).
