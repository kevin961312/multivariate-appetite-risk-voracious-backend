# Piloto: inicialización canónica determinista de MRCD (p ≥ n)

- **Fecha:** 2026-10-06 · **Rama:** `experimento/mrcd-canonico` · **Estado:** piloto exploratorio. No es una decisión
  y no cambia `rrcov` ni el protocolo de fidelidad de [ADR 0006](../adr/0006-libreria-pymrcd.md).
- **Entorno:** R 4.5.2, macOS arm64 (Accelerate + Rlapack 3.12.1), `rrcov` 1.7-7 **oficial** desde
  `referencias/R-lib` (verificado con `find.package`), `robustbase` 0.99-6, `RNGkind("Mersenne-Twister",
  "Inversion", "Rejection")`.
- **Código:** `tools/r/experimentos/r6pack_canonico.R` (variante), `verificar_canonico.R` (identidad con rrcov),
  `diagnostico_causa.R` (causa), `piloto_canonico.R` (piloto), `resumen_piloto.R` (tablas).
- **Resultados crudos:** `tools/r/experimentos/resultados/piloto_canonico.csv` (400 filas, 158 KB),
  `diagnostico_causa_C{1,2}.csv`, logs `*.log` y `resumen_piloto.md` en esa misma carpeta.

## 1. Objetivo

Con p ≥ n, `rrcov::CovMrcd` no es reproducible: una perturbación de 1e-14 en los datos cambia los subconjuntos
iniciales 1–5, y con ellos `rho`, `best` y `cov` (riesgo R1, §6 de
[`mrcd-especificacion.md`](../metodos/mrcd-especificacion.md)). El piloto evalúa una hipótesis del dueño: una
inicialización **canónica** que quita esa dependencia del redondeo y deja el resto de MRCD como en `rrcov`.
Las preguntas son tres: si la variante es determinista, cuánto cambia la solución y si pierde calidad.

## 2. Hipótesis y variante evaluada

**Causa propuesta.** En `initset` (`detmrcd.R:65-76`) los datos se proyectan sobre los autovectores `P` de R1
(tanh), R2 (Spearman), R3 (normal scores), SCM y `covx` (BACON). Con p ≥ n esas matrices tienen rango ≤ n−1
(`covx` ≤ ceil(n/2)−1). Dentro del espacio nulo, LAPACK devuelve una base arbitraria, y Qn no es invariante a
rotaciones, así que la distancia y el orden dependen de esa base.

**Variante `canonical`** (en `initset`, solo para los conjuntos 1–5):

1. Se conservan solo las direcciones con λ_i > λ_1 · max(n, p) · `.Machine$double.eps` · κ, con κ = 1. La
   proyección, las escalas Qn, `estloc` y las distancias se calculan en ese subespacio de rango r
   (`P` pasa a ser p × r; las líneas `:70-75` no cambian).
2. Cada autovector conservado se orienta para que su componente de mayor |valor| sea positiva (si hay empate, se
   toma la primera).
3. Los desempates del orden se resuelven como en R: `sort.list`, que usa radix estable.
4. El conjunto 6 (OGK) queda **exactamente** como en `rrcov`.

La selección de `rho`, los C-steps y la estimación final son los de `rrcov` oficial. Los `initHsets` canónicos se
inyectan con `correr_instrumentado(x, initHsets=H)`. Los cambios llevan la marca `## [CANONICO]
detmrcd.R:<línea>`.

**Umbral.** `max(n, p) · eps · λ_1` es la cota habitual del error de redondeo de `dsyevr` (estable hacia atrás,
`O(p · eps · ‖A‖)`; §11 de la especificación). Por debajo de esa cota, un autovalor no se distingue de 0.
Se prueban κ = 0.1 y κ = 10.

## 3. Verificaciones previas

- **Sin el cambio** (κ = NA, sin fijar el signo), la copia reproduce **bit a bit** los `initHsets` de
  `rrcov:::.detmrcd(save.hsets=TRUE)` en C1–C10 (`verificar_canonico.log`) y en las 400 réplicas del piloto
  (`ver_hsets_oficial` = TRUE en todas).
