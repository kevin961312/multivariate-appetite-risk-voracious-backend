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
