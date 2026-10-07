# Método: T²MRCD (carta de control)

Tipo: **carta** (`domain/charts/t2mrcd/`). Es la carta por defecto del producto y usa el estimador
[MRCD](mrcd.md). Ver [ADR 0004](../adr/0004-cartas-y-estimadores-extensibles.md),
[ADR 0005](../adr/0005-api-fase-i-fase-ii.md) y [ADR 0007](../adr/0007-limites-t2mrcd-por-bootstrap.md) (con su enmienda del Paso 2b) y
[ADR 0008](../adr/0008-ciclo-de-vida-de-la-carta.md). Sin
cita no hay default ([CLAUDE.md](../../CLAUDE.md), regla dura 3).

Estado: el dominio (Paso 2) existe y **con los defaults decididos la Fase I se ejecuta completa** (P2, P3, P4,
P5 y P6 cerradas el 2026-10-07). El mecanismo `failed / T2MRCD_DECISION_PENDING` se conserva: si alguien pasa
explícitamente un campo decisivo como `None`, la Fase I se detiene antes de ajustar nada. La API HTTP es del Paso 3.
**Paso 2b.1 (dominio, implementado el 2026-10-07; pendiente de commit):** dos límites (Fase I y Fase II por OOB),
agregación pool, depuración automática, comparación y recalibración como funciones del dominio. **Paso 2b.2
(aplicación: versiones persistidas, registro de observaciones, anotaciones, aprobación) es objetivo**, no código
existente.

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
| P4 | `alpha_limit` es parámetro, default **0.005** (proporción, no porcentaje) → cuantil de probabilidad **0.995**. **Agregación (actualizada 2026-10-07, Paso 2b, Q1: pool)**: se juntan los T² de todas las réplicas y se toma un único cuantil 1−α. Sustituye al «promedio de cuantiles por réplica» (la «opción b» original de P4; no confundir con la etiqueta «Q1») porque con m valores por réplica y m·α < 1 el cuantil queda acotado por el máximo y el α efectivo sube (≈ 0.018 en Fase I con m = 75, ≈ 0.035 en Fase II con m ≈ 28, frente a 0.005). Regla de cuantil: tipo 7 (`numpy method="linear"` = default de `stats::quantile` de R), **elección técnica reversible no fijada por el dueño** | `bootstrap.alpha_limit` (`DEFAULT_ALPHA_LIMIT`), `bootstrap.aggregation` y `bootstrap.phase2_aggregation` (`pooled_quantile`; `mean_of_replicate_quantiles` fue eliminada), `QUANTILE_METHOD` | **cerrada** (regla de cuantil: ver «Decisiones abiertas») |
| P5 | Remuestreo con reemplazo de tamaño `h` (las filas limpias); en cada réplica se reajusta MRCD. **Actualizada en 2b:** dos límites. Fase I: T² de la muestra (atípico histórico: `T² > límite`). Fase II: T² de las filas **OOB** con ese ajuste (señal: `T² > límite`, estricta). Revierte la anulación OOB del 2026-10-07 anterior (ADR 0007, enmienda) | `bootstrap.py` (`run_replicate`, `calibrate_limits`), `chart.py` | **cerrada**; implementada en 2b.1 |
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
| `params.bootstrap.aggregation` | pool de los T² de todas las réplicas, un cuantil 1−α | Decisión del dueño 2026-10-07 (Paso 2b, Q1: pool); sustituye al promedio de cuantiles (ver motivo en P4) |
| `params.bootstrap.phase2_alpha_limit` | 0.005 | Decisión del dueño 2026-10-07; sin cita bibliográfica |
| regla de cuantil | tipo 7 (`method="linear"`) | `stats::quantile` de R (default); elección técnica reversible |
| `params.bootstrap.clean_criterion` | subconjunto `best` de MRCD | Decisión del dueño 2026-10-07 (P2) |
| `T2MRCDChart.statistic_reference` | «Artículo T²MRCD del dueño (en proceso de publicación)» | Decisión del dueño 2026-10-07 (P6) |

### Mecanismo `details.pending`

