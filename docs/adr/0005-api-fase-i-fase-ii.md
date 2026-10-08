# ADR 0005 — API por carta: Fase I (entrenar) y Fase II (monitorear)

- **Estado:** Aceptado
- **Fecha:** 2026-10-06
- **Amplía:** [ADR 0003](0003-api-asincrona.md). Se mantiene la API asíncrona; cambian las rutas.

## Contexto

Una carta de control se usa en dos fases:

- **Fase I:** con datos históricos se ajusta el estimador (p. ej. MRCD) y se calculan los límites de control.
- **Fase II:** las observaciones nuevas se puntúan contra ese modelo guardado y se marcan las señales.

Un único `POST /v1/analyses` mezclaba ambas cosas y no permitía reutilizar un modelo entrenado.
Además, por el [ADR 0004](0004-cartas-y-estimadores-extensibles.md), cada carta tiene su propia API.

## Decisión

Rutas por carta (`<carta>` es su identificador, p. ej. `t2mrcd`):

| Fase | Método y ruta | Respuesta |
| --- | --- | --- |
| I | `POST /v1/charts/<carta>/models` (datos históricos n×p en JSON o CSV + parámetros de la carta) | `202 {model_id}` |
| I | `GET /v1/charts/<carta>/models/{model_id}` | estado `queued \| running \| succeeded \| failed`; si `succeeded`, el modelo (límites, parámetros efectivos y lo que la carta exponga) |
| II | `POST /v1/charts/<carta>/models/{model_id}/monitorings` (observaciones nuevas) | `202 {monitoring_id}` |
| II | `GET /v1/charts/<carta>/models/{model_id}/monitorings/{monitoring_id}` | estado; si `succeeded`, estadístico por observación y señales |

- **Las dos fases son asíncronas** (`202` + polling), con el mismo contrato de estados, aunque hoy la ejecución
  sea en línea. Así no se rompe nada cuando lleguen Celery y los lotes grandes.
- Fase II exige un modelo de Fase I en `succeeded`, del mismo tenant y de la misma carta. Si no, `409`
  (modelo no listo o fallido) o `404` (no existe o es de otro tenant).
- Errores con el formato uniforme `{code, message, details}`. Mientras el estimador no exista, Fase I
  termina en `failed` con `MRCD_NOT_IMPLEMENTED` (para T²MRCD).
- Lo común entre cartas (tenant, estados de trabajo, errores, formato de entrada n×p) se comparte;
  los parámetros, los resultados y los schemas son de cada carta.

## Consecuencias

- El puerto de persistencia guarda **modelos** (Fase I) y **monitoreos** (Fase II), no «análisis» genéricos.
- Los casos de uso pasan a ser `TrainModel`, `GetModel`, `MonitorObservations` y `GetMonitoring`.
- El Paso 3 implementa estas rutas para `t2mrcd`.

## Alternativas descartadas

- **Fase II síncrona:** más simple para el cliente, pero rompe el contrato cuando haya lotes grandes.
- **Un solo recurso «analysis» con `phase=`:** no expresa que un monitoreo depende de un modelo entrenado.

## Enmienda 2026-10-07 (Paso 2): catálogo de códigos, validación síncrona e idempotencia

Sustituye al párrafo de la línea 32-33 sobre `MRCD_NOT_IMPLEMENTED` (superado, ver enmienda del
[ADR 0002](0002-mrcd-sin-aproximaciones.md)).

**Catálogo de códigos** (formato uniforme `{code, message, details}`):

| Código | Origen | Cuándo |
| --- | --- | --- |
| `T2MRCD_DECISION_PENDING` | dominio | Un campo estadístico decisivo es `None` (con los defaults no ocurre); `details.pending` lista los campos |
| `MRCD_FIT_FAILED` | dominio | `pymrcd` lanzó `RError`; `details.r_message` |
| `BOOTSTRAP_REPLICATE_FAILED` | dominio | Una réplica falló; la Fase I falla (no se descartan réplicas) |
| `BOOTSTRAP_LIMIT_NOT_FINITE` | dominio | La agregación devolvió un límite no finito |
| `T2MRCD_CLEAN_CRITERION_INVALID` | dominio | El criterio de fila limpia no devolvió una máscara booleana de longitud n |
| `T2MRCD_NO_CLEAN_OBSERVATIONS` | dominio | El criterio no dejó ninguna fila limpia |
| `INVALID_INPUT` | dominio | Entrada vacía, no finita, con `p` distinto del modelo o con suma por fila desbordada |
| `INTERNAL_ERROR` | aplicación | Excepción inesperada (no `DomainError`); sin traza en el registro, el detalle va al log |
| `CHART_NOT_FOUND` | aplicación | Carta no registrada |
| `MODEL_NOT_FOUND` | aplicación | Modelo inexistente, de otra carta o de otro tenant |
| `MODEL_NOT_READY` | aplicación | Modelo no `succeeded` (Fase II) |
| `MONITORING_NOT_FOUND` | aplicación | Monitoreo inexistente o ajeno |

