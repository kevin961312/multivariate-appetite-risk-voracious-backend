# Pre-registro: Monte Carlo de la carta T²MRCD con `rrcov` oficial frente a `canonical2`

- **Fecha:** 2026-10-06 · **Rama:** `experimento/mrcd-canonico` · **Estado:** PROTOCOLO PENDIENTE DE APROBACIÓN.
  La corrida completa **no se ha lanzado**. Solo se ha hecho la prueba de tiempos (`--piloto`, §10).
- **Continúa** los pilotos [1](2026-10-06-mrcd-canonico-piloto.md) y [2](2026-10-06-mrcd-canonico-piloto2.md), cuya
  recomendación (piloto 2, §7) fue pasar a un Monte Carlo de la carta.
- **Código:** `tools/r/experimentos/mc_canonico2.R` (MD5 `b5619ad209bef5dcc86a400ee1f8ab75`), que usa
  `tools/r/experimentos/r6pack_canonico.R` (MD5 `5e55bd43b08cfc5e778e43c4c91e180c`, variante `VAR_CANON2(1, 1)`).
- **Entorno de referencia:**
  - R 4.5.2, macOS arm64 (Apple M2, 8 núcleos), BLAS de Accelerate y LAPACK 3.12.1.
  - `rrcov` 1.7-7 **oficial** desde `referencias/R-lib` (`detmrcd.R` con MD5 `d56485337b83f927bba70002357be341`),
    `robustbase` 0.99-6 y `EnvStats` 3.1.0.
  - `RNGkind("Mersenne-Twister", "Inversion", "Rejection")`.
- **Regla de pre-registro:** una vez aprobado, el protocolo y el MD5 del script quedan congelados. Cualquier cambio
  posterior se declara como **desviación** en el informe de resultados, con su motivo.

## 1. Pregunta

¿La carta de control T²MRCD de la tesis del dueño tiene **el mismo desempeño** cuando el estimador MRCD usa los
subconjuntos iniciales `canonical2` (deterministas) que cuando usa `rrcov` oficial?

- Se mide en la probabilidad de falsa alarma en control y en la probabilidad de señal fuera de control.
- El objetivo es decidir si `canonical2` puede ofrecerse como **modo opcional** de pymrcd (un ADR propio, como
  desviación documentada del ADR 0006).
- No se pretende sustituir a `rrcov`: los tests golden de fidelidad siguen siendo contra `rrcov` oficial.

Solo se comparan **dos variantes**:

- `off`: `rrcov::CovMrcd` oficial.
- `c2`: `canonical2` con los umbrales **fijados** en el piloto 2: V_r con λ_i > λ_1·max(n, p)·eps, y complemento con
  σ_j > σ_1(data)·√eps. No se tocan.

## 2. La carta T²MRCD según la tesis (con citas)

Fuentes leídas (solo lectura; no se ejecutó ni se copió nada):

- **[NB]** `Downloads/Tesis/Thesis_Robust_Control_Chart_High_Dimensional_Processes/ChartControlT2MRCDNormal/Simulation(MRCD,TMOD,RMDP).ipynb`.
  Las celdas se numeran desde 0 y las líneas, dentro de cada celda. Es el cuaderno que produjo las figuras del
  README (`README.md:13`).
- **[R]** `Downloads/Tesis/ChartControlT2MRCDNormalParalelo/`: `T2MRCDNormal.R`, `SimulationT2ChartMedia.R`,
  `SignalProbability.R`, `MethodUCLKernel.R` y `T2MRCDNormal_TPU.R`. Es una versión anterior con las mismas funciones.
- **[ART]** El artículo derivado de la tesis, «Outlier-robust Phase I monitoring of high-dimensional processes with
  individual observations» (`Downloads/Tesis/Articulo MRCD/…_Latex.zip`, archivo `Template.tex`).
- El documento de la tesis (`Downloads/MscThesis_Kevin_Pineda/Documento_Memorias/`) **no existe** en esa ruta, ni
  aparece en `Downloads/`. Por eso la metodología se toma del código y del artículo.