- Inyectar esos `initHsets` en `CovMrcd` da un objeto idéntico slot a slot a `CovMrcd(x)` en C1–C10, así que en
  las perturbaciones se usa la inyección.
- Para comprobar el objetivo, `logobj` (log det(ρI + (1−ρ)·c·S_B)/p, con S_B dividido por h como en `.RCOV`) se
  comparó con `cs_obj` capturado: la diferencia máxima es 6.7e-16.
- **Paralelismo:** se pidió `parallel::mclapply`, pero aborta con *segfault* en `eigen()` en este Mac (Accelerate
  no es seguro tras `fork`). Por eso se usó un **cluster PSOCK** de 8 procesos, y un proceso PSOCK da el mismo
  resultado que el proceso padre en C1.

## 4. Causa: confirmada, con una corrección

Diagnóstico en C1 (50×200) y C2 (100×200). Las cifras de C1 están en `diagnostico_causa_C1.log`. Las columnas
dicen: cuántas direcciones caen bajo el umbral; el salto entre el último λ conservado y el mayor |λ| nulo; la
mediana de |proyección| en el espacio nulo y en el significativo; la mediana de Qn en el nulo; qué parte de la
distancia aporta el nulo; y cuántas de 5 rotaciones aleatorias dentro del nulo cambian el subconjunto.

| Conjunto (C1) | λ ≈ 0 | salto (log10) | mediana \|proy\| nulo | mediana \|proy\| sig. | mediana Qn nulo | fracción de distancia del nulo | rotaciones que cambian el subconjunto |
|---|---|---|---|---|---|---|---|
| R1 tanh | 151 | 14.7 | 0.19 | 1.25 | 0.27 | 0.75 | 5/5 |
| R2 Spearman | 151 | 14.7 | 0.17 | 1.24 | 0.24 | 0.76 | 2/5 |
| R3 normal scores | 151 | 14.6 | 0.13 | 1.26 | 0.16 | 0.75 | 2/5 |
| SCM | 150 | 14.5 | 5.1e-16 | 1.23 | 7.3e-16 | 0.75 | 5/5 |
| covx BACON | 176 | 14.7 | 0.23 | 1.06 | 0.089 (mín. 1.1e-3) | 0.59 | 0/5 |

- **Se confirma** que las direcciones de λ ≈ 0 son exactamente p − rango (151/151/151/150/176 en C1;
  101/101/101/100/151 en C2). Hay un salto de unos 14 órdenes de magnitud entre las conservadas y las nulas, y una
  rotación dentro del espacio nulo cambia el subconjunto (conjuntos 1–4). Con la perturbación 1e-14, `rrcov`
  cambia los conjuntos {1, 4} en las 3 perturbaciones de C1 y de C2; la variante canónica no cambia ninguno.
- **Corrección a la premisa.** Las proyecciones son ruido (~1e-15) **solo en SCM**: su espacio nulo es el
  complemento del espacio de las filas de x. En R1, R2, R3 y `covx` el espacio nulo es el de la matriz
  *transformada* (tanh, rangos, normal scores, la mitad de las filas), no el de x. Ahí las proyecciones de x son
  O(0.1–1), las escalas Qn valen O(0.1) y aportan entre el 50 % y el 75 % de la distancia. Por tanto, truncar no
  quita solo ruido: **descarta variación real de los datos**. Es un cambio de método en esos cuatro conjuntos,
  no una limpieza numérica.
- En `covx`, las filas de `Hinit` se proyectan casi en un punto dentro del nulo, así que el subconjunto 5 tiende a
  ser `Hinit` sea cual sea la rotación (0/5). Aun así, `rrcov` cambia ese conjunto en algunas perturbaciones
  del piloto.

## 5. Diseño del piloto

