# Método: T²MRCD (carta de control)

Tipo: **carta** (`domain/charts/t2mrcd/`). Es la carta por defecto del producto y usa el estimador
[MRCD](mrcd.md). Ver [ADR 0004](../adr/0004-cartas-y-estimadores-extensibles.md),
[ADR 0005](../adr/0005-api-fase-i-fase-ii.md) y [ADR 0007](../adr/0007-limites-t2mrcd-por-bootstrap.md). Sin
cita no hay default ([CLAUDE.md](../../CLAUDE.md), regla dura 3).

Estado: el dominio (Paso 2) existe y **con los defaults decididos la Fase I se ejecuta completa** (P2, P3, P4,
P5 y P6 cerradas el 2026-10-07). El mecanismo `failed / T2MRCD_DECISION_PENDING` se conserva: si alguien pasa
explícitamente un campo decisivo como `None`, la Fase I se detiene antes de ajustar nada. La API HTTP es del Paso 3.

- **Estimador declarado:** MRCD, siempre. Sin *fallbacks* ni «modos rápidos» (ADR 0004, punto 5): si MRCD
  falla, la Fase I termina en `failed / MRCD_FIT_FAILED`.
- **Artículo de referencia:** «Artículo T²MRCD del dueño (en proceso de publicación)» (P6). No bloquea; la
  cita final (autores, año, revista) se incorpora cuando se publique (**deuda**).

## Estadística

| Elemento | Definición | Fuente | Estado |
| --- | --- | --- | --- |
| Estadística T² por observación | Distancia de Mahalanobis al cuadrado respecto a la ubicación y dispersión MRCD, calculada con `pymrcd.mahalanobis` (la rutina de `CovMrcd.R:46`, `rrcov` 1.7-7) | Artículo T²MRCD del dueño (en proceso de publicación; sección/ecuación por citar al publicarse) | cálculo coincide bit a bit con `mah` de `CovMrcd`; cita final pendiente |

## Decisiones P1–P6 (dueño, 2026-10-07)

Los identificadores son los que citan `params.py`, `chart.py`, `bootstrap.py` y `model.py`.

| Id | Decisión | Dónde vive en el código | Estado |
| --- | --- | --- | --- |
| P1 | MRCD se ajusta con `pymrcd`. Si un campo decisivo se pasa como `None`, la Fase I termina en `failed / T2MRCD_DECISION_PENDING` con `details.pending`, comprobado **antes** de ajustar. Valores «SOLO TEST» solo en `tests/support/` | `chart.py` (`fit_phase1`) | decidido |
| P2 | Filas limpias = subconjunto `best` del ajuste MRCD del histórico con `alpha = 0.75` (default **de la carta**; `MRCDParams` conserva el 0.5 de `rrcov`). `h = ceiling(0.75·n)` (`rrcov` `detmrcd.R:397`): n = 100 → 75, n = 41 → 31 | `bootstrap.clean_criterion` (`best_subset_criterion`), `T2MRCD_MRCD_ALPHA` | **cerrada** |
| P3 | B = `n_replicates` configurable, **100 por defecto**. Cita: Q. Heng, H. Shen y K. Lange (2026), «A stability framework for parameter selection in the minimum covariance determinant problem», *Journal of Computational and Graphical Statistics*, 35(1):27–39, doi:10.1080/10618600.2025.2495780 | `bootstrap.n_replicates` (`DEFAULT_N_REPLICATES`) | **cerrada**, con cita |
| P4 | `alpha_limit` es parámetro, default **0.005** (proporción, no porcentaje) → cuantil de probabilidad **0.995**. Agregación: **promedio de los cuantiles por réplica** (opción b del dueño). Regla de cuantil: tipo 7 (`numpy method="linear"` = default de `stats::quantile` de R), **elección técnica reversible no fijada por el dueño** | `bootstrap.alpha_limit` (`DEFAULT_ALPHA_LIMIT`), `bootstrap.aggregation` (`mean_of_replicate_quantiles`, `QUANTILE_METHOD`) | **cerrada** (regla de cuantil: ver «Decisiones abiertas») |
| P5 | Remuestreo con reemplazo de tamaño `h` (las filas limpias); en cada réplica se reajusta MRCD y se toma el cuantil de los T² de **la muestra**. **Un único límite** (`BootstrapLimits.limit`) para Fase I (atípico histórico: `T² > límite`) y Fase II (señal: `T² > límite`, estricta). No hay parte *out-of-bag* | `bootstrap.py` (`run_replicate`, `calibrate_limits`), `chart.py` | **cerrada** |
| P6 | `statistic_reference` = «Artículo T²MRCD del dueño (en proceso de publicación)» | `T2MRCDChart.statistic_reference` (`STATISTIC_REFERENCE`) | **cerrada**; cita final al publicarse (deuda) |