| Elemento | Definición en la tesis | Cita |
|---|---|---|
| Estadístico (Fase I, observaciones individuales) | T²_i = (x_i − μ̂_MRCD)ᵗ Σ̂_MRCD⁻¹ (x_i − μ̂_MRCD) | ART `Template.tex:116-118` |
| Implementación | `CovMrcd(Data, alpha = alphaMRCD)`; `mahalanobis(x, center = $center, cov = $cov)` | NB celda 5:205-211; R `SimulationT2ChartMedia.R:63-69` |
| h / α de MRCD | `AlphaMRCD <- 0.75`; «h = ⌊0.75·n⌋», con target identidad | NB celda 6:21; ART `:138` |
| Distribución en control | N_p(0, Σ) con Σ = 0.5^\|i−j\| (código); en el artículo, además, una Σ aleatoria | NB celda 6:14-20; ART `:134` |
| n, p | p ∈ {200, 250}, n = 100 (cuaderno); n ∈ {50, 100, 150} (artículo) | NB celda 6:9-10; ART `:134` |
| Límite de control (UCL) | Se simulan muestras en control. Se guardan los T² de las observaciones **del subconjunto `best`** y se toma `UCL = qemp(1 − 0.05, T2Total)` (cuantil empírico de todos los T² juntos) | NB celda 5:208-211, 236; celda 6:22, 80 |
| UCL alternativos | `UCLMax = qemp(0.95, máximo de T² por muestra)`; UCL por núcleo (KDE) | NB celda 6:79, 81; celda 5:1-21 |
| α (error tipo I) | 0.05 | NB celda 6:22; ART `:158` |
| Fuera de control | ⌊π·n⌋ atípicos ~ N_p(μ₁, Σ), añadidos **al final** de los n − ⌊π·n⌋ en control | NB celda 5:261-269; ART `:136`, `:160` |
| Desplazamientos | μ₁ = c·1_p con c ∈ {0, 0.01, 0.05, 0.10, 0.15, 0.25, 0.50, 0.60, 0.75, 0.90, 1} | NB celda 6:106-118; ART `:136` |
| No centralidad | `DeltaNCP = sqrt(t(μ₁−μ₀) Σ⁻¹ (μ₁−μ₀))` en el código; sin raíz en el artículo | NB celda 6:161; ART `:136` |
| Proporción de atípicos π | 0.2 (cuaderno); 0.1 (`T2MRCDNormal.R:27`); {5, 10, 20} % (artículo) | NB celda 6:11; ART `:134` |
| Métrica | «Probabilidad de señal» = fracción de los T² **de los atípicos** que superan el UCL. Con δ = 0 se usan los T² del subconjunto `best` de una muestra en control | NB celda 5:23-54, 277-281, 327; ART `:160` |
| Réplicas | 10 000 para el UCL y 10 000 por desplazamiento (cuaderno); 1000 (artículo) | NB celda 6:12, 23; ART `:134`, `:158` |
| `rrcov` usado | Versión **modificada** 1.7-7.9000 (`rrcov.zip`) | NB celda 3:2-5; `README.md:17` |

### 2.1 Supuestos explícitos, que **el dueño debe confirmar** antes de la corrida

- **S1 (crítico): UCL calculado con el subconjunto `best` o con las n observaciones.**
  - El código calibra el UCL con los T² del subconjunto `best` (celda 5:210-211). El artículo dice «we find the n
    estimations of the control statistic» (ART `:158`).
  - Con `rrcov` oficial y p > n, la diferencia es enorme. En el piloto (§10), el UCL con `best` vale 41–77 y el
    UCL con las n observaciones, 700–1560.
  - Con el UCL del código, el **29 % de las observaciones en control** supera el límite si la carta se aplica a
    las n de la Fase I (0.26–0.30 en todas las configuraciones, incluida n > p). Es porque las que quedan fuera de
    `best` tienen un T² mucho mayor.
  - En la práctica, la carta del código señala «la observación no está en `best`». La «probabilidad de señal»
    mide entonces sobre todo si el atípico queda fuera de `best`.
  - **Se calculan las dos definiciones con los mismos ajustes.** La decisión usa la del código
    (`--ucl=best`, valor por defecto) **salvo que el dueño indique `--ucl=todas`** antes de lanzar. La otra se
    presenta como análisis de sensibilidad, con los mismos márgenes.