- **Configuraciones** (target `identity`, defaults de `CovMrcd`: alpha = 0.5, h = ceil(n/2), maxcond = 50):

  | id | config | n | p | Σ | contaminación |
  |---|---|---|---|---|---|
  | 1–4 | `I_50x200`, `I_100x200`, `I_50x250`, `I_100x250` | 50/100 | 200/250 | I | — |
  | 5 | `AR1_50x200` | 50 | 200 | AR(1), φ = 0.7 | — |
  | 6 | `CONT_50x200` | 50 | 200 | I | filas 1–5 (10 %) desplazadas +5 en todas las coordenadas (como C10) |
  | 7 | `I_100x20` | 100 | 20 | I | — |
  | 8 | `AR1_200x40` | 200 | 40 | AR(1), φ = 0.7 | — |

- **Datos:** `x = matrix(rnorm(n·p)) %*% chol(Σ)`. **Réplicas:** 50 por configuración (400 en total; el piloto
  tardó 551 s, así que no hizo falta bajar a 30). **Semillas:** réplica r de la configuración c =
  20262000 + 1000·c + r; la perturbación j usa esa semilla + 100000·j.
- **Por réplica, para las dos variantes:**
  1. Tres perturbaciones `x·(1 + 1e-14·u)` con u ~ U(−1, 1). Se cuentan los cambios de `initHsets` (como
     conjunto, por columna), de `best`, de `rho` (|Δ| > 1e-10) y de `cov` (‖Δ‖_F/‖cov‖_F > 1e-8).
  2. `rho`, `crit` (log det de la `cov` final) y log obj = log det(ρI + (1−ρ)·c·S_best)/p en el espacio
     estandarizado, con el `rho` propio de cada variante y con el `rho` de `rrcov` para ambas.
  3. ‖cov_can − cov_ofi‖_F/‖cov_ofi‖_F y solapamiento de `best`.
  4. Contaminada: fracción de atípicos dentro de `best` y AUC de `mah` (atípico frente a limpio).
  5. n > p: identidad de las dos variantes.
  6. Tiempo por ajuste.
- **Sensibilidad al umbral:** κ ∈ {0.1, 10} sobre los mismos datos.

## 6. Resultados

Formato de las celdas: «a/b» es réplicas que cumplen / réplicas totales; «m [p5, p95]» es mediana y percentiles
5 y 95 entre réplicas; «media / mediana [p5, p95]» donde se indica.

### 6.1 Rango conservado y sensibilidad al umbral

| config | r por conjunto 1..5 | r igual con κ = 0.1 | r igual con κ = 10 | initHsets distintos (κ = 0.1 y 10 frente a κ = 1) | conjuntos can ≠ ofi |
|---|---|---|---|---|---|
| p > n, n = 50 (1, 3, 5, 6) | 49, 49, 49, 50, 24 | 50/50 | 50/50 | 0 y 0 | 5 de 6 (siempre) |
| p > n, n = 100 (2, 4) | 99, 99, 99, 100, 49 | 50/50 | 50/50 | 0 y 0 | 5 de 6 (siempre) |
| n > p (7, 8) | p en todos | 50/50 | 50/50 | 0 y 0 | 0 |

El rango es siempre el teórico (n−1, n−1, n−1, n, ceil(n/2)−1). Con un salto de unos 14 órdenes, el resultado
**no depende de κ** en un rango de 100×.

### 6.2 Determinismo ante una perturbación de 1e-14 (3 por réplica): réplicas con algún cambio

| config | initHsets ofi / can | best ofi / can | rho ofi / can | cov ofi / can | conjuntos cambiados por perturbación (ofi) |
|---|---|---|---|---|---|
| I_50x200 | 50/50 · 0/50 | 14/50 · 0/50 | 42/50 · 0/50 | 43/50 · 0/50 | 1.80 |
| I_100x200 | 50/50 · 0/50 | 12/50 · 0/50 | 45/50 · 0/50 | 45/50 · 0/50 | 1.95 |
| I_50x250 | 50/50 · 0/50 | 14/50 · 0/50 | 48/50 · 0/50 | 50/50 · 0/50 | 1.83 |
| I_100x250 | 50/50 · 0/50 | 11/50 · 0/50 | 48/50 · 0/50 | 48/50 · 0/50 | 1.96 |
| AR1_50x200 | 50/50 · 0/50 | 12/50 · 0/50 | 47/50 · 0/50 | 47/50 · 0/50 | 1.77 |
| CONT_50x200 | 50/50 · 0/50 | 8/50 · 0/50 | 46/50 · 0/50 | 46/50 · 0/50 | 1.79 |
| I_100x20 | 0/50 · 0/50 | 0/50 · 0/50 | 0/50 · 0/50 | 0/50 · 0/50 | 0 |
| AR1_200x40 | 0/50 · 0/50 | 0/50 · 0/50 | 0/50 · 0/50 | 0/50 · 0/50 | 0 |

