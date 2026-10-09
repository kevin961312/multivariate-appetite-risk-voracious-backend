# ADR 0003 — API asíncrona desde el día uno

- **Estado:** Aceptado — ampliado por [0005](0005-api-fase-i-fase-ii.md) y [0009](0009-api-por-pasos-encadenables.md)
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

## Enmienda 2026-10-07 (Paso 3): carriles y cola en hilos

Las rutas `/v1/analyses` del texto original quedaron superadas por el ADR 0005 y el [ADR 0009](0009-api-por-pasos-encadenables.md);
el contrato (`202` + polling, estados, tenant que oculta lo ajeno) se mantiene.

- **`InlineJobQueue` ya no ejecuta en la petición:** encola en `ThreadPoolExecutor`, así que el `POST` responde de
  inmediato. Esto cierra la deuda «Fase I fuera del hilo de la API». Un `GET` inmediato puede ver `queued`,
  `running` o ya el resultado: el cliente no debe asumir ninguno.
- **Un ejecutor por carril** (`JobLane`), por coste y no por carta. Por qué: con una sola cola, un bootstrap de
  minutos haría esperar a una puntuación de milisegundos. Carriles y tipos de trabajo (`lane_of`):

| Carril | Trabajos | Variable (hilos, default) |
| --- | --- | --- |
| `estimation` | `mrcd_fit` | `VORACIOUS_QUEUE_WORKERS_ESTIMATION` (1) |
| `calibration` | `limits`, `comparison` (lo más costoso) | `VORACIOUS_QUEUE_WORKERS_CALIBRATION` (1) |
| `light` | `model_assembly`, `score`, `version_proposal` | `VORACIOUS_QUEUE_WORKERS_LIGHT` (4) |
| `orchestration` | `pipeline` | `VORACIOUS_QUEUE_WORKERS_ORCHESTRATION` (2) |

- **Orquestación en su propio carril, por continuaciones.** La tubería no calcula ni espera: cada paso, al
  terminar, encola el trabajo `pipeline`, que decide y crea el siguiente (avance atómico con
  `append_step`). Por qué un carril aparte: son decisiones breves que no deben hacer cola detrás de una calibración de
  minutos, ni ocupar sus hilos.
- **Entrega duplicada:** el `claim` atómico `queued → running` de los repositorios hace que un mensaje repetido no
  vuelva a ejecutar el paso (con una cola real, p. ej. Celery, ocurre).
- **Límites conocidos:** los hilos de la cola comparten el GIL: el paralelismo real de un ajuste viene de los hilos de la
  extensión C de `pymrcd` y del reparto de réplicas en procesos (no medido de extremo a extremo; deuda). El reparto de réplicas en procesos es del `TaskMapper`, no de la cola. Los
  trabajos viven en el proceso: reiniciarlo pierde la cola y los repositorios en memoria (Paso 4+: Celery y Postgres).
