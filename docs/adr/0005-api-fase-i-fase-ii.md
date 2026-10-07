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
