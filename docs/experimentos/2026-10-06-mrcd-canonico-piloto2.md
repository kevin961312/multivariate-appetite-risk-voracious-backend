# Piloto 2: inicialización canónica que conserva la información (`canonical2`)

- **Fecha:** 2026-10-06 · **Rama:** `experimento/mrcd-canonico` · **Estado:** piloto exploratorio. No es una decisión
  y no cambia `rrcov` ni el protocolo de fidelidad de [ADR 0006](../adr/0006-libreria-pymrcd.md).
- **Continúa** el [piloto 1](2026-10-06-mrcd-canonico-piloto.md), con el mismo entorno: R 4.5.2, macOS arm64
  (Accelerate + Rlapack 3.12.1), `rrcov` 1.7-7 oficial desde `referencias/R-lib`, `robustbase` 0.99-6 y
  `RNGkind("Mersenne-Twister", "Inversion", "Rejection")`.
- **Código:**
  - `tools/r/experimentos/r6pack_canonico.R`: variantes `VAR_CANON` y `VAR_CANON2`; los cambios llevan la marca
    `## [CANONICO2]`.
  - `diagnostico_canonico2.R`: comprobaciones previas.
  - `piloto_canonico2.R` y `resumen_piloto2.R`.
- **Resultados crudos:** `tools/r/experimentos/resultados/piloto_canonico2.csv` (450 filas, 346 KB),
  `diagnostico_canonico2_{C1,C2,C5,C7,C8,C10}.{csv,log}`, `piloto_canonico2.log` y `resumen_piloto2.md`.

## 1. Objetivo e hipótesis

El piloto 1 mostró dos cosas:

- La variante truncada (`canonical`) es determinista.
- Pero no es neutra. En R1, R2, R3 y `covx`, el espacio nulo de la matriz *transformada* contiene variación real
  de x (entre el 50 % y el 75 % de la distancia), y descartarlo cambia el método. Por eso la variante llega a
  otra solución y su objetivo, con el mismo `rho`, es algo peor.

**Hipótesis del dueño.** `rrcov` usa una base *arbitraria* del espacio nulo. `canonical2` elige dentro de ese
espacio una base **determinada por los datos**: las direcciones principales de la variación de x. Elimina solo
las direcciones en las que x no varía. Así se espera conservar la información, y con ella la calidad de
`rrcov`, y ganar el determinismo.

## 2. La variante `canonical2`

Afecta a los conjuntos 1–5. El 6 (OGK) queda intacto.

1. **V_r:** los autovectores de la matriz (R1, R2, R3, SCM o `covx`) con
   λ_i > λ_1 · max(n, p) · eps · κ (κ = 1), igual que en `canonical`. A cada uno se le fija el signo para que su
   componente de mayor |valor| sea positiva.
2. **Complemento:** Z = data · (I − V_r V_rᵀ), calculado como `data − (data %*% V_r) %*% t(V_r)`, sin pedir a
   LAPACK la base nula.
   - `data` es exactamente lo que `initset` proyecta en `detmrcd.R:70` (`data %*% P`), sin más centrado.
   - Es la x de `r6pack`, que ya viene centrada por medianas y escalada por Qn en `doScale`
     (`detmrcd.R:124`; `rb/detmcd.R:249` centra y `:285` escala), y a la vez la x estandarizada de
     `detmrcd.R:416-422`.
3. **W:** la SVD de Z. Se conservan los vectores singulares derechos con σ_j > σ_1(data) · √eps · κ2 (κ2 = 1),
   con el signo fijado igual que en el paso 1.
4. **P = [V_r, W]**, de r + s columnas. El resto de `initset` es el de `rrcov` sin cambios (`:70-75`):
   proyección, `lambda` con Qn, distancias, orden estable y los h primeros.

### 2.1 Cambio de umbral en el paso 3

El encargo pedía σ_j > σ_1(Z) · max(n, p) · eps. En las comprobaciones previas (§3) eso falló de dos maneras, y
se cambió por **σ_1(data) · √eps**.

- **Referencia σ_1(Z) en lugar de σ_1(data).** Cuando Z es puro ruido de redondeo (siempre en SCM, y en los
  cinco conjuntos con n > p), σ_1(Z) también es ruido (~1e-12). Un umbral relativo a ese valor conserva **todas**
  las direcciones de ruido:

  | Caso | Conjunto | Direcciones s conservadas con umbral relativo a σ_1(Z) |
  |---|---|---|
  | C1 | SCM | 50 |
  | C7 | los cinco | 20 en cada uno |

  Con eso se perderían el determinismo y la identidad con `rrcov` cuando n > p. La escala correcta es la de los
  datos.