Magnitud del cambio: máximo de las 3 perturbaciones; mediana [p5, p95] entre réplicas.

| config | max\|Δrho\| ofi | max\|Δrho\| can | relF(Δcov) ofi | relF(Δcov) can | max\|Δcrit\| ofi | max\|Δcrit\| can |
|---|---|---|---|---|---|---|
| I_50x200 | 1.8e-3 [2e-15, 7.0e-3] | 1.9e-15 [6.6e-16, 4.4e-15] | 3.8e-3 [8.2e-15, 0.76] | 8.3e-15 [8.0e-15, 9.5e-15] | 1.3 [1.4e-12, 5.2] | 1.3e-12 [4.2e-13, 3.4e-12] |
| I_100x200 | 1.3e-3 [9.5e-16, 3.7e-3] | 7.5e-16 [3.3e-16, 1.4e-15] | 1.6e-3 [7.5e-15, 0.63] | 7.5e-15 [7.4e-15, 7.7e-15] | 1.3 [8.1e-13, 3.6] | 6.5e-13 [3.7e-13, 1.3e-12] |
| I_50x250 | 1.8e-3 [6.3e-5, 7.7e-3] | 3.7e-15 [7.7e-16, 8.8e-15] | 4.0e-3 [2.9e-4, 0.78] | 9.4e-15 [8.1e-15, 1.3e-14] | 1.5 [0.11, 6.5] | 2.9e-12 [6.3e-13, 7.5e-12] |
| I_100x250 | 1.2e-3 [2.4e-5, 3.5e-3] | 6.8e-16 [3.1e-16, 1.7e-15] | 1.7e-3 [2.6e-5, 0.71] | 7.7e-15 [7.6e-15, 7.9e-15] | 1.4 [3.7e-3, 3.8] | 7.7e-13 [3.7e-13, 1.8e-12] |
| AR1_50x200 | 3.5e-3 [9.2e-5, 1.1e-2] | 1.1e-15 [3.6e-16, 2.5e-15] | 6.0e-3 [2.2e-4, 0.60] | 7.8e-15 [7.5e-15, 8.3e-15] | 2.1 [0.12, 7.1] | 6.0e-13 [2.3e-13, 1.5e-12] |
| CONT_50x200 | 1.5e-3 [1.1e-15, 5.3e-3] | 1.6e-15 [3.2e-16, 4.3e-15] | 2.4e-3 [8.2e-15, 0.68] | 8.1e-15 [7.9e-15, 9.4e-15] | 1.6 [1.2e-12, 5.6] | 1.6e-12 [3.4e-13, 4.7e-12] |
| I_100x20 / AR1_200x40 | 0 · 8.6e-16 | igual que ofi | 4.9e-15 · 3.6e-15 | igual que ofi | 2e-14 · 6.2e-14 | igual que ofi |

La variante canónica responde a la perturbación como una función continua (cambios de 1e-15 a 1e-12, del orden
de la propia perturbación). `rrcov` salta en todas las réplicas con p > n.

### 6.3 Objetivo: canónico − oficial (media / mediana [p5, p95])