Con los defaults la Fase I no tiene nada pendiente. Si `bootstrap.aggregation` o `bootstrap.phase2_aggregation`
se pasan explícitamente como `None`, la Fase I termina en `failed / T2MRCD_DECISION_PENDING` y
`details.pending` los lista (comprobado antes de ajustar). La **recalibración** sí tiene pendientes con los
defaults: `recalibration.covariance_test`, `recalibration.mean_test` y `recalibration.n_test_resamples` (las
pruebas formales de cambio no tienen cita; ver más abajo). Con alguno en `None` la recalibración responde
`T2MRCD_DECISION_PENDING` salvo `force_replace`, y también se comprueba antes de ajustar. El mecanismo existe
para que una decisión futura sin cerrar nunca se rellene con un valor inventado.

## Límites de control: bootstrap

Ningún estimador da un límite de control, el artículo de T²MRCD solo trata la Fase I y no hay artículo de
Fase II. Como en producción hay **un solo histórico** por cliente (p. ej. 200 × 300), los límites de ambas
fases se calibran por bootstrap sobre las filas limpias. El porqué completo y las alternativas descartadas
están en el [ADR 0007](../adr/0007-limites-t2mrcd-por-bootstrap.md).

- **Semillas:** huecos fijos de `seeds.py` (`SeedSequence(seed, spawn_key=…)`), **no** `spawn(B)`. Cada uso
  aleatorio tiene su hueco: `(0, r)` calibración de la ronda `r` de la Fase I (y, con `r = 0`, la Fase I final de
  EXTEND); `(1, r)` calibración de la ronda `r` de la depuración de las filas nuevas al recalibrar; `(2,)` prueba
  de S; `(3,)` prueba de μ. Dentro de una calibración con clave `k`: `k+(0,i)` es la réplica `i` y `k+(1,0)`,
  `k+(1,1)` los diagnósticos del error Monte Carlo. Por qué: con `spawn(B)` cambiar B, las rondas o los
  remuestreos de una prueba desplazaría las semillas de los demás usos; con huecos fijos no. En REPLACE el
  modelo **reutiliza** la calibración de la última ronda de depuración de las filas nuevas (misma base, mismo
  orden, mismos parámetros y semilla), así que sus límites conservan el hueco `(1, r)` en lugar de repetir las B
  réplicas. El resultado no depende del número de procesos.
- **Réplica fallida = Fase I fallida** (`BOOTSTRAP_REPLICATE_FAILED`): no se descartan réplicas.
- **Reparto:** por `TaskMapper` (dominio) con el contexto enviado una vez; el adaptador con procesos es del Paso 3.
- **Dos límites, mismas réplicas (2b).** Cada réplica remuestrea **con reemplazo `h` filas** (las limpias) y
  reajusta MRCD. Límite de **Fase I**: T² de las filas de la muestra. Límite de **Fase II**: T² de las filas
  que no entraron (OOB) con ese ajuste: imitan observaciones nuevas. Cada límite es el cuantil 1−`alpha_limit`
  (1−`phase2_alpha_limit` en Fase II; 0.995 por defecto) del **pool** de T² de todas las réplicas, tipo 7. Ver
  ADR 0007, enmienda. Una réplica sin filas OOB falla con `BOOTSTRAP_OOB_EMPTY`.
- **Límite operativo por régimen.** El modelo guarda `phase1_limit` y `phase2_limit`; `operative_limit` depende de
  `limit_regime`: la versión v0 vigila con el de Fase I (provisional y fijo); las recalibradas, con el de Fase II. Que el de Fase II salga mayor que el de Fase I es diagnóstico, no invariante.
- **Control de calidad de la tubería:** con estimador clásico y un muestreador de **muestras independientes**
  (normal, solo en tests, nunca en `src/`), n > p, los límites simulados coinciden con Beta (Fase I) y F
  (Fase II). Eso valida la tubería (cuantil, pool, T²), **no** el bootstrap OOB: con el clásico, el OOB da un
  límite de Fase II ≈ +16 % sobre la F por el efecto .632 (cada réplica usa ≈ 63 % de filas distintas), es decir,
  conservador.
- **Error Monte Carlo (M6):** el reporte lo incluye. Se estima remuestreando con reemplazo las B réplicas
  `MC_ERROR_RESAMPLES = 200` veces (constante técnica, `aggregation.py`; no estadística). Con **B = 1 no está
  disponible** (`None`): no hay variabilidad entre réplicas que medir.