- **Factor max(n, p)·eps en lugar de √eps, incluso con referencia σ_1(data).** Ese umbral queda **dentro del
  ruido** del residuo. Z se obtiene restando productos de longitud p, y su error es mayor que el de una SVD
  directa: en C1/SCM, σ(ruido) = 7.5e-12 ≈ 1670·eps·σ_1, por encima de 200·eps·σ_1 = 8.9e-13. Por eso conserva
  2 direcciones de ruido en C1 y cambia el conjunto 4 ante la perturbación.
  - En el piloto se dejó como **control** (`canonical2 (umbral eps)`, tabla §5.1). No es determinista en
    ninguna de las 4 configuraciones de N(0, I) con p > n, con cambios en 19–48 de 50 réplicas.
  - Con n > p, en 9 de 50 réplicas cambia los subconjuntos de `I_100x20` y en 2 de 50 los de `AR1_200x40`.
- **Por qué √eps.** Separa bien el ruido de la variación real:

  | | Valor relativo a σ_1(data) | Casos |
  |---|---|---|
  | Ruido observado | ≤ 3.7e-13 | C1, C2, C5, C7, C8, C10 |
  | Variación real más pequeña conservada | ≥ 4.0e-4 | C2/R3: 0.0093 / 23.2 |
  | Umbral √eps | 1.5e-8 | queda unos 4.5 órdenes por encima del ruido y por debajo de la variación real |

  La sensibilidad con κ, κ2 ∈ {0.1, 1, 10} es nula: en 450 réplicas, ninguna de las 8 combinaciones distintas de
  (1, 1) cambia un solo subconjunto (§4).

## 3. Comprobaciones previas

### (a) Direcciones conservadas en C1 (50×200)

Columnas: r = direcciones de V_r; s = direcciones de W; σ_s(Z) = último valor singular conservado; σ_{s+1}(Z) =
primero descartado; fracción de la distancia que aporta W (mediana entre observaciones).

| Conjunto | r | s | r + s | σ_s(Z) | σ_{s+1}(Z) | Qn mediana V_r / W | Fracción de la distancia que aporta W |
|---|---|---|---|---|---|---|---|
| R1 tanh | 49 | 50 | 99 | 1.36 | — | 1.89 / 0.40 | 0.53 |
| R2 Spearman | 49 | 50 | 99 | 1.21 | — | 1.87 / 0.38 | 0.52 |
| R3 normal scores | 49 | 50 | 99 | 0.79 | — | 1.97 / 0.25 | 0.52 |
| SCM | 50 | **0** | 50 | — | 7.5e-12 | 1.88 / — | 0 |
| covx BACON | 24 | 26 | 50 | 7.86 | 7.2e-14 | 1.75 / 0.155 | 0.53 |

- **R1, R2, R3 y `covx`:** W recupera la variación real que `canonical` descartaba. W aporta en torno al 52 %
  de la distancia.
- **SCM:** no conserva nada, porque en ese conjunto el complemento es ruido. Por eso el conjunto 4 de
  `canonical2` es **idéntico** al de `canonical`, y `canonical2` difiere de `canonical` en 4 de los 6 conjuntos.
- **C2 y C10:** el patrón es el mismo (C2: s = 100, 100, 100, 0, 51).
- **n > p (C7, C8):** s = 0 en los cinco conjuntos.

### (b) Sensibilidad al umbral

Se probó la rejilla (κ, κ2) ∈ {0.1, 1, 10}² en C1, C2, C5, C7, C8 y C10, y luego en las 450 réplicas del piloto.
En todos los casos se obtienen **0 conjuntos distintos** de los de (1, 1).

### (c) n > p

En C7 y C8, `canonical2` da los mismos `initHsets` que `rrcov` bit a bit, y `CovMrcd(initHsets = canonical2)` es
idéntico a `CovMrcd(x)`. En el piloto se mantiene en 100 de 100 réplicas (§5.6).

### Otras verificaciones

- Con κ = NA y sin signo, la copia sigue reproduciendo bit a bit a `rrcov` (`ver_hsets` = TRUE en las 450
  réplicas).
