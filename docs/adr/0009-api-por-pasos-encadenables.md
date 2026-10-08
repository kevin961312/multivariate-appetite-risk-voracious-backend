# ADR 0009 — API por pasos independientes, encadenables por identificador

- **Estado:** Aceptado (decisión del dueño, 2026-10-07)
- **Fecha:** 2026-10-07
- **Amplía:** [ADR 0005](0005-api-fase-i-fase-ii.md) (rutas definitivas en su enmienda del Paso 3) y
  [ADR 0003](0003-api-asincrona.md) (carriles de la cola).
- **Relacionado:** [ADR 0004](0004-cartas-y-estimadores-extensibles.md),
  [ADR 0007](0007-limites-t2mrcd-por-bootstrap.md), [ADR 0008](0008-ciclo-de-vida-de-la-carta.md),
  [`../metodos/t2mrcd.md`](../metodos/t2mrcd.md).

## Contexto

La Fase I de T²MRCD es una cadena de cómputo de minutos: ajustar MRCD, calibrar los límites por bootstrap,
depurar, volver a ajustar y ensamblar el modelo (ADR 0007). La recalibración repite la misma cadena sobre
observaciones nuevas (ADR 0008). Una sola llamada «entrenar» esconde todo eso: si falla la ronda 3 de una
depuración, el cliente no puede ver el ajuste que ya existía ni repetir solo la calibración con otro `B`, y el
equipo no puede depurar ni ajustar un paso sin ejecutar todos. El dueño lo formuló así: cada paso debe ser una
API independiente, encadenable por identificador, para avanzar paso a paso, mantener, ajustar y depurar cada
una; «si todo se hace en un solo API se colapsa».

## Decisión

1. **Un recurso y un trabajo asíncrono por paso**, todos con el contrato `202 {id, status:"queued"}` + `GET`
   (ADR 0003): dataset (`/v1/datasets`), ajuste MRCD (`/fits`), límites (`/limits`), depuración
   (`/depurations`), modelo (`/models`), y en Fase II puntuación (`/scores`), recalibración, comparación y
   versión. Un paso recibe **identificadores** de los pasos anteriores, no datos: el encadenamiento es por
   referencia y el cliente (o la orquestación) puede detenerse, revisar y continuar.
2. **Hay además una orquestación pura** (`/pipelines/phase1`, recalibración en modo `pipeline`) que solo
   encadena los mismos pasos; no tiene lógica propia. Existe para el cliente que no quiere ir paso a paso.
3. **El dominio ofrece las piezas públicas** que cada paso necesita (`fit_base`, `calibrate`, `depurate_step`,
   `assemble_model`, `compare`, `validate_phase1_input`, `stage_spawn_key`) y `fit_phase1` y `recalibrate` se
   **componen** con ellas. Por qué: así hay un solo código estadístico, y no una versión «para la API» y otra
   «para la tubería».
4. **Una sola API de MRCD bajo la carta, con `alpha` parametrizable** (default 0.75; decisión del dueño P1). No
   existe un «MRCD puro» aparte con 0.5. Detalle en la nota del ADR 0004.
5. **Cada recurso lleva su linaje** (`parent_id`, `rows`, `lineage_round`, `origin_ref`). La semilla de cada
   calibración se **deduce del linaje**, no la elige el cliente (ver `t2mrcd.md`, «Semilla por linaje»).
6. **Carriles de la cola** por coste de trabajo (enmienda del ADR 0003) para que un bootstrap no bloquee una
   puntuación.
7. **Errores y tenant uniformes** para todos los pasos (enmienda del ADR 0005): `X-Tenant-ID` obligatorio y
   `{code, message, details}`.

## Consecuencias

- **Equivalencia en bits.** Encadenar los pasos por HTTP, ejecutar la tubería y llamar a `fit_phase1`
  (o `recalibrate`) producen el **mismo modelo bit a bit**. Se prueba (`tests/integration/*_chain.py`) en Fase I
  y en recalibración (EXTEND, REPLACE forzado e INSUFFICIENT). Es lo que impide que la API por pasos se
  convierta en un segundo método. Las huellas del fixture de composición solo se han fijado en Darwin arm64
  (deuda).
- **Semillas por linaje, no por orden de ejecución.** Como el hueco de semilla depende de la posición del paso
  en la cadena y no del momento en que corre, el resultado no depende del carril, del número de procesos ni de
  si el cliente fue paso a paso o con la tubería.
- **Parámetros coherentes entre pasos.** Los pasos no se confían en lo que diga el cliente en cada llamada: el
  ajuste exige los parámetros del ajuste (`T2MRCD_FIT_PARAMS_MISMATCH`), los límites los heredan de la cadena
  (`LIMITS_PARAMS_MISMATCH`) y una recalibración los fija una vez (Q8). Una cadena incoherente se rechaza antes
  de gastar cómputo.
- **Estado persistido codificado (M1).** Cada paso guarda datos (arreglos base64 con dtype y forma, estrictos,
  con `format_version`), así que el siguiente paso puede correr en otro proceso o, después, en otro nodo.
- **Concurrencia atómica.** Los repositorios en memoria son seguros entre hilos y ofrecen `claim`
  (`queued → running` por comparar-y-cambiar) y las altas atómicas `add_if_none_in_progress` y
  `add_proposal_if_none` (D6): cierra la deuda de atomicidad del Paso 2.
- **Coste.** Más recursos, más rutas y más estado que mantener (y los datasets derivados duplican matrices en
  memoria hasta que exista almacenamiento externo). A cambio, cada paso se prueba, mide y reintenta aislado. El
  reparto de réplicas en procesos crea un pool por llamada (spawn caro): deuda de rendimiento.
- **Equipo.** Cada paso tiene su tipo de trabajo (`JobKind`) y su carril; añadir una carta nueva implica sus
  propios pasos por puerto y adaptador (nota del ADR 0004), sin tocar los de T²MRCD.

## Alternativas descartadas

- **API monolítica (`POST …/models` que hace todo).** Es la forma original del ADR 0005. Se descarta: oculta
  fallos intermedios, no permite reutilizar un ajuste ni repetir una calibración, y obliga a depurar un cómputo
  de minutos completo para cualquier cambio.
- **«MRCD puro» con `alpha = 0.5` como API aparte.** Descartado por el dueño (P1): duplicaría el estimador con
  un default que T²MRCD no usa (alpha 0.75, ADR 0007), abriría la puerta a confundir dos métodos y rompe la
  regla de que el único MRCD es el de `rrcov` con sus parámetros (ADR 0002). El ajuste suelto es el mismo MRCD
  con `alpha` configurable.
- **Pasos con datos en el cuerpo en lugar de referencias.** Más simple para el cliente, pero impide el linaje
  (de él sale la semilla) y reenvía matrices grandes en cada llamada.
- **Un hilo/proceso común para todo.** Un bootstrap de minutos retrasaría puntuaciones de segundos; ver carriles.