El mapeo a HTTP (`404`, `409`, `422`…) es del Paso 3.

**Validación síncrona de Fase II.** `MonitorObservations` valida las observaciones con
`validate_phase2_input` **antes** de encolar: una entrada incompatible con el modelo (p. ej. otro número de
variables) es un error inmediato del cliente, no un monitoreo `failed` que descubre al hacer polling. La Fase I
no se valida igual por ahora (deuda del Paso 3, ver `ESTADO.md`).

**Jobs idempotentes.** `RunTrainingJob` y `RunMonitoringJob` no hacen nada si el registro ya no está `queued`.
Con una cola real (Celery) un mensaje puede entregarse dos veces; así un duplicado no vuelve a ejecutar
minutos de cómputo ni pisa un resultado. Limitación conocida: la transición `queued → running` no es atómica
(deuda del Paso 3).

**`JobRequest` solo lleva identificadores.** Los datos viven en el repositorio, de modo que el mensaje es
pequeño y serializable por cualquier cola.

## Enmienda 2026-10-07 (Paso 2b): endpoints del ciclo de vida

Ciclo de vida en el [ADR 0008](0008-ciclo-de-vida-de-la-carta.md). El backend es dueño del ciclo; el front solo
muestra y pide. **Endpoints previstos del Paso 3** (no existen aún); todos bajo `/v1/charts/<carta>/models/{model_id}`,
con tenant y el contrato asíncrono `202` + polling cuando el trabajo es largo:

| Método y ruta | Respuesta |
| --- | --- |
| `GET …/versions`, `GET …/versions/{version_id}` | lista y detalle de versiones (inmutables) con estado `proposed \| active \| superseded \| rejected`, límites y reporte antes/después |
| `POST …/versions/{version_id}/approve`, `POST …/versions/{version_id}/reject` | aprueba (con `effective_from` no retroactivo) o rechaza una **propuesta** |
| `GET …/status` | estado de la carta: `requires_new_base > proposal_pending > revalidation_due > startup/active`, versión vigente y avisos |
| `POST …/monitorings` (ampliado) | ahora cada observación lleva `observed_at` y `batch_label`; `202 {monitoring_id}` |
| `GET …/observations?from=&to=&signals_only=` | observaciones registradas (fecha, lote, valores, T², límite usado, versión) por rango |
| `PUT …/observations/{observation_id}/annotation` | anota una señal: causa asignable, cuál, acción (solo observaciones con señal) |
| `POST …/structural-events` | registra un evento estructural y marca «requiere nueva base» |
| `POST …/recalibrations` | `202 {recalibration_id}` (base + rango de fechas + criterios de depuración); produce una **propuesta** |
| `GET …/recalibrations/{recalibration_id}` | estado; si `succeeded`, el reporte y la versión propuesta |

**Códigos nuevos** (formato `{code, message, details}`; el mapeo a HTTP es del Paso 3):

| Código | Cuándo |
| --- | --- |
| `VERSION_NOT_FOUND` | Versión inexistente, de otro modelo o de otro tenant |
| `VERSION_NOT_PROPOSED` | Se aprueba o rechaza una versión que no está en estado propuesta |
| `PROPOSAL_PENDING` | Ya hay una propuesta sin resolver |
| `RECALIBRATION_IN_PROGRESS` | Ya hay una recalibración en curso para el modelo |
| `RECALIBRATION_NOT_FOUND` | Recalibración inexistente o ajena |
| `OBSERVATION_NOT_FOUND` | Observación inexistente o ajena |
| `NOT_A_SIGNAL` | Se anota una observación sin señal (Q12) |
| `RANGE_BEFORE_STRUCTURAL_EVENT` | El rango pedido incluye datos anteriores al último evento estructural |
| `RECALIBRATION_INSUFFICIENT_OBSERVATIONS` | Tras filtrar y depurar quedan menos observaciones que el mínimo (25 por defecto) |
| `EFFECTIVE_FROM_NOT_AFTER_SCORED` | `effective_from` no es posterior a la última observación ya puntuada (Q6) |
| `OBSERVATION_BEFORE_FIRST_VERSION` | `observed_at` anterior a la primera versión vigente |
| `BOOTSTRAP_OOB_EMPTY` | Una réplica no tiene filas OOB (ver ADR 0007, enmienda) |

## Enmienda 2026-10-07 (Paso 2b.2): código nuevo y nombre de estado

- **Estado de versión:** el catálogo de endpoints decía `approved`; el nombre vigente es `active` (ADR 0008,
  enmienda 2b.2). Corregido en la tabla de arriba.
