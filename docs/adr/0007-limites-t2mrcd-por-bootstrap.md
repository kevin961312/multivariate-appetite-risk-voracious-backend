# ADR 0007 — Límites de control de T²MRCD por bootstrap

- **Estado:** Aceptado. Enmendado el 2026-10-07 (mismo día, antes del primer commit): P2, P3, P4 y P6 cerradas y parte *out-of-bag* anulada (ver «Historial»)
- **Fecha:** 2026-10-07
- **Relacionado:** [ADR 0004](0004-cartas-y-estimadores-extensibles.md) (contrato de carta),
  [ADR 0005](0005-api-fase-i-fase-ii.md) (códigos de error), [`../metodos/t2mrcd.md`](../metodos/t2mrcd.md).

## Contexto

- Ningún estimador (MRCD incluido) entrega un límite de control, y no hay artículo de Fase II que lo defina.
  El artículo de T²MRCD (en proceso de publicación) trata solo la Fase I; se cita de forma provisional (P6).
- En producción cada cliente aporta **un solo conjunto histórico** (p. ej. 200 observaciones × 300 variables):
  no hay una segunda muestra con la que calibrar la Fase II.
- No hay una distribución teórica citada para el T² de MRCD con p > n (ver P6); adoptar una sin fuente violaría la regla dura 3.

## Decisión (dueño, 2026-10-07)

Los límites de Fase I **y** de Fase II se calibran por **bootstrap sobre las filas limpias** del histórico:

1. Se ajusta MRCD al histórico completo con `alpha = 0.75` (default de la carta; `MRCDParams` conserva el 0.5 de
   `rrcov`). Las filas limpias son el subconjunto `best`: `h = ceiling(0.75·n)` (`rrcov` `detmrcd.R:397`), p. ej.
   n = 100 → 75 y n = 41 → 31 (P2).
2. Cada una de B réplicas remuestrea **con reemplazo `h` filas** de las limpias, reajusta MRCD sobre la muestra
   y calcula el T² de **esa muestra** (P5).
3. De cada réplica se toma el cuantil de probabilidad 1 − `alpha_limit` (`alpha_limit = 0.005` → 0.995;
   proporciones, no porcentajes) y el límite es el **promedio de los B cuantiles** (P4, opción b del dueño). La
   regla de cuantil es la de tipo 7 (`numpy method="linear"`, default de `stats::quantile`): elección técnica
   reversible, no fijada por el dueño. `alpha_limit` y el `alpha` de MRCD son parámetros distintos.
4. Hay **un único límite** (`BootstrapLimits.limit`): en Fase I marca los atípicos históricos (`T² > límite`) y
   en Fase II las señales (`T² > límite`, estricto).
5. B = `n_replicates` configurable, **100 por defecto**, citado: Qiang Heng, Hui Shen y Kenneth Lange (2026),
   «A stability framework for parameter selection in the minimum covariance determinant problem», *Journal of
   Computational and Graphical Statistics*, 35(1):27–39, doi:10.1080/10618600.2025.2495780 (P3).
6. `statistic_reference` = «Artículo T²MRCD del dueño (en proceso de publicación)» (P6); no bloquea.

Detalles de implementación que se deciden aquí por su efecto en la reproducibilidad y la robustez:

- **Semillas:** `SeedSequence(seed).spawn(B)`, una por réplica. Así el resultado no depende del orden de
  ejecución ni del número de procesos; `seed` es obligatoria y entera.
- **Una réplica fallida hace fallar la Fase I** (`BOOTSTRAP_REPLICATE_FAILED`, con la de menor índice). Descartar
  réplicas «que no convergen» sesgaría el límite en silencio: sería un *fallback* (ADR 0004, punto 5).
- **Los límites se guardan con el modelo** (`n_clean`, `seed`, B, `alpha_limit`). La Fase II no recalcula nada.
- **Reparto vía `TaskMapper`:** el dominio solo describe la tarea (`run_replicate(context, task)`); quién la
  ejecuta (serie, procesos, Celery) es un adaptador de `infrastructure`. El contexto (`x_clean`, parámetros) se
  entrega **una vez** y cada tarea lleva solo índice y semilla, para no reenviar la matriz B veces.

## Alternativas descartadas

| Alternativa | Por qué no |
| --- | --- |
| Límite analítico (chi-cuadrado, beta, F) | No hay fuente citada para el T² de MRCD con p > n; adoptarlo sin fuente violaría la regla dura 3. |
| Calibrar Fase II con una muestra aparte | El cliente solo tiene un histórico. |
| Límite de Fase II con las filas *out-of-bag* | Anulado por el dueño (2026-10-07): un único límite, más simple de explicar y auditar. |
| Descartar réplicas fallidas | Sesga el límite en silencio (equivale a un fallback). |
| `multiprocessing` dentro del dominio | El dominio no importa procesos ni hilos (contrato `domain` limpio, M1); es un adaptador. |

## Consecuencias

- **Coste de minutos.** Medido el 2026-10-07 (Mac de desarrollo, 8 núcleos, `pymrcd` sin optimizar): un ajuste
  200×300 ≈ 47 s y una réplica de 150×300 ≈ 27 s; B = 100 son ≈ 45 min en serie y ≈ 6–8 min en 8 núcleos. La
  Fase I no cabe en una petición HTTP: debe salir del hilo de la API (Paso 3).
- **Persistencia.** Los criterios y la agregación son *callables* (estrategias) dentro de los parámetros; un
  repositorio real no puede guardar una función, así que habrá que persistirlas **por nombre** y resolverlas
  en un registro (Paso 3).
- **BLAS a 1 hilo.** Con un proceso por núcleo, cada proceso debe usar BLAS de 1 hilo o se sobresuscribe la CPU.
  Hay que probar que los límites no cambian por ello (Paso 3).
- **Optimización de `pymrcd` (M6)** antes de producción: se optimiza la implementación, nunca el método (ADR 0002).

## Pendientes

- **Cita final del artículo T²MRCD** (P6) cuando se publique (deuda de la regla dura 3).
- **Regla de cuantil** tipo 7: confirmar o cambiar (elección técnica reversible).
- Cita del bootstrap de límites T² y de `alpha_limit = 0.005` (hoy decisiones del dueño).
- **Recalibración a petición** (futuro, no implementada): recalcular los límites con el procedimiento de Fase I y
  los datos acumulados en Fase II. Abiertas: qué datos (solo Fase II o histórico + Fase II), si se incluyen las
  observaciones con señal (recomendado: todas) y si se crea un modelo nuevo enlazado (recomendado) o una versión.
  Detalle en [`../metodos/t2mrcd.md`](../metodos/t2mrcd.md).
- Con los defaults ya no hay decisiones pendientes y la Fase I se ejecuta completa. El mecanismo
  `failed / T2MRCD_DECISION_PENDING` se mantiene si un campo se pasa explícitamente como `None`.

## Historial

- **2026-10-07 (versión inicial):** forma decidida; P2, P4, P6 y la cita de B pendientes; Fase II calibrada con
  las filas limpias *out-of-bag* y remuestreo de tamaño `n_clean`.
- **2026-10-07 (enmienda, mismo día):** el dueño cierra P2 (alpha 0.75), P3 (cita), P4 (0.005, promedio de
  cuantiles) y P6; el remuestreo pasa a tamaño `h`; se **anula la parte *out-of-bag***: un único límite para
  ambas fases.