| config | Δrho | Δcrit | Δ log obj (rho propio) | Δ log obj (mismo rho = rho ofi) | con el mismo rho: can mejor / can peor | prueba del signo (p) |
|---|---|---|---|---|---|---|
| I_50x200 | 2.7e-3 / 2.8e-3 [−7.1e-3, 1.0e-2] | 2.06 / 1.80 [−5.31, 7.73] | 0.0103 / 0.0090 [−0.027, 0.039] | 1.4e-4 / 2.3e-4 [−2.0e-3, 1.6e-3] | 18 / 31 | 0.085 |
| I_100x200 | 2.2e-3 / 1.5e-3 [−1.8e-3, 7.0e-3] | 1.86 / 1.32 [−1.91, 6.25] | 0.0093 / 0.0066 [−0.010, 0.031] | −8.9e-4 / 4.0e-5 [−5.2e-3, 1.1e-3] | 22 / 28 | 0.48 |
| I_50x250 | 2.2e-3 / 2.3e-3 [−7.1e-3, 9.3e-3] | 1.84 / 1.97 [−5.80, 7.88] | 0.0074 / 0.0079 [−0.023, 0.032] | 9.8e-5 / 2.1e-4 [−1.5e-3, 1.1e-3] | 10 / 40 | 2.4e-5 |
| I_100x250 | 1.4e-3 / 1.1e-3 [−3.3e-3, 5.8e-3] | 1.55 / 1.29 [−3.72, 6.51] | 0.0062 / 0.0052 [−0.015, 0.026] | −1.1e-4 / 1.1e-4 [−2.3e-3, 1.1e-3] | 20 / 29 | 0.25 |
| AR1_50x200 | 8.1e-3 / 8.2e-3 [−7.0e-3, 2.3e-2] | 4.95 / 4.86 [−4.42, 13.7] | 0.0247 / 0.0243 [−0.022, 0.069] | −7.6e-5 / 0 [−1.7e-3, 1.3e-3] | 24 / 21 | 0.77 |
| CONT_50x200 | 2.4e-3 / 1.4e-3 [−1.5e-3, 7.4e-3] | 2.64 / 1.78 [−1.31, 8.10] | 0.0132 / 0.0089 [−0.0066, 0.041] | 5.5e-4 / 4.3e-4 [−9.6e-4, 2.4e-3] | 15 / 34 | 0.0094 |
| I_100x20, AR1_200x40 | 0 | 0 | 0 | 0 | 0 / 0 | — |

Lectura de la tabla:

- **Δcrit lo explica casi todo Δrho**: la correlación entre ambos es ≥ 0.99 en todas las configuraciones con
  p > n. El `rho` canónico es mayor en el 68–82 % de las réplicas, y a más `rho`, mayor log det. Comparar `crit`
  sin igualar `rho` mezcla dos efectos.
- **Con el mismo rho**, las diferencias son pequeñas. Multiplicadas por p, para pasarlas a log det total, la
  mediana va de 0.000 a 0.086 y el rango p5–p95 es de ≈ [−1.0, 0.47]. La variabilidad propia de `crit` en
  `rrcov` ante la perturbación tiene una mediana de 1.3–2.1. Aun así, el signo tiende a ir en contra de la
  variante canónica: juntando las 6 configuraciones con p > n, es peor en 183 de 292 réplicas con Δ ≠ 0 (prueba
  del signo p = 1.8e-5). La media global es −4.8e-5, porque la cola izquierda es más larga.
- **Conjunto ganador** (`iBest`). En `rrcov` gana casi siempre el 5, BACON (35–43 de 50). En la variante
  canónica gana casi siempre el 4, SCM truncada (37–46 de 50). Es justo el conjunto cuyo truncado quita solo ruido.

### 6.4 Distancia entre soluciones frente a la variabilidad propia de `rrcov`

| config | relF(cov_can, cov_ofi) | solape de best (media, mín.) | best idéntico | relF propio de rrcov (todas) | relF propio de rrcov si cambia best | réplicas con relF can-ofi > relF propio |
|---|---|---|---|---|---|---|
| I_50x200 | 0.489 [0.283, 0.799] | 0.86, 0.64 | 1/50 | 3.8e-3 [8.2e-15, 0.76] | 0.656 (n = 14) | 43/50 |
| I_100x200 | 0.293 [0.184, 0.641] | 0.91, 0.70 | 0/50 | 1.6e-3 [7.5e-15, 0.63] | 0.452 (n = 12) | 48/50 |
| I_50x250 | 0.484 [0.284, 0.685] | 0.87, 0.68 | 0/50 | 4.0e-3 [2.9e-4, 0.78] | 0.645 (n = 14) | 43/50 |
| I_100x250 | 0.334 [0.190, 0.607] | 0.92, 0.72 | 1/50 | 1.7e-3 [2.6e-5, 0.71] | 0.661 (n = 11) | 40/50 |
| AR1_50x200 | 0.380 [0.025, 0.593] | 0.91, 0.76 | 5/50 | 6.0e-3 [2.2e-4, 0.60] | 0.517 (n = 12) | 44/50 |
| CONT_50x200 | 0.549 [0.275, 0.739] | 0.84, 0.68 | 1/50 | 2.4e-3 [8.2e-15, 0.68] | 0.671 (n = 8) | 45/50 |
| n > p (7, 8) | 0 | 1, 1 | 50/50 | ≈ 4e-15 | — | 0/50 |