- **S2: α de MRCD = 0.75.**
  - Viene del cuaderno final y del artículo. `T2MRCDNormal.R:37` y `T2MRCDNormal_TPU.R:134` usan 0.50.
  - En `rrcov` 1.7-7 oficial el valor por defecto es 0.5 (`CovControlMrcd`), así que se pasa `alpha = 0.75`
    explícitamente.
  - h = ⌈0.75·n⌉, como hace `rrcov` (`detmrcd.R:400`), y no ⌊0.75·n⌋ como dice el artículo. Para n = 50 eso da
    38 en lugar de 37.
  - **Atención:** el piloto 2 validó `canonical2` con α = 0.5. Con 0.75, el determinismo se re-verifica en esta
    corrida (compuerta G2).
- **S3: probabilidad de señal por observación o «al menos una».**
  - La métrica primaria es la del código: la fracción de atípicos con T² > UCL.
  - El artículo la define como «la probabilidad de que al menos una de las n observaciones esté fuera de
    control» (ART `:132`).
  - Esa versión se reporta como secundaria: la proporción de réplicas con al menos un atípico detectado (con
    McNemar) y la métrica con `UCLMax`.
- **S4: generación de los datos.**
  - Se usa `x = Z %*% chol(Σ)` en lugar de `MASS::mvrnorm`, que es lo que la tesis usa en la práctica porque
    `exists("jnp")` es falso en R (NB celda 5:170-193). `mvrnorm` usa `eigen()`, que en Accelerate no es
    reproducible entre plataformas.
  - La distribución es la misma, aunque la secuencia aleatoria es otra.
  - Los atípicos van al final, como en la tesis.
- **S5: Σ.** Se usan las configuraciones del dueño:
  - N(0, I).
  - AR(1) con φ = 0.7.
  - La **Σ de la tesis** (0.5^\|i−j\|) en (100, 200), que reproduce el cuaderno (NB celda 6:9-20).
  - La Σ aleatoria del artículo **no** se incluye.
- **S6: escenarios.**
  - Del rejilla de la tesis solo se usan c ∈ {0.10, 0.25, 0.50} con π = 10 %, y c = 0.25 con π = 20 %.
  - El escenario difícil (`DIF`) y el de atípicos de correlación (`COR`) **no están en la tesis**. Se definen
    aquí (§3).
- **S7: no centralidad.** Se reporta δ con raíz, como en el código (= distancia de Mahalanobis del desplazamiento).
- **S8: UCL por núcleo.** No se evalúa. Es una alternativa secundaria en la tesis, y su código tiene un recorte
  ad hoc (celda 5:5).
- **S9: `rrcov` oficial y no el modificado.** Los valores absolutos **no reproducirán las figuras de la tesis**. La
  comparación es interna: `off` frente a `c2`, con los mismos datos.

## 3. Configuraciones, escenarios y réplicas

**Configuraciones** (`cfg`):

| id | nombre | n | p | Σ | papel |
|---|---|---|---|---|---|
| 1 | I_50x200 | 50 | 200 | I | dueño (C1) |
| 2 | I_100x200 | 100 | 200 | I | dueño (C2) |
| 3 | I_50x250 | 50 | 250 | I | dueño (C3) |
| 4 | I_100x250 | 100 | 250 | I | dueño (C4) |
| 5 | AR07_50x200 | 50 | 200 | 0.7^\|i−j\| | AR(1); la mayor diferencia frente a `rrcov` en el piloto 2 |
| 6 | I_100x20 | 100 | 20 | I | **control n > p**: debe ser idéntica bit a bit |
| 7 | AR05_100x200 | 100 | 200 | 0.5^\|i−j\| | Σ y n de la tesis (NB celda 6) |

**Conjuntos de datos por configuración** (`set`). π es la proporción de atípicos y m = ⌊π·n⌋:

| id | nombre | contenido | atípicos |
|---|---|---|---|
| 0 | CAL | en control: **calibración** del UCL de cada variante | — |
| 1 | IC | en control: **falsa alarma** | — |
| 2 | M010 | desplazamiento de la media μ₁ = 0.10·1_p, π = 10 % | N(μ₁, Σ) |
| 3 | M025 | μ₁ = 0.25·1_p, π = 10 % | N(μ₁, Σ) |
| 4 | M050 | μ₁ = 0.50·1_p, π = 10 % | N(μ₁, Σ) |
| 5 | M025_P20 | μ₁ = 0.25·1_p, π = 20 % | N(μ₁, Σ) |
| 6 | DIF | **difícil**: +1.5 solo en las 10 primeras variables, π = 10 % | N(μ₁, Σ) |
| 7 | COR | **atípicos de correlación**: media 0 y varianzas 1, π = 10 % | N(0, Σ_c), Σ_c = (−0.9)^\|i−j\| |

No centralidad δ = √(μ₁ᵗ Σ⁻¹ μ₁) por configuración:

| config | M010 | M025 | M050 | DIF |
|---|---|---|---|---|
| I, p = 200 | 1.41 | 3.54 | 7.07 | 4.74 |
| I, p = 250 | 1.58 | 3.95 | 7.91 | 4.74 |
| AR07_50x200 | 0.60 | 1.50 | 3.00 | 2.83 |
| I_100x20 | 0.45 | 1.12 | 2.24 | 4.74 |
| AR05_100x200 | 0.82 | 2.05 | 4.10 | 3.12 |

En COR, E[T²] = tr(Σ⁻¹Σ_c), frente a p en control:

- Con Σ = I es igual a p; solo cambia la dispersión, que es unas 3 veces mayor. Es el caso de atípicos
  «invisibles» en la media.
- Con AR(1) es mucho mayor: 1074 frente a 200 con φ = 0.7, y 571 frente a 200 con φ = 0.5.

**Réplicas** (conjuntos de datos simulados; cada uno se ajusta con las dos variantes):

| configuraciones | CAL | cada uno de los 7 sets de evaluación | total de conjuntos |
|---|---|---|---|
| n = 50 (1, 3, 5) | 1000 | **2000** | 15 000 por configuración |
| n ≥ 100 (2, 4, 6, 7) | 1000 | **1000** | 8000 por configuración |
| **Total** | | | **77 000 conjuntos, 154 000 ajustes MRCD**, más 14 000 ajustes perturbados (§5) |

**Semillas:**

- Réplica r del set s en la configuración c: `20263000 + 100000·c + 10000·s + r`, con
  `set.seed(·, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")`.
- Perturbación: esa semilla + 50 000 000.
- Bootstrap del análisis: 20263999.

## 4. Métricas

Las dos variantes se calibran **cada una con su propio UCL**, con los mismos 1000 conjuntos CAL, y se evalúan con
los mismos conjuntos. Así se compara la carta completa, calibración incluida, que es lo que vería un usuario. El
diseño es **pareado**: cada conjunto simulado alimenta a `off` y a `c2`.

**Primarias** (definición del UCL según S1):

- **FA (falsa alarma), set IC:**
  - Con `--ucl=best`: fracción de los T² del subconjunto `best` que superan el UCL. Es la métrica de la tesis
    con δ = 0.
  - Con `--ucl=todas`: fracción de las n observaciones que lo superan.
- **SP (probabilidad de señal), sets 2–7:** fracción de los T² de los m atípicos que superan el UCL.
- **Δ = métrica(c2) − métrica(off)**, en cada una de las 42 celdas primarias: 6 configuraciones con p > n por
  7 sets.

**Secundarias** (se reportan y no deciden):

- SP y FA con el otro UCL (S1).
- Métrica con `UCLMax` (celda 6:81).
- Proporción de réplicas con al menos un atípico detectado, con McNemar exacto sobre los pares discordantes (S3).
- **Swamping:** fracción de observaciones limpias por encima del UCL. En IC es la falsa alarma sobre las n
  observaciones.
- ARL₀ = 1/FA y ARL₁ = 1/SP. Son una transformación geométrica: en Fase I con observaciones individuales el ARL
  no es la medida natural.
- UCL de cada variante y su error estándar.
- `rho`, `crit`, `best` idéntico, solape de `best` y relF(Δcov).
- Tiempo por ajuste.

## 5. Variabilidad propia de `rrcov` (parte del argumento)