- **Código nuevo `RECALIBRATION_DECISION_PENDING`** (aplicación): la recalibración tiene decisiones estadísticas
  sin cerrar (hoy, las pruebas formales de S y μ sin cita; `details.pending` lista los campos). Es una
  **validación síncrona** previa a encolar, para que el cliente lo sepa de inmediato. Se omite con `force_replace`
  o cuando hay un evento estructural sin resolver (que ya fuerza el reemplazo). Si llegara a ejecutarse, la
  carta falla con su propio código (`T2MRCD_DECISION_PENDING`).

## Enmienda 2026-10-07 (Paso 3): rutas definitivas, códigos HTTP y catálogo completo

El texto original no se reescribe. **Sustituye** a las rutas de las tablas anteriores (`POST …/models` con datos,
`…/monitorings`, `PUT …/annotation`) por las que existen, organizadas en pasos independientes y encadenables
por id ([ADR 0009](0009-api-por-pasos-encadenables.md)). Todas exigen `X-Tenant-ID`; un recurso de otro tenant
responde como inexistente.

**Rutas** (`<c>` = `/v1/charts/t2mrcd`; los `POST` de cómputo responden `202 {id, status:"queued"}` y se consultan con `GET`):

| Paso | Método y ruta | Notas |
| --- | --- | --- |
| Dataset | `POST /v1/datasets` (`201`), `GET /v1/datasets/{id}` | JSON, CSV o multipart; `413`/`415`; guarda linaje y huella |
| Ajuste MRCD | `POST <c>/fits`, `GET <c>/fits/{id}` | única API de MRCD, `alpha` parametrizable (default 0.75) |
| Límites | `POST <c>/limits`, `GET <c>/limits/{id}` | `{fit_id, params}`; en datasets derivados hereda los parámetros |
| Depuración | `POST <c>/depurations`, `GET <c>/depurations/{id}` | humana `{dataset_id, assignable_cause}` solo sobre el dataset raíz; automática `{fit_id, limits_id}` |
| Modelo | `POST <c>/models` | **solo por referencias** (ajuste y límites); ya no recibe datos. Sustituye a `POST …/models` de este ADR |
| Orquestación | `POST <c>/pipelines/phase1`, `GET <c>/pipelines/{id}` (alias `/pipelines/phase1/{id}`) | solo encadena los pasos anteriores |
| Modelo | `GET <c>/models/{id}` (`?include=` para matrices, M3), `GET …/status` | estado de la carta (ADR 0008) |
| Fase II | `POST <c>/models/{id}/scores` (`202`), `GET …/scores/{score_id}` | sustituye a `monitorings` |
| Observaciones | `GET …/observations?from=&to=&signals_only=`, `POST …/observations/{id}/annotations` (`201`) | la anotación es un `POST` **append-only** (P4): sustituye a `PUT …/annotation`; no se sobrescribe, se añade |
| Eventos | `POST …/structural-events` (`201`), `GET …/structural-events` | |
| Recalibración | `POST …/recalibrations {mode: stepwise\|pipeline}`, `GET …/recalibrations/{id}`, `POST …/recalibrations/{id}/cancel` | `stepwise` responde `201` con `candidates_dataset_id` (candidatas congeladas); `cancel` cancela la recalibración en curso |
| Pasos de recalibración | `POST <c>/limits {fit_id, recalibration_id}`, `POST <c>/depurations` | hereda parámetros (Q8); exclusión humana tomada de las anotaciones |
| Comparación | `POST …/comparisons`, `GET …/comparisons/{id}` | `RECALIBRATION_DECISION_PENDING` (422) mientras no haya pruebas formales citadas; con reemplazo forzado no hay comparación |
| Versiones | `POST …/versions` (propuesta, `202`), `GET …/versions`, `GET …/versions/{number}` (`?include=`), `POST …/versions/{number}/approve`, `…/reject` | la versión se identifica por su número dentro del modelo |

`/ready` sigue sin checks (deuda).

**Estados de job:** `queued | running | succeeded | failed`. Un fallo de dominio de un **trabajo** no es un error HTTP:
queda en el registro `failed` y el `GET` responde `200` con `{code, message, details}` en el cuerpo. Solo los
errores **síncronos** (validación, estado, recurso) usan la tabla siguiente. Fuente única: `CODE_TO_STATUS` en
`api/errors.py`; un `DomainError` síncrono sin entrada responde `422` y un código sin mapeo responde `500`.

**Catálogo de códigos síncronos con su HTTP** (se suma al catálogo de las enmiendas anteriores, cuyo «mapeo a HTTP
es del Paso 3» queda resuelto aquí):