La solución canónica es **otra** solución de MRCD: comparte el 84–92 % de `best` y su `cov` difiere de la de
`rrcov` en un 30–55 % (Frobenius relativa). Esa distancia supera la variabilidad típica de `rrcov` ante la
perturbación, cuya mediana es ~0.2–0.6 %, porque casi siempre solo cambia `rho`. Es del mismo orden que la
variabilidad de `rrcov` cuando la perturbación cambia `best` (0.45–0.67, en un 16–28 % de las réplicas). Con
p > n, una diferencia de un 30–60 % en `cov` es el tamaño habitual de «otro óptimo local» de MRCD.

### 6.5 Contaminados (CONT_50x200: 5 atípicos desplazados +5)

| variante | fracción de atípicos en best (media, máx.) | AUC de mah (media, mín.) |
|---|---|---|
| oficial | 0, 0 | 1, 1 |
| canónica | 0, 0 | 1, 1 |

Las dos variantes excluyen siempre a los atípicos y los separan perfectamente. Con un desplazamiento de +5 en las
200 coordenadas, este escenario **no discrimina** entre ellas.

### 6.6 n > p

`I_100x20` y `AR1_200x40`: la variante canónica es **idéntica bit a bit** a `rrcov` en 50/50 réplicas (`initHsets`,
`best`, `rho` y `cov`). No se trunca nada (r = p) y fijar el signo no cambió ningún orden. Por la propiedad T3
(Qn(−v) ≠ Qn(v) bit a bit), en otros datos podría cambiar un `lambda` en el último bit, pero en el piloto no ocurrió.

### 6.7 Tiempo por ajuste (s; media / mediana [p5, p95]; con 8 procesos en paralelo)

| config | oficial | canónico (r6pack + CovMrcd) | de ello, r6pack canónico |
|---|---|---|---|
| I_50x200 | 1.41 / 1.38 [1.30, 1.64] | 1.32 / 1.28 [1.22, 1.56] | 1.24 |
| I_100x200 | 2.55 / 2.52 [2.42, 2.81] | 2.45 / 2.41 [2.30, 2.74] | 2.35 |
| I_50x250 | 2.15 / 2.12 [2.02, 2.37] | 2.02 / 2.00 [1.91, 2.23] | 1.91 |
| I_100x250 | 3.68 / 3.80 [2.97, 4.07] | 3.53 / 3.66 [2.77, 4.08] | 3.42 |
| AR1_50x200 | 1.38 / 1.37 [1.31, 1.46] | 1.29 / 1.29 [1.21, 1.39] | 1.22 |
| CONT_50x200 | 1.20 / 1.29 [1.00, 1.38] | 1.11 / 1.15 [0.94, 1.30] | 1.05 |
| I_100x20 | 0.056 / 0.055 | 0.050 / 0.049 | 0.039 |
| AR1_200x40 | 0.260 / 0.258 | 0.248 / 0.247 | 0.229 |

El coste es el mismo, con una diferencia de 4–10 %, que es ruido de medida e incluye el sobrecoste de la
instrumentación en ambas variantes. Lo domina OGK, el conjunto 6, que no cambia.

## 7. Conclusiones

**Lo que el piloto sí permite concluir:**