- Los resultados de `rrcov` y de `canonical` coinciden exactamente con los del piloto 1 en las 400 réplicas comunes
  (`rho` y `crit`). Se reutiliza, por tanto, la misma `canonical`.

## 4. Diseño

- **Configuraciones:** las 8 del piloto 1, con las mismas semillas (20262000 + 1000·c + r), más una nueva:
  - **9 `CONTD_50x200`:** contaminación difícil. N(0, I) con n = 50 y p = 200; 10 % de filas (las 5 primeras)
    desplazadas **+1.5 solo en las 10 primeras coordenadas**.
- **Réplicas:** 50 por configuración, 450 en total; el piloto tardó 1041 s con 8 procesos PSOCK.
- **Variantes:** `rrcov`, `canonical` (piloto 1), `canonical2` y, como control, `canonical2` con umbral eps.
- **Perturbación:** **5** por réplica (semilla de la réplica + 100000·j). Las 3 primeras son las del piloto 1.
- **Métricas:** las del piloto 1, más el **percentil** del objetivo de cada variante dentro de los 5 objetivos
  que `rrcov` obtiene bajo sus propias perturbaciones. El percentil es (#rrcov < v + ½·#empates)/5: 0 significa
  mejor que las 5 y 1, peor que las 5. Se calcula de dos formas:
  - con el mismo `rho` (el de `rrcov` sin perturbar), que compara subconjuntos en igualdad de condiciones;
  - con el `rho` propio de cada ajuste.

## 5. Resultados

Formato: «m [p5, p95]» es mediana y percentiles 5 y 95 entre réplicas; «media / mediana [p5, p95]» donde se
indica; «a/b» es réplicas que cumplen / réplicas totales.

### 5.1 Determinismo

Ante la perturbación de 1e-14 (5 por réplica), las celdas cuentan réplicas con algún cambio en
**initHsets · best · rho · cov** (`rho`: > 1e-10; `cov`: relF > 1e-8).

| config | rrcov | canonical | canonical2 | canonical2 con umbral eps (control) |
|---|---|---|---|---|
| I_50x200 | 50 · 15 · 45 · 46 | 0 · 0 · 0 · 0 | **0 · 0 · 0 · 0** | 20 · 10 · 10 · 14 |
| I_100x200 | 50 · 12 · 46 · 46 | 0 · 0 · 0 · 0 | **0 · 0 · 0 · 0** | 48 · 22 · 26 · 34 |
| I_50x250 | 50 · 16 · 48 · 50 | 0 · 0 · 0 · 0 | **0 · 0 · 0 · 0** | 19 · 5 · 7 · 8 |
| I_100x250 | 50 · 11 · 49 · 49 | 0 · 0 · 0 · 0 | **0 · 0 · 0 · 0** | 42 · 23 · 19 · 29 |
| AR1_50x200 | 50 · 14 · 49 · 49 | 0 · 0 · 0 · 0 | **0 · 0 · 0 · 0** | 1 · 1 · 0 · 1 |
| CONT_50x200 | 50 · 14 · 49 · 49 | 0 · 0 · 0 · 0 | **0 · 0 · 0 · 0** | 0 · 0 · 0 · 0 |
| CONTD_50x200 | 50 · 11 · 48 · 49 | 0 · 0 · 0 · 0 | **0 · 0 · 0 · 0** | 20 · 3 · 11 · 12 |
| I_100x20 | 0 · 0 · 0 · 0 | 0 · 0 · 0 · 0 | 0 · 0 · 0 · 0 | 9 · 1 · 0 · 1 |
| AR1_200x40 | 0 · 0 · 0 · 0 | 0 · 0 · 0 · 0 | 0 · 0 · 0 · 0 | 2 · 1 · 0 · 1 |

Magnitud del cambio: máximo de las 5 perturbaciones; mediana [p5, p95] entre réplicas.

| config | relF(Δcov) rrcov | relF(Δcov) canonical2 | \|Δcrit\| rrcov | \|Δcrit\| canonical2 |
|---|---|---|---|---|
| I_50x200 | 4.5e-3 [8.8e-15, 0.77] | 8.5e-15 [8.0e-15, 1.0e-14] | 1.5 [2.1e-12, 5.2] | 2.2e-12 [4.7e-13, 3.8e-12] |
| I_100x200 | 2.0e-3 [7.6e-15, 0.65] | 7.5e-15 [7.5e-15, 7.6e-15] | 1.3 [1.0e-12, 4.0] | 8.7e-13 [4.6e-13, 1.5e-12] |
| I_50x250 | 4.3e-3 [6.0e-4, 0.78] | 9.7e-15 [8.4e-15, 1.5e-14] | 1.6 [0.19, 6.9] | 3.2e-12 [1.5e-12, 8.0e-12] |
| I_100x250 | 1.9e-3 [1.2e-4, 0.76] | 7.7e-15 [7.6e-15, 7.8e-15] | 1.7 [0.05, 4.9] | 9.7e-13 [5.1e-13, 1.6e-12] |
| AR1_50x200 | 7.5e-3 [1.1e-3, 0.60] | 7.9e-15 [7.6e-15, 8.3e-15] | 2.5 [0.33, 7.1] | 7.7e-13 [3.8e-13, 1.6e-12] |
| CONT_50x200 | 3.8e-3 [8.9e-5, 0.71] | 8.3e-15 [7.9e-15, 1.0e-14] | 1.9 [0.083, 6.6] | 2.1e-12 [7.9e-13, 6.0e-12] |
| CONTD_50x200 | 4.2e-3 [6.4e-4, 0.81] | 8.5e-15 [8.0e-15, 1.1e-14] | 1.9 [0.18, 4.8] | 1.9e-12 [7.4e-13, 4.7e-12] |

### 5.2 Objetivo frente a `rrcov`

Valores como media / mediana [p5, p95].

| config | Δrho canonical | Δrho canonical2 | Δcrit canonical | Δcrit canonical2 |
|---|---|---|---|---|
| I_50x200 | 2.7e-3 / 2.8e-3 [−7.1e-3, 1.0e-2] | 7.1e-4 / 0 [−6.4e-3, 6.8e-3] | 2.06 / 1.80 [−5.31, 7.73] | 0.46 / 0 [−4.69, 4.91] |
| I_100x200 | 2.2e-3 / 1.5e-3 [−1.8e-3, 7.0e-3] | −1.8e-4 / 3.1e-5 [−4.9e-3, 4.5e-3] | 1.86 / 1.32 [−1.91, 6.25] | −0.34 / −0.02 [−4.74, 3.65] |
| I_50x250 | 2.2e-3 / 2.3e-3 [−7.1e-3, 9.3e-3] | −1.6e-4 / 1.1e-4 [−9.2e-3, 8.5e-3] | 1.84 / 1.97 [−5.80, 7.88] | −0.18 / −0.11 [−7.33, 6.92] |
| I_100x250 | 1.4e-3 / 1.1e-3 [−3.3e-3, 5.8e-3] | −6.0e-4 / −3.1e-4 [−4.6e-3, 3.4e-3] | 1.55 / 1.29 [−3.72, 6.51] | −0.79 / −0.53 [−5.18, 3.81] |
| AR1_50x200 | 8.1e-3 / 8.2e-3 [−7.0e-3, 2.3e-2] | 1.9e-3 / 7.9e-4 [−7.9e-3, 1.1e-2] | 4.95 / 4.86 [−4.42, 13.7] | 1.15 / 0.51 [−4.91, 6.64] |
| CONT_50x200 | 2.4e-3 / 1.4e-3 [−1.5e-3, 7.4e-3] | 1.5e-4 / 2.2e-4 [−4.8e-3, 5.6e-3] | 2.64 / 1.78 [−1.31, 8.10] | 0.12 / 0.24 [−5.34, 5.83] |
| CONTD_50x200 | 3.6e-3 / 3.5e-3 [−2.6e-3, 1.3e-2] | 5.2e-4 / 0 [−5.0e-3, 6.0e-3] | 2.74 / 2.62 [−1.86, 10.0] | 0.32 / 0 [−3.68, 4.33] |

**Con el mismo rho** (Δ log obj, `canonical2` − `rrcov`):

| config | Δ canonical | Δ canonical2 | canonical peor / Δ≠0 (p del signo) | canonical2 peor / Δ≠0 (p del signo) | best canonical2 = best rrcov |
|---|---|---|---|---|---|
| I_50x200 | 1.4e-4 / 2.3e-4 | −3.8e-4 / 0 [−2.5e-3, 3.3e-4] | 31/49 (0.085) | **3/20** (0.0026) | 30/50 |
| I_100x200 | −8.9e-4 / 4.0e-5 | −9.0e-4 / 0 [−4.5e-3, 0] | 28/50 (0.48) | **2/23** (6.6e-5) | 27/50 |
| I_50x250 | 9.8e-5 / 2.1e-4 | −1.7e-4 / 0 [−1.8e-3, 6.7e-4] | 40/50 (2.4e-5) | 7/17 (0.63) | 33/50 |
| I_100x250 | −1.1e-4 / 1.1e-4 | −4.5e-4 / 0 [−3.5e-3, 2.8e-4] | 29/49 (0.25) | **3/22** (8.6e-4) | 28/50 |
| AR1_50x200 | −7.6e-5 / 0 | −2.3e-4 / 0 [−1.9e-3, 7.3e-4] | 21/45 (0.77) | **6/25** (0.015) | 25/50 |
| CONT_50x200 | 5.5e-4 / 4.3e-4 | −2.0e-4 / 0 [−1.6e-3, 1.0e-4] | 34/49 (0.0094) | **4/20** (0.012) | 30/50 |
| CONTD_50x200 | 1.1e-4 / 2.1e-4 | −3.7e-4 / 0 [−2.9e-3, 0] | 35/47 (0.0011) | **2/12** (0.039) | 38/50 |
| **Global p > n** | | | **218/339 peor** (p = 1.5e-7) | **27/139 peor** (p = 1.7e-13: canonical2 **mejor**) | 211/350 |

- `canonical2` llega al **mismo `best` que `rrcov`** en el 50–76 % de las réplicas (Δ = 0).
- Cuando difiere, con el mismo `rho` **suele ser mejor**: es peor solo en 27 de 139 réplicas.
- `canonical` (la truncada) era peor en 218 de 339.
- El Δcrit de `canonical2` está centrado en 0, mientras que el de `canonical` es sistemáticamente positivo.

### 5.3 Percentil dentro de lo que produce el redondeo de `rrcov`

Cada celda es «mejor que las 5 · dentro · peor que las 5 (media del percentil)».

| config | canonical, mismo rho | canonical2, mismo rho | canonical, rho propio | canonical2, rho propio | réplicas con las 5 perturbaciones de rrcov iguales (mismo rho) |
|---|---|---|---|---|---|
| I_50x200 | 15 · 8 · 27 (0.63) | 13 · 34 · **3** (0.37) | 7 · 10 · 33 (0.75) | 14 · 15 · 21 (0.56) | 35/50 |
| I_100x200 | 18 · 4 · 28 (0.58) | 17 · 31 · **2** (0.32) | 7 · 12 · 31 (0.75) | 18 · 17 · 15 (0.48) | 38/50 |
| I_50x250 | 6 · 11 · 33 (0.76) | 7 · 40 · **3** (0.42) | 11 · 6 · 33 (0.71) | 12 · 22 · 16 (0.52) | 34/50 |
| I_100x250 | 16 · 7 · 27 (0.61) | 15 · 32 · **3** (0.36) | 11 · 10 · 29 (0.69) | 23 · 18 · 9 (0.35) | 39/50 |
| AR1_50x200 | 19 · 12 · 19 (0.51) | 14 · 32 · **4** (0.39) | 6 · 5 · 39 (0.82) | 8 · 19 · 23 (0.59) | 36/50 |
| CONT_50x200 | 11 · 7 · 32 (0.72) | 11 · 37 · **2** (0.40) | 7 · 8 · 35 (0.78) | 17 · 20 · 13 (0.49) | 36/50 |
| CONTD_50x200 | 11 · 8 · 31 (0.69) | 9 · 40 · **1** (0.39) | 4 · 11 · 35 (0.79) | 9 · 22 · 19 (0.58) | 39/50 |

**Con el mismo `rho`:**

- `canonical2` cae dentro de lo que `rrcov` produce por redondeo, o por debajo, en el 92–98 % de las réplicas. Es
  peor que las 5 perturbaciones de `rrcov` solo en 1–4 de 50 por configuración, y la media de su percentil es
  0.32–0.42 (< 0.5).
- `canonical` es peor que las 5 en 19–33 de 50.
- En el 68–78 % de las réplicas, las 5 perturbaciones de `rrcov` dan el mismo subconjunto. Por eso «dentro»
  suele significar «empata con `rrcov`».

**Con el `rho` propio**, la comparación mezcla subconjunto y `rho`. Aun así, la media de `canonical2` es
0.35–0.59, frente a 0.69–0.82 de `canonical`.

### 5.4 Distancia entre soluciones (`cov`, relF frente a `rrcov`)

| config | canonical | canonical2 | solape de best (can / can2) | best idéntico (can / can2) | relF propio de rrcov (5 perturbaciones) |
|---|---|---|---|---|---|
| I_50x200 | 0.489 [0.283, 0.799] | 0.0080 [2e-16, 0.716] | 0.86 / 0.93 | 1/50 / 30/50 | 0.0045 [8.8e-15, 0.77] |
| I_100x200 | 0.293 [0.184, 0.641] | 0.0042 [2.8e-5, 0.616] | 0.91 / 0.94 | 0/50 / 27/50 | 0.0020 [7.6e-15, 0.65] |
| I_50x250 | 0.484 [0.284, 0.685] | 0.0051 [4.4e-4, 0.693] | 0.87 / 0.94 | 0/50 / 33/50 | 0.0043 [6.0e-4, 0.78] |
| I_100x250 | 0.334 [0.190, 0.607] | 0.0048 [1.3e-4, 0.620] | 0.92 / 0.95 | 1/50 / 28/50 | 0.0019 [1.2e-4, 0.76] |
| AR1_50x200 | 0.380 [0.025, 0.593] | 0.135 [0, 0.579] | 0.91 / 0.94 | 5/50 / 25/50 | 0.0075 [1.1e-3, 0.60] |
| CONT_50x200 | 0.549 [0.275, 0.739] | 0.0053 [1.1e-4, 0.704] | 0.84 / 0.93 | 1/50 / 30/50 | 0.0038 [8.9e-5, 0.71] |
| CONTD_50x200 | 0.410 [0.132, 0.729] | 0.0037 [1.1e-15, 0.654] | 0.88 / 0.96 | 3/50 / 38/50 | 0.0042 [6.4e-4, 0.81] |

La distribución de la distancia entre `canonical2` y `rrcov` es **la misma** que la de `rrcov` consigo mismo bajo
el redondeo, tanto en la mediana (~0.004–0.008) como en la cola (p95 ~0.6–0.7). Con `canonical`, la mediana era
de 0.3–0.55. La excepción es AR(1), con una mediana de 0.135, porque solo 25 de 50 réplicas tienen el mismo `best`.

### 5.5 Contaminados

Fracción de atípicos dentro de `best` como (media, máx.) y AUC de `mah` como (media, mín.).

| config | atípicos en best: rrcov | canonical | canonical2 | AUC: rrcov | canonical | canonical2 |
|---|---|---|---|---|---|---|
| CONT_50x200 (+5 en las 200 coordenadas) | 0, 0 | 0, 0 | 0, 0 | 1, 1 | 1, 1 | 1, 1 |
| CONTD_50x200 (+1.5 en 10 coordenadas) | 0.272, 0.6 | 0.240, 0.6 | 0.264, 0.6 | 0.680, 0.40 | 0.696, 0.34 | 0.680, 0.40 |

- En `CONTD`, las tres variantes rinden igual de mal: la contaminación es casi indetectable, con alrededor de un
  27 % de los atípicos dentro de `best` y una AUC de ~0.68.
- ΔAUC de `canonical2` − `rrcov` = 0.0004 [−0.002, 0.032]; ΔAUC de `canonical` − `rrcov` = 0.016 [−0.067, 0.112].
- Réplicas con algún atípico en `best`: 42 (`rrcov`), 38 (`canonical`) y 42 (`canonical2`) de 50.
- Ninguna variante es mejor que otra en robustez dentro de estos escenarios.

### 5.6 n > p

En `I_100x20` y `AR1_200x40`, `canonical` y `canonical2` son **idénticas bit a bit** a `rrcov` (`best`, `rho` y
`cov`) en 50/50 réplicas cada una. En cambio, el control con umbral eps cambia `initHsets` bajo perturbación
(9/50 y 2/50) y rompería esta identidad.

### 5.7 Tiempo por ajuste (s, mediana; con 8 procesos en paralelo)

| config | rrcov | canonical | canonical2 |
|---|---|---|---|
| I_50x200 | 1.40 | 1.30 | 1.33 |
| I_100x200 | 2.52 | 2.43 | 2.48 |
| I_50x250 | 2.15 | 2.02 | 2.04 |
| I_100x250 | 3.93 | 3.78 | 3.77 |
| AR1_50x200 | 1.39 | 1.29 | 1.32 |
| CONT_50x200 / CONTD_50x200 | 1.37 / 1.38 | 1.29 / 1.28 | 1.31 / 1.30 |
| I_100x20 / AR1_200x40 | 0.055 / 0.251 | 0.047 / 0.240 | 0.049 / 0.243 |

Las SVD adicionales no se notan: el coste lo domina OGK.

### 5.8 Conjunto ganador

En `rrcov` gana casi siempre el conjunto 5 (BACON), en 35–43 de 50 réplicas. En `canonical2` también gana
mayoritariamente el 5 (26–42 de 50), y el resto lo reparten el 4 y el empate 4|5. `canonical`, en cambio, se iba
casi siempre al 4. Esto confirma que conservar el complemento devuelve a BACON su papel.

## 6. Conclusiones

**Lo que el piloto sí permite concluir** (en la plataforma de referencia):

1. **`canonical2` es determinista** ante perturbaciones de 1e-14. En las 7 configuraciones con p > n, ninguna de
   las 1750 perturbaciones cambia nada, cuando `rrcov` cambia `rho` en el 90–98 % de las réplicas y `best` en el
   22–32 %. No depende de los umbrales en un rango de 100× en cada uno.
2. **El umbral del complemento debe ser relativo a la escala de los datos y bastante mayor que el de la SVD**
   (√eps·σ_1(data)). Con el umbral inicialmente propuesto, la variante vuelve a depender del redondeo y pierde la
   identidad con `rrcov` cuando n > p.
3. **Conserva la calidad de `rrcov`:**
   - Llega al mismo subconjunto final en el 60 % de las réplicas.
   - Su `cov` dista de la de `rrcov` lo mismo que `rrcov` dista de sí mismo bajo el redondeo.
   - Con el mismo `rho`, su objetivo es igual o mejor en el 81 % de las réplicas con diferencia (p = 1.7e-13).
   - Cae dentro de la nube de resultados de `rrcov`, o por debajo, en el 92–98 % de las réplicas.
   - `canonical` (piloto 1) era sistemáticamente peor.
4. **Con n > p es idéntica bit a bit a `rrcov`**, así que no afecta al protocolo de fidelidad en ese régimen.
5. **El coste es el mismo.**

**Lo que NO se puede concluir:**

- Nada sobre la carta **T²MRCD**: ni el ARL, ni la probabilidad de señal, ni los límites de control. Eso requiere
  un Monte Carlo de Fase I y Fase II.
- Que `canonical2` sea más robusta. En la contaminación difícil las tres variantes rinden igual, y de forma
  modesta (AUC ~0.68).
- Reproducibilidad **entre plataformas** (Linux con OpenBLAS, `long double` de 80 bits). Solo se probó la
  perturbación de la entrada en el Mac de referencia. Siguen siendo posibles los empates en las distancias, los
  valores singulares casi repetidos dentro de W y los saltos `d`/`f32(d)` de Qn (T1). El piloto no los muestra,
  pero no los descarta.
- Que el «mejor objetivo» de `canonical2` sea una ventaja estadística: la magnitud es pequeña (Δ log obj de
  ~1e-4 por dimensión).
- `canonical2` **no es `rrcov`** cuando p > n: difiere en 4 de los 6 subconjuntos iniciales y en el 40 % de los
  `best`. Si se adopta, es una desviación documentada con su propio ADR (consecuencia abierta del ADR 0006), y
  los tests golden de fidelidad siguen siendo contra `rrcov` oficial.

## 7. Recomendación

**Pasar al Monte Carlo con `canonical2`**, comparada con `rrcov`. `canonical` queda descartada.

Antes de empezar se fijan estos criterios de decisión:

- **Medida principal:** ARL₀ y ARL₁ (probabilidad de señal) de T²MRCD en Fase I y Fase II. Para `rrcov`, se
  incluye la dispersión que introduce su redondeo.
- **Escenarios:** contaminación difícil, con desplazamientos pequeños, pocas coordenadas, atípicos de correlación
  o cúmulos, entre el 10 % y el 20 %.
- **Reproducibilidad entre plataformas:** el mismo lote en Linux con OpenBLAS.
- **Umbrales** como en §2: λ_1·max(n, p)·eps para V_r y σ_1(data)·√eps para W.