- B = 100 cita a Heng, Shen y Lange (2026) (P3). El bootstrap de límites T² como tal **sigue sin cita
  bibliográfica** (decisión del dueño, no de un artículo): ver «Decisiones abiertas».

### Remuestreo solo sobre `best` (decisión del dueño, 2026-10-07)

Ambos límites se calibran remuestreando únicamente las filas `best` (alpha 0.75), no todas las filas. **Por qué:**
con todas las filas, una contaminación no detectada entraría en el remuestreo e inflaría el límite
(enmascaramiento); `best` es la mejor estimación de la parte limpia. **Consecuencia conocida, medida por el
validador** (n = 200, p = 3, normal limpia, B = 50): la falsa alarma real frente a observaciones nuevas en
control es ≈ 2.0–2.4 % en Fase I y ≈ 1.6–2.2 % en Fase II frente al 0.5 % nominal (con todas las filas, ≈ 0.4 %),
porque `best` es el 75 % central y las nuevas incluyen las colas. Del mismo modo, la depuración automática con ese
límite puede quitar entre 1 y 10 filas buenas. Es una **característica del diseño**, no un error. **Estudio
futuro posible:** reponderado tipo MCD (añadir a `best` las observaciones con distancia robusta no extrema).

**Ejemplo (n = 100, p = 250).** `h = ceiling(0.75·100) = 75`: MRCD (alpha 0.75) deja 75 filas limpias. Cada una
de las B = 100 réplicas remuestrea 75 filas con reemplazo y ajusta MRCD (con p > n, rho por número de condición,
ver [`mrcd.md`](mrcd.md)). El límite de Fase I es el cuantil 0.995 del pool de B·75 = 7500 T²; el de Fase II,
el de los T² OOB (en promedio ≈ 28 filas por réplica, unas 2800 en total). Con n = 41, `h = 31`.

Medida (2026-10-07, Mac de desarrollo, 8 núcleos, `pymrcd` sin optimizar): un ajuste 200×300 ≈ 47 s y una
réplica de 150×300 ≈ 27 s; B = 100 son ≈ 45 min en serie y ≈ 6–8 min en 8 núcleos.

## Fase I (ajuste y límites)

Orden de `fit_phase1` (dominio 2b.1), y por qué:

1. **Validar la entrada** (`INVALID_INPUT`): matriz no vacía y **sin valores no finitos**. `rrcov` descarta en
   silencio las filas no finitas (`CovMrcd.R:19-20`); la carta necesita un T² por cada observación histórica y
   por eso las **rechaza** en lugar de descartarlas.
2. **Comprobar pendientes** (solo si un campo se pasó como `None`; `T2MRCD_DECISION_PENDING`) **antes** de gastar minutos de cómputo.
3. **Exclusión humana:** las filas con causa asignable confirmada (`assignable_cause`) se quitan primero; una
   persona sabe lo que un umbral no.
4. **Depuración automática** (hasta `max_depuration_rounds`, 5): en cada ronda, ajuste MRCD, filas limpias,
   límites bootstrap, y se quitan las filas con `T² > límite de Fase I`; se repite hasta converger. Si se agotan
   las rondas, `depuration_converged = False`.
5. **Ajustar MRCD** a la base final (`MRCD_FIT_FAILED` si `pymrcd` falla). Si alguna fila finita queda fuera del
   ajuste porque su suma por fila desborda (`rrcov` también la descarta, `CovMrcd.R:19-20`), se rechaza con
   `INVALID_INPUT` y `details.rows` (máx. 20), por la misma razón que en el punto 1.
6. **Aplicar el criterio de fila limpia** (P2: subconjunto `best` de MRCD con alpha 0.75). Debe devolver una máscara booleana de longitud n
   (`T2MRCD_CLEAN_CRITERION_INVALID`) con al menos una fila `True` (`T2MRCD_NO_CLEAN_OBSERVATIONS`).
7. **Calibrar los límites** por bootstrap (`BOOTSTRAP_REPLICATE_FAILED`, `BOOTSTRAP_LIMIT_NOT_FINITE`).
8. **Puntuar el histórico** y marcar las atípicas.