1. **La causa está confirmada.** Con p ≥ n, el espacio nulo de las matrices 1–5 tiene exactamente p − rango
   direcciones, y su base cambia con el redondeo. Como Qn no es invariante a rotaciones, cambia el subconjunto.
   Hay un matiz: solo en SCM esas proyecciones son ruido. En R1, R2, R3 y `covx` son variación real de x, que
   pesa entre el 50 % y el 75 % de la distancia.
2. **La variante canónica es determinista frente a perturbaciones de 1e-14 en esta plataforma:** 0 cambios en
   300 perturbaciones por configuración con p > n. Con `rrcov`, en cambio, cambian los `initHsets` en el 100 % de
   las réplicas, `rho` en el 84–96 % y `best` en el 16–28 %. El umbral no es delicado: κ entre 0.1 y 10 da el
   mismo rango y los mismos subconjuntos en las 400 réplicas.
3. **Con n > p es idéntica bit a bit a `rrcov`.** El protocolo de fidelidad para n > p no se vería afectado.
4. **No cuesta más.**
5. **No es `rrcov`.** Elige otro conjunto ganador (SCM truncada en lugar de BACON), un `rho` algo mayor
   (+0.001 a +0.008 de mediana) y una `cov` que difiere un 30–55 %. Es una diferencia del tamaño de los saltos que
   el propio `rrcov` da ante el redondeo cuando cambia `best`. Con el mismo `rho`, su objetivo es
   **ligeramente peor en mediana** (p = 1.8e-5 juntando las configuraciones), aunque la magnitud es mucho menor
   que la variabilidad de `crit` en `rrcov`.

**Lo que NO se puede concluir:**

- Nada sobre la carta **T²MRCD**: ni el ARL, ni la probabilidad de señal, ni los límites de control. El piloto
  mide el estimador, no la carta, y eso requiere un Monte Carlo de Fase I y Fase II.
- Nada sobre robustez en contaminaciones difíciles. El único escenario (+5 en todas las coordenadas) es trivial
  para las dos variantes.
- Nada sobre reproducibilidad **entre plataformas** (Linux con OpenBLAS, x86-64 con `long double`). Solo se
  probó la perturbación de la entrada en el Mac de referencia. La variante canónica sigue dependiendo de LAPACK
  en el subespacio significativo, de autovalores casi repetidos dentro de él y de los saltos `d`/`f32(d)` de Qn
  (T1). El piloto no muestra efecto de eso, pero tampoco lo descarta.
- Que la canónica sea «mejor» o «peor» que MRCD en sentido estadístico. Con 50 réplicas, la diferencia en el
  objetivo con el mismo `rho` es pequeña y de signo desfavorable. Su efecto sobre la eficiencia o el sesgo de
  `cov` no se midió.
- Que el truncamiento sea neutro en R1, R2, R3 y `covx`: no lo es, porque descarta variación real (ver la
  conclusión 1).

## 8. Recomendación

El Monte Carlo **sí vale la pena**, pero acotado y con estos criterios decididos antes de correrlo.

- **Métrica principal:** ARL₀ y probabilidad de señal (ARL₁) de T²MRCD en Fase I y Fase II, con `rrcov` y con la
  canónica. Para `rrcov` se incluye la dispersión que introduce su no determinismo: varias perturbaciones de
  1e-14 por réplica.
- **Escenarios:** contaminación difícil (desplazamientos pequeños o en pocas coordenadas, atípicos de
  correlación, cúmulos, entre el 10 % y el 20 %), además de N(0, I) y AR(1) con p > n.
- **Reproducibilidad entre plataformas:** el mismo conjunto en Linux con OpenBLAS.
- **Variante intermedia a añadir:** truncar **solo SCM** (conjunto 4), que es donde el truncado quita únicamente
  ruido, y estabilizar R1, R2, R3 y `covx` de otra forma (por ejemplo, completar el espacio nulo con una base
  canónica en lugar de descartarlo). Así se separa el efecto de «determinismo» del de «cambio de método».
- Si se adopta, debe entrar como **modo explícito y documentado** con su propio ADR, como pide la consecuencia
  abierta del ADR 0006. Los tests golden de fidelidad siguen siendo contra `rrcov` oficial.