`alpha` de MRCD (0.75, tamaño del subconjunto `h`) y `alpha_limit` (0.005, nivel del límite) son **parámetros
distintos** y no deben confundirse.

### Campo ↔ default ↔ fuente

| Campo | Default | Fuente |
| --- | --- | --- |
| `params.mrcd.alpha` | 0.75 (la carta) | Decisión del dueño 2026-10-07 (P2); el default de `MRCDParams` sigue siendo 0.5 (`rrcov` 1.7-7, ver [`mrcd.md`](mrcd.md)) |
| `h` | `ceiling(0.75·n)` | `rrcov` `detmrcd.R:397` |
| `params.bootstrap.n_replicates` | 100 | Heng, Shen y Lange (2026), doi:10.1080/10618600.2025.2495780 (P3) |
| `params.bootstrap.alpha_limit` | 0.005 (cuantil 0.995) | Decisión del dueño 2026-10-07 (P4); sin cita bibliográfica |
| `params.bootstrap.aggregation` | promedio de cuantiles por réplica | Decisión del dueño 2026-10-07 (P4, opción b) |
| regla de cuantil | tipo 7 (`method="linear"`) | `stats::quantile` de R (default); elección técnica reversible |
| `params.bootstrap.clean_criterion` | subconjunto `best` de MRCD | Decisión del dueño 2026-10-07 (P2) |
| `T2MRCDChart.statistic_reference` | «Artículo T²MRCD del dueño (en proceso de publicación)» | Decisión del dueño 2026-10-07 (P6) |

### Mecanismo `details.pending`

Con los defaults no queda nada pendiente. Si `bootstrap.aggregation` se pasa explícitamente como `None`, la
Fase I termina en `failed / T2MRCD_DECISION_PENDING` y `details.pending` contiene `bootstrap.aggregation`
(comprobado antes de ajustar). El mecanismo existe para que una decisión futura sin cerrar nunca se rellene con
un valor inventado.

## Límites de control: bootstrap

Ningún estimador da un límite de control, el artículo de T²MRCD solo trata la Fase I y no hay artículo de
Fase II. Como en producción hay **un solo histórico** por cliente (p. ej. 200 × 300), los límites de ambas
fases se calibran por bootstrap sobre las filas limpias. El porqué completo y las alternativas descartadas
están en el [ADR 0007](../adr/0007-limites-t2mrcd-por-bootstrap.md).

- **Semillas:** `SeedSequence(seed).spawn(B)`; el resultado no depende del número de procesos.
- **Réplica fallida = Fase I fallida** (`BOOTSTRAP_REPLICATE_FAILED`): no se descartan réplicas.
- **Reparto:** por `TaskMapper` (dominio) con el contexto enviado una vez; el adaptador con procesos es del Paso 3.
- **Un solo límite.** Cada réplica remuestrea **con reemplazo `h` filas** (las limpias), reajusta MRCD y calcula
  el T² de esa muestra. De cada réplica sale su cuantil de probabilidad 1 − `alpha_limit` (0.995 por defecto) y
  el límite es el promedio de los B cuantiles. Ese mismo valor (`BootstrapLimits.limit`) marca los atípicos
  históricos en Fase I y las señales en Fase II. No hay parte *out-of-bag* ni límite aparte de Fase II: el
  dueño la anuló el 2026-10-07 (ver ADR 0007, historial).
- B = 100 cita a Heng, Shen y Lange (2026) (P3). El bootstrap de límites T² como tal **sigue sin cita
  bibliográfica** (decisión del dueño, no de un artículo): ver «Decisiones abiertas».

**Ejemplo (n = 100, p = 250).** `h = ceiling(0.75·100) = 75`: MRCD (alpha 0.75) deja 75 filas limpias. Cada una
de las B = 100 réplicas remuestrea 75 filas con reemplazo, ajusta MRCD (con p > n, rho por número de condición,
ver [`mrcd.md`](mrcd.md)) y toma el cuantil 0.995 de sus 75 T². El límite es la media de esos 100 cuantiles.
Con n = 41, `h = 31`.

Medida (2026-10-07, Mac de desarrollo, 8 núcleos, `pymrcd` sin optimizar): un ajuste 200×300 ≈ 47 s y una
réplica de 150×300 ≈ 27 s; B = 100 son ≈ 45 min en serie y ≈ 6–8 min en 8 núcleos.

## Fase I (ajuste y límites)

Orden de `fit_phase1`, y por qué:

1. **Validar la entrada** (`INVALID_INPUT`): matriz no vacía y **sin valores no finitos**. `rrcov` descarta en
   silencio las filas no finitas (`CovMrcd.R:19-20`); la carta necesita un T² por cada observación histórica y
   por eso las **rechaza** en lugar de descartarlas.
