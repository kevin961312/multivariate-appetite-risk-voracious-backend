# ADR 0007 — Límites de control de T²MRCD por bootstrap

- **Estado:** Aceptado. Enmendado el 2026-10-07 (mismo día, antes del primer commit): P2, P3, P4 y P6 cerradas y parte *out-of-bag* anulada (ver «Historial»). **Enmendado de nuevo el 2026-10-07 (Paso 2b): los puntos 3 y 4 de la decisión y la fila OOB de las alternativas quedan superseridos por la «Enmienda 2026-10-07 (Paso 2b)»**
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

## Enmienda 2026-10-07 (Paso 2b): dos límites, agregación pool y límite operativo por régimen

Decisión del dueño. Sustituye los puntos 3 y 4 de la «Decisión» y la fila «Límite de Fase II con las filas
*out-of-bag*» de las alternativas (el texto anterior se conserva como historial). Ciclo de vida completo en el
[ADR 0008](0008-ciclo-de-vida-de-la-carta.md).

- **Vuelve el límite de Fase II por OOB.** En cada réplica: muestra con reemplazo de tamaño `h` de las filas
  limpias, reajuste de MRCD sobre la muestra y T² de las filas que no entraron (OOB) con ese ajuste. Es
  remuestreo no paramétrico: no se asume normalidad (MRCD es robusto y la distribución del T² es desconocida).
  Por qué se revierte la anulación: el límite de Fase I (T² de la propia muestra) está sesgado a la baja para
  observaciones nuevas, que es lo que puntúa la Fase II; las OOB sí imitan datos no vistos por el ajuste.
- **Dos límites por modelo:** `phase1_limit` (T² de las muestras) y `phase2_limit` (T² de las OOB). Ambos salen de
  las **mismas réplicas**, así que no cuesta ningún ajuste adicional.
- **Agregación pool (Q1, sustituye P4 opción b).** En cada fase se juntan los T² de **todas** las réplicas y se
  toma un único cuantil 1−α, tipo 7. Motivo: con m valores por réplica y m·α < 1 el cuantil por réplica queda
  acotado por el máximo de esa réplica y el promedio de cuantiles tiene un α efectivo mayor que el pedido:
  ≈ 0.018 en Fase I con m = 75 (n = 100, h = 75) y ≈ 0.035 en Fase II con m ≈ 28, frente a 0.005. Con el pool el
  cuantil se calcula sobre B·m valores y el α pedido sí es alcanzable.
- **Parámetros:** `alpha_limit` (Fase I) y `phase2_alpha_limit` (Fase II), ambos default 0.005, configurables.
- **Límite operativo por régimen (Q2).** La versión v0 vigila con el límite de Fase I, provisional y fijo (no hay
  datos propios de Fase II). Las versiones recalibradas vigilan con el límite de Fase II. Una observación se
  puntúa con el límite de la versión vigente en su fecha y se guarda cuál usó.
- **Señal:** sigue siendo `t2 > límite`, estricta.
- **Diagnóstico, no invariante (Q9):** que el límite de Fase II resulte mayor que el de Fase I se informa, pero
  no se exige.
- **Prueba de calidad de la tubería:** con estimador clásico y un muestreador de muestras independientes (normal,
  solo en `tests/`) los límites simulados coinciden con Beta (Fase I) y F (Fase II) para n > p. No valida el
  bootstrap OOB: con el clásico, el OOB da una Fase II ≈ +16 % sobre la F (efecto .632, ≈ 63 % de filas
  distintas por réplica), conservador.
- **Remuestreo solo sobre `best` (dueño, 2026-10-07):** para ambos límites. Con todas las filas, una contaminación
  no detectada inflaría el límite (enmascaramiento); `best` es la mejor estimación. Consecuencia medida (n = 200,
  p = 3, normal limpia, B = 50): falsa alarma real ≈ 2.0–2.4 % en Fase I y ≈ 1.6–2.2 % en Fase II frente al 0.5 %
  nominal (≈ 0.4 % con todas las filas), pues `best` es el 75 % central y las nuevas incluyen las colas; la
  depuración automática puede quitar 1–10 filas buenas. Es una característica del diseño. Estudio futuro:
  reponderado tipo MCD.
- **Semillas por huecos fijos** (`seeds.py`), no `spawn(B)`: cambiar B, rondas o remuestreos de una prueba no
  desplaza las demás semillas. Esto sustituye lo escrito en «Detalles de implementación» sobre `spawn(B)`.
- **M6:** el reporte incluye el error Monte Carlo del límite.
- **Persistencia:** `BootstrapLimits` deja de ser un único `limit`; guarda `phase1_limit`, `phase2_limit` y su
  procedencia. El modelo añade `limit_regime` y `operative_limit`. Implementado en el dominio (2b.1).

Pendiente (heredado): cita bibliográfica del bootstrap OOB y de `alpha_limit = 0.005`; regla de cuantil tipo 7.
- **2026-10-07 (Paso 2b):** vuelve el límite de Fase II por OOB, agregación pool en ambas fases y límite operativo por régimen (ver enmienda arriba).

## Enmienda 2026-10-07 (Paso 2b.2): alternativa evaluada y descartada

**Alternativa evaluada y descartada: bootstrap de los *valores* de T² de `best` (propuesta del dueño, 2026-10-07).**
Calcular μ₀ y S₀ una vez con el histórico, obtener los T² de las `h` filas de `best` (p. ej. 75), remuestrear
esos valores 100 veces con reemplazo, tomar el cuantil 0.995 de cada remuestreo y promediar. Tiene la ventaja de
costar un solo ajuste MRCD. **Se evaluó por simulación** (datos normales limpios, `pymrcd`, 20 000 observaciones
nuevas en control para medir la falsa alarma real; script `metodo_dueno.py`, fuera del repositorio):

| Caso | Resultado |
| --- | --- |
| n = 200, p = 10 (3 conjuntos de datos) | límite ≈ máximo de los T² de `best` (11.9–13.0); 74 % del histórico queda por debajo; falsa alarma con observaciones nuevas **34–37 %** |
| n = 100, p = 250 | falsa alarma con observaciones nuevas **100 %** |

**Por qué falla.** MRCD elige `best` como las `h` filas de menor T² (verificado: los T² de `best` son exactamente
los `h` menores del histórico). Un remuestreo de *valores* no puede superar el máximo de la muestra, así que el
cuantil 0.995 de cada remuestreo cae cerca de ese máximo y el límite queda en el percentil ≈ 75 de los T² del
histórico. Con p > n, además, las observaciones nuevas no participaron en S₀ y su T² es mucho mayor que el de las
filas con las que se ajustó. Y al fijar μ₀ y S₀ **ignora el error de estimación de μ y S**, justo lo que se
quiere capturar. Remuestrear *filas* y reajustar MRCD en cada réplica propaga ese error.

**Decisión del dueño (2026-10-07), opción (a): mantener lo implementado** (remuestrear filas de `best` y reajustar
MRCD en cada réplica). El coste de minutos (ver «Consecuencias») se acepta; se atacará con M5 (optimizar
`pymrcd`), no cambiando el método.