Coste: hasta `(1 + max_depuration_rounds)·B` ajustes MRCD en la Fase I de la v0 (cada ronda calibra).

`n_replicates` y `seed` solo admiten **enteros** (`bool` y `float` se rechazan, `n_replicates >= 1`,
`seed >= 0`): una cuenta de réplicas o una semilla ambiguas (`True`, `100.0`) no deben interpretarse en
silencio porque cambiarían el resultado sin dejar rastro. `alpha_limit`, si se da, debe estar en (0, 1).

### Contenido del modelo (`T2MRCDModel`)

| Campo | Contenido |
| --- | --- |
| `params`, `n_features` | Parámetros y `p` con los que se ajustó |
| `mrcd` | Ajuste MRCD del histórico completo (ver [`mrcd.md`](mrcd.md)) |
| `base_mask` | Filas de la entrada que forman la base (tras exclusión humana y depuración automática) |
| `row_disposition` | Destino de cada fila de la entrada (`RowDisposition`: conservada, causa asignable, automática, ya en la base) |
| `clean_mask` | Filas limpias de la entrada (las remuestreadas; subconjunto de la base) |
| `limits` | `phase1_limit` y `phase2_limit` y su procedencia: `n_clean`, `seed`, `n_replicates` (B), `alpha_limit`, `phase2_alpha_limit`, error Monte Carlo |
| `limit_regime` | `LimitRegime`: `PHASE1_PROVISIONAL` (v0) o `PHASE2` (recalibradas). `operative_limit` = `phase1_limit` o `phase2_limit` según el régimen |
| `historical_t2` | T² de cada fila de la entrada con el ajuste final |
| `historical_outlier` | `historical_t2 > phase1_limit` (**estricto**) |
| `depuration_rounds` | Rondas de depuración automática que quitaron filas |
| `depuration_converged` | `True`/`False` en la v0; **`None` en las recalibradas** (no se intentó depurar) |
| `final_depuration_skipped` | `True` en las recalibradas: la Fase I final **no vuelve a depurar** la nueva base. Motivo: la base vigente ya estaba depurada y las filas nuevas se depuraron antes de comparar; depurar otra vez con el límite de `best` (ver arriba) recortaría filas buenas en cada versión |
| `pymrcd_version` | Versión de `pymrcd` del ajuste, para auditar reproducibilidad |
| `seed`, `statistic_reference` | Semilla raíz y cita de la estadística (P6) con las que se ajustó |

## Fase II (puntuación y señales)

- Entrada: observaciones nuevas contra un modelo de Fase I en `succeeded`. Se valida de forma síncrona
  (`validate_phase2_input`: no vacía, finita, mismo `p`) antes de encolar.
- Salida: T² por observación, señal `t2 > límite` (estricta), el límite usado (`operative_limit`) y su régimen
  (`limit_kind`). No se recalcula nada al puntuar: el límite sale de la versión vigente.
- **Objetivo 2b.2 (aplicación, ADR 0008):** cada observación se registra con `observed_at`, `batch_label`, valores, T², límite
  usado y versión; las que señalan admiten anotación (causa asignable, cuál, acción). La v0 vigila con el límite
  de Fase I (provisional y fijo); las versiones recalibradas, con el de Fase II.

## Recalibración a petición (dominio implementado en 2b.1; aplicación en 2b.2)

Cierra las decisiones abiertas anteriores (datos, señales, modelo frente a versión): **es una versión nueva e
inmutable, en estado propuesta**, que solo rige al aprobarse (ADR 0008). Pasos:

1. **Selección:** base (versión) + rango de fechas. Mínimo de observaciones `min_observations` = 25. Si el rango
   incluye datos anteriores a un evento estructural, se rechaza (`RANGE_BEFORE_STRUCTURAL_EVENT`).
2. **Depuración:** humana (observaciones con causa asignable confirmada) y automática iterativa (también en v0),
   máximo `max_depuration_rounds` = 5; si no converge, continúa con `converged=false` en el reporte.