2. **Comprobar pendientes** (solo si un campo se pasó como `None`; `T2MRCD_DECISION_PENDING`) **antes** de gastar minutos de cómputo.
3. **Ajustar MRCD** al histórico (`MRCD_FIT_FAILED` si `pymrcd` falla). Si alguna fila finita queda fuera del
   ajuste porque su suma por fila desborda (`rrcov` también la descarta, `CovMrcd.R:19-20`), se rechaza con
   `INVALID_INPUT` y `details.rows` (máx. 20), por la misma razón que en el punto 1.
4. **Aplicar el criterio de fila limpia** (P2: subconjunto `best` de MRCD con alpha 0.75). Debe devolver una máscara booleana de longitud n
   (`T2MRCD_CLEAN_CRITERION_INVALID`) con al menos una fila `True` (`T2MRCD_NO_CLEAN_OBSERVATIONS`).
5. **Calibrar los límites** por bootstrap (`BOOTSTRAP_REPLICATE_FAILED`, `BOOTSTRAP_LIMIT_NOT_FINITE`).
6. **Puntuar el histórico** y marcar las atípicas.

`n_replicates` y `seed` solo admiten **enteros** (`bool` y `float` se rechazan, `n_replicates >= 1`,
`seed >= 0`): una cuenta de réplicas o una semilla ambiguas (`True`, `100.0`) no deben interpretarse en
silencio porque cambiarían el resultado sin dejar rastro. `alpha_limit`, si se da, debe estar en (0, 1).

### Contenido del modelo (`T2MRCDModel`)

| Campo | Contenido |
| --- | --- |
| `params`, `n_features` | Parámetros y `p` con los que se ajustó |
| `mrcd` | Ajuste MRCD del histórico completo (ver [`mrcd.md`](mrcd.md)) |
| `clean_mask` | Filas limpias del histórico (las remuestreadas; `h` filas) |
| `limits` | `limit` (único, común a Fase I y II) y su procedencia: `n_clean`, `seed`, `n_replicates` (B), `alpha_limit` |
| `historical_t2` | T² de cada observación histórica |
| `historical_outlier` | `historical_t2 > limits.limit` (**estricto**) |
| `pymrcd_version` | Versión de `pymrcd` del ajuste, para auditar reproducibilidad |
| `seed`, `statistic_reference` | Semilla raíz y cita de la estadística (P6) con las que se ajustó |

## Fase II (puntuación y señales)

- Entrada: observaciones nuevas contra un modelo de Fase I en `succeeded`. Se valida de forma síncrona
  (`validate_phase2_input`: no vacía, finita, mismo `p`) antes de encolar.
- Salida: T² por observación, señal `t2 > límite` (estricta, P5; el mismo límite de Fase I) y el límite usado. No se
  recalcula nada: el límite sale del modelo. Recalibrarlo con datos de Fase II es una funcionalidad **futura**
  (ver «Recalibración a petición»).

## Recalibración a petición (objetivo, no implementado)

Fase II usa durante un tiempo el límite de Fase I. Cuando el dueño lo solicite, se recalcularían los límites con
el **mismo procedimiento de Fase I** sobre los datos acumulados en Fase II. Va al Paso 3 o a una tarea propia.
Decisiones abiertas: (1) qué datos, solo Fase II o histórico + Fase II; (2) si entran las observaciones con
señal (**recomendación: todas**, porque MRCD con alpha 0.75 ya separa las atípicas); (3) si el resultado es un
modelo nuevo enlazado al anterior (**recomendado**, conserva la trazabilidad de las señales ya emitidas) o una
versión del mismo modelo.

## Tests golden

Referencia de la carta (distinta de la del estimador). Los tests del Paso 2 usan implementaciones «SOLO TEST»
«SOLO TEST» en `tests/support/` (no son referencia estadística); los defaults de producción ya no dependen de ellos.

| Caso | n | p | Contaminación | Semilla | Tolerancia | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| Fase I: límites | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ | pendiente (Paso 5; falta la fuente de referencia) |
| Fase II: T² y señales | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ | pendiente (Paso 5) |

## Decisiones abiertas

- **Regla de cuantil** (P4): hoy tipo 7 (`method="linear"`); elección técnica reversible, no fijada por el dueño
  ni por un artículo. Confirmar o cambiar.
- **Cita final del artículo T²MRCD** (P6): autores, año, revista y sección/ecuación de la estadística, cuando
  se publique (deuda de la regla dura 3).
- Cita bibliográfica del bootstrap de límites T² y del valor `alpha_limit = 0.005` (hoy decisiones del dueño).
- **Recalibración a petición**: datos, inclusión de señales y modelo nuevo frente a versión (arriba).
- Fuente de referencia de los golden de la carta (¿código R existente o cálculo propio verificado contra el artículo?).

**Cerradas el 2026-10-07:** P2, P3 (con cita), P4 (valor y agregación), P5 (límite único) y P6 (referencia provisional).
