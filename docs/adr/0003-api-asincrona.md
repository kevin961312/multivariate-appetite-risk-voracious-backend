# ADR 0003 — API asíncrona desde el día uno

- **Estado:** Aceptado
- **Fecha:** 2026-10-06

## Contexto

Ajustar MRCD sobre muchos portafolios (o portafolios grandes) no cabe en el ciclo de una petición HTTP.
La arquitectura objetivo ejecuta los análisis en workers Celery. Si hoy la API respondiera el resultado de
forma síncrona, al llegar Celery habría que romper el contrato con los clientes.

## Decisión

- `POST /v1/analyses` responde **`202 Accepted`** con `analysis_id`, siempre.
- `GET /v1/analyses/{id}` devuelve el estado: `queued | running | succeeded | failed` y, si aplica,
  resultado o error `{code, message, details}`.
- La ejecución pasa por el puerto `JobQueue`. Hoy `InlineJobQueue` la corre en el mismo proceso; mañana
  `CeleryJobQueue` la encola. El contrato HTTP no cambia.
- Los análisis pertenecen a un tenant; `GET` de un análisis ajeno responde igual que uno inexistente (`404`).

## Consecuencias

- Los clientes hacen *polling* (más adelante, opcionalmente webhooks) desde el principio.
- Con `InlineJobQueue` el estado puede estar ya en `failed`/`succeeded` al primer `GET`; los clientes no deben
  asumir que verán `queued`.

## Alternativas descartadas

- **Endpoint síncrono ahora y asíncrono después:** obliga a versionar o romper la API.
- **WebSockets/SSE como único canal:** complica clientes y balanceadores; se puede añadir encima del polling.