3. **Comparación con la base:** cambio en S con Frobenius relativa ‖S₁−S₀‖_F/‖S₀‖_F (umbral parametrizable, 0.10) y
   cambio en μ. **Reemplazar** si cualquiera de las pruebas formales de S o μ (`any_formal_test_change`) detecta
   cambio, o además si el umbral lo supera **y** `threshold_decides = True`; si no, **ampliar**. Ver «Umbral
   Frobenius parametrizable».
4. **Nuevo límite de Fase II** por OOB con pool, heredando B, α y MRCD de la versión vigente (Q8).
5. **Propuesta** con reporte antes/después. `effective_from` posterior a la última observación puntuada (Q6).

Constante técnica `BASE_CONSISTENCY_RTOL = 1e-9` (`chart.py`): al recalibrar se comprueba que la base recibida
reproduce los T² guardados (`rtol`, redondeo de BLAS). Es una comprobación de consistencia, **no prueba
identidad**: **pendiente en 2b.2** guardar un hash del contenido de la base al persistir.

Un **evento estructural** marca «requiere nueva base»: se sigue vigilando con la versión vigente (Q7) y el
siguiente recálculo reemplaza con datos posteriores. **Revalidación periódica** configurable (6 meses o N
observaciones) genera aviso.

### Defaults del ciclo de vida

| Campo | Default | Fuente |
| --- | --- | --- |
| `min_observations` | 25, configurable, sin regla por variable (MRCD vale en alta y baja dimensión) | Documento de diseño del dueño, 2026-10-07; sin cita bibliográfica |
| `phase2_alpha_limit` | 0.005 | Decisión del dueño 2026-10-07; sin cita |
| `relative_change_threshold` | 0.10 sobre Frobenius relativa, configurable | Documento de diseño del dueño; **sin cita** (decisión abierta) |
| `threshold_decides` | `False`: el umbral es informativo | Decisión del dueño 2026-10-07 (motivo abajo) |
| revalidación | 6 meses o N observaciones, configurable | Documento de diseño del dueño; **sin cita** |
| `max_depuration_rounds` | 5 | Técnico (Q5), acota el bucle; no es estadístico |
| métrica de cambio en S | ‖S₁−S₀‖_F/‖S₀‖_F | Decisión del dueño (Q4); sin cita |

### Umbral Frobenius parametrizable (decisión del dueño, 2026-10-07)

`relative_change_threshold` (0.10) y `threshold_decides` (`False`). Con `False` el umbral solo se informa
(`exceeds_threshold`) y deciden las pruebas formales de S y μ (`any_formal_test_change`); con `True` también
reemplaza si el cambio supera el umbral. **Por qué el default `False`:** con datos estables la Frobenius relativa
de MRCD sale ≈ 0.25–0.5 (n = 200, p = 3; 100 % de 60 pares > 0.10; ejemplo real: dos muestras 200×3 del mismo
proceso dieron 57 % con MRCD y 28 % con la clásica), así que 0.10 reemplazaría siempre y nunca se ampliaría.
Mientras las pruebas formales no tengan cita, la recalibración responde `T2MRCD_DECISION_PENDING` salvo
`force_replace`, **en ambos modos**.

### Pendiente: pruebas formales de cambio

Las pruebas por remuestreo de igualdad de covarianzas y de medias **no tienen cita todavía**. Mientras falten,
la recalibración termina en `failed / T2MRCD_DECISION_PENDING` (con `details.pending`: `recalibration.covariance_test`,
`.mean_test`, `.n_test_resamples`) salvo que se fuerce el reemplazo; nunca se sustituyen por otra prueba sin fuente.

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
- **Pruebas formales de cambio en S y en μ** por remuestreo: pendientes de cita; también el umbral 0.10 y el 6 meses.
- **Reponderado tipo MCD** para el remuestreo (estudio futuro; ver «Remuestreo solo sobre `best`»).
- **Hash del contenido de la base** al persistir (2b.2).
- Fuente de referencia de los golden de la carta (¿código R existente o cálculo propio verificado contra el artículo?).

**Cerradas el 2026-10-07:** P2, P3 (con cita), P4 (valor; agregación **pool** desde el Paso 2b), P5 (dos límites: Fase I y Fase II por OOB, desde el Paso 2b), P6 (referencia provisional) y la recalibración (versión inmutable propuesta, ADR 0008).