En las **200 primeras réplicas de cada (configuración, set)**, incluido CAL, se vuelve a ajustar `rrcov` con
x·(1 + 1e-14·U(−1, 1)). En las 50 primeras también `canonical2`. Se mide:

- **disc(off′, off):** fracción de las n observaciones cuya decisión (T² > UCL_off) cambia por la perturbación.
  Se calcula en todas las réplicas y solo en las réplicas en que cambia `best`.
- **disc(c2, off):** la misma fracción entre `canonical2` y `rrcov`, en las mismas réplicas.
- **Δ_self:** cambio de la métrica de la celda entre `rrcov` perturbado y sin perturbar.
- **UCL_off′:** UCL de `rrcov` sustituyendo los 200 conjuntos CAL perturbados.
- **H2 (descriptiva, no decide):** si disc(c2, off) es del mismo orden que disc(off′, off). Se reporta la
  diferencia con IC al 95 % pareado. La lectura prevista es que `canonical2` cae dentro del ruido de redondeo
  propio de `rrcov`, o no.

## 6. Criterios de decisión (fijados de antemano)

**Márgenes de equivalencia:**

- **|Δ SP| ≤ 0.02:**
  - Las diferencias entre cartas que la tesis considera relevantes son de 0.1 o más en sus figuras.
  - 0.02 es del orden del error Monte Carlo de la propia tesis con 1000 réplicas.
- **|Δ FA| ≤ 0.01:** es el 20 % del α nominal de 0.05.

**Error estándar:** de un **bootstrap pareado en dos etapas** con B = 2000. En cada remuestreo se toman con
reemplazo:

1. las réplicas CAL, y se recalculan los dos UCL;
2. las réplicas del set.

Ambas variantes usan los mismos índices. Así el SE incluye la incertidumbre del UCL. Los IC son normales,
Δ ± z·SE. Se usa el SE bootstrap y no percentiles porque los cuantiles extremos que exige Bonferroni necesitarían
B muy grande.

**Clasificación de cada celda:**

- **Equivalencia (intersección-unión):** con el IC al 90 % (z = 1.645, TOST con α = 0.05):
  - `EQUIV` si el IC cae dentro de (−M, M);
  - `NO_INFERIOR` (solo SP) si el límite inferior es > −M pero el superior ≥ M;
  - `NO_DEMOSTRADA` en otro caso.
  - Para afirmar «equivalentes en todas las celdas» deben pasar **todas**. Por el principio de intersección-unión
    (Berger, 1982), eso controla el error global en α **sin corrección**.
- **Fallo (con corrección por comparaciones múltiples):** con el IC ajustado por Bonferroni para K = 42
  (z = 3.038):
  - en SP, `falla` si el límite superior es < −M: `c2` es peor que `off` en más del margen;
  - en FA, si el IC queda entero fuera de (−M, M), en cualquier dirección.
  - Afirmar que **alguna** celda falla es una afirmación de unión, y por eso necesita la corrección.

**Compuertas** (deben cumplirse todas):

- **G1:** en la configuración 6 (n > p), `cov`, `best` y `rho` son idénticos bit a bit en el 100 % de las réplicas
  de todos los sets.
- **G2:** `canonical2` es determinista en el 100 % de las réplicas perturbadas: el mismo `best`, |ΔT²| ≤ 1e-8·máx T²
  y las mismas decisiones.
- **G3:** ninguna réplica con error.

**Decisión global:**

| Resultado | Condición | Consecuencia |
|---|---|---|
| **ADOPTAR COMO MODO OPCIONAL** | Ninguna `falla`, G1–G3 se cumplen, las 6 celdas FA son `EQUIV` y las 36 celdas SP son `EQUIV` o `NO_INFERIOR` | ADR propio para `canonical2` como opción no predeterminada; `rrcov` sigue siendo el valor por defecto y la referencia golden. Si hay celdas `NO_INFERIOR`, el dueño revisa la diferencia favorable |
| **NO ADOPTAR** | Alguna celda con `falla`, o falla G1, G2 o G3 | `canonical2` se descarta como opción de la carta |
| **INCONCLUSO** | Ningún fallo, pero alguna celda `NO_DEMOSTRADA` | No se adopta por ahora. Ampliar réplicas exige un **nuevo** pre-registro, no una extensión sobre la marcha |