| HTTP | Códigos |
| --- | --- |
| 400 | `TENANT_REQUIRED` (falta `X-Tenant-ID`) |
| 404 | `CHART_NOT_FOUND`, `MODEL_NOT_FOUND`, `MONITORING_NOT_FOUND`, `VERSION_NOT_FOUND`, `RECALIBRATION_NOT_FOUND`, `OBSERVATION_NOT_FOUND`, `DATASET_NOT_FOUND`, `FIT_NOT_FOUND`, `LIMITS_NOT_FOUND`, `DEPURATION_NOT_FOUND`, `PIPELINE_NOT_FOUND`, `COMPARISON_NOT_FOUND`, `ROUTE_NOT_FOUND` |
| 405 | `METHOD_NOT_ALLOWED` |
| 409 | `MODEL_NOT_READY`, `FIT_NOT_READY`, `LIMITS_NOT_READY`, `COMPARISON_NOT_READY`, `DEPURATION_NOT_FINAL`, `VERSION_NOT_PROPOSED`, `PROPOSAL_PENDING`, `RECALIBRATION_IN_PROGRESS`, `RECALIBRATION_NOT_IN_PROGRESS`, `NOT_A_SIGNAL`, `EFFECTIVE_FROM_NOT_AFTER_SCORED` |
| 413 | `PAYLOAD_TOO_LARGE` (por encima de `VORACIOUS_MAX_UPLOAD_MB`) |
| 415 | `UNSUPPORTED_MEDIA_TYPE` |
| 422 | `INVALID_INPUT` (incluye errores de schema, con `details.errors`), `RANGE_BEFORE_STRUCTURAL_EVENT`, `RECALIBRATION_INSUFFICIENT_OBSERVATIONS`, `RECALIBRATION_DECISION_PENDING`, `OBSERVATION_BEFORE_FIRST_VERSION`, `T2MRCD_FIT_PARAMS_MISMATCH`, `LIMITS_FIT_MISMATCH`, `LIMITS_PARAMS_MISMATCH`, `RECALIBRATION_MISMATCH`, `VERSION_INPUTS_MISMATCH` y, por defecto, cualquier `DomainError` síncrono (p. ej. `T2MRCD_DECISION_PENDING`) |
| 500 | `INTERNAL_ERROR` (el detalle va al log, nunca al cuerpo) |
| variable | `HTTP_ERROR`: cualquier otro error HTTP del enrutado (conserva su estado y su texto) |

Códigos nuevos del Paso 3 y su porqué:

| Código | Cuándo |
| --- | --- |
| `T2MRCD_FIT_PARAMS_MISMATCH` | Los parámetros enviados difieren de los del ajuste referenciado |
| `LIMITS_FIT_MISMATCH` | Los límites no se calibraron sobre el ajuste indicado |
| `LIMITS_PARAMS_MISMATCH` | Parámetros de los límites distintos de los heredados del dataset derivado |
| `RECALIBRATION_MISMATCH` | Un paso referencia recursos que no pertenecen a esa recalibración (o a ninguna) |
| `VERSION_INPUTS_MISMATCH` | Los pasos pedidos para la versión no son los que exige la decisión (EXTEND: ajuste y límites del dataset de extensión; REPLACE: los de la última ronda de las filas nuevas; sin reemplazo forzado, la comparación); `details.reason` dice cuál |
| `FIT_NOT_READY`, `LIMITS_NOT_READY`, `COMPARISON_NOT_READY`, `DEPURATION_NOT_FINAL` | El paso referenciado no ha terminado; `DEPURATION_NOT_FINAL`: la depuración no está `succeeded` o no es la final de su cadena (un modelo solo se ensambla con la ronda final) |
| `RECALIBRATION_NOT_IN_PROGRESS` | La recalibración ya terminó (o ya tiene su propuesta pedida) y no admite más pasos |
| `ROUTE_NOT_FOUND`, `METHOD_NOT_ALLOWED`, `HTTP_ERROR` | Errores de enrutado en el mismo formato uniforme |

**Validación síncrona ampliada.** Ahora también se rechazan antes de encolar la entrada de Fase I
(`validate_phase1_input`), los parámetros incoherentes entre pasos y las decisiones pendientes
(`T2MRCD_DECISION_PENDING`, `RECALIBRATION_DECISION_PENDING`). Cierra la deuda «validación síncrona del histórico».

**Jobs.** El `JobRequest` lleva `kind`, `tenant_id`, `scope` (la carta), `resource_id` y, para los hijos de un
modelo, `model_id`. `JobKind`: `mrcd_fit`, `limits`, `depuration`, `model_assembly`, `score`, `comparison`,
`version_proposal`, `pipeline`. Se retiran `TRAIN`, `MONITOR` y `RECALIBRATE` (y `monitorings` pasa a `scores`),
porque ya no hay un trabajo monolítico. La idempotencia pasa de «no hacer nada si no está `queued`» a un `claim`
atómico `queued → running`, que cierra la limitación anotada en la enmienda del Paso 2.