## 7. Número de réplicas: justificación por precisión

Del piloto (§10, 5 réplicas por celda, una estimación tosca), la desviación típica por réplica de la diferencia
pareada d_r es:

| Métrica | DE de d_r |
|---|---|
| SP con n = 100 | 0.10–0.14 |
| SP con n = 50 | 0.14–0.23 |
| FA | 0.027 |

Objetivo: SE ≤ 0.005 en SP y ≤ 0.001 en FA.

| Celdas | R | SE esperado | Potencia TOST por celda si Δ = 0 |
|---|---|---|---|
| SP con n = 50 | 2000 | ≤ 0.0051 | ≈ 0.977 |
| SP con n ≥ 100 | 1000 | ≤ 0.0045 | ≈ 0.995 |
| FA | 1000–2000 | ≈ 0.0009 | ≈ 1 |

**Potencia global.** Con 36 celdas SP, la cota de Bonferroni de la probabilidad de declarar equivalencia en todas,
si de verdad lo son, es ≥ 1 − (18·0.023 + 18·0.005) ≈ 0.50. La correlación positiva entre celdas la sube en la
práctica. Por tanto, **un resultado INCONCLUSO es posible aunque las cartas sean equivalentes**.

- **Opción para el dueño:** subir `R_EVAL_50` a 3000. La potencia por celda pasaría a ≈ 0.995 y la corrida
  duraría unas 2.5 h más.
- **Calibración:** en el piloto, con solo 5 réplicas CAL, SE(UCL) ≈ 0.05–0.2 sobre un UCL de 40–77. Con 1000 se
  espera ≈ 0.004–0.015. Ya está incluido en el SE bootstrap.

## 8. Plan de cómputo y reproducibilidad

- **Cómputo:** 8 procesos **PSOCK**. `fork`/`mclapply` aborta en `eigen()` con Accelerate.
  - Bloques de 25 réplicas de un mismo (configuración, set).
  - Cada bloque se escribe de forma atómica (`.tmp` y luego `rename`) como `checkpoints/ck_c{c}_s{s}_b{bbb}.rds`.
  - **Reanudar:** basta con relanzar el mismo comando; los bloques existentes no se recalculan.
  - Orden de ejecución: primero los más caros (n·p²) y la calibración.
- **Salida** (`tools/r/experimentos/resultados/mc_canonico2/`):
  - `mc_canonico2_replicas.csv`: una fila por conjunto. Unas 77 000 filas, **≈ 14 MB** extrapolando del piloto,
    a 7 cifras.
  - `mc_canonico2_resumen.csv`: una fila por celda y definición de UCL.
  - `mc_canonico2_gates.csv`.
  - `mc_canonico2_decision.txt`.
  - `manifiesto.txt`: R, ruta de `rrcov`, BLAS, LAPACK, parámetros y MD5 del script, de `r6pack_canonico.R` y de
    `detmrcd.R`.
  - Los checkpoints (≈ 150 MB) quedan en local y los ignora un `.gitignore` propio.
- **Duración estimada:** **≈ 11 h** de reloj en este Mac (§10), más unos 15 min de análisis.
- **Comandos:**

  ```
  caffeinate -i Rscript tools/r/experimentos/mc_canonico2.R [--ucl=best|todas] \
      > tools/r/experimentos/resultados/mc_canonico2.log 2>&1; echo "EXIT=$?"
  # si se interrumpe: relanzar igual (reanuda). Solo análisis: --fase=analizar
  ```

- **Reproducibilidad:** con la misma plataforma, el resultado es determinista (semillas fijas por réplica,
  independientes del reparto entre procesos, y un bootstrap con semilla fija).
  - `rrcov` mismo **no es reproducible entre plataformas**: esa es la motivación del experimento.

## 9. Qué NO evalúa

- **Otras plataformas:** queda pendiente repetir el mismo lote en Linux con OpenBLAS y `long double` de 80 bits.
  `canonical2` solo se ha probado ante perturbaciones de la entrada en este Mac.
- El `rrcov` modificado (ogkU con MAD) que usó la tesis, la Σ aleatoria del artículo, n = 150, π = 5 %, la rejilla
  completa de δ, el UCL por núcleo, los datos gamma, `target = "equicorrelation"`, otros α de MRCD y la selección de
  α por bootstrap (BRP/K-MRCD).
- La Fase II.
- La comparación con otras cartas (T²MOD, RMDP).
- Si la carta T²MRCD es **buena** en términos absolutos. Solo se evalúa si cambia al usar `canonical2`.

## 10. Prueba de tiempos (`--piloto`; NO válida para decidir)

- **Comando:** `Rscript tools/r/experimentos/mc_canonico2.R --piloto`
  - Salida en `tools/r/experimentos/resultados/mc_canonico2_piloto/`, con `piloto.log` y los CSV.
  - 5 réplicas por celda y B = 200.
  - Perturbación de `rrcov` en 2 réplicas por celda y de `canonical2` en 1.
- **Coste:** 56 celdas, 280 conjuntos y 728 ajustes en **186 s**, con 0 errores.

**Tiempo por ajuste (s, mediana) con 8 procesos, y extrapolación:**

| config | off | c2 | horas estimadas (corrida completa) |
|---|---|---|---|
| I_50x200 | 1.33 | 1.31 | 1.47 |
| I_100x200 | 2.67 | 2.59 | 1.63 |
| I_50x250 | 2.17 | 2.15 | 2.41 |
| I_100x250 | 3.87 | 3.87 | 2.41 |
| AR07_50x200 | 1.33 | 1.32 | 1.48 |
| I_100x20 | 0.05 | 0.05 | 0.03 |
| AR05_100x200 | 2.69 | 2.59 | 1.64 |
| **Total** | | | **11.1 h** |

**Observaciones del piloto** (descriptivas, 5 réplicas; sirven para el protocolo, no como resultado):

- **G1:** n > p idéntica en 40/40. **G2:** `canonical2` determinista con α = 0.75 en 56/56 réplicas perturbadas.
- **UCL según la definición:**
  - Con `best`: `off` frente a `c2` dan 40.70 / 40.66 (I_50x200) y 74.72 / 74.55 (I_100x200). Diferencia
    relativa ≤ 0.2 %.
  - Con las n observaciones: 700–1560. Esta diferencia es la que motiva S1.
- **Falsa alarma sobre las n con el UCL del código:** 0.26–0.30.
- **Con α = 0.75**, `best` de `c2` coincide con el de `off` solo en 0–8 % de las réplicas. En el piloto 2, con
  α = 0.5, era el 60 %.
- **Inestabilidad propia de `rrcov` con α = 0.75:**
  - Su `best` cambia ante la perturbación de 1e-14 en el 63–94 % de las réplicas.
  - disc(off′, off) = 0.06–0.19 de las observaciones.
  - disc(c2, off) = 0.13–0.22.

## Decisiones del dueño (2026-10-06, antes de la corrida completa)

- **S1:** el límite de control se calcula **como en el código de la tesis** (`--ucl=best`: cuantil empírico de los T² del subconjunto `best`). La versión del artículo (`todas`) se calcula y se reporta como **secundaria**; no entra en la regla de decisión.
- **S2:** `alpha = 0.75`, como en la tesis.
- **Réplicas:** las del protocolo (n = 50: 2000 por conjunto de evaluación; n ≥ 100: 1000). No se amplían.
- **Umbrales de `canonical2`:** fijados como en el piloto 2 (V_r: λ_i > λ_1·max(n,p)·eps; complemento: σ_j > σ_1(data)·√eps).
- El resto de supuestos (S3–S9) se aceptan tal como están escritos.

## Estado (2026-10-06)

Corrida completa **detenida por decisión del dueño** a los pocos minutos de empezar; no hay resultados. Protocolo y script quedan listos por si se retoma.

## Nota de trazabilidad

Este archivo se renombró de `2026-10-07-mc-canonico2-protocolo.md` a `2026-10-06-mc-canonico2-protocolo.md`
y se corrigieron fechas por errata: la fecha real es 2026-10-06. El contenido del pre-registro no cambió. El
comentario de cabecera de `tools/r/experimentos/mc_canonico2.R` conserva el nombre antiguo del protocolo a
propósito, para no alterar su MD5 pre-registrado.
