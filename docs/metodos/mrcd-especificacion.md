# MRCD — especificación exacta del port de `rrcov::CovMrcd` (F1b)

## Registro de cambios

- **2026-10-09** — Paso 4 (validación en Linux): **enmienda de tolerancias fuera de la plataforma de
  referencia**, decisión del dueño escrita **antes** de volver a comparar. Origen: dictamen del validador sobre
  la etapa `gate` de Docker (Linux arm64 nativo y amd64 emulado; gcc + OpenBLAS + glibc), sin defecto del port.
  (1) **D1:** segundo canal de R1 en los tests por etapa de `initset` (§6, «Segundo canal de R1»; fila nueva
  en §11): con `k ∉ required_sets(n, p)` y `min(lambda)/max(lambda) ≤ 10·p·eps`, las etapas posteriores a
  `is_lambda` y `is_ord` se registran como `DivergenciaR1`. (2) **D2:** con `target = equicorrelation`,
  `r6.center`, `r6.scale`, `r6.x` y la `U` de OGK desde cero heredan la clase B de `mW` (filas `U` y `x` de
  `doScale` de §11). (3) **D3:** casos sintéticos de `uniroot` con libm, solo en la referencia (fila nueva en
  §11). (4) Dos defectos de test corregidos con clases ya declaradas (`test_etapas_bloque2.py:115`,
  `test_zeroin.py:61`). Detalle y evidencia en **§11.1**; resumen en ADR 0006, enmienda 2026-10-09. En la
  plataforma de referencia no cambia nada. **Pendiente de confirmar por el dueño:** por la letra de D3
  («`tanh`, `cos`, `exp` u otra función de libm»), los casos `x^3 - 2` y `(x-0.3)^3` también son
  solo-referencia, porque `r_pow` con exponente 3 llama a `pow` de libm (`_rbase.py:106`); el dictamen los
  agrupaba con los aritméticos («poly…»). Se aplica la letra (más estricta en cobertura fuera, sin relajar
  nada) salvo que el dueño diga otra cosa.
- **2026-10-07** — M5, tarea T6: §3.12.9 alineada con el código implementado. (1) módulo real `pymrcd._qn_ext`
  (no `_qnc`) y API con búfer de salida `out`; (2) hilos por defecto resueltos en C; (3) fallo de `pthread_create`
  ⇒ `OSError` (decisión del dueño; sustituye a e.8); (4) `R_qsort`/`rPsort`/`whimed_i` se prueban contra la
  transliteración literal en `tests/` (más contraste con R ad hoc, 0 diferencias), los fixtures R de esas primitivas
  son deuda; (5) A1 «CI con sanitizers» es deuda (corrida manual del validador: 200 000 vectores sin avisos); (6) el
  test de `U` con p > 60 compara un bloque de 60 columnas; (7) riesgo residual de `CFLAGS` externas. Resultados M5
  y P1=A en el apartado «Estado de la implementación» de §3.12.9.
- **2026-10-07** — M5, tarea T1: especificación de `qn0` en C. Nueva **§3.12.9** (tabla original → port,
  opciones de compilación sin FMA, análisis de `±0`, prueba de `j ≤ n`, hilos, tolerancias y ahorros) y §7
  acotada (la extensión C aprobada es la única excepción a «sin Numba/Cython»). Evidencia: sondas S15–S19 (en
  §3.12.9). Hallazgos: (1) el binario del oráculo no tiene FMA en `_qn0`, `_Qn0`, `_whimed_i`, `_R_qsort` ni
  `_Rf_rPsort`, pero `clang` contrae por defecto `k_L` y `(s*s − d*d)/4`: `-ffp-contract=off` es obligatorio;
  (2) la versión numpy actual da el **signo de cero** distinto al de R en ≈19 % de los casos con `±0` (nunca el
  valor) y de forma **no determinista** (`np.sort(axis=0)`); no afecta a ninguna salida de `cov_mrcd`; (3) con el
  `k` por defecto `1 ≤ j ≤ n` en la rama «no encontrado» (demostrado; `j = n` se alcanza) y la acotación de
  `qn_sn.c:280-290` es inalcanzable. Se extrajeron `sort.c`, `qsort.c` y `qsort-body.c` del tarball de R.
- **2026-10-06** — Correcciones tras el bloque 1 del convertidor, que refutó supuestos de la sonda S3. Evidencia:
  sondas **S11–S14** (anexo A) y el código que ya coincide con R en `packages/pymrcd/src/pymrcd/`.
  1. **FMA.** El R del oráculo (`clang -O2`, arm64) fusiona `a*b + c` en `fmadd` en `cov.c`, `zeroin.c`,
     `qnorm.c` y `simple_matprod`/`simple_crossprod` (`array.c`); `cov_na_1` vectoriza en bloques de 8 sin FMA
     y la cola con FMA. La afirmación de §3.12.4 («secuencial sin FMA coincide bit a bit») era **falsa**.
     Nueva §3.12.8 y trampa T26.
  2. **`eigen`.** `scipy.linalg.lapack.dsyevr` es el de Accelerate, no el Rlapack 3.12.1 de R: no coincide bit a
     bit (S12). Se acepta con tolerancia B (decisión del dueño). Corregidos §3.12.6, §6, T3, T13, T22, §11.
  3. **Alineación.** `dgemv('T')` de Accelerate da bits distintos según la alineación del operando; R lo tiene a
     `48 mod 64` bytes (S13). §3.12.6 y T27.
  4. **LAPACK.** `scipy.linalg.lapack.dpotrf/dpotri/dgetrf` son de Accelerate; hace falta el port de
     referencia de `dlapack.f` sobre el BLAS de scipy (`_rlapack.py`) (S14). §3.12.6 y T28.
  5. **R1.** §6 y la fila S3b alineadas con el hallazgo final: con p ≥ n dependen del redondeo los conjuntos 1–5;
     el 5 ya desde p ≥ ceil(n/2); solo el 6 es estable.
  6. **§12.** P1–P8 marcadas como resueltas; nuevas decisiones: `eigen` con tolerancia B y port de
     `qchisq`/`pgamma` de nmath para `.MCDcons` (corrige §3.6, T21 y §11).
  7. **Fixtures.** Constan dos errores del contrato de exportación de R (§10).

Documento de trabajo del agente **analista-port**. Es la referencia que siguen `convertidor-python` (port),
`ingeniero-r` (oráculo e intermedios) y `validador-estadistico`. **La referencia es el código**: cada
afirmación lleva `archivo:línea`. Donde algo se comprobó ejecutando R, se indica como **[sonda S#]** (anexo A).

- **Referencia:** `rrcov` 1.7-7 **oficial de CRAN** (`referencias/rrcov-1.7-7/`, MD5 de `R/detmrcd.R`
  `d56485337b83f927bba70002357be341`, verificado), `robustbase` 0.99-6, R 4.5.2.
- **Oráculo verificado [S0]:** R 4.5.2 `aarch64-apple-darwin20`; BLAS = **Accelerate** (vecLib); LAPACK =
  **Rlapack 3.12.1 de R** (Fortran de referencia); `capabilities("long.double") == FALSE`,
  `.Machine$sizeof.longdouble == 8` ⇒ en este oráculo **`LDOUBLE` es `double`**. `rrcov` cargado desde
  `referencias/R-lib` (versión 1.7.7, sin `ogkU` ni `only.values`: 0 coincidencias en `deparse(.detmrcd)`).
  `robustbase` 0.99-6 del sistema (idéntico a `referencias/robustbase-0.99-6/`).
- **Entorno Python medido:** numpy 2.5.3 y scipy 1.18.1, ambos sobre Accelerate (BLAS y LAPACK).

## 0. Abreviaturas de rutas

| Abreviatura | Ruta |
| --- | --- |
| `detmrcd.R`, `CovMrcd.R`, `CovControl.R`, `AllClasses.R` | `referencias/rrcov-1.7-7/R/` |
| `qnsn.R`, `rb/detmcd.R`, `OGK.R`, `comedian.R`, `covMcd.R` | `referencias/robustbase-0.99-6/R/` |
| `qn_sn.c`, `wgt_himed_templ.h`, `rowMedians_TYPE-template.h` | `referencias/robustbase-0.99-6/src/` |
| `median.R`, `nlm.R`, `cor.R`, `mahalanobis.R`, `quantile.R` | `referencias/R-4.5.2/src/library/stats/R/` |
| `cov.c`, `zeroin.c`, `optimize.c` | `referencias/R-4.5.2/src/library/stats/src/` |
| `eigen.R`, `sort.R`, `rank.R`, `scale.R`, `sweep.R`, `det.R`, `chol.R`, `seq.R`, `all.equal.R` | `referencias/R-4.5.2/src/library/base/R/` |
| `array.c` | `referencias/R-4.5.2/src/main/array.c` |
| `Lapack.c` | `referencias/R-4.5.2/src/modules/lapack/Lapack.c` |
| `qnorm.c` | `referencias/R-4.5.2/src/nmath/qnorm.c` |
| `[tar]summary.c`, `[tar]sort.c`, `[tar]radixsort.c`, `[tar]arithmetic.c`, `[tar]arithmetic.h`, `[tar]Defn.h` | dentro de `referencias/R-4.5.2.tar.gz` (`src/main/…`, `src/include/Defn.h`); no están extraídos en `referencias/R-4.5.2/src/main/` |

Notación: índices de R en base 1; en el pseudocódigo Python, base 0. `f32(z)` = `float(np.float32(z))`
(redondeo al más cercano, empates a par). `seqsum(v)` = suma **secuencial** izquierda→derecha en `float64`
(p. ej. `np.cumsum(v)[-1]`, o acumulador explícito); **nunca** `np.sum`/`sum` de numpy, que es por pares.

---

## 1. Grafo de llamadas

```
CovMrcd(x, …, control=CovControlMrcd())                         CovMrcd.R:1-82
 ├─ filtro de filas: is.finite(x %*% rep.int(1, ncol(x)))       CovMrcd.R:19-20   → matprod/dgemv (array.c:788-843)
 ├─ .detmrcd(x, alpha, h, hsets.init=initHsets, save.hsets,     CovMrcd.R:27-31
 │           rho, maxcond, target=0|1, maxcsteps, trace)        detmrcd.R:26-637
 │   ├─ h/alpha, obj = det(.)^(1/p)                              detmrcd.R:393-414 → det.R:25-29, Lapack.c:1403-1458 (dgetrf), [tar]arithmetic.h:35 (R_POW)
 │   ├─ 1. vmx = apply(mX,1,median)                              detmrcd.R:417     → median.R:21-33 → [tar]summary.c:479-518 (mean)
 │   │     vsd = apply(mX,1,Qn); vsd[vsd<minscale] <- minscale  detmrcd.R:418-419 → qnsn.R:20-68 → qn_sn.c:98-296 → wgt_himed_templ.h:27-122
 │   │     mU = scale(x, vmx, vsd)                               detmrcd.R:421     → scale.R:21-58 → sweep.R
 │   ├─ .TargetCorr(mX, target)                                  detmrcd.R:207-229 (target=1: cor spearman → cor.R:21-71, rank.R, cov.c; sin; mean)
 │   ├─ target==1: eigenEQ, mW = mU %*% mQ %*% misqL             detmrcd.R:231-248, 426-434
 │   ├─ mT <- diag(p)                                            detmrcd.R:436
 │   ├─ r6pack(t(mX), h, full.h=FALSE, adjust.eignevalues=FALSE, scaled=FALSE, scalefn=Qn)   detmrcd.R:446 (r6pack LOCAL, detmrcd.R:57-197)
 │   │   ├─ doScale(x, median, Qn)                               detmrcd.R:123-125 → rb/detmcd.R:229-289 (+ non0Q → quantile.R:57-67, qnorm.c)
 │   │   ├─ 1 tanh → cor → eigen(sym)                            detmrcd.R:132-135
 │   │   ├─ 2 cor spearman → eigen(sym)                          detmrcd.R:138-140
 │   │   ├─ 3 qnorm(normal scores) → cor(complete.obs) → eigen   detmrcd.R:143-146 → qnorm.c:47+
 │   │   ├─ 4 SCM = crossprod(x.nrmd) → eigen                    detmrcd.R:149-155 → array.c:983-1020 (dsyrk)
 │   │   ├─ 5 BACON: order(znorm), cov(x[Hinit,]) → eigen        detmrcd.R:158-163
 │   │   ├─ 6 ogkscatter(x, Qn) → eigen                          detmrcd.R:84-111, 166-167
 │   │   ├─ initset(x, Qn, P, h) ×6                              detmrcd.R:65-76 → doScale, colMedians (comedian.R:21-22 → rowMedians_TYPE-template.h), mahalanobisD (OGK.R:48-53), sort.list (sort.R:240-275 → radix)
 │   │   └─ return(hsets)  (adjust.eignevalues=FALSE)            detmrcd.R:173-174
 │   ├─ hsets.init <- hsets.init[1:h, ]                          detmrcd.R:459
 │   ├─ scfac = robustbase::.MCDcons(p, h/n)                     detmrcd.R:460 → covMcd.R:602-607 (qchisq, pgamma)
 │   ├─ 3.4 rho_k por conjunto: eigen(scfac*mS) → uniroot(fncond)│ rejilla   detmrcd.R:465-515 → eigen.R:45-74 (isSymmetric eigen.R:22-43, all.equal.R:99-174; La_rs Lapack.c:166-237), nlm.R:55-170 → optimize.c:331-386 → zeroin.c:89-194
 │   ├─ 3.5 cutoffrho, rho, initV, setsV                         detmrcd.R:518-535
 │   ├─ 3.6 .cstep_mrcd ×(1 + |setsV|)                           detmrcd.R:342-383, 547-575
 │   │   ├─ .RCOV(invert=TRUE)                                   detmrcd.R:269-290 → chol (chol.R:21-29, Lapack.c:1078-1104) / chol2inv (Lapack.c:1139-1182) | .InvSMW (detmrcd.R:302-317)
 │   │   └─ sort.int(vdst, index.return=TRUE)                    detmrcd.R:361, 372 → sort.R:80-115 → radix ([tar]radixsort.c)
 │   ├─ final: weightedScov /(h-1), MRCDcov, iMRCDcov             detmrcd.R:577-593
 │   ├─ retro-transformación (target=1: mQ, msqL; luego Dx, vmx)  detmrcd.R:599-615
 │   ├─ dist = mahalanobis(t(mX)…) [NO usado por CovMrcd]         detmrcd.R:618
 │   └─ mcdestimate = determinant(MRCDcov)$modulus                detmrcd.R:619 → Lapack.c:1403-1458
 ├─ mah = mahalanobis(x, initmean, icov, inverted=TRUE)          CovMrcd.R:46 → mahalanobis.R:30-43
 └─ new("CovMrcd", …)                                            CovMrcd.R:66-81
```

## 2. Defaults

| Parámetro | Default | Origen | Nota |
| --- | --- | --- | --- |
| `alpha` | `0.5` | `CovControl.R:22`; prototipo `AllClasses.R:138` | `CovMrcd` lo toma de `control@alpha` (`CovMrcd.R:2`) |
| `h` | `NULL` | `CovControl.R:23`; `AllClasses.R:139` | si no es `NULL`, `alpha <- h/n` (`detmrcd.R:396`) |
| `maxcsteps` | `200` | `CovControl.R:24`; `AllClasses.R:140` | |
| `rho` | `NULL` | `CovControl.R:25`; `AllClasses.R:141` | `NULL` ⇒ selección automática (`detmrcd.R:465`) |
| `target` | `"identity"` | `CovControl.R:26` (`match.arg`, `:34`); `AllClasses.R:142` | `CovMrcd` lo mapea a `0` si `== "identity"`, si no a `1` (`CovMrcd.R:29`) |
| `maxcond` | `50` | `CovControl.R:27`; `AllClasses.R:143` | |
| `trace` | `FALSE` | `CovControl.R:28`; `AllClasses.R:144` | solo `cat`, sin efecto numérico |
| `initHsets` | `NULL` | `CovMrcd.R:5` | |
| `save.hsets` | `FALSE` | `CovMrcd.R:5` | el objeto S4 **no** guarda `initHsets` (`CovMrcd.R:66-81`) |
| `minscale` | `0.001` | `detmrcd.R:27` | no expuesto por `CovMrcd` |
| `mindet` | `0` | `detmrcd.R:388` | no se usa en ningún cálculo (`detmrcd.R:207-229`) |
| `objective` | `"geom"` | `detmrcd.R:389` | `obj(x) = det(x)^(1/p)` (`detmrcd.R:410-413`) |
| `tol` de `uniroot` | `.Machine$double.eps^0.25` = `2^-13` exacto | `nlm.R:60` | |
| `maxiter` de `uniroot` | `1000` | `nlm.R:60` | |
| `scalefn` de r6pack | `Qn` | `detmrcd.R:446` | Qn de `robustbase` (rrcov `import(robustbase)`, `NAMESPACE`) |

---

## 3. Especificación por función, en orden de ejecución

### 3.1 `CovMrcd` (`CovMrcd.R:1-82`)

Entradas: `x` matriz `n0 × p` `float64`. Pasos:

1. Conversión `data.frame`/vector (`CovMrcd.R:12-16`): capa de API, no numérica.
2. `ok <- is.finite(x %*% rep.int(1, ncol(x)))` (`:19`); `x <- x[ok, , drop=FALSE]` (`:20`). El producto es
   `matprod` con `ncy==1` ⇒ `dgemv('N')` si no hay NaN/Inf, si los hay `simple_matprod` (`array.c:798-833`).
   Python: `ok = np.isfinite(r_matvec(x, np.ones(p)))`. Se descarta cualquier fila con NaN/±Inf **y** cualquier fila
   finita cuya suma desborde a ±Inf (comportamiento de R, se replica).
3. `.detmrcd(...)` con `target = 0 if target == "identity" else 1` (`:27-31`).
4. Salidas (`:38-46`, `:66-81`):
   - `center = as.vector(mcd$initmean)` (p), `cov = mcd$initcovariance` (p×p), `icov = mcd$icov` (p×p),
     `rho`, `target = mcd$target` (p×p), `cnp2 = mcd$calpha` (= `scfac`), `crit = mcd$mcdestimate`,
     `best = sort(mcd$best)` (h, base 1), `alpha`, `quan = h`, `n.obs = n`, `X = x` filtrada.
   - `mah = mahalanobis(x, mcd$initmean, mcd$icov, inverted=TRUE)` (`:46`) sobre la **x filtrada original**
     (no sobre la `mX` reconstruida de `detmrcd.R:610`; ver §8).
   - `iBest`, `n.csteps`, `initHsets` van a la lista `ans` (`:57`) pero **no** al objeto S4: para intermedios
     hay que llamar a `rrcov:::.detmrcd` directamente.

### 3.2 `.detmrcd`: preámbulo (`detmrcd.R:385-414`)

```
mX = x.T                                   # :385   (p × n)
n, p = mX.shape[1], mX.shape[0]            # :393-394
if h is not None: alpha = h / n            # :396
elif alpha is not None: h = ceil(alpha*n)  # :397   (producto IEEE y ceil, idéntico en Python)
if alpha < 0.5 or alpha > 1: error         # :400-401
h = int(h)                                 # :404   (as.integer trunca)
obj(M) = r_pow(det(M), 1/p)                # :410-413
```
`det(M)` = `sign * exp(modulus)` con `modulus = Σ log|U_ii|` de `dgetrf` (`det.R:25-29`, `Lapack.c:1415-1436`);
si `dgetrf` devuelve `info>0`, `modulus=-Inf` ⇒ `det=0`. `r_pow` = `R_POW` (`[tar]arithmetic.h:35`,
`[tar]arithmetic.c:204-247`): `y==2 → x*x`; `x==1 o y==0 → 1`; `x==0 → 0 (y>0)`; finito → `pow(x,y)` de libm
(Python: `math.pow`). **No** sustituir por `exp(modulus/p)`: R subdesborda a `0` (o desborda a `Inf`) y entonces
todos los objetivos empatan (ver trampa T19).

### 3.3 Paso 1: estandarización (`detmrcd.R:416-422`)

```
vmx = [r_median(mX[i, :]) for i in range(p)]          # :417  median.R:21-33
vsd = [Qn(mX[i, :]) for i in range(p)]                # :418  sobre los datos SIN centrar
vsd[vsd < minscale] = minscale                         # :419  (minscale = 0.001)
Dx  = diag(vsd)                                        # :420
mU  = (x - vmx[None, :]) / vsd[None, :]                # :421  scale.R:31-53: sweep "-" y luego sweep "/" (dos redondeos)
mX  = mU.T                                             # :422
```
Python: elemento a elemento, exacto en cualquier plataforma.

### 3.4 Objetivo (`.TargetCorr`, `detmrcd.R:207-229`) y transformación (`:423-436`)

- `target == 0`: `R = I` (`:212-213`).
- `target == 1` (`:214-227`):
  ```
  cortmp  = r_cor_spearman(mU)                    # :217  = rank por columna + cor pearson (cor.R:66-70)
  cortmp  = sin((0.5*pi) * cortmp)                # :218  1/2*pi == 0.5*pi exacto; usar math.sin por elemento
  vals    = [cortmp[i, j] for j in range(p) for i in range(j)]   # :219 upper.tri en ORDEN COLUMNA
  constcor = r_mean(vals)                         # :219  media de dos pasadas ([tar]summary.c:479-518)
  b = min(0, -1/(p-1) + 0.01)
  if constcor <= b: constcor = b                  # :222-224
  R = constcor * J + (1 - constcor) * I           # :225-226  (dos productos escalar×matriz y suma)
  ```
  Orden de `vals`: `rows, cols = np.tril_indices(p, -1); vals = cortmp[cols, rows]` reproduce el orden de
  columna de R: (0,1),(0,2),(1,2),(0,3)…
- `target == 1` (`:426-434`): `eigenEQ(mT)` (`:231-248`) **no** usa LAPACK:
  ```
  rho_t = T[0, 1]; d = p
  H = zeros(d, d); H[:, 0] = 1/sqrt(d)
  for j in 2..d (base 1):  H[0:j-1, j-1] = 1/sqrt(j*(j-1)); H[j-1, j-1] = -(j-1)/sqrt(j*(j-1))
  values = [1 + (d-1)*rho_t] + [1 - rho_t]*(d-1)
  ```
  `mQ = H`; `msqL = diag(sqrt(values))`; `misqL = diag(r_pow(sqrt(values), -1))` (`:431`, `pow(·,-1)`, no `1/x`);
  `mW = (mU %*% mQ) %*% misqL` (`:432`, asociatividad izquierda); `mX = t(mW)` (`:433`).
  El producto por la diagonal se puede hacer por columnas (`(A·d_j)`) **con resultado bit a bit idéntico** a
  `dgemm` con la matriz diagonal (los demás términos son `0·a = 0` exactos; ver T9). `mU %*% mQ` sí es `dgemm`.
- `mT <- diag(p)` (`:436`) **siempre**, para cualquier `target`: a partir de aquí todo trabaja con `T = I` en el
  espacio transformado. Consecuencia: la rama no-identidad de `fncond` es código muerto (§8).

### 3.5 `r6pack` local (`detmrcd.R:57-197`), llamada en `:446`

Se ejecuta **la definición local** de `detmrcd.R` (no `robustbase::r6pack`). Argumentos efectivos:
`x = t(mX)` (n×p: `mU` si `target=0`, `mW` si `target=1`), `h`, `full.h=FALSE`, `adjust.eignevalues=FALSE`,
`scaled=FALSE`, `scalefn=Qn`.

1. **Re-estandarización** (`:123-125`): `x <- doScale(x, center=median, scale=Qn)$x`
   (`rb/detmcd.R:229-289`): `center_j = r_median(x[:, j])` (`:237`); `x = x - center` (`:249`);
   `scale_j = Qn(x[:, j])` **sobre la columna ya centrada** (`:253`); si algún `scale_j == 0` (`:268`) se
   sustituye con `non0Q` (`:273-283`, ver §3.12.5); `x = x / scale` (`:285`). Error si `scale` NA o `< 0`
   (`:266-267`).
2. `nsets = 6`, `hsets` entero `h × 6` (`:127-128`).
3. **Conjunto 1** (`:132-135`): `y1 = tanh(x)` (**`math.tanh` por elemento**, ver T12); `R1 = r_cor(y1)`;
   `P = r_eigen_sym(R1).vectors`; `hsets[:,0] = initset(x, P, h)`.
4. **Conjunto 2** (`:138-140`): `R2 = r_cor(r_rank_cols(x))` (Spearman = Pearson de rangos promedio,
   `cor.R:66-70`); `P = eigvec(R2)`; `initset`.
5. **Conjunto 3** (`:143-146`): `y3 = r_qnorm((r_rank_cols(x) - 1/3) / (n + 1/3))`; `R3 = r_cor(y3)`
   (`use="complete.obs"` ⇒ `cov_complete1`, `cov.c:244-301`; misma aritmética que `cov_na_1`); `P`; `initset`.
6. **Conjunto 4** (`:149-155`): `znorm = sqrt(r_rowsums(x*x))`; `ii = znorm > 2.220446049250313e-16`;
   `x_nrmd = x.copy(); x_nrmd[ii, :] = x[ii, :] / znorm[ii, None]`; `SCM = r_crossprod(x_nrmd)` (**`dsyrk`
   'U','T' + espejo**, `array.c:983-1020`; ver T8); `P = eigvec(SCM)`; `initset`.
7. **Conjunto 5** (`:158-163`): `ind5 = r_order(znorm)` (estable); `half = ceil(n/2)`; `Hinit = ind5[:half]`;
   `covx = r_cov(x[Hinit, :])` (**filas en el orden de `Hinit`**, que fija el orden de las sumas);
   `P = eigvec(covx)`; `initset`.
8. **Conjunto 6** (`:166-167`): `P = ogkscatter(x, Qn)` (§3.5.2); `initset`.
9. `return hsets` (`:173-174`). Todo `:176-196` es código muerto (§8).

#### 3.5.1 `initset(data, scalefn, P, h)` (`detmrcd.R:65-76`)

```
lam        = doScale(r_matprod(data, P), median, Qn).scale          # :70  (n×p)·(p×p) dgemm
sqrtcov    = r_matprod(P, lam[:, None] * P.T)                       # :71  lambda * t(P): recicla lambda por filas de t(P)
sqrtinvcov = r_matprod(P, P.T / lam[:, None])                       # :72  DIVISIÓN, no producto por 1/lambda
estloc     = r_vecmat(r_colmedians(r_matprod(data, sqrtinvcov)), sqrtcov)   # :73 colMedians (C) y luego vector %*% matriz = dgemv('T')
centeredx  = r_matprod(data - estloc[None, :], P)                   # :74  rep(estloc, each=n) = estloc en cada fila
dist       = r_rowsums((centeredx / lam[None, :]) ** 2)  # **2 = x*x      # :75  mahalanobisD(·, FALSE, lam), OGK.R:48-53
return r_order(dist)[:h] + 1                                        # :75  sort.list → radix estable
```
Atención: `colMedians` (C, `(a+b)/2`, `rowMedians_TYPE-template.h:138`) ≠ `median()` de R (media de dos pasadas)
para longitud par (T4). `t(P)` debe materializarse como matriz (orden Fortran) para replicar `dgemm('N','N')` (T8).

#### 3.5.2 `ogkscatter(Y, Qn, only.P=TRUE)` (`detmrcd.R:84-111`)

```
U = eye(p)                                                     # :87  diagonal = 1 (NO Qn(2Y_i)^2/4)
for i in 1..p-1 (base 0):                                      # :89  i = 2:p en base 1
    for j in 0..i-1:                                           # :91-92
        s = Qn(Y[:, i] + Y[:, j]); d = Qn(Y[:, i] - Y[:, j])   # :94  orientación Y_i − Y_j con i > j (¡Qn(-v) ≠ Qn(v) bit a bit!, T2)
        U[i, j] = (s*s - d*d) / 4                              # :94  ^2 = x*x (R_POW); resta; /4
    U[0:i, i] = U[i, 0:i]                                      # :97
P = r_eigen_sym(U).vectors                                     # :101
```
`:105-110` (rama `only.P=FALSE`) es código muerto. Vectorización exacta: §7.

### 3.6 Factor de consistencia (`detmrcd.R:459-460`)

`hsets.init <- hsets.init[1:h, ]` (`:459`; conserva el **orden de distancia** de `initset`, no ordenado).
`scfac = .MCDcons(p, h/n)` (`covMcd.R:602-607`): `q = qchisq(h/n, p)`; `caI = pgamma(q/2, p/2 + 1) / alpha`;
`scfac = 1/caI`. Python propuesto: `q = scipy.stats.chi2.ppf(a, p)`; `pg = scipy.special.gammainc(p/2+1, q/2)`;
`scfac = 1/(pg/a)`. **Medido [S5]:** diferencia relativa máxima con R `6.5e-15` (q: `1.8e-15`, pgamma: `6.5e-15`)
en una rejilla p ∈ {1…1000}, n ∈ {20,51,100,1000}, α ∈ {0.5,0.75,0.9}. Exactitud bit a bit exigiría portar
`nmath/qchisq.c`, `qgamma.c`, `pgamma.c` (pregunta P3).
**Actualización 2026-10-06:** el dueño decidió portar `qchisq`/`pgamma` de nmath (§12, D10); la vía scipy
queda solo como oráculo independiente en tests. Las contracciones `a*b + c` → `fmadd` de `qgamma.c`/`pgamma.c`
(≈100) **ya están localizadas** por desensamblado de `libR.dylib` (§3.12.8) y reproducidas en
`packages/pymrcd/src/pymrcd/_nmath.py`.

### 3.7 Selección de `rho` (`detmrcd.R:462-539`)

Solo si `rho is None` (`:465`). Para cada `k = 1..6` (`:466-515`):

```
idx  = hsets_init[:, k] - 1                     # orden de la columna, tal cual (fija el orden de suma)
XS   = mX[:, idx]                               # :467  p×h
mu   = r_rowmeans(XS)                           # :468  suma secuencial por columnas, luego /h (array.c:2001-2098)
mE   = XS - mu[:, None]                         # :469
mS   = r_matprod(mE, mE.T_materializada) / (h - 1)   # :470  dgemm, NO syrk; divisor h-1
A    = scfac * mS                               # :473
w    = r_eigen(A).values                        # :473  eigen() sin symmetric= (T13)
e1, ep = min(w), max(w)                         # :474-475
fncond(r) = (r + (1-r)*ep) / (r + (1-r)*e1) - maxcond          # :479-484
try:    rho6[k] = r_uniroot(fncond, 1e-5, 0.99).root            # :495, :500
except: grid = [1e-6] + list(min(0.001 + arange(990)*0.001, 0.99)) + [0.999999]   # :503, seq.R:88-96
        og   = abs(fncond(grid))                                # :505 (rama identidad; siempre, ver §8)
        rho6[k] = min(grid[og == min(og)])                      # :506, :511
```
- `all(mT == diag(p))` (`:472`, `:504`) es **siempre TRUE** por `:436`.
- `r_uniroot` = `uniroot` de R (`nlm.R:55-170`) con `lower=1e-5, upper=0.99`: evalúa `f.lower=f(lower)` y luego
  `f.upper=f(upper)` (`:57`, forzadas en `:66-67`); **error** (⇒ rejilla) si alguna es NA/NaN (`:66-67`) o si
  `!isTRUE(sign(f.lower)*sign(f.upper) <= 0)` (`:138-141`); `extendInt="no"` ⇒ sin extensión (`:71`, `:79-80`);
  pasa `truncate(f) = max(min(f, DBL_MAX), -DBL_MAX)` (`:75-78`) a `R_zeroin2` con `tol=2^-13`, `maxiter=1000`
  (`:154-156`). Port **iteración por iteración** de `R_zeroin2` (`zeroin.c:89-194`), **con las tres contracciones
  FMA del binario** (§3.12.8), con la envoltura `fcn2`
  (`optimize.c:292-329`: valor no finito ⇒ `-DBL_MAX` si `-Inf`, si no `+DBL_MAX`). No convergencia ⇒ solo
  *warning* (`nlm.R:159-165`), se usa la raíz. `f(root)` se evalúa (`nlm.R:168`) sin efecto.
- Rejilla: `seq(0.001, 0.99, by=0.001)` = `from + (0:n)*by` con `n = as.integer((to-from)/by + 1e-10) = 989`,
  luego `pmin(x, to)` (`seq.R:88-96`); total 992 valores. **[S4]** `identical(g[2:991], 0.001+(0:989)*0.001)`.
- Camino frecuente: datos bien condicionados (n ≫ p, poca correlación) ⇒ `f(lower) < 0` y `f(upper) < 0` ⇒ error ⇒
  rejilla ⇒ `rho_k = 1e-6`. **[S6]** `n=100, p=5` iid ⇒ `rho = 9.9999999999999995e-07`.

Después (`:518-535`):
```
cutoff = max(0.1, r_median(rho6))             # :518  mediana de 6 = media de dos pasadas de los centrales
rho    = max(rho6[rho6 <= cutoff])            # :519
Vsel   = [k if rho6[k] <= cutoff else NA]     # :527-528 ; si todos NA → error "None of the initial subsets is well-conditioned" (:529-531)
initV  = min(Vsel no NA)                      # :533
setsV  = Vsel no NA sin su primer elemento    # :534-535  (orden creciente)
```
Si `rho` viene dado (`:536-539`): `setsV = 1:ncol(hsets.init)` e `initV = 1` ⇒ **el conjunto 1 se procesa dos
veces** (T17).

### 3.8 C-steps: `.cstep_mrcd` (`detmrcd.R:342-383`), `.RCOV` (`:269-290`), `.InvSMW` (`:302-317`)

```
def cstep(mX, rho, h, scfac, index, maxcsteps):         # mT = I, target sin uso
    n = mX.shape[1]
    XX = mX[:, index-1]                                 # :350  orden de 'index' tal cual
    vMu = r_rowmeans(XX)                                # :353
    ret = RCOV(XX, vMu, rho, scfac, invert=True)        # :356
    mIS = ret.inv
    D = mX - vMu[:, None]
    vdst = diag(r_matprod(D.T, r_matprod(mIS, D)))      # :360  (ver T15 sobre el cálculo completo n×n)
    index = sort(r_order(vdst)[:h] + 1)                 # :361  sort.int(index.return=TRUE) → radix estable
    it = 1
    while it < maxcsteps:                               # :365
        XX = mX[:, index-1]; vMu = r_rowmeans(XX)       # :366-367
        ret = RCOV(XX, vMu, rho, scfac, invert=True)    # :368
        mIS = ret.inv
        D = mX - vMu[:, None]
        vdst = diag(r_matprod(D.T, r_matprod(mIS, D)))  # :371
        nndex = sort(r_order(vdst)[:h] + 1)             # :372
        if all(nndex == index): break                   # :374-375
        index = nndex; it += 1                          # :377-378
    return dict(index=index, numit=it, mu=vMu, cov=ret.rcov, icov=ret.inv, dist=vdst, scfac=scfac)  # :381-382

def RCOV(XX, vMu, rho, scfac, invert):                  # :269-290
    mE = XX - vMu[:, None]; hh = mE.shape[1]; p = mE.shape[0]
    mS = r_matprod(mE, mE.T_mat) / hh                   # :274  divisor h (¡no h-1!)
    rcov = rho*I + ((1-rho)*scfac) * mS                 # :275  ((1-rho)*scfac) primero (asociatividad izquierda)
    if p > hh:                                          # :278  hh = h
        inv = InvSMW(rho, nu=(1-rho)*scfac, mU=mE/sqrt(hh))      # :279-281  DIVISIÓN por sqrt(h)
    else:
        inv = r_chol2inv(r_chol(rcov))                  # :283
    return rcov, mS, inv

def InvSMW(rho, nu, mU):                                # :302-317 con mT = I
    # vD = 1, imD = I, R = I, constcor = R[2,1] = 0, imR = 1/(1-0)*(I - 0/(1+(p-1)*0)*J) = I  (exacto)
    r   = r_pow(rho, -1)                                # :313  pow(rho,-1)
    A   = r * mU                                        # imB %*% mU   (exacto, T9)
    G   = r_matprod(mU.T_mat, A)                        # :314  t(mU) %*% (imB %*% mU)
    Tm  = r_chol2inv(r_chol(eye(hh) + nu * G))          # :314  diag(pp[2]) + nu*(...)
    B   = r_matprod(r_matprod(A, nu * Tm), mU.T_mat * r)   # :316  ((imB%*%mU) %*% (nu*Temp)) %*% (t(mU)%*%imB)
    return r*I - B                                      # :316  imB - (...)
```
- Si se sale por `maxcsteps` sin converger (o si `maxcsteps <= 1`), `index` devuelto es el **nuevo** pero `mu`,
  `cov`, `icov` son los de la iteración anterior (`:377`, `:381`). Se replica tal cual (T18).
- `.InvSMW` con `p>1` necesita `R[2,1]` (`:309`); con `p=1` nunca se llega (p>h imposible si h≥1).

### 3.9 Selección del mejor (`detmrcd.R:546-575`)

```
hset_csteps = zeros(nsets, int)                     # :546
ret = cstep(..., index=hsets_init[:, initV])        # :547
objret = obj(ret.cov); hindex = ret.index; best6 = [initV]     # :548-550
for k in setsV:                                     # :551
    tmp = cstep(..., index=hsets_init[:, k])        # :559
    objtmp = obj(tmp.cov); hset_csteps[k] = tmp.numit           # :560-561
    if objtmp < objret: ret, objret, hindex, best6 = tmp, objtmp, tmp.index, [k]   # :564-570
    elif objtmp == objret: best6.append(k)          # :571-572  igualdad EXACTA
```
`n.csteps[initV]` queda en `0` (no se registra) **[S6]**: `n.csteps = 0,1,2,3,2,3`.

### 3.10 Estimación final y retro-transformación (`detmrcd.R:577-619`)

```
c_alpha = ret.scfac                                         # :577
mE = mX[:, hindex-1] - ret.mu[:, None]                      # :578  ret.mu (puede no ser la media de hindex, T18)
W  = r_matprod(mE, mE.T_mat) / (h - 1)                      # :579  divisor h-1
MRCDmu  = r_rowmeans(mX[:, hindex-1])                       # :583
MRCDcov = rho*I + ((1-rho)*c_alpha) * W                     # :584
if p > n:  (n = número de observaciones, no h)              # :588  'target <= 1' siempre TRUE
    iMRCDcov = InvSMW(rho, nu=(1-rho)*c_alpha, mU=mE/sqrt(h-1))   # :589-591
else:
    iMRCDcov = r_chol2inv(r_chol(MRCDcov))                  # :593
if target == 1:                                             # :599-607  (asociatividad izquierda, dgemm reales)
    MRCDmu   = r_matvec(r_matprod(mQ, msqL), MRCDmu)        # :603
    MRCDcov  = (((mQ·msqL)·MRCDcov)·msqL)·t(mQ)             # :604
    iMRCDcov = (((mQ·misqL)·iMRCDcov)·misqL)·t(mQ)          # :605
    mT       = (((mQ·msqL)·I)·msqL)·t(mQ)                   # :606  (mT = I en este punto)
# :610-615 (Dx diagonal ⇒ escalados exactos, T9)
MRCDmu   = vsd * MRCDmu + vmx                               # :611  Dx %*% MRCDmu (dgemv con diagonal = producto exacto) + vmx
MRCDcov  = (vsd[:,None] * MRCDcov) * vsd[None,:]            # :612
mT       = (vsd[:,None] * mT) * vsd[None,:]                 # :613
iv       = 1 / vsd                                          # :614  diag(1/diag(Dx))
iMRCDcov = (iv[:,None] * iMRCDcov) * iv[None,:]             # :615  producto por recíprocos, NO división
crit     = r_logdet(MRCDcov)                                # :619  modulus de dgetrf (suma secuencial de log|U_ii|)
```
`:601`, `:610` (reconstrucción de `mX`) y `:618` (`dist`) no afectan a ninguna salida de `CovMrcd` (§8).

### 3.11 Salida `mah` (`CovMrcd.R:46`, `mahalanobis.R:30-43`)

`xc = x - center[None,:]` (`sweep`), `mah = r_rowsums(r_matprod(xc, icov) * xc)`.

### 3.12 Primitivas (R/C → Python)

#### 3.12.1 `Qn` (`qnsn.R:20-68`) y `qn0` (`qn_sn.c:118-296`)

```
def Qn(x):
    if any NaN: return NaN          # :27   (devuelve NA)
    n = len(x); if n == 0: NaN; if n == 1: return 0.0       # :28-29
    k = comb(n//2 + 1, 2)                                  # :21, :33-45 (dflt.k ⇒ constant 2.21914)
    r = 2.21914 * qn0(x, k)                                # :44, :48-49
    if n <= 12: return r * TAB[n - 2]                      # :56-63 ; TAB = (.399356,.99365,.51321,.84401,.61220,.85877,.66993,.87344,.72014,.88906,.75743)
    return r / Qn_finite_c(n)                              # :65
def Qn_finite_c(n):                                        # :13-16 (la 2.ª definición sobrescribe a la de :8-11)
    if n % 2: return (1.60188 + (-2.1284 - 5.172/n)/n)/n + 1
    return (3.67561 + (1.9654 + (6.987 - 77/n)/n)/n)/n + 1
```
**[S1b]** 500 casos `n∈13..300` y todos los `n∈2..12`: `identical(Qn(x), (2.21914*raw)/fc)` y `… *TAB`.

`qn0` (port literal, base 0; `qn_sn.c:133-296`):
```
y = sorted(x)                                                        # :156-158 (R_qsort; solo valores)
nn2 = n*(n+1)//2 ; n2 = n*n                                          # :145-146
k_L = int(5 - 1.75*(n % 2) + ((0.3939 - 0.0067*(n % 2)) * n) * (n-1))  # :154 aritmética double, trunc hacia 0
hq = n//2 + 1                                                        # :155
nl, nr, knew = nn2, n2, k + nn2                                      # :167
left  = [n - i + 1 for i in range(n)]                                # :176-177
right = [n]*n if k >= k_L else [n if i <= hq else n - (i - hq) for i in range(n)]   # :178-185
found = False
while not found and nr - nl > n:                                     # :187
    work, wgt = [], []
    for i in range(1, n):                                            # :191-198
        if left[i] <= right[i]:
            w = right[i] - left[i] + 1; jh = left[i] + w // 2
            work.append(f32(y[i] - y[n - jh])); wgt.append(w)        # :195 (float)(…)
    trial = whimed_i(work, wgt)                                      # :199
    j = 0
    for i in range(n-1, -1, -1):                                     # :213-218
        while j < n and f32(y[i] - y[n - j - 1]) < trial: j += 1
        P[i] = j
    j = n + 1
    for i in range(n):                                               # :222-227
        while f32(y[i] - y[n - j + 1]) > trial: j -= 1
        Q[i] = j
    sump = sum(P); sumq = sum(Q) - n                                 # :228-234 (int64)
    if knew <= sump: right = P[:]; nr = sump                          # :238-241
    elif knew > sumq: left = Q[:]; nl = sumq                          # :245-248
    else: found = True                                               # :252-253
if found: return trial                                               # :260-261  ← valor redondeado a float32
work = [y[i] - y[n - jj] for i in range(1, n) for jj in range(left[i], right[i] + 1)]   # :266-272 sin f32
kk = min(max(knew - (nl + 1), 0), len(work) - 1)                     # :278-290
return kth_smallest(work, kk)                                        # :291-292 rPsort ⇒ solo el valor
```
- `whimed_i(a, w)` (`wgt_himed_templ.h:27-122`): devuelve **el menor `a_j` tal que `2·Σ_{a_i ≤ a_j} w_i > Σ w`**
  (las ramas `:85`, `:93`, `:105-110` lo prueban). Es pura selección: cualquier implementación exacta
  (ordenar + `cumsum` entero) da **el mismo valor**; no hay aritmética de coma flotante.
- `rPsort`/`pull` son selecciones del k-ésimo: valor único, implementación libre (`np.partition`).
- **Trampa T1 [S1]:** en 264 de 3000 casos el resultado es `f32(d)` y no el `d` exacto (rama `found`). El oráculo
  O(n²) aprobado (M2) debe aceptar **`qn0 ∈ {d, f32(d)}`** y el port fiel debe reproducir la rama exacta
  que tomó R (se comprueba contra la salida de R, no contra el oráculo).

#### 3.12.2 Medianas y medias

- `r_median(v)` (`median.R:21-33`): impar ⇒ elemento central (`sort(partial)`); par ⇒
  `r_mean([lo, hi])` con la media de dos pasadas: `s=(0+lo)+hi; s=s/2; t=(0+(lo-s))+(hi-s); s=s+t/2`
  (`[tar]summary.c:482-506`; `LDOUBLE=double` en el oráculo, `[tar]Defn.h:2426-2430`, [S0]).
  **[S1b]** `median(c(0.1,0.7,5,-3))` = `0.40000000000000002` ≠ `(0.1+0.7)/2` = `0.39999999999999997`.
- `r_mean(v)` general (`[tar]summary.c:479-518`): `s = seqsum(v)/N`; si finito: `s += seqsum(v - s)/N`.
- `r_colmedians` (`comedian.R:21-22` → `rowMedians_TYPE-template.h:123-142`): par ⇒ `(lo + hi)/2` **sin**
  corrección (`:138`).
- `r_rowmeans`/`r_rowsums` (`array.c:2001-2098`): para cada fila, acumulación secuencial sobre columnas
  `j=0..m-1`, luego `/m`. Python: `acc = zeros(nrow); for j: acc += A[:, j]` (vectorizado por filas, secuencial
  por columnas), o `np.cumsum(A, axis=1)[:, -1]`.

#### 3.12.3 Rangos, orden

- `r_rank` (`rank.R:19-50`, `[tar]sort.c:1495-1590`): empates `average` = `(i+j+2)/2` (`sort.c:1555`), igual a
  `scipy.stats.rankdata(method="average")` (semienteros exactos).
- `order`, `sort.list`, `sort.int(index.return=TRUE)` con `method="auto"` ⇒ **radix** para numéricos
  (`sort.R:97-115`, `:211-228`, `:250-269`), estable, con redondeo de dígitos **desactivado**
  (`setNumericRounding(retGrp ? 2 : 0)`, `[tar]radixsort.c:1580`; `retGrp=FALSE` desde `order`, `sort.R:227`).
  `-0.0` y `0.0` empatan (`dtwiddle`, `[tar]radixsort.c:636-650`). Python: `np.argsort(v, kind="stable")`.
  NaN: `order` los pone al final; `sort.int(…, index.return=TRUE)` con `na.last=NA` **los elimina antes**
  (`sort.R:105-108`), desplazando índices (solo ocurre con datos degenerados; replicar).

#### 3.12.4 `cor`/`cov` (`cor.R:21-71`, `cov.c`)

Fórmula (`cov.c:201-240`, `:304-370`, `:244-301`):
```
m_j  = seqsum(X[:, j]) / N ; m_j = m_j + seqsum(X[:, j] - m_j) / N       # MEAN, dos pasadas
C_ij = seqsum((X[:, i] - m_i) * (X[:, j] - m_j)) / (N - 1)              # :333 / :265  (j <= i)
cor:  s_i = sqrt(C_ii); R_ij = clamp(C_ij / (s_i * s_j), -1, 1); R_ii = 1   # :355-366 / :286-298, CLAMP :59
      si s_i == 0 o s_j == 0 ⇒ NA + warning (:358-360, :811) ⇒ eigen() falla después (T20)
```
~~**[S3]** la versión secuencial sin FMA reproduce `cov()` de R **bit a bit**.~~ **Falso (corregido
2026-10-06).** La acumulación `sum += (x_k − m_i)*(y_k − m_j)` (`cov.c:333` en `cov_na_1`, `:265` en
`cov_complete1`) está compilada con FMA en el oráculo, con un patrón distinto en cada rama (§3.12.8):
- `cov_complete1` (`use="complete.obs"`, conjunto 3): `fmadd` en **todos** los `k`.
- `cov_na_1` (`use="everything"`, conjuntos 1, 2, 5 y `.TargetCorr`): con `n ≥ 8`, los primeros
  `8·floor(n/8)` términos con producto redondeado y suma aparte (sin FMA, en orden de `k`), y la cola con `fmadd`.

La fórmula de medias (dos pasadas) no cambia. **[S11]** (n=37, p=9): secuencial sin FMA difiere de R en 28/81
entradas; FMA en todo `k` difiere de `cov(use="everything")` en 39/81 pero coincide con `use="complete.obs"`;
`r_cov` de `_rbase.py` (bloques de 8 + cola FMA) coincide en 0/81 diferencias en ambas ramas.

#### 3.12.5 `doScale` con escala 0: `non0Q` (`rb/detmcd.R:268-283`) y `quantile` tipo 7

```
alph = [10/20, …, 19/20, 19.75/20]                 # :276 c(10:19, 19.75)/20
qq   = r_quantile7(abs(u), alph)                   # :277 S = abs porque centerName == "median" (:273-274)
i    = primer índice con qq != 0 → qq[i] / r_qnorm((alph[i]+1)/2) ; si ninguno → 1   # :278-281
r_quantile7 (quantile.R:57-67): idx = 1 + (n-1)*p; lo = floor(idx); hi = ceil(idx); q = x[lo];
      si idx > lo y x[hi] != q: h = idx - lo; q = (1-h)*q + h*x[hi]
```
No usar `np.quantile` (fórmula de interpolación distinta). Este camino se activa con columnas con > ~50 % de
valores iguales (p. ej. retornos nulos); **[S6]** 60 % de ceros en una columna: `CovMrcd` termina sin error.

#### 3.12.6 Álgebra lineal (réplica de las llamadas de R)

| R | C/LAPACK | Python exigido |
| --- | --- | --- |
| `A %*% B` (matriz·matriz) | `dgemm('N','N')` sobre memoria columna (`array.c:839-841`) | `scipy.linalg.blas.dgemm(1.0, F(A), F(B))` con operandos en orden Fortran y `t(·)` **materializada** |
| `A %*% v` | `dgemv('N')` (`array.c:831-833`) | `scipy.linalg.blas.dgemv(1.0, F(A), v)` |
| `v %*% B` | `dgemv('T')` sobre `B` (`array.c:834-838`) | `dgemv(1.0, F(B), v, trans=1)` con `F(B)` **alineada como en R** (ver nota de alineación) |
| cualquier operando con NaN/Inf | `simple_matprod` (`array.c:719-740`, `:806-811`) | triple bucle con acumulación secuencial **con FMA** (`sum += x*y` es `fmadd`, `array.c:728`; §3.12.8) |
| `crossprod(X)` | `dsyrk('U','T')` + espejo (`array.c:983-1020`) | `scipy.linalg.blas.dsyrk(1.0, F(X), trans=1, lower=0)` + copiar triángulo superior al inferior |
| `eigen(A, symmetric=TRUE)` | `dsyevr(jobz='V', range='A', uplo='L', abstol=0)` de **Rlapack 3.12.1** con consulta previa de `lwork`/`liwork` óptimos (`Lapack.c:166-237`); orden decreciente (`eigen.R:59-62`) | `scipy.linalg.lapack.dsyevr(A, compute_v=1, range='A', lower=1, abstol=0.0, lwork=…, liwork=…)` con `lwork`/`liwork` de `dsyevr_lwork`; invertir orden de valores y columnas. **No es bit a bit**: es el `dsyevr` de Accelerate (S12); **aceptado con tolerancia B** (§11, decisión D9) |
| `eigen(A)` sin `symmetric` | `isSymmetric.matrix` (`eigen.R:22-43`, `all.equal.R:99-174`) ⇒ casi siempre `La_rs` con `jobz='V'` (T13) | idem fila anterior, previa réplica del test de simetría |
| `chol(A)` | `dpotrf('U')` de Rlapack (`Lapack.c:1090-1104`); error si no DP | **port de referencia** `DPOTRF('U')` + `DPOTRF2` de `dlapack.f` sobre el BLAS de scipy (`_rlapack.py:dpotrf_upper`); `info>0` ⇒ error. `scipy.linalg.lapack.dpotrf` **no sirve** (Accelerate, S14) |
| `chol2inv(R)` | `dpotri('U')` de Rlapack + espejo superior→inferior (`Lapack.c:1162-1178`) | **port de referencia** `DPOTRI` = `DTRTRI` + `DLAUUM` de `dlapack.f` (`_rlapack.py:dpotri_upper`) + espejo |
| `determinant(A)$modulus` | `dgetrf` de Rlapack, `Σ log|U_ii|` secuencial (`Lapack.c:1415-1436`) | **port de referencia** `DGETRF`/`DGETRF2` (+ `DLASWP`) de `dlapack.f` (`_rlapack.py:dgetrf`) + `math.log` y suma secuencial |

**LAPACK (corregido 2026-10-06, T28).** R no llama al LAPACK del sistema: usa su `libRlapack` (Fortran de
referencia 3.12.1, `referencias/R-4.5.2/src/modules/lapack/dlapack.f`), que llama al BLAS del sistema (Accelerate).
`scipy.linalg.lapack` es el LAPACK de Accelerate, con otros algoritmos internos. Como toda la aritmética de
`DPOTRF`, `DPOTRI` y `DGETRF` de referencia está en llamadas BLAS (`dtrsm`, `dsyrk`, `dgemm`, `dtrmm`, `dtrmv`,
`dgemv`, `ddot`, `dscal`) o en escalares exactos (`sqrt`, `1/x`, intercambios), su traducción literal sobre
`scipy.linalg.blas` (mismo Accelerate) reproduce los bits de R. Bloques de `ILAENV` de referencia: 64 para
`DPOTRF`, `DTRTRI`, `DLAUUM`, `DGETRF` (`dlapack.f:165090-165303`; `_rlapack.py:_NB`). `DSYEVR` no se porta
(decisión D9): tolerancia B.

**Alineación de memoria (corregido 2026-10-06, T27).** El `dgemv('T')` de Accelerate da bits distintos según
la dirección de inicio del operando. En el oráculo, un vector de R de más de 120 `double` se reserva con `malloc`
(región *small* de macOS) y sus datos empiezan tras la cabecera de 48 bytes (`SEXPREC_ALIGN`,
`[tar]Defn.h:219-224`, `:418`) ⇒ **datos a `48 mod 64` bytes** (medido con `.Internal(inspect())`). El helper
`_fortran` de `_rlinalg.py` copia los operandos de más de 120 elementos con esa alineación; los más pequeños
(pools propios de R, región *tiny*) no tienen alineación fija y se dejan con la de numpy. **[S13]** `v %*% B`,
`B` 200×40: con los datos a `48 mod 64` 0/40 diferencias con R; con cualquier otro desplazamiento múltiplo de 8,
22–28/40. Se aplica a todos los operandos BLAS por coherencia; solo está medido para `dgemv('T')`.

**[S7]** `mE %*% t(mE)` con `p=5, h=15`: R **no** es simétrica exacta; numpy `mE @ mE.T` usa `syrk` (simétrica,
≠ R); `mE @ copia(mE.T)` tampoco coincide; `dgemm(1.0, F(mE), F(t(mE)))` de scipy **coincide bit a bit**.
`crossprod`: `dsyrk` U + espejo coincide bit a bit; `x.T @ x` no.

#### 3.12.7 libm y `qnorm`

- `tanh`, `sin`, `log`, `exp`, `pow`: usar `math.*` por elemento (libm de la plataforma, la misma que usa R).
  **[S8]** `np.tanh` difiere de R en 1995/10000 casos (1 ulp); `math.tanh` en 0. `np.sin`, `np.log`, `np.exp`
  coinciden aquí, pero su implementación SIMD depende de la CPU: se exige `math.*`.
- `sqrt`, `+ − × ÷`: IEEE correctamente redondeados ⇒ numpy vale.
- `qnorm` (`qnorm.c:47-…`, AS241 de Wichura): **portar literalmente** `qnorm5`. **[S8]** `scipy.special.ndtri`
  difiere en 676/999 puntos `(i-1/3)/(n+1/3)` (≤ 6.4e-16 relativo). El port literal debe incluir las
  contracciones FMA del binario (§3.12.8): sin ellas tampoco coincide.
- `x^y` ⇒ `r_pow` (§3.2); `x^2` ⇒ `x*x`; `x^(-1)` ⇒ `math.pow(x, -1.0)`.

#### 3.12.8 Contracción FMA en el binario del oráculo (añadido 2026-10-06)

El R del oráculo (`aarch64-apple-darwin20`, `clang -O2`) se compiló con contracción de coma flotante: `clang`
fusiona `x*y + z` en `fmadd`/`fmsub`/`fmla` (**un** redondeo). El código fuente no lo muestra; se determinó
desensamblando `stats.so` y `libR.dylib` (lo documenta el convertidor en las cabeceras de `_fma.py`, `_rbase.py`
y `_rzeroin.py`) y se confirma por coincidencia bit a bit con R. Python no fusiona nunca (ni numpy), así que
cada contracción se reproduce con `fma(a,b,c) = RN(a·b+c)` exacto: `_fma.py` (Boldo–Melquiond 2008 con
redondeo a impar; racional exacto en exponentes extremos).

| Código de R | Expresión contraída | Patrón | Port |
| --- | --- | --- | --- |
| `cov.c:333` (`cov_na_1`, `use="everything"`) | `sum += (xx[k]-xxm)*(yy[k]-yym)` | vectorizado: con `n ≥ 8`, bloques de 8 con `fmul` + `fadd` secuencial en orden de `k` (sin FMA) para `k < 8·floor(n/8)`; la cola con `fmadd`. Con `n < 8`, todo `fmadd` | `_rbase.py:_cov_core(vectorized=True)` |
| `cov.c:265` (`cov_complete1`, `use="complete.obs"`) | idem | `fmadd` en todo `k` (el `if(ind[k])` impide vectorizar) | `_cov_core(vectorized=False)` |
| `zeroin.c:134` | `tol_act = 2*EPSILON*fabs(b) + tol/2` | `fma(|b|, 2·eps, tol/2)` | `_rzeroin.py:133` |
| `zeroin.c:159` | `cb*q*(q-t1) - (b-a)*(t1-1.0)` | `fma(cb·q, q−t1, −((b−a)·(t1−1)))`, luego `t2·(…)` | `_rzeroin.py:150` |
| `zeroin.c:167` | `0.75*cb*q - fabs(tol_act*q)/2` | `fma(0.75·cb, q, −(|tol_act·q|/2))` | `_rzeroin.py:158` |
| `qnorm.c:82-90`, `:107-118`, `:127-138` (AS 241) | polinomios de Horner `(…*r + c_k)` y `r = .180625 - q*q` | cada paso de Horner `fma(acc, r, c_k)`; `r = fma(−q, q, .180625)` | `_rbase.py:_horner_fma`, `r_qnorm` |
| `qnorm.c:151-157` (`r > 27`) | `… + 2*log1p(…)` | `fma(log1p(…), 2, s2 − log(2π·x2))` | `_rbase.py:_qnorm_far_tail` |
| `array.c:728` (`simple_matprod`), `:751` (`simple_crossprod`) | `sum += x*y` | `fmadd` en todo `j` | `_rlinalg.py:_simple_matprod` |

Sin FMA (verificado por coincidencia): medias de dos pasadas y sumas (`summary.c`, `array.c:2001-2098`, `cov.c`
`MEAN`), `mahalanobis` (producto y `rowSums` son operaciones R separadas), `qn0` (restas y comparaciones). Lo que
corre dentro de BLAS/LAPACK (Accelerate o Rlapack Fortran) se replica llamando a las mismas rutinas, no se
analiza aquí. `qchisq`/`pgamma`/`qgamma` de nmath (D10): sus ≈100 contracciones se localizaron desensamblando
`libR.dylib` (las `static` `pgamma_smallx`, `pd_upper_series`, `dpois_wrap`, `dpnorm` y `ppois_asymp` están
integradas en `_Rf_pgamma_raw`) y se reproducen con `fma` en `packages/pymrcd/src/pymrcd/_nmath.py`. En otra plataforma u otro compilador (p. ej. x86-64 sin FMA por defecto) el
patrón cambia: es parte de la plataforma de referencia (P6).

#### 3.12.9 `qn0` en C (M5, tarea T1; añadido 2026-10-07)

Alcance: especificación de la extensión C de `pymrcd` que sustituye a la implementación numpy de `qn0`
(`packages/pymrcd/src/pymrcd/qn.py:197-289`) y construye los pares de OGK
(`packages/pymrcd/src/pymrcd/ogk.py:24-58`). Decisiones del dueño (2026-10-07): port **literal** de `qn0` +
`whimed_i` + `R_qsort` + `rPsort` a C; CPython C-API con protocolo de búfer; `pthreads` con paralelismo **entre
columnas**; `setuptools`; **sin respaldo Python** (P1=A); todos los núcleos por defecto; M1: los pares
`Y_i ± Y_j` se construyen en C por hilo; P5: si el C literal da un signo de cero distinto al de la versión Python
actual, manda el C (igual a R). Aquí no hay código: solo el contrato que debe cumplir `convertidor-python`.

**Fuentes leídas** (rutas completas; las tres de R se extrajeron hoy de `referencias/R-4.5.2.tar.gz`, que no se
versiona):

| Abreviatura | Ruta | MD5 |
| --- | --- | --- |
| `qn_sn.c` | `referencias/robustbase-0.99-6/src/qn_sn.c` | — |
| `wgt_himed.c`, `wgt_himed_templ.h` | `referencias/robustbase-0.99-6/src/` | — |
| `qnsn.R` | `referencias/robustbase-0.99-6/R/qnsn.R` | — |
| `sort.c` | `referencias/R-4.5.2/src/main/sort.c` | `fb06d6d29e508700a0c48e56fe8b4931` |
| `qsort.c` | `referencias/R-4.5.2/src/main/qsort.c` | `aed8963a407b216482687faf796a5693` |
| `qsort-body.c` | `referencias/R-4.5.2/src/main/qsort-body.c` | `e9ad0818f8128f7b4bbe5fabb0d05e45` |
| `choose.c` | `referencias/R-4.5.2/src/nmath/choose.c` | — |
| `[tar]Utils.h`, `[tar]Arith.h` | `R-4.5.2/src/include/R_ext/` dentro del tarball | — |

Cadena de llamadas portada: `Qn` (`qnsn.R:48-49`, `.C(Qn0, …)`) → `Qn0` (`qn_sn.c:98-104`) → `qn0`
(`qn_sn.c:118-296`) → `R_qsort` (`qn_sn.c:158`; definido en `qsort.c:164-167` con el cuerpo `qsort-body.c:27-169`,
`INTt = size_t` por `qsort-body.c:37-39` porque `qsort_Index` está indefinido desde `qsort.c:162`), `whimed_i`
(`qn_sn.c:199`; instanciado en `wgt_himed.c:37-38` con `wgt_himed_templ.h:15-20`: pesos `int`, sumas `int64_t`;
cuerpo `wgt_himed_templ.h:27-122`) y `rPsort` (`qn_sn.c:291` y `wgt_himed_templ.h:63`; macro `rPsort` →
`Rf_rPsort` en `[tar]Utils.h:46`; `sort.c:724-727` → `rPsort2` `sort.c:692-698` → `psort_body` `sort.c:668-681`
con `rcmp` `sort.c:45-54`).

##### a) Tabla original → port

| Original | Port C | Desviación de API y justificación |
| --- | --- | --- |
| `qnsn.R:27` (`anyNA ⇒ NA`), `:29` (`n==0 ⇒ NA`, `n==1 ⇒ 0`) | Sigue en el envoltorio Python (`qn.py:313-322`). El escaneo NaN/Inf de las columnas con `n ≥ 2` se hace **en C, fusionado con la copia** `x → y` (ahorro A3) | Lógica de R, no de `qn0`. Semántica idéntica a la actual: columna con NaN ⇒ `NaN`; algún `±Inf` en columna sin NaN ⇒ `ValueError("Qn con valores infinitos no está soportado por el port")` (desviación ya vigente, `qn.py:308-325`) |
| `qnsn.R:21`, `:44`, `:49`: `k = choose(n %/% 2 + 1, 2)` como `double`; `Qn0` lo pasa a `int64_t` (`qn_sn.c:101-102`) | `k = (int64_t)hq*(hq-1)/2`, `hq = n/2 + 1` | Mismo entero: `choose.c:126-136` con `k=2` calcula `n·((n−1)/2)` (exacto, < 2^53 para `n < 2^31`) y lo redondea con `R_forceint`; para `hq ≤ 3` usa la simetría `:128-129` (1 y 3). Sin `R_alloc` de `ik` (`:101`) |
| `qn_sn.c:98-104` (`Qn0`, interfaz `.C`, `Sint`) | No se porta; la entrada es la función CPython (§ «API») | Interfaz de R. `n` llega como `Py_ssize_t`: se rechaza `n > INT_MAX` (R lo rechaza en `qnsn.R:30-31`) |
| `qn_sn.c:118` firma `qn0(const double x[], int n, const int64_t k[], int len_k, double *res)` | Misma firma + puntero al espacio de trabajo del hilo | Se conserva el bucle `len_k` (`:165-294`) literal; se llama siempre con `len_k = 1` |
| `qn_sn.c:133-142` (9 × `R_alloc` de tamaño `n`) | `malloc` **una vez por hilo**, de tamaño `n` (todas las columnas de una llamada tienen la misma `n`) | `R_alloc` exige el intérprete de R. Reutilizar es neutro: `qn0` escribe cada celda antes de leerla (prueba en A1) |
| `qn_sn.c:144-155` (`nn2`, `n2`, `k_L`, `h`) | Literal, con los mismos tipos (`int64_t`, `int`) y la misma expresión de `k_L` (`double` truncado por la conversión a `int64_t`, `fcvtzs` en el binario) | Se calculan una vez por llamada (ahorro A5). **La expresión de `k_L` la contrae `clang` por defecto** (sonda S19): exige `-ffp-contract=off` |
| `qn_sn.c:156-158` (copia + `R_qsort(y, 1, n)`) | Literal. En OGK, la «copia» es la construcción del par: `y[r] = Y[r,i] + Y[r,j]` o `Y[r,i] − Y[r,j]` (ahorro A2) | Ninguna. `R_qsort` es obligatorio: decide la posición de `±0` (apartado c) |
| `qn_sn.c:160-162`, `:168-170`, `:201-212`, `:219-221`, `:235-237`, `:242-256`, `:263-275`, `:282-289` (`#ifdef DEBUG_*`, `REprintf`) | Se omiten | Código de depuración, compilado fuera en R (`DEBUG_qn` no definido) |
| `qn_sn.c:172` `Rboolean found = FALSE` | `bool found = false` (`<stdbool.h>`) | Tipo equivalente |
| `qn_sn.c:173` `double trial = R_NaReal` | `double trial = NAN` | `R_NaReal` es el NA de R (NaN con carga 1954, `[tar]Arith.h:48`, `:58`). Su valor inicial **nunca sale**: `trial` solo se devuelve con `found` (`:260-261`), que exige haber asignado `trial` en `:199` |
| `qn_sn.c:176-185` (`left`, `right` iniciales) | Literal | — |
| `qn_sn.c:187-258` (bucle principal) | Literal, mismas comparaciones y mismo orden | Opcionales neutros: A6 (sumas fusionadas) y A7 (intercambio de punteros) |
| `qn_sn.c:195`, `:215`, `:224` `(float)(…)` | Literal: conversión `double → float → double` | Obligatorio (T1). En el binario: pares `fcvt s,d` / `fcvt d,s` y `fcmp` en `double` (S18) |
| `qn_sn.c:199` `whimed_i(work, weight, j, a_cand, a_srt, p)` (usa `p` como `w_cand`) | Literal, **con el mismo alias de `p`** | — |
| `wgt_himed_templ.h:56` `return NA_REAL` (`n == 0`) | `return NAN` | Inalcanzable con `k` por defecto: dentro del bucle `j ≥ 1` (apartado d, lema 5) |
| `wgt_himed_templ.h:27-122` (resto) | Literal: `int` para pesos, `int64_t` para sumas, `rPsort` sobre la copia `a_srt` (`:61-63`), selección de candidatos **en el orden original de `a`** (`:86-99`), y copia de vuelta a `a`/`w` (`:116-119`) | Prohibido sustituirlo por «ordenar + `cumsum`» (lo hace `qn.py:134-157`): da el mismo valor pero no el mismo **signo de cero** (apartado c) |
| `qn_sn.c:260-261` (rama `found`) | Literal | — |
| `qn_sn.c:266-272` (`work` de la rama «no encontrado», sin `float`) | Literal, en el mismo búfer `work` de tamaño `n` | Demostrado `j ≤ n` (apartado d); además comprobación defensiva por elemento que **lanza error** si `j == n` antes de escribir (nunca se activa) |
| `qn_sn.c:278-290` (`knew -= nl+1` y acotación) | Literal | Para `k` por defecto la acotación es inalcanzable (apartado d, lema 6); se conserva |
| `qn_sn.c:291-292` `rPsort(work, j, (int)knew)` | Literal | — |
| `sort.c:724-727` `rPsort` → `sort.c:692-698` `rPsort2(x, 0, n-1, k)` | Literal; `R_xlen_t` → `ptrdiff_t` | `R_xlen_t` es `ptrdiff_t` en 64 bits |
| `sort.c:668-681` `psort_body` (`bool nalast=true`) | Literal | — |
| `sort.c:45-54` `rcmp` (`ISNAN`) | Literal con `isnan` | `ISNAN` es la macro de R sobre `isnan`. Ningún NaN llega (columnas con NaN se excluyen antes) |
| `qsort.c:164-167` + `qsort-body.c:27-169` (`R_qsort`, Singleton CACM #347 con Peto) | Literal **con sus `goto`** (`L10`, `L20`, `L80`, `L100`), `size_t` para índices, `double R = 0.375` (`:47`), `--v` base 1 (`:55`), pilas `il[40]`/`iu[40]` (`:41`) | Ninguna. No se «arregla» el centinela de la inserción (`:156-162`, sin cota inferior): es correcto porque `:139` evita el tramo izquierdo |
| `detmrcd.R:89-95` (pares de OGK, `scalefn(sYi + sYj)^2 - scalefn(sYi - sYj)^2) / 4`) | En C, por par `(i > j)` y por hilo: construir `Y_i + Y_j` en `y`, `qn0`; construir `Y_i − Y_j` en `y`, `qn0`; `s = 2.21914·q₊`, `d = 2.21914·q₋`, luego `·TAB[n−2]` o `/fc`; `U[i,j] = (s*s − d*d)/4`; espejo `U[j,i]` (`:97`); diagonal 1 (`:87`) | **Decisión: `(s*s − d*d)/4` va a C.** Es bit a bit idéntico a numpy (`ogk.py:56`) porque son las mismas operaciones IEEE binary64 elementales (`×`, `×`, `−`, `/4`), con los mismos operandos y en el mismo orden, **siempre que no haya contracción**: `clang` por defecto la convierte en `fnmul` + `fmadd` (S19), por eso `-ffp-contract=off` es obligatorio. `x/4` y `x·0.25` coinciden (potencia de dos, mismo real exacto). `2.21914`, `TAB[n−2]` (`qnsn.R:58-63`) y `fc = Qn.finite.c(n)` (`qnsn.R:13-16`) se calculan **en Python** con el código actual (`qn.py:31-68`) y se pasan como `double`: mismo valor, sin duplicar constantes. `^2` es `x*x` (`R_POW`, §3.12.1) |

**API implementada** (módulo privado `pymrcd._qn_ext`, tipos en `_qn_ext.pyi`; la carga y el `ImportError` sin
respaldo, en `pymrcd/_cext.py`). Las funciones **escriben en un búfer de salida `out`** que pasa el llamador
(sin asignar ni devolver arreglos), de ahí que los tipos sean `Buffer` y no `ndarray`:
- `qn0_columns(x, out, k, n_threads, poison=False)`: `qn0` crudo por columna de `x` (`n × m`, `float64`, cualquier
  *stride*, sin copiar) en `out` (`m`). Requiere `n ≥ 2` (el envoltorio Python resuelve `n ≤ 1`).
- `ogk_u(y, out, constant, factor, small_n, n_threads, poison=False)`: triángulos de `U` de `detmrcd.R:87-97` en
  `out` (`p × p`); `constant` es 2.21914, `factor` el de `Qn.finite.c`/`TAB`, y `small_n` indica si `factor`
  multiplica (`n ≤ 12`) o divide. `p < 2` y `n ≤ 1` los resuelve el envoltorio. `poison` es un gancho de prueba
  (llena el espacio de trabajo antes de cada columna, ahorro A1).
- `n_threads = 0` ⇒ valor por defecto, **resuelto en C**: `PYMRCD_NUM_THREADS` si está definida (entero entre 1 y
  4096; otro valor, `ValueError`) y, si no, los CPU visibles por afinidad (`sched_getaffinity` en Linux) o los
  CPU en línea (`sysconf`). Motivo de resolverlo en C: importar `os` en `pymrcd` rompería el contrato 2 de
  `import-linter` por el camino `domain → pymrcd → os`. Siempre acotado por el número de columnas o pares.
  `default_threads()` y `build_info()` exponen el valor resuelto y las salvaguardas de compilación.
- Ganchos privados para pruebas: `_r_qsort`, `_rpsort`, `_whimed_i`, `_k_l`.

##### b) Cero FMA en el oráculo y opciones obligatorias

**Evidencia (sonda S18, 2026-10-07).**

```
SO=/Library/Frameworks/R.framework/Versions/4.5-arm64/Resources/library/robustbase/libs/robustbase.so
LIB=/Library/Frameworks/R.framework/Versions/4.5-arm64/Resources/lib/libR.dylib
md5 $SO $LIB        # 990b0a43016a97ce3a0210e39f692281, 04289a93151a21dda0dd368e137ecae9
otool -tV $SO > rb.s; otool -tV $LIB > libR.s
fn(){ awk -v s="^$1:" 'BEGIN{p=0} $0~s{p=1;print;next} p&&/^_[A-Za-z0-9_]+:$/{exit} p{print}' $2; }
fn _qn0 rb.s | grep -cE '\b(fmadd|fmsub|fnmadd|fnmsub|fmla|fmls)\b'      # idem para cada símbolo
```

| Símbolo | Binario | Líneas | FMA | Otras instrucciones de coma flotante relevantes |
| --- | --- | --- | --- | --- |
| `_Qn0` | `robustbase.so` | 65 | 0 | conversión `k` → `int64` |
| `_qn0` | `robustbase.so` | 721 | 0 | `k_L` con `fmul`/`fadd` separados y `fcvtzs`; 3 pares `fcvt s,d`/`fcvt d,s` (`:195`, `:215`, `:224`) con `fcmp` en `double`; llama a `_R_qsort`, `_whimed_i` y `_Rf_rPsort` |
| `_whimed_i` | `robustbase.so` | 305 | 0 | sin aritmética de coma flotante (solo comparaciones); llama a `_Rf_rPsort` |
| `_R_qsort` | `libR.dylib` | 129 | 0 | `R += ±δ` con `fcsel` + `fadd`; `ij` con `ucvtf` + `fmul` + `fcvtzu` (`qsort-body.c:65`, `:69`) |
| `_Rf_rPsort` | `libR.dylib` | 65 | 0 | `rPsort2`, `psort_body` y `rcmp` integrados (sin `bl`) |

Confirma el hallazgo del orquestador: la cadena `qn0` de R no tiene contracciones, así que el port **no** lleva
`fma` (a diferencia de §3.12.8) y su resultado es independiente de la plataforma (no hay libm ni BLAS).

**Sonda S19 (riesgo concreto).** Apple clang 17.0.0 (`arm64-apple-darwin25.1.0`), `-O2` sin más opciones,
compila `k_L` (`qn_sn.c:154`) con **3 `fmadd`** y `(s*s - d*d)/4` como `fnmul` + `fmadd`; con
`-ffp-contract=off -fno-fast-math`, 0 FMA en `-O2` y `-O3`. Las `CFLAGS` de CPython del entorno
(`sysconfig`: `-O3 … -arch arm64`) **no** desactivan la contracción. GCC contrae por defecto en modo GNU
(`-ffp-contract=fast`) e ignora `#pragma STDC FP_CONTRACT`.

**Obligatorio en la compilación y en el código:**
1. `extra_compile_args` de `setuptools`: `-std=c11 -ffp-contract=off -fno-fast-math -pthread` (al final, para
   que prevalezcan sobre las `CFLAGS` de CPython). Prohibidos `-Ofast`, `-ffast-math`, `-ffinite-math-only`,
   `-fno-signed-zeros`, `-fassociative-math`, `-freciprocal-math`. MSVC (no soportado hoy): `/fp:strict`.
2. En el fuente: `#pragma STDC FP_CONTRACT OFF` (y `#pragma clang fp contract(off)` bajo `__clang__`) como
   segunda barrera; `#if FLT_EVAL_METHOD != 0 → #error` (x87 de 32 bits rompería el redondeo de `(float)`);
   `#if defined(__FAST_MATH__) || (defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__) → #error`;
   `_Static_assert(sizeof(double) == 8 && sizeof(float) == 4)`.
3. Entorno de coma flotante en tiempo de ejecución (cada hilo, al empezar): `fegetround() == FE_TONEAREST` y
   sin *flush-to-zero* (comprobación con un subnormal: `DBL_MIN/2 != 0`, sobre `volatile`); si falla, error. Los
   pares de OGK y `y[i] − y[m]` pueden ser subnormales (S15 usa `1e-300`) y otra extensión cargada en el proceso
   puede activar FTZ (p. ej. bibliotecas enlazadas con `crtfastmath.o` en Linux).
4. Compuerta posterior a la compilación (en la plataforma de referencia): desensamblar la extensión
   (`otool -tV` en macOS; `objdump -d` en Linux) y exigir **0** de `fmadd|fmsub|fnmadd|fnmsub|fmla|fmls`
   (arm64) o `vfmadd|vfmsub|vfnmadd|vfnmsub` (x86-64) **en todo el binario**, y presencia de los pares
   `fcvt s,d`/`fcvt d,s` en `qn0`.
5. No hay reducciones de coma flotante en el código portado (las sumas `sump`, `sumq`, `w_tot`, `wleft`… son
   enteras), así que la autovectorización de `-O2/-O3` no puede reasociar nada. La conversión `(float)` de un
   `double` fuera de rango es indefinida en C11 (6.3.1.5) pero en arm64/x86-64 (`fcvt`/`cvtsd2ss`) da `±Inf`
   según IEEE 754, igual que el binario de R y que `np.float32`; las entradas con `±Inf` se rechazan antes y las
   diferencias de valores finitos solo desbordan a `±Inf` en `float` si superan `FLT_MAX`, caso que R trata igual.

##### c) Análisis de `±0`

Las comparaciones de `qn0` y sus primitivas (`<`, `>`, `<=` en `qn_sn.c:192`, `:215`, `:224`, `:238`, `:245`;
`wgt_himed_templ.h:68-73`, `:87`, `:95`; `rcmp` `sort.c:51-53`; `qsort-body.c:74`, `:82`, `:87`, `:96`, `:102`,
`:152`, `:162`) tratan `−0 == +0`. Por tanto el **flujo de control** y el **valor numérico** del resultado son
independientes de dónde estén los `±0`; lo único que puede cambiar es el **signo de un resultado cero**.

Dónde aparece `−0`:
- **En `x` (entrada de `qn0`)**, en la ruta `cov_mrcd`: (1) `vsd` (`detmrcd.R:418`) sobre los datos crudos: solo si
  los datos traen `−0.0`; (2) `doScale` (`rb/detmcd.R:249`, `:253`): `x − med` es `−0` solo con `x = −0` y
  `med = +0` (en redondeo al más cercano `a − a = +0`); (3) `initset` (`detmrcd.R:70`): `data %*% P` sale de
  `dgemm`; un `−0` exigiría que todos los productos fuesen `−0` y depende de cómo acumule el BLAS (no
  especificado: riesgo de plataforma, irrelevante por el punto siguiente); (4) OGK (`detmrcd.R:94`): `Y_i + Y_j`
  es `−0` solo si ambos son `−0`; `Y_i − Y_j` solo si `Y_i = −0` e `Y_j = +0` (`Y = xc/scale` con `scale > 0`
  conserva el signo).
- **En `y`**: el mismo multiconjunto que `x`; la posición de cada `±0` dentro del bloque de ceros la decide la
  permutación de `R_qsort` (determinista, sin aleatoriedad: `qsort-body.c:47`, `:65`, `:69`).
- **En `work`** (`qn_sn.c:195`, `:269`): `y[i] − y[n−jj]` es `−0` si y solo si `y[i] = −0` e `y[n−jj] = +0`
  (con `n−jj < i`, es decir, `+0` colocado antes que `−0` en `y`); `(float)` conserva el signo.
- **En `trial`** (`:199`): `whimed_i` devuelve `a_srt[n2]` tras `rPsort` (`wgt_himed_templ.h:63-64`); entre
  empates, la posición (y por tanto el signo) depende de `rPsort` y del orden en que `:86-99` copia candidatos.
- **En el resultado**: `trial` (`:261`) o `work[knew]` (`:292`). Luego `2.21914·(−0) = −0` y `·TAB`, `/fc` lo
  conservan: `Qn` de R **puede devolver `−0`** (S15: 2715 de 20000 casos).

**Efecto en `cov_mrcd`: ninguno.** `vsd < minscale` (`detmrcd.R:419`) convierte `±0` en `minscale`; en
`doScale`, `scale < 0` es falso para `−0` y `scale == 0` lo envía a `non0Q` (`rb/detmcd.R:266-283`), que lo
sustituye; en OGK, `^2` da `+0` (`detmrcd.R:94`) y `U` nunca es `−0` (`t1 − t2` con `t1 == t2` es `+0`). El signo
solo es visible en `Qn` como API y en el intermedio `vsd_raw` (`detmrcd.py:398`).

**La versión Python actual diverge** (S15, S16): `np.sort` (`qn.py:212`), el `argsort` estable de
`_whimed_columns` (`qn.py:150`) y `lexsort` en `_kth_exact` (`qn.py:188`) colocan los `±0` de otra forma. Medido:
3809 y 3778 de 20000 casos con signo de cero distinto al de R (dos corridas del mismo archivo), **0** con valor
distinto; y `np.sort(axis=0)` sobre `±0` (numpy 2.5.3, arm64) **no es determinista** entre llamadas del mismo
proceso (20 de 20 resultados distintos). Una transliteración literal en Python de `R_qsort` + `whimed_i` +
`rPsort` + `qn0` (sonda en el *scratchpad*, no versionada) coincide con R en **0 de 20000** bits distintos. Por P5
la referencia es el C literal; el port C además elimina ese no determinismo.

Consecuencia normativa: **nada** de `R_qsort`, `whimed_i` ni `rPsort` puede sustituirse por otra ordenación o
selección «equivalente» (p. ej. `qsort` de libc, `np.sort`, ordenar + `cumsum`), aunque dé el mismo valor.

##### d) `j ≤ n` en la rama «no encontrado» (`qn_sn.c:266-272`)

Notación (base 0 para `i`, base 1 para `jj`, como en C): `D_i(jj) = (float)(y[i] − y[n−jj])`, no decreciente en
`jj` (`y` ordenado; la resta redondeada y `(float)` son monótonas). `c_i = right[i] − left[i] + 1`. `hq = n/2 + 1`
(`:155`), `k = C(hq, 2)` (por defecto, `qnsn.R:21`).

1. **Invariantes.** `nl = Σ_{i=0}^{n−1}(left[i] − 1)` siempre (inicio `:145`, `:167`, `:176-177`; actualización
   `:245-248` con `sumq = Σ(q[i] − 1)`, `:233`). `nr ≥ Σ right[i]`, con igualdad desde la primera actualización de
   `right` (`:238-241`, `sump = Σ p[i]`); antes, `nr = n² ≥ Σ right[i]` porque `right[i] ≤ n` (`:178-185`).
2. **`trial ≥ 0` y cada actualización de `right` tiene `trial > 0`.** `left[i] ≥ n − i + 1` siempre: al inicio por
   `:177`; tras `:247`, `q[i] = 1 + #{jj : D_i(jj) ≤ trial}` (`:222-227`) y los `jj ≤ n − i` dan `y[i] − y[m]` con
   `m ≥ i`, `≤ 0 ≤ trial`. Así todo candidato (`jj ≥ left[i]`) tiene `m = n − jj ≤ i − 1` y diferencia `≥ 0`, y
   `trial`, que es uno de ellos, es `≥ 0`. Si `trial ≤ 0`, `sump = #{D < trial} ≤ #{(i,m): y[i] < y[m]} ≤ n(n−1)/2 <
   nn2 < knew`, luego `:238` no se cumple.
3. **Cotas estrictas.** Todo candidato vivo cumple `trial_L < D < trial_R`, con `trial_L` el último que movió
   `left` (`jj ≥ q_L[i]` ⇒ `D > trial_L`) y `trial_R` el último que movió `right` (`jj ≤ p_R[i]` ⇒ `D < trial_R`).
   El nuevo `trial` es uno de ellos, así que siempre `trial_L < trial_R`.
4. **`c_0 = 0` y `c_i ≥ 0` para `i ≥ 1`.** Fila 0: `right[0] = n` (inicio; y `p[0] = n` porque todas las
   diferencias `y[0] − y[m] ≤ 0 < trial_R`), `left[0] = n + 1` (inicio; y `q[0] = n + 1` porque `trial_L ≥ 0`).
   Filas `i ≥ 1`: (a) ambos iniciales: `c_i = i` o `c_i = hq`; (b) `right = p_R`, `left` inicial o `q_L`: `c_i =
   #{jj : trial_L < D_i(jj) < trial_R} ≥ 0` (o `p_R[i] − (n − i) ≥ 0` si `left` es inicial, por el lema 2);
   (c) `right` inicial reducido (`i > hq`, `:183`) y `left = q_L`: `c_i = hq − #{m < i : D ≤ trial_L}`. Si fuese
   negativo, la fila `i` tendría `≥ hq + 1` diferencias `≤ trial_L`; por monotonía, los `C(hq+2, 2)` pares del
   bloque `{i−hq−1, …, i}` también, pero `:245` exige `knew > sumq` ⇔ `#{pares m < i con D ≤ trial_L} < k =
   C(hq, 2) < C(hq+2, 2)`. Contradicción. **Este caso usa el `k` por defecto**; con otro `k` (no usado en
   `cov_mrcd`) no está demostrado, y es justo lo que anuncia el comentario de `:280`.
5. **`j ≤ n`.** Al salir sin `found` (`:187`), `nr − nl ≤ n`. Por 1 y 4: `j = Σ_{i≥1} max(c_i, 0) = Σ_i c_i =
   Σ right − nl ≤ nr − nl ≤ n`. Si el bucle no se ejecuta (`n(n−1)/2 ≤ n` ⇔ `n ≤ 3`): `j = 1` (`n = 2`) o
   `j = 3` (`n = 3`). Además `j ≥ 1`: si `right` se actualizó, `j = nr − nl ≥ 1` (`nr ≥ knew > nl`); si no, los
   `C(hq+1, 2) = k + hq` pares del bloque `{0, …, hq}` están en la banda y como mucho `k − 1` son `≤ trial_L`. El
   mismo argumento da `j ≥ 1` dentro del bucle, así que `whimed_i` nunca recibe `n = 0` (`NA_REAL` inalcanzable).
6. **La acotación `:280-290` es inalcanzable con `k` por defecto.** `knew > nl` siempre. Si `right` se actualizó,
   `knew ≤ nr = nl + j`. Si no, `knew ≤ Σ right[i]`: con `n = 2m`, `Σ right = n² − (m−2)(m−1)/2` y la desigualdad
   equivale a `2m² − 2 ≥ 0`; con `n = 2m+1`, a `(3m² + 3m)/2 ≥ m(m+1)/2`. Luego `0 ≤ knew − nl − 1 ≤ j − 1`.
7. **Otros índices.** Bucle de `p`: `j < n` está en la condición (`:215`). Bucle de `q` (`:224`, sin cota): para la
   fila `i` se detiene como tarde en `m = n − j + 1 = i` (`y[i] − y[i] = +0`, `> trial` falso por el lema 2) y `j`
   solo decrece, así que `m ≤ n − 1`. `R_qsort` usa centinelas (`qsort-body.c:96`, `:102`, `:156-162`) válidos sin
   NaN (excluidos antes).

**Comprobación empírica** (S15 + S17, transliteración instrumentada): 26000 casos, `max j/n = 1.0` (**`j = n` se
alcanza**: el búfer de tamaño `n` es justo, sin holgura), acotación activada 0 veces, 1075 casos «no encontrado»
sin ninguna actualización de `right`.

**Requisito:** búfer `work` de tamaño `n`, como R, más la comprobación defensiva de la tabla (a) que lanza
`RuntimeError` en lugar de escribir fuera; no se amplía el búfer (cambiaría el comportamiento si la prueba fallase:
se prefiere fallar).

##### e) Hilos: invariantes y determinismo

1. Cada columna (o par de OGK) es una función pura de sus datos y de `n`: sin estado global ni `static`
   (verificado: `R_qsort` solo usa locales, `qsort-body.c:41-48`; `psort_body`, `sort.c:669-670`; `whimed_i`,
   `wgt_himed_templ.h:44-47`). El port no puede añadir estado compartido.
2. Espacio de trabajo **privado por hilo**, reservado entero antes de crear hilos; un fallo de `malloc` ⇒
   `MemoryError` antes de calcular nada; ninguna reserva dentro de los hilos.
3. Cada posición de salida (`res[c]` o `U[i,j]`/`U[j,i]`) la escribe **un solo** hilo; no hay reducciones entre
   hilos.
4. El reparto (bloques fijos o contador atómico C11) no altera ningún valor por 1-3: el resultado es idéntico bit a
   bit para cualquier `n_threads` y cualquier planificación.
5. GIL liberado durante el cálculo (`Py_BEGIN_ALLOW_THREADS`) con los `Py_buffer` retenidos; la entrada es de solo
   lectura y la salida un arreglo nuevo (sin alias). Contrato: nadie muta la entrada durante la llamada (en
   `pymrcd` son arreglos internos).
6. Errores (Inf, `j == n`, entorno FP del punto b.3) en marcas por hilo con el **menor índice de columna**; se
   informan tras el `join`, con mensaje determinista.
7. Todos los hilos se unen antes de volver (sin hilos vivos si `TaskMapper` hace `fork` después).
8. Si `pthread_create` falla, se unen los hilos ya creados y se lanza `OSError` (con `errno`); no hay cálculo
   parcial. **Decisión del dueño (2026-10-07)**: sustituye a la propuesta original de «terminar en el hilo
   llamador», para no ocultar un fallo del sistema ni tener una ruta de ejecución más que probar.
9. Riesgo solo de rendimiento: dentro del *bootstrap* con procesos (`TaskMapper`) habrá procesos × hilos; el
   parámetro `n_threads` debe poder fijarse desde arriba. No afecta a los bits.

##### f) Tolerancias declaradas antes de comparar

Comparación **por bits** (`view(np.uint64)`, que distingue `±0`; no `np.array_equal`, que los iguala); los NaN
solo por posición (su carga no sale de `cov_mrcd`, que falla antes).

| Comparación | Datos | Tolerancia |
| --- | --- | --- |
| `qn0` C vs `.C(Qn0, …)` de R (crudo) | fixtures nuevos: S15 (±0), S17 (genéricos), y casos con `n ∈ 2..12`, `n` grande (≥ 1000), escalas `1e-300`/`1e300` | **exacta en bits, incluido el signo del cero**; también fuera de la plataforma de referencia (sin libm ni BLAS; condiciones de b) |
| `Qn` C (vía envoltorio) vs `robustbase::Qn` | idem | exacta en bits |
| `R_qsort` C vs `.Internal(qsort(x, FALSE))` (`sort.R:152`); `rPsort` C vs `.Internal(psort(x, k))` (`sort.c:763-764`, `:744`); `whimed_i` C vs `.C(wgt_himed_i, …)` (`wgt_himed.c:45-58`) | vectores con `±0`, empates y longitudes `1..200`; ganchos de prueba privados del módulo | exacta en bits **de todo el arreglo resultante** (posición de cada `±0`), no solo del valor seleccionado. **Implementado de otro modo:** los tests comparan contra la transliteración literal en Python (`tests/r_sort_literal.py`), no contra fixtures de R; el contraste directo con R lo hicieron ad hoc el validador y el convertidor (0 diferencias), pero **no está versionado** (deuda) |
| `qn0` C vs oráculo Python actual (el `qn.py` de hoy, movido a `tests/support/` como oráculo) | aleatorios y fixtures existentes | exacta en bits **salvo** `a == 0 and b == 0` con signo distinto (P5; S15); en ese caso manda la comparación con R |
| `U` de OGK C vs `ogk.py:24-58` actual | fixtures C1–C11 (incluye `p > n`) y `n=40, p=600` | **exacta en bits sin excepción** (`U` nunca es `−0`, apartado c). **Implementado:** con `p > 60` el test compara un bloque de 60 columnas; la `U` completa quedó cubierta por la instantánea bit a bit (2933 claves) que no se versionó (deuda) |
| `r6.U` C vs R (§10) | fixtures | exacta en bits (clase E, como hoy) |
| `cov_mrcd` antes ↔ después | todos los fixtures golden, más datos con empates, con `−0.0` y con `p ≫ n`; «antes» capturado con el commit `54ede77` en la misma máquina y guardado (`.npz`) | **exacta en bits en todas las salidas y en los intermedios**, salvo el signo de los ceros de `vsd_raw` (P5); justificación en c |
| Independencia de hilos | `n_threads ∈ {1, 2, 3, 7, núcleos}` y orden de columnas invertido | exacta en bits |

##### g) Ahorros de cálculo (sin cambiar ningún bit)

| Id | Dónde | Qué se ahorra | Por qué no cambia el resultado | Cómo se prueba |
| --- | --- | --- | --- | --- |
| A1 | `qn_sn.c:133-142`; temporales de `qn.py:197-289` | 9 reservas por llamada → 9 por hilo y llamada | `qn0` escribe antes de leer: `y` (`:156-157`), `left`/`right` (`:176-185`), `work`/`weight` hasta `j` (`:191-198`, `:266-272`), `p`/`q` completos (`:213-227`), `a_srt` (`wgt_himed_templ.h:61-62`), `a_cand`/`w_cand` hasta `kcand` (`:86-99`) | compilación con `-fsanitize=address,undefined` en un trabajo de CI (**deuda: no hay trabajo de CI; solo una corrida manual del validador, 200 000 vectores sin avisos**); modo de depuración que llena el espacio con NaN de carga distinta antes de cada columna y exige los mismos bits; orden de columnas invertido |
| A2 | `ogk.py:44-56` | las copias `arr[:, bi]`, `arr[:, bj]`, `yi + yj`, `yi − yj`, `concatenate` (5 matrices `n × lote`) y la copia `x → y` de `qn0` | la construcción del par **es** la copia de `:156-157`: una sola suma/resta IEEE por elemento, igual que numpy; la copia es la identidad de bits | `U` C vs `ogk.py` actual, bit a bit |
| A3 | `qn.py:323-329` | `np.isnan(arr)`, `arr[:, ~has_nan]`, `np.isinf`, `arr[:, ok]` (dos pasadas y dos copias) | se comprueba lo mismo, en la pasada de copia; solo lectura | columnas con NaN, con Inf, con ambos; mismo tipo y mensaje de error |
| A4 | `qn.py:281-288` (`np.asarray`, lotes `_CHUNK_ELEMENTS`) | copia de entrada y lotes | lectura por *strides* del búfer; la copia a `y` es necesaria de todos modos | entradas C-contiguas, F-contiguas y con `strides` arbitrarios: mismos bits |
| A5 | `qn_sn.c:144-155` | `nn2`, `n2`, `k_L`, `h`, `k` una vez por llamada en vez de por columna | funciones puras de `n` con la misma expresión (y sin contracción, b) | cubierto por las comparaciones de f |
| A6 | `qn_sn.c:228-234` | una pasada de `n` por iteración: `sump`, `sumq` acumulados dentro de `:213-218` y `:222-227` | sumas **enteras** `int64_t` (exactas, conmutativas; `≤ n² < 2^63`) | f |
| A7 | `qn_sn.c:239-240`, `:246-247` | copias de `n` enteros por iteración: intercambio de punteros `right ↔ p`, `left ↔ q` | tras el intercambio, `p` y `q` apuntan a datos obsoletos que se sobrescriben enteros antes de leerse: `whimed_i` usa `p` solo como borrador (`:199`), luego `:213-218` y `:222-227` rellenan `p` y `q` completos; la rama final solo lee `left`/`right`; con `len_k > 1` se reinicializan en `:176-185` | f (ahorro menor; opcional) |

**Llamadas a `Qn` repetidas en la ruta `cov_mrcd` (pedido c): no hay en posición general.** Inventario:
`vsd` sobre `x` crudo (`detmrcd.R:418`, `p` llamadas); `doScale` de `r6pack` sobre `x_j − median(x_j)` con `x = mU`
o `mW` (`detmrcd.R:124`, `p`); `initset` sobre `proj_k − median` para seis `P` distintas (`detmrcd.R:70`, `6p`);
OGK sobre `p(p−1)` pares distintos (`detmrcd.R:94`). Ningún par de llamadas recibe los mismos bits: `mU =
(x − vmx)/vsd` no es `x`, y `Qn` no es equivariante bit a bit ante traslación ni escala (T2, S9), así que no se
puede derivar una escala de otra. Único caso degenerado: `p = 1` (las seis `P` valen `[1]` y `initset` repite el
mismo `Qn` seis veces); no se propone memorizar (ahorro de `5` llamadas de longitud `n` frente al coste de
comparar entradas), y fuera de `qn0` excede esta tarea.

**Dentro de `qn0` (pedido d), lo que no se toca:** el `(float)` repetido en `:195`, `:215` y `:224` (son pares
distintos en cada barrido; precalcular las `n²` diferencias cuesta `O(n²)` de memoria); el barrido lineal de `p`/`q`
(ya es `O(n)` por iteración; la búsqueda binaria de `qn.py:86-131` era solo para vectorizar en numpy); la copia
`a → a_srt` de cada ronda de `whimed_i` (`rPsort` permuta y el orden de `a` decide los candidatos y el signo del
cero); y `R_qsort` en lugar de otra ordenación (apartado c).

**Estado de la implementación (M5, 2026-10-07).**
- **Decisiones del dueño:** P1 = A (sin respaldo Python: el `Qn` de numpy vive solo en `tests/` como oráculo); P4 =
  M1 (pares de OGK y `(s*s − d*d)/4` en C); P5 (ante `±0` la referencia es R); ahorros A1–A7 sin cambiar bits.
- **Evidencia de fidelidad** (todo exacto en bits, incluido el signo del cero): `Qn` igual a R en 252 fixtures
  antiguos, 188 nuevos, 26 000 sondas y 6 000 vectores del validador; `U` de OGK igual al bucle de R en 6
  configuraciones × 1, 3 y 8 hilos; instantánea de `cov_mrcd` de 2933 claves (14 golden + 2 sintéticos) con 0
  diferencias antes/después. 0 instrucciones FMA en el binario (11 pares `fcvt`; `scripts/check_pymrcd_fma.sh`).
- **Defensa contra `CFLAGS` externas:** `-fno-signed-zeros`, `-fassociative-math` y `-freciprocal-math` en el
  entorno no están prohibidos por el código, solo contrarrestados por `-fno-fast-math` al final de las opciones
  (§b.1). Riesgo bajo; no hay comprobación en tiempo de compilación.
- **Rendimiento** (Mac M2, 8 núcleos): ver `docs/ESTADO.md`. El criterio «≥ 10× con un hilo» **no** se cumple
  (4.1×): `qn0` literal cuesta ≈ 66–70 µs por columna con `n = 200`, frente a ≈ 77–82 µs de `.C(Qn0)` de R; más
  velocidad exigiría cambiar el algoritmo, lo que este apartado prohíbe.

**Sondas de esta sección** (2026-10-07; R 4.5.2, robustbase 0.99-6, numpy 2.5.3, arm64):
- **S15** (`±0`): 20000 vectores, `n ∈ 2..40`, semilla `20261007` (`numpy.random.default_rng`), fracción de ceros
  `U(0.3, 0.95)` con signo aleatorio y el resto `{−3..3}·{1, 0.5, 1e-300}`. R `.C(Qn0)`: 18630 ceros, 2715 de ellos
  `−0`. Transliteración literal: 0 bits distintos. `pymrcd` actual: 3809 / 3778 bits distintos (dos corridas), 0
  valores distintos.
- **S16** (no determinismo de numpy): matriz `40 × 3000` de `±0` con 5 filas a 1; 20 llamadas a `qn0_columns`
  ⇒ 20 resultados distintos; `np.sort(axis=0)` ⇒ 20 distintos; `np.sort` 1-D de 5000 `±0` ⇒ estable (1).
- **S17** (genéricos): 6000 vectores, `n ∈ 2..200`, semilla 7; normal, enteros `−5..5`, Cauchy redondeada a 0.1 y
  mezcla 60/40 con ruido `1e-3`. Literal y `pymrcd` actual: 0 bits distintos frente a R.
- **S18**: desensamblado (tabla de b). **S19**: contracción por defecto de `clang` (texto de b).

---

## 4. Trampas de exactitud

| # | Trampa | Dónde | Cómo se replica |
| --- | --- | --- | --- |
| T1 | **Qn devuelve a veces un valor redondeado a float32** (rama `found`) | `qn_sn.c:195`, `:215`, `:224`, `:260-261` | Port literal con `f32()` en las tres comparaciones/asignaciones; oráculo M2 acepta `{d, f32(d)}` [S1] |
| T2 | **`Qn(-v) ≠ Qn(v)` y `Qn(v+c) ≠ Qn(v)-shift` bit a bit** (no es invariante a signo ni a traslación por T1) | `qn_sn.c:191-227` | Respetar orientación `Y_i − Y_j` con `i>j` (`detmrcd.R:94`), centrar antes de Qn donde R centra (`rb/detmcd.R:249-253`) y **no** centrar donde R no centra (`detmrcd.R:418`). **[S9]** 86/2000 casos `Qn(x)≠Qn(-x)`; 611/2000 con traslación |
| T3 | **El signo de los autovectores importa** (vía T2: `lambda = Qn(data %*% P)`) | `detmrcd.R:70` | Usar `dsyevr` con los mismos argumentos que R (§3.12.6). **[S10]** cambiar signos de columnas de `P` cambia `lambda` en 4/20 casos (rel. ≤ 3.8e-8). **2026-10-06:** el `dsyevr` de scipy (Accelerate) puede devolver otro signo que Rlapack (S12); aceptado con tolerancia B (D9). En tests por etapa, `initset` recibe la `P` de R |
| T4 | Dos medianas distintas: `median()` (media de dos pasadas) vs `colMedians` (`(a+b)/2`) | `median.R:32` + `[tar]summary.c:479-518`; `rowMedians_TYPE-template.h:138` | `r_median` para `vmx`, `doScale`, `cutoffrho`; `r_colmedians` solo en `estloc` (`detmrcd.R:73`) |
| T5 | Sumas secuenciales (no por pares) en `rowMeans`, `rowSums`, `mean`, `cov/cor` | `array.c:2024-2098`; `[tar]summary.c:483-506`; `cov.c:201-219`, `:333` | `seqsum` / `np.cumsum`; nunca `np.sum`/`np.mean`/`np.cov`/`np.corrcoef` |
| T6 | Orden de las columnas de `hsets.init` = orden de distancia (no ordenado) y fija el orden de suma de `rowMeans` | `detmrcd.R:75`, `:459`, `:350`, `:467` | Conservar el orden de R al exportar/importar `initHsets` |
| T7 | Orden de `vals` en `upper.tri` (columna mayor) para `constcor` | `detmrcd.R:219` | `rows, cols = np.tril_indices(p,-1); cortmp[cols, rows]` |
| T8 | `%*%` = `dgemm('N','N')` en columna mayor; `crossprod` = `dsyrk('U')`+espejo; numpy `A@A.T` usa `syrk` | `array.c:788-843`, `:983-1020` | Helpers `r_matprod`, `r_matvec`, `r_vecmat`, `r_crossprod` con `scipy.linalg.blas` y operandos Fortran [S7] |
| T9 | Productos por matrices diagonales/identidad: R hace `dgemm` completo | `detmrcd.R:432`, `:313-316`, `:611-615` | Sustituir por escalado elemento a elemento es **bit a bit idéntico** (términos `0·a=0` exactos; un único redondeo `a·d`) mientras no haya NaN/Inf; conservar el orden `(d_i·M_ij)·d_j` y `1/vsd` multiplicado (`:614-615`) |
| T10 | Divisores distintos: `h` en `.RCOV`, `h-1` en selección de rho y en el final | `detmrcd.R:274`, `:280`, `:470`, `:579`, `:590` | Replicar literalmente |
| T11 | Umbral SMW distinto: `p > h` en C-steps, `p > n` en el final | `detmrcd.R:272-278` (n local = h), `:588` | Replicar literalmente |
| T12 | `tanh`, `sin`, `log`, `pow` de libm | `detmrcd.R:132`, `:218`; `Lapack.c:1434`; `[tar]arithmetic.c:225` | `math.*` por elemento [S8] |
| T13 | `eigen()` sin `symmetric=` en `:473`: rama `isSymmetric` ⇒ `La_rs` con **`jobz='V'`** (aunque solo se usen valores) | `detmrcd.R:473`, `eigen.R:57-62`, `Lapack.c:183` | `dsyevr` con vectores (`compute_v=1`), `lower=1` (de Accelerate: no bit a bit, D9). **[S4]** valores `jobz='N'` ≠ `jobz='V'` (rel. 1.0e-15…3.2e-15); `mS` de `dgemm` puede no ser simétrica exacta pero pasa `isSymmetric` (tol `100·eps`). Si el test fallara, R usaría `La_rg` (`dgeev`, `eigen.R:63-66`): portar también esa rama |
| T14 | `uniroot` = `R_zeroin2` con `tol=2^-13`; errores ⇒ rejilla | `nlm.R:55-170`, `zeroin.c:89-194`, `detmrcd.R:495-514` | Port literal **con 3 FMA** (`zeroin.c:134`, `:159`, `:167`; §3.12.8) (brentq no sirve: otra interpolación y criterio) |
| T15 | `vdst = diag(t(D) %*% (mIS %*% D))` calcula el producto **n×n completo** | `detmrcd.R:360`, `:371` | Fiel: dos `dgemm` y diagonal (bit a bit con mismo BLAS). `einsum` cambia el orden de la reducción de longitud p (pregunta P5) |
| T16 | `rho` de la rejilla: `seq` = `from+(0:n)*by` y `pmin(·, to)`; `min(grid[og == min(og)])` con igualdad exacta | `seq.R:88-96`, `detmrcd.R:503-506` | Replicar [S4] |
| T17 | Con `rho` dado, el conjunto 1 se procesa dos veces; `iBest` puede repetir `1` | `detmrcd.R:536-539`, `:547`, `:551` | Replicar. **[S6]** `iBest = 1 1 2 3 4 5 6` |
| T18 | Sin convergencia en `maxcsteps`, `index` nuevo con `mu`/`cov` viejos; el final usa ese `mu` | `detmrcd.R:365-382`, `:578` | Replicar literalmente |
| T19 | `obj = det^(1/p)`: `det` puede subdesbordar a 0 (p grande) ⇒ todos empatan ⇒ gana `initV` e `iBest` acumula | `detmrcd.R:412`, `:564-572`, `det.R:25-29` | Calcular `det` como `sign·exp(modulus)` y luego `r_pow`; nunca en log |
| T20 | Columna constante ⇒ `cor` con NA ⇒ `eigen` lanza error y `CovMrcd` falla | `cov.c:358-360`, `eigen.R:55` | Lanzar error equivalente, sin *fallback*. **[S6]** `"infinite or missing values in 'x'"` |
| T21 | `scfac` vía scipy difiere ≤ 6.5e-15 relativo de nmath | `covMcd.R:602-607` | **Superada 2026-10-06:** se porta nmath (D10); scipy queda como oráculo independiente |
| T22 | `dsyevr` depende de `lwork` (bloqueo de `dsytrd`) | `Lapack.c:203-218` | Consultar `lwork` óptimo como R (§3.12.6). Necesario pero no suficiente: el `dsyevr` de Accelerate no es el de Rlapack (T28, D9) |
| T23 | `mah` final se calcula sobre la `x` filtrada original, no sobre la reconstruida | `CovMrcd.R:46` vs `detmrcd.R:610`, `:618` | Usar `x` filtrada |
| T24 | `target` ≠ `"identity"` cualquier cadena ⇒ equicorrelación en `CovMrcd` | `CovMrcd.R:29` | La API del port valida `{identity, equicorrelation}`; documentado como validación, no cambia números |
| T25 | `alpha*n` y `ceiling`; `h/n` como `double` | `detmrcd.R:397`, `:460` | Mismo IEEE en Python |
| T26 | **Contracción FMA** del binario de R (`clang -O2`, arm64): `a*b+c` con un solo redondeo | `cov.c:265`, `:333`; `zeroin.c:134`, `:159`, `:167`; `qnorm.c:82-138`, `:151-157`; `array.c:728`, `:751` | `fma` exacto (`_fma.py`) en cada contracción; `cov_na_1` en bloques de 8 sin FMA + cola FMA (§3.12.8). **[S11]** secuencial sin FMA: 28/81 entradas de `cov` distintas |
| T27 | `dgemv('T')` de Accelerate depende de la **alineación** del operando | `array.c:834-838`; `[tar]Defn.h:219-224` | Copiar operandos de > 120 `double` con datos a `48 mod 64` bytes (`_rlinalg.py:_fortran`). **[S13]** |
| T28 | `scipy.linalg.lapack` es el LAPACK de **Accelerate**, no el Rlapack 3.12.1 de R | `Lapack.c` → `dlapack.f` | `dpotrf`, `dpotri`, `dgetrf`: port literal de `dlapack.f` sobre `scipy.linalg.blas` (`_rlapack.py`). `dsyevr`: tolerancia B (D9). **[S14]** |

**Base 1 → base 0:** índices de observaciones (`hsets`, `index`, `best`, `Hinit`, `ind5`) se guardan en R en base 1;
el port trabaja en base 0 y **exporta en base 1** para comparar. `x[ , ]` sin `drop` en `:161`, `:180`.

## 5. Determinismo

El camino `CovMrcd` es **determinista**: `sample()` (`detmrcd.R:349`) solo se ejecuta con `index=NULL`, y
`.cstep_mrcd` siempre recibe `index` (`:547`, `:559`). `rank` usa `ties.method="average"` (sin `runif`,
`rank.R:30-36`). No hay `set.seed` en la cadena. El determinismo es **por plataforma**: depende de BLAS/LAPACK
y libm (§6).

## 6. Riesgo R1 — revisión con evidencia (corrige el plan)

El plan supone que con p > n solo los conjuntos 1 y 4 dependen del redondeo. **No es así:**

1. Con p ≥ n, `R1`, `R2`, `R3` (correlaciones de n filas: rango ≤ n−1) y `SCM` (rango ≤ n) tienen espacio nulo
   de dimensión ≥ p−n+1; `covx` (calculada con `half = ceil(n/2)` filas, `detmrcd.R:159-161`) tiene rango ≤
   `half−1`, así que su espacio nulo existe **ya con p ≥ ceil(n/2)**, aunque n > p. La base que LAPACK devuelve
   dentro del espacio nulo la fija el ruido de redondeo, y `initset` no es invariante a rotaciones dentro de
   él (Qn no lo es).
2. **[S2]** Perturbación simétrica de `1e-14·max|M|` en la entrada de `eigen` (5 semillas):
   `n=100,p=5` y `n=100,p=40`: los 6 conjuntos idénticos; `n=60,p=40`: conjunto 5 distinto en 5/5;
   `n=30,p=60` y `n=20,p=100`: **conjuntos 1–5 distintos en 5/5**, el 6 (OGK) idéntico.
3. **[S3b]** Con perturbación de `1e-16·max|M|` (por debajo de 1 ulp en muchas entradas) y `CovMrcd` completo:
   con p > n cambian 1–4 conjuntos, **cambia `rho`** (p. ej. `0.1044` → `0.1031`) y `cov` difiere hasta `0.80`
   en valor absoluto aunque `best` coincida; con `n=60, p=40` nada cambia a esa escala. S3b es una **cota
   inferior** (pocas semillas, una escala): que en una corrida cambien 1–4 conjuntos, o ninguno con `n=60, p=40`,
   no clasifica a los demás como estables. La clasificación vale por el argumento estructural del punto 1 y por S2.
3b. **Hallazgo final (2026-10-06):** con **p ≥ n** dependen del redondeo los conjuntos **1 a 5**; el **5** ya
   desde **p ≥ ceil(n/2)** (aunque n > p); solo el **6** (OGK: `U` por Qn de pares, sin espacio nulo forzado)
   es estable. Matiz: con p = n exacto, `SCM` puede tener rango completo y el conjunto 4 no tiene espacio nulo
   estructural; se trata como R1 igualmente (criterio conservador, coherente con D1).
4. Además del espacio nulo, T3: el signo de cada autovector cambia `lambda` vía Qn (todo p).

Consecuencia para el protocolo aprobado:
- (i) y (ii) no cambian y son la prueba estricta de fidelidad.
- (iii) desde cero: con **p ≥ n** solo el conjunto **6** se puede exigir exacto; los conjuntos 1–5 son
  divergencia R1. Con **ceil(n/2) ≤ p < n**, el conjunto 5 es R1. Como `rho` es función de los seis conjuntos
  (`:518-519`), **`rho`, `best`, `cov`, `icov`, `center`, `mah` y `crit` desde cero no son comparables con p ≥
  ceil(n/2)** cuando algún conjunto R1 difiera. Pregunta P1.
- Lo anterior vale aunque Python y R usen el mismo BLAS: R usa Rlapack de referencia y scipy el LAPACK de
  Accelerate. ~~**[S3]** En `cor` 12×12, valores propios bit a bit iguales, vectores a ≤1.7e-16 y mismos
  signos.~~ **Corregido 2026-10-06:** ese caso era favorable y no generaliza. **[S12]** `eigen(cor(X))`
  con p = 5, 12, 30 coincide en valores; con p = 60 difieren 42/60 valores (≤ 10 ulp del propio valor,
  ≤ 5.2·eps·λmax) y 9 vectores cambian de signo (≤ 2.6e-14 módulo signo); con p = 120, 95/120 valores y 17
  signos. El convertidor midió 1–4 ulp y cambios de signo en los fixtures del bloque 1. Como el `eigen` del
  port no es bit a bit (D9), en el protocolo (iii) **incluso con n > p** cualquiera de los 6 conjuntos (también
  el 6, cuya `P6` sale de `eigen(U)`) puede diferir de R vía T3 (signo o último bit de `P` ⇒ `lambda` ⇒ orden de
  `dist`). Es la divergencia de un autovector **bien condicionado**, no la del espacio nulo: en S10 el cambio de
  signo alteró `lambda` en 4/20 casos pero el orden final en 0/20, así que se espera rara; si aparece, se registra
  con la diferencia de `P` medida y no se relaja ninguna tolerancia. La prueba estricta de extremo a extremo
  sigue siendo (ii), con `initHsets` de R.

**Caso límite conocido: C5 (AR(1) 50×200).** En C5 `rho_1 ≈ rho_2 ≈ cutoff` con un margen de ~1.1e-15
relativo, del orden del ruido que D9 introduce en `eigen` (3e-16–6e-16). Los conjuntos 1 y 2 son **el mismo
subconjunto en distinto orden**: permutarlo no cambia `cov`, pero sí `iBest` y `n.csteps`. Por eso el nivel (ii)
no puede exigir esas dos salidas por igualdad cuando el margen está por debajo del ruido; comprueba, en cambio,
que el margen de cada decisión de `rho` frente al cutoff supera una cota clase B de **1e-12 relativo** y, si no
la supera, lo registra como caso límite en lugar de relajar una tolerancia (declarado antes de comparar).

**Protocolo (iii) por régimen (n, p), ampliación de ADR 0006 (Enmienda 2026-10-06).**

| Régimen | Conjuntos exigidos exactos desde cero | R1 |
| --- | --- | --- |
| p ≥ n | solo el 6 | 1–5 |
| ceil(n/2) ≤ p < n | 1–4 y 6 | 5 |
| p < ceil(n/2) | los 6 | ninguno |

Con D9, un conjunto exigido que difiera por `eigen` se registra con la diferencia de `P` medida. Para el
régimen intermedio se añade el golden **C11 (60×40)**.

**Segundo canal de R1: tests por etapa fuera de la plataforma de referencia (añadido 2026-10-09, decisión del
dueño D1; Paso 4, validación en Linux).** La tabla anterior describe R1 **desde cero** (nivel iii), donde la
divergencia entra por la base que `eigen` elige dentro del espacio nulo. Fuera de `REFERENCE_PLATFORM`
(`packages/pymrcd/tests/fixtures_r.py:34`: macOS arm64), R1 tiene un segundo canal que alcanza también a los
tests **por etapa** (nivel i), **aunque la `P` sea la de R**:

- *Mecanismo.* Con p ≥ n, `SCM` (y `R1`–`R3`) tiene espacio nulo estructural (punto 1). Si la `P` de R lo
  contiene, las columnas de `data %*% P` (`detmrcd.R:70`) correspondientes a esos autovectores son ruido de
  redondeo, su Qn `lambda` es ≈ 5e-16 y `sqrtinvcov = P %*% (t(P) / lambda)` (`:72`) tiene entradas ~1e15. Una
  diferencia de 1 ulp de BLAS (OpenBLAS frente a Accelerate) en `data %*% sqrtinvcov` (`:73`), en `estloc`
  (`:73`, `dgemv`) o en `centeredx` (`:74`) queda amplificada por `1/lambda` y domina `dist` (`:75`); el orden
  `sort.list(dist)` (`:75`) cambia. Es el mismo fenómeno de R1 (dependencia del redondeo dentro del espacio
  nulo), no un defecto del port.
- *Evidencia medida (2026-10-09, imagen Docker `gate`, gcc + OpenBLAS + glibc; Linux arm64 nativo y amd64
  emulado).* Caso **C1, conjunto 4** (n = 50, p = 200): `dist` difiere hasta **6.9 %** relativo y `ord`
  difiere en **20 de 25** posiciones; en amd64, `is_colmed` difiere **13.8** en relativo y `lambda` **0.195**
  en **150** columnas (las del espacio nulo, p − n = 150); `min(lambda)/max(lambda) = 1.7e-16`.
- *Regla (alcance exacto).* En los tests por etapa de `initset` (`test_etapas_bloque2.py:154`,
  `test_initset_stages`) **fuera de la plataforma de referencia**, si y solo si se cumplen **las dos**
  condiciones:
  1. el conjunto `k` **no** pertenece a `required_sets(n, p)` (la misma regla del protocolo iii,
     `test_extremo_a_extremo.py:85`, tabla anterior); **y**
  2. hay **prueba estructural de espacio nulo**: `min(lambda) / max(lambda) ≤ 10·p·eps` sobre el `lambda` de R
     (`is.k.lambda`, §10; en C1-4 vale 1.7e-16 frente a la cota 10·200·2.22e-16 = 4.4e-13),

  entonces las etapas **posteriores a `is_lambda`** que dependen de `1/lambda` (`is_colmed`, `is_estloc`,
  `is_centeredx`, `is_dist`) y el orden `is_ord` se **registran** como `DivergenciaR1` (aviso con el error
  medido de cada una: máximo relativo, número de posiciones distintas en `ord`) en lugar de hacer fallar el test.
  Se **siguen exigiendo** con su clase de §11: `is_proj` (B), `is_lambda` (E dada `is_proj` de R),
  `is_sqrtcov` (B) e `is_sqrtinvcov` (B). Si falla cualquiera de las dos condiciones, todas las etapas se exigen
  como hasta ahora (§11).
- *En la plataforma de referencia no cambia nada:* allí las mismas etapas se siguen exigiendo con las clases de
  §11 (bit a bit donde §11 lo dice), también para los conjuntos R1. Ninguna tolerancia se relaja; la regla
  cambia el veredicto (fallo → aviso medido) solo cuando concurren el régimen R1 y la prueba numérica del
  espacio nulo.
- *Consecuencia de producto (ya declarada en ADR 0006, «Consecuencias»):* en Linux con p ≥ n el modelo puede
  diferir del de macOS (`rrcov` mismo no es reproducible entre plataformas en ese régimen).

## 7. OGK con Qn para todo p: vectorización sin cambiar el método

Coste: `p(p−1)` llamadas a Qn de longitud n (**[S6]** `n=40, p=600`: 6.9 s en R). Regla: se vectoriza **entre
columnas independientes**; dentro de cada columna se ejecuta la misma secuencia de `qn0`.

1. Construir por pares `i>j` (base 0) `S[:,m] = Y[:,i] + Y[:,j]`, `D[:,m] = Y[:,i] − Y[:,j]` (un redondeo cada uno,
   igual que R; orientación fija, T2). El orden de `m` es libre: cada `U[i,j]` es independiente.
2. `Qn` por lotes sobre las `2·p(p−1)/2` columnas (n común): ordenar cada columna (`np.sort(axis=0)`, solo
   valores); estado `left, right (n×M)`, `nl, nr, knew, found (M)`; iterar el `while` de `qn_sn.c:187` con una
   máscara de columnas activas. Equivalencias exactas permitidas dentro de una iteración:
   - `work/weight` (`:191-198`): el orden de empaquetado no altera `whimed_i` (selección). Las entradas no
     válidas se excluyen, no se ponen con peso 0 en una implementación que no lo soporte.
   - `whimed_i`: ordenar los `work` válidos de la columna y tomar el primero con `2·cumsum(w) > Σw` (entero).
   - `P[i]` (`:213-218`) = `#{j ∈ [0,n): f32(y[i] − y[n−1−j]) < trial}`. Prueba: para `i` fijo el predicado es
     monótono en `j` (`y` ordenado; resta en double y `f32` son monótonas) y es más débil para `i−1` que para `i`,
     así que el puntero arrastrado nunca salta un `j` válido. Implementable con búsqueda binaria vectorizada
     evaluando el **mismo** predicado `f32(y_i − y_m) < trial` (no con `searchsorted` sobre `y`).
   - `Q[i]` (`:222-227`) = `n + 1 − #{m ∈ [0,n): f32(y[i] − y[m]) > trial}` por el mismo argumento
     (`trial ≥ 0` y el predicado exige `y[m] < y[i]`, por lo que el índice no se sale de rango).
   - Rama no encontrada (`:262-293`): por columna, `work` de longitud ≤ n, `np.partition`.
3. `U[i,j] = (s*s − d*d)/4` con `s, d` ya multiplicados por la constante y corregidos (`Qn` completo, §3.12.1).
4. Con la implementación por lotes también se calculan `vsd` (`:418`), `doScale` (`:124`) y los 6 `lambda`.

**Acotado 2026-10-07 (M5, decisión del dueño):** el runtime de `pymrcd` sigue sin Numba ni Cython (ADR 0006,
P4), con **una única excepción aprobada**: la extensión C propia de `qn0` y de los pares de OGK (§3.12.9), port
literal de `qn_sn.c` + `wgt_himed_templ.h` + `R_qsort` + `rPsort`, con la C-API de CPython y sin dependencias de
runtime nuevas. Desde ese cambio, los puntos 1-2 de esta sección describen el **oráculo** numpy (pasa a
`tests/support/`, sin respaldo en `src/`, P1=A) y no la implementación; el punto 3 se hace en C (§3.12.9 a). Las
equivalencias de 2 valen para el **valor**, no para el signo de un cero (§3.12.9 c). ADR 0006 y P4 deben
recoger la excepción (tarea del documentador).

## 8. Código muerto en la versión oficial (verificado; documentar, no portar)

| Código | Líneas | Por qué no se ejecuta |
| --- | --- | --- |
| `fncond` no identidad y rejilla con `apply` | `detmrcd.R:485-493`, `:507-510` | `mT <- diag(p)` en `:436` ⇒ `all(mT == diag(p))` siempre TRUE (`:472`, `:504`). Incluye el `eigen(rcov)` de `:489` |
| `sample(1:n, h)` | `detmrcd.R:348-349` | `index` siempre se pasa (`:547`, `:559`) |
| `vMu` / `mIS` por parámetro | `detmrcd.R:352-358` | se llaman sin ellos: siempre se calculan (`:353`, `:356`) — **no** es muerto, es el camino normal |
| `classPC` y reordenación de la *six pack* | `detmrcd.R:176-196` | `adjust.eignevalues=FALSE` (`:446`) ⇒ `return` en `:173-174` |
| `ogkscatter` con `only.P=FALSE` | `detmrcd.R:105-110` | `only.P=TRUE` (`:166`) |
| objetivo `"det"` | `detmrcd.R:407-408` | `objective <- "geom"` (`:389`) |
| `mindet`, argumento `target` de `.RCOV`/`.cstep_mrcd` | `detmrcd.R:207`, `:269`, `:342` | no intervienen en ningún cálculo |
| `target <= 1` | `detmrcd.R:588` | `target ∈ {0,1}` (`CovMrcd.R:29`) |
| reconstrucción de `mX` y `dist` | `detmrcd.R:601`, `:610`, `:618` | `CovMrcd` descarta `mcd$mah` y recalcula sobre `x` (`CovMrcd.R:46`). Se puede exportar como intermedio de depuración |
| `trace` | `detmrcd.R:521-525`, `:552-574` | solo `cat` |
| `initHsets`/`save.hsets` | `detmrcd.R:448-457`, `:632` | **vivo** cuando el usuario pasa `initHsets` (protocolo ii): `if(is.vector) as.matrix`, comprobaciones de rango y `[1:h, ]` (con una sola columna, `[1:h, ]` la convierte en vector y `ncol` falla: pasar siempre 6 columnas) |

## 9. Diferencias con la variante modificada (`referencias/rrcov-1.7-7-modificado/`)

`diff -r` de `R/` contra la oficial: solo `detmrcd.R`; en `src/`: `ogkU.c` nuevo, `Makevars` (OpenMP) y
`rrcov_init.c` (registro de `ogkU_C`).

| Oficial | Modificada | Efecto |
| --- | --- | --- |
| `detmrcd.R:166` `P <- ogkscatter(x, scalefn, only.P=TRUE)` para todo p | `:166-171`: si `p(p−1)/2 > 1000` (p ≥ 46) usa `.Call("ogkU_C")` con **MAD sin constante** en lugar de Qn | **Cambia el método** (otra U ⇒ otra P6 ⇒ otro conjunto 6 ⇒ potencialmente otro `rho` y otro resultado). Prohibido por ADR 0002/0006 |
| `detmrcd.R:473` `eigen(scfac * mS)$values` (`jobz='V'`) | `:478` `eigen(…, symmetric=TRUE, only.values=TRUE)` (`jobz='N'`) | Valores propios distintos en ~1e-15 relativo **[S4]** ⇒ `e1`, `ep`, `rho_k` distintos en la última cifra; con p > n `e1` es ruido distinto (−8.9e-16 vs −4.3e-15) |
| `detmrcd.R:489` `eigen(rcov)$values` | `:494` `symmetric=TRUE, only.values=TRUE` | Sin efecto: código muerto en ambas (§8) |

El `rrcov` instalado en el sistema es la variante modificada: **nunca** usarlo como oráculo.

## 10. Intermedios a exportar para F2

Método de captura: copia **textual** de `referencias/rrcov-1.7-7/R/detmrcd.R` con llamadas `.cap(nombre, valor)`
insertadas (sin tocar ninguna expresión), evaluada con `environment = asNamespace("rrcov")` cargado desde
`referencias/R-lib`; se valida con `identical()` que sus salidas coinciden con `rrcov:::.detmrcd` y `CovMrcd`
oficiales. Serialización sin pérdida (17 cifras significativas, ADR 0006; o `%a`). Matrices en el orden de R,
índices en base 1. `k` = conjunto 1..6; `t` = iteración de C-step (0 = paso inicial `:356-361`).

| Nombre | Forma | Captura (`archivo:línea`, tras la línea) |
| --- | --- | --- |
| `in.x` | n×p | `CovMrcd.R:20` (x filtrada) y `in.ok` (n0, lógico) `:19` |
| `pre.n`, `pre.p`, `pre.h`, `pre.alpha` | escalares | `detmrcd.R:404` |
| `std.vmx` | p | `detmrcd.R:417` |
| `std.vsd_raw`, `std.vsd` | p | `detmrcd.R:418`, `:419` |
| `std.mU` | n×p | `detmrcd.R:421` |
| `tgt.cortmp_rank`, `tgt.cortmp_sin`, `tgt.constcor`, `tgt.R` | p×p, p×p, 1, p×p | `detmrcd.R:217`, `:218`, `:224`, `:226` (solo target=1) |
| `eq.values`, `eq.mQ`, `eq.mW` | p, p×p, n×p | `detmrcd.R:427-432` (solo target=1) |
| `r6.center`, `r6.scale`, `r6.x` | p, p, n×p | `detmrcd.R:124` (`doScale` completo) |
| `r6.y1`, `r6.R1`, `r6.P1` | n×p, p×p, p×p | `detmrcd.R:132-134` (+ `r6.ev1` valores) |
| `r6.rank`, `r6.R2`, `r6.P2` | n×p, p×p, p×p | `detmrcd.R:138-139` |
| `r6.y3`, `r6.R3`, `r6.P3` | n×p, p×p, p×p | `detmrcd.R:143-145` |
| `r6.znorm`, `r6.xnrmd`, `r6.SCM`, `r6.P4` | n, n×p, p×p, p×p | `detmrcd.R:149-154` |
| `r6.ind5`, `r6.Hinit`, `r6.covx`, `r6.P5` | n, half, p×p, p×p | `detmrcd.R:158-162` |
| `r6.U`, `r6.P6` | p×p, p×p | `detmrcd.R:97-101` (U completa antes de `eigen`) |
| `is.k.proj`, `is.k.lambda` | n×p, p | `detmrcd.R:70` |
| `is.k.sqrtcov`, `is.k.sqrtinvcov` | p×p | `detmrcd.R:71-72` |
| `is.k.colmed`, `is.k.estloc` | p, p | `detmrcd.R:73` |
| `is.k.centeredx`, `is.k.dist`, `is.k.ord` | n×p, n, h | `detmrcd.R:74-75` |
| `hs.init` | h×6 (orden original) | `detmrcd.R:459` |
| `scfac` (+ `scfac.q`, `scfac.pg`) | 1 | `detmrcd.R:460` (`covMcd.R:604-605`) |
| `rs.k.mu`, `rs.k.mS`, `rs.k.veigen`, `rs.k.e1`, `rs.k.ep` | p, p×p, p, 1, 1 | `detmrcd.R:468-475` |
| `rs.k.path`, `rs.k.flower`, `rs.k.fupper`, `rs.k.root`, `rs.k.iter`, `rs.k.estimprec`, `rs.k.irho` | `uniroot`/`grid`, escalares | `detmrcd.R:495-511` (con `uniroot` devolviendo `iter`, `estim.prec`) |
| `rs.rho6`, `rs.cutoff`, `rs.rho`, `rs.Vsel`, `rs.initV`, `rs.setsV` | 6, 1, 1, 6, 1, var | `detmrcd.R:518-535` |
| `cs.k.t.index`, `cs.k.t.vMu`, `cs.k.t.mS`, `cs.k.t.rcov`, `cs.k.t.inv`, `cs.k.t.vdst`, `cs.k.t.nndex` | h, p, p×p, p×p, p×p, n, h | `detmrcd.R:350-361` (t=0) y `:366-372` (t≥1); para p grande, solo fixtures pequeños |
| `cs.k.smw.G`, `cs.k.smw.Temp` | h×h | `detmrcd.R:314` (solo p>h) |
| `cs.k.numit`, `cs.k.obj`, `cs.k.det` | 1 | `detmrcd.R:547-548`, `:559-561` |
| `sel.best6pack`, `sel.hindex`, `sel.n_csteps` | var, h, 6 | `detmrcd.R:575` |
| `fin.mE`, `fin.W`, `fin.mu_std`, `fin.cov_std`, `fin.icov_std` | p×h, p×p, p, p×p, p×p | `detmrcd.R:578-593` |
| `fin.center`, `fin.cov`, `fin.icov`, `fin.target`, `fin.crit` | p, p×p, p×p, p×p, 1 | `detmrcd.R:615`, `:619` |
| `out.*` (`center`, `cov`, `icov`, `rho`, `target`, `cnp2`, `crit`, `best`, `mah`, `quan`, `alpha`, `n.obs`) | — | `CovMrcd.R:66-81` (objeto S4) |
| `out.iBest`, `out.n.csteps`, `out.initHsets` | — | `rrcov:::.detmrcd(…, save.hsets=TRUE)` (`detmrcd.R:621-634`) |

**Errores del contrato de fixtures detectados en el bloque 1 (2026-10-06; los corrige `ingeniero-r`).** Para que
conste, porque invalidan comparaciones hechas con esos fixtures antes de la corrección:
- `eigen_auto`: el fixture exportaba como entrada `S` pero los valores esperados se calculaban con
  `eigen(1.3*S)`. Regla: la entrada exportada debe ser **exactamente** el objeto pasado a la función (aquí
  `scfac * mS`, `detmrcd.R:473`), no uno del que se derive.
- `determinant/general`: exportaba `abs(det)^(1/7)` en vez de `det^(1/p)` (`detmrcd.R:412`: `det(x)^(1/p)`, con
  `det` con signo y `p` la dimensión de la matriz). Regla: la expresión del fixture se copia textual de la línea
  citada.

## 11. Tolerancias propuestas

Tres clases. **E** (exacto, `rtol=atol=0`): operaciones escalares IEEE sin BLAS/LAPACK ni libm transcendental,
reproducibles en cualquier plataforma si el port sigue §3 (incluidas las FMA de §3.12.8, que son exactas). **L**:
dependen de libm. **B**: dependen de BLAS/LAPACK (bit a bit en el Mac del oráculo si se usan los helpers §3.12.6
con la alineación de T27 y el LAPACK portado de T28; en Linux/OpenBLAS no). **Excepción (2026-10-06, D9):**
`eigen` (`dsyevr` de Accelerate, no de Rlapack) es B **también en el oráculo**: valores y vectores se comparan
siempre con tolerancia.

| Cantidad | Clase | Tolerancia en tests por etapa (entradas de R) | Extremo a extremo | Justificación |
| --- | --- | --- | --- | --- |
| enteros (`h`, `hsets`, `index`, `best`, `iBest`, `n.csteps`, `numit`, `initV`, `setsV`, `ord`) | E | exacto | exacto (salvo R1, §6) | discretos |
| medianas (`vmx`, centros de `doScale`, `colMedians`, `cutoffrho`) | E | **exacto** | exacto | selección + media de 2 en IEEE |
| `Qn`, `vsd`, `r6.scale`, U de OGK | E | **exacto** (endurece 1e-14) | `vsd` y U exactos; `lambda` ver abajo. **`target = equicorrelation` fuera de la referencia (D2, 2026-10-09):** `r6.scale` y la U calculada desde cero (`ogk_u` sobre la `x` de Python) heredan la clase **B** de `mW` (rtol 1e-12, atol `1e-14·max|ref|`), con la salvedad de la fila `lambda` (rtol 2^-23 si Qn salta a f32); `ogk_u(x de R)` sigue siendo E exacto | qn0 = restas, comparaciones, 2 operaciones finales; con equicorrelación la entrada `mW = mU %*% mQ` es `dgemm` (`detmrcd.R:432`) |
| `lambda` de `initset` | E dada su entrada | exacto | **rtol 2^-23** (≈1.19e-7) si la proyección `data %*% P` no es bit a bit | T1/T2: Qn salta entre `d` y `f32(d)` ante cambios de 1 ulp; no es relajar el port sino la propiedad de qn0 |
| `mU`, `x` de `doScale`, `x.nrmd`, `znorm`, rangos | E | **exacto** (endurece 1e-13) | exacto. **`target = equicorrelation` fuera de la referencia (D2, 2026-10-09):** `r6.center`, `r6.scale` y `r6.x` calculados desde `mW` de Python heredan la clase **B** de `mW` (rtol 1e-12, atol `1e-14·max|ref|`; si `r6.scale` salta a f32, rtol 2^-23 en `r6.scale` y `r6.x`); `doScale(mW de R)` sigue siendo E exacto | resta/división/sqrt IEEE; con equicorrelación la entrada de `doScale` (`detmrcd.R:124`) es `mW = mU %*% mQ` (`:432`, clase B) |
| `y1`, `cortmp_sin`, `y3` | L | rtol 1e-15 (`math.*`, AS241 portado) | idem | ≤ 4 ulp entre libm |
| `R1`, `R2`, `R3`, `covx`, `constcor` | E (L si entra `y1`) | **exacto** sobre entradas de R (endurece 1e-12). Para `R1`, «entrada de R» es `r6.y1`: `r_cor(r6.y1 de R)` es E (como `test_intermedios_bloque1.py:78`); la clase L es la de `y1` y no se traslada a `R1` (corrección 2026-10-09 de `test_etapas_bloque2.py:115`) | rtol 1e-12, atol 1e-14 | fórmula secuencial con el patrón FMA de cada rama (§3.12.4, §3.12.8) [S11] |
| `SCM` | B | rtol 1e-12, atol 1e-14 | idem | `dsyrk`; bit a bit con mismo BLAS |
| productos `dgemm` (`proj`, `sqrtcov`, `mS`, `W`, `G`…) | B | rtol 1e-12, atol `1e-14·max|ref|` | idem | error de `dgemm` ≤ k·eps·(|A||B|) |
| autovalores | B (también en el oráculo, D9) | atol `10·p·eps·λmax` (≤ 1e-10·λmax para p ≤ 4.5e4; endurece) | idem | `dsyevr` es estable hacia atrás: `O(p·eps·‖A‖)`. **[S12]** Accelerate vs Rlapack ≤ 5.2·eps·λmax (p ≤ 120) |
| autovectores | B (también en el oráculo, D9) | solo autoespacios con gap relativo > 1e-8, módulo signo, `‖v−v_R‖ ≤ 10·p·eps·λmax/gap`; el **signo** se informa (T3) pero no hace fallar el test (D9); la etapa siguiente (`initset`) se prueba con la `P` de R | idem | sensibilidad eps/gap; Accelerate y Rlapack pueden elegir signos distintos [S12] |
| `scfac` | L (tras D10) | **exacto en la plataforma de referencia** (nmath portado con las FMA de §3.12.8 y la libm del Mac, D10); **fuera de ella, rtol 1e-14** (otra libm en `lgamma`/`log`/`exp`, otro patrón FMA) | idem | scipy: medido 6.5e-15 [S5]; nmath portado: mismas operaciones y libm que R, de ahí la exactitud solo en la referencia |
| `e1`, `ep` | B | atol `10·p·eps·λmax` | idem | autovalores |
| `rho_k`, `rho` (uniroot o rejilla) | E dada `(e1,ep)` | **exacto** (endurece 1e-12) | atol 1e-12 | `R_zeroin2` es escalar puro |
| `uniroot` sintético con libm (`root`, `f_root`, `f_lower`, `f_upper`) (D3, 2026-10-09) | L (`root`); `f_root` sin tolerancia declarada | **solo en la plataforma de referencia**, bit a bit; fuera de ella el caso se **salta** con motivo explícito | — | la función de prueba llama a libm; `f_root` sufre cancelación (5.4e-10 relativo con 1 ulp); ver nota D3 |
| etapas de `initset` posteriores a `is_lambda` y `is_ord`, conjunto R1 con espacio nulo, fuera de la referencia (D1, 2026-10-09) | B amplificada por `1/lambda` | **registro** `DivergenciaR1` con error medido (no falla) si y solo si `k ∉ required_sets(n, p)` **y** `min(lambda)/max(lambda) ≤ 10·p·eps`; si no, su clase habitual | (nivel iii ya cubierto por §6) | segundo canal de R1 (§6); en la referencia, sin cambio |
| `rcov`, `inv_rcov`, `vdst` de C-step | B | rtol 1e-12, atol `1e-14·max|ref|`; `vdst` rtol 1e-12 | idem | dgemm/dpotrf/dpotri con cond ≤ `maxcond` en espacio estandarizado |
| `obj`/`det` por conjunto | B | rtol 1e-12 | rtol 1e-12 | |
| `center` (target=0) | E dado `hindex` | **exacto** | exacto | `rowMeans` + escalado exacto (T9) |
| `center` (target=1), `cov`, `icov`, `target` | B | rtol 1e-9, atol 1e-11 | rtol 1e-9, atol 1e-11 | se mantiene el plan; ver nota |
| `mah` | B | rtol 1e-9 | rtol 1e-9 | |
| `crit` | B | atol 1e-9 | atol 1e-9 | log-det |

Nota: el `atol` absoluto de `cov`/`icov` depende de la escala de los datos (con retornos ~1e-2, `icov` ~1e4);
los fixtures deberían incluir datos de escala O(1) y otros de escala financiera, y el test debe informar el
error relativo a `max|ref|` además del absoluto.

### 11.1 Enmienda 2026-10-09: tolerancias fuera de la plataforma de referencia (Paso 4)

**Decisión del dueño, 2026-10-09**, tomada tras el dictamen del validador estadístico sobre la etapa `gate` de la
imagen Docker (Linux arm64 nativo y amd64 emulado; gcc + OpenBLAS + glibc) y **escrita antes de volver a
comparar**. Principio sin cambios: en la plataforma de referencia (`REFERENCE_PLATFORM`,
`packages/pymrcd/tests/fixtures_r.py:34`; P6) **no se relaja nada** y se sigue exigiendo bit a bit donde la tabla
lo dice. Fuera de ella rigen las clases de la tabla; esta enmienda declara tres casos que no tenían regla y
registra dos defectos de test que se corrigen con clases **ya declaradas**. El validador no encontró ningún
defecto del port.

**Defectos de test (se corrigen con las clases existentes, sin regla nueva):**
- `test_etapas_bloque2.py:115` comparaba `set1_matrix(x)` contra `r6_R1` con la clase **L** de `y1` (fila
  `y1`). Lo declarado es la fila `R1`: **E sobre entradas de R**, es decir, `r_cor(r6.y1 de R)` exacto; `y1`
  se prueba aparte con L (ya lo hace `test_intermedios_bloque1.py:77-78`).
- `test_zeroin.py:61` comparaba `root` como **E** en casos cuya función usa libm. Por la definición de la clase
  L («dependen de libm», inicio de §11) `root` es **L** en esos casos; queda cubierto por D3.

**D1 — R1 en los tests por etapa fuera de la referencia.** Mecanismo, evidencia (C1-4, n = 50, p = 200: `dist`
hasta 6.9 %, `ord` distinto en 20/25; amd64: `is_colmed` 13.8 relativo, `lambda` 0.195 en 150 columnas;
`min(lambda)/max(lambda)` = 1.7e-16) y regla completa en **§6, «Segundo canal de R1»**. Alcance:
`test_initset_stages` (`test_etapas_bloque2.py:154`); cantidades `is_colmed`, `is_estloc`, `is_centeredx`,
`is_dist`, `is_ord`; condición: fuera de la referencia **y** `k ∉ required_sets(n, p)`
(`test_extremo_a_extremo.py:85`) **y** `min(lambda)/max(lambda) ≤ 10·p·eps`. Efecto: aviso `DivergenciaR1` con
la medición en lugar de fallo. Se siguen exigiendo `is_proj` (B), `is_lambda` (E), `is_sqrtcov` e
`is_sqrtinvcov` (B). En la referencia: sin cambio.

**D2 — `target = equicorrelation`.** *Mecanismo:* la entrada de `doScale` en `r6pack` (`detmrcd.R:124`) es
`mW = mU %*% mQ %*% misqL` (`:432`); el producto `mU %*% mQ` es `dgemm` (clase B, fila de productos `dgemm`),
así que fuera de la referencia `mW` puede diferir en ulps y todo lo que se calcula desde cero a partir de él
hereda esa clase. *Evidencia medida (amd64, caso C8_eq):* `r6_x` 7.29e-16·max, `r6_U` 6.55e-15·max (dentro de
B). *Alcance:* `r6.center`, `r6.scale`, `r6.x` y la `U` de OGK calculados desde cero en la cadena con
equicorrelación → **B** (rtol 1e-12, atol `1e-14·max|ref|`), con la salvedad de la fila `lambda`: si un Qn
(`r6.scale` o un elemento de `U`) salta entre `d` y `f32(d)` por la diferencia de entrada, rtol **2^-23** en esa
cantidad y en las que la dividen (`r6.x`). *Sin cambio:* con entradas de R (`doScale(mW de R)`,
`ogk_u(r6.x de R)`) siguen siendo **E exactos** en cualquier plataforma (Qn en C no depende de libm ni de BLAS,
ADR 0006 enmienda 2026-10-07 punto 7). Con `target = identity` no cambia nada (`mU` es E). En la referencia:
sin cambio.

**D3 — funciones sintéticas trascendentales de `uniroot`.** *Mecanismo:* los casos sintéticos de
`test_zeroin.py` (`_NAMED`, `test_zeroin.py:25-36`) cuya función llama a libm (`math.cos`, `math.exp`,
`math.tanh` u otra; fuera de la referencia la libm es glibc, no la del Mac) evalúan `f` con otros bits; `root`
pasa a ser L y `f_root`, evaluado junto a la raíz, sufre **cancelación**: con 1 ulp de diferencia en `root` se
midió **5.4e-10 relativo**, y no hay tolerancia declarada para él. *Regla:* esos casos son **solo de la
plataforma de referencia** (allí, bit a bit: `root`, `f_root`, `iter`, `estim_prec`, `f_lower`, `f_upper`);
fuera de ella se **saltan** con motivo explícito (D3). *Por qué no se pierde cobertura:* la fidelidad de
`R_zeroin2` fuera de la referencia la cubren los **38 casos `fncond` reales** (`detmrcd.R:479-484`; dan 0 bits
distintos en Linux) y los sintéticos puramente aritméticos, que se siguen exigiendo como E en todas las
plataformas. Si alguna vez se compara `root` de un caso con libm fuera de la referencia, su clase es **L**.
*Precisión de alcance:* `r_pow` con exponente distinto de 2 llama a `pow` de libm
(`packages/pymrcd/src/pymrcd/_rbase.py:106`, port de `R_pow`), así que por la letra de la regla los casos
`x^3 - 2` y `(x-0.3)^3 (raiz triple)` son de libm y quedan **solo en la referencia**; son puramente aritméticos
`x*x - 2`, `3*x - 1`, `x - 1e-5`, `x*x + 1` y `1/x - 7` (`r_pow` con `y == 2` es `x*x`, `_rbase.py:94-95`).
Ver pregunta abierta en el registro de cambios.

## 12. Preguntas abiertas

**Estado 2026-10-06:** P1–P8 están **resueltas** (ver «Decisiones del dueño (2026-10-06)» al final); P3 queda revisada por D10. No hay preguntas
abiertas. Se añaden las decisiones D9 y D10, tomadas tras el bloque 1.

- **P1 (R1). [Resuelta]** ¿Se acepta que en el protocolo (iii) con p ≥ n solo el conjunto 6 se exija exacto y que `rho`,
  `best` y las salidas continuas desde cero no se comparen (solo se registra la divergencia R1), y que con
  ceil(n/2) ≤ p < n el conjunto 5 sea R1? La prueba estricta de extremo a extremo queda en (ii) con `initHsets`
  de R.
- **P2 (BLAS). [Resuelta; ampliada por T27/T28: alineación y LAPACK de referencia portado]** ¿Se aprueba que el port use helpers sobre `scipy.linalg.blas`/`lapack` (`dgemm`, `dgemv`,
  `dsyrk`, `dsyevr`, `dpotrf`, `dpotri`, `dgetrf`) con operandos Fortran, en lugar de `@`/`np.linalg`? Sin eso
  no hay coincidencia bit a bit ni siquiera en el Mac del oráculo [S7].
- **P3 (nmath). [Resuelta; revisada por D10: se porta nmath]** ¿`scfac` vía scipy (≤ 6.5e-15 relativo) o portar `qchisq`/`pgamma` de nmath para exactitud? Lo
  mismo para `qnorm`: aquí se exige portar AS241 (pequeño), porque `ndtri` difiere en 2/3 de los puntos.
- **P4 (rendimiento). [Resuelta; acotada 2026-10-07 por la extensión C de §3.12.9, ADR 0006 enmienda 2026-10-07]** El runtime de `pymrcd` es solo numpy y scipy (ADR 0006). ¿Se admite Numba/Cython para
  `qn0` por lotes, o se queda la vectorización en numpy de §7?
- **P5 (`vdst`). [Resuelta: fiel, producto completo]** El cálculo fiel es O(n²p) y O(n²) de memoria (n=10 000 ⇒ 800 MB). ¿Se mantiene fiel o se
  aprueba `einsum` (cambia el orden de una suma de longitud p y puede alterar empates en la frontera h)?
- **P6 (plataforma del oráculo). [Resuelta: macOS arm64 / Accelerate / Rlapack 3.12.1; incluye el patrón FMA de §3.12.8]** Los fixtures se generan en arm64/Accelerate/Rlapack con `long double = double`.
  En x86-64 Linux, R usaría `long double` de 80 bits en `mean`, `rowMeans`, `cov` y daría otros bits. ¿Se fija
  esta plataforma como oráculo oficial (recomendado) y se anota en `docs/metodos/mrcd.md`?
- **P7 (errores de R). [Resuelta: error equivalente, sin *fallback*]** Columna constante (T20), `p=1` con `target="equicorrelation"` (`mean` de vacío ⇒ NaN ⇒
  `if(NA)` en `detmrcd.R:222`, y `eigenEQ` con `2:1` en `:238`) y `dpotrf` no definida positiva hacen fallar a R.
  Propuesta: el port lanza un error tipado equivalente, sin *fallback*. Confirmar.
- **P8. [Resuelta: error en el port, diferencia de API documentada]** Validación de `target` (T24): el port rechaza valores fuera de `{identity, equicorrelation}` donde R los
  trataría como equicorrelación. Confirmar que se documenta como diferencia de API.
- **D9 (decisión del dueño, 2026-10-06). `eigen` con tolerancia B.** No se porta `DSYEVR` de Rlapack: el port
  usa `scipy.linalg.lapack.dsyevr` (Accelerate) con los mismos argumentos que R (§3.12.6) y se acepta que
  difiera en 1–4 ulp en autovalores (hasta ~10 ulp del valor en p ≥ 60, S12) y en el signo de autovectores.
  Valores y vectores se comparan con las tolerancias B de §11 también en la plataforma de referencia; el signo
  se informa sin hacer fallar el test, y las etapas siguientes se prueban con la `P` de R. Efecto en (iii): §6.
- **D10 (decisión del dueño, 2026-10-06). `.MCDcons` con nmath portado.** Se portan `qchisq` (vía `qgamma`) y
  `pgamma` de `referencias/R-4.5.2/src/nmath/` para `scfac` (`covMcd.R:602-607`), con sus contracciones FMA
  (§3.12.8, ya localizadas en `libR.dylib`). Sustituye a la vía scipy de P3 (que queda como oráculo independiente en
  tests); tolerancia de `scfac`: exacta (§11).

---

## Anexo A. Sondas ejecutadas (R 4.5.2 oficial, `rrcov` de `referencias/R-lib`)

| Id | Qué se comprobó | Resultado |
| --- | --- | --- |
| S0 | Entorno | arm64, Accelerate BLAS, Rlapack 3.12.1, `long.double=FALSE`, `sizeof.longdouble=8`; rrcov 1.7.7 oficial cargado |
| S1 | `qn0` vs oráculo O(n²), 3000 casos, n ∈ {2..30, 50, 100, 101, 200} | 2736 exacto `d`, 264 `f32(d)`, 0 otros |
| S1b | `Qn = (2.21914·raw)/fc` (n>12) y `·TAB` (n≤12); `median` par con dos pasadas | idénticos; `0.40000000000000002` |
| S2 | Sensibilidad de `hsets` a perturbación `1e-14·max` en `eigen` | ver §6 |
| S3 | numpy/scipy vs R en el Mac: `matmul` 40×12·12×9, `cov` secuencial, `eigh(evr)` | ~~bit a bit; vectores ≤ 1.7e-16, sin cambio de signo~~ **Refutada 2026-10-06** en `cov` (sin FMA no coincide, S11) y `eigen` (no generaliza, S12); `dgemm` Fortran sigue valiendo (S7) |
| S3b | `CovMrcd` con `initHsets` perturbados `1e-16·max` | p>n: cambian 1–4 conjuntos, `rho` y `cov` (hasta 0.80); n=60,p=40: idénticos. **Cota inferior**: la clasificación final es la de §6 punto 3b (p ≥ n: conjuntos 1–5 R1; el 5 desde p ≥ ceil(n/2); solo el 6 estable) |
| S4 | `eigen(scfac·mS)`: simetría exacta, `isSymmetric`, `jobz V` vs `N`; rejilla `seq` | `dgemm` no simétrica exacta (p=5,h=15) pero `isSymmetric=TRUE`; V≠N (1.0e-15…3.2e-15); rejilla idéntica |
| S5 | `.MCDcons` R vs scipy | rel. máx 6.5e-15 |
| S6 | Casos de control | `iBest`, `n.csteps` con 0 en `initV`; `rho` dado ⇒ `iBest=1 1 2 3 4 5 6`; columna constante ⇒ error; 60 % ceros ⇒ OK; iid n=100,p=5 ⇒ `rho=1e-6`; n=40,p=600 ⇒ 6.9 s |
| S7 | `mE %*% t(mE)` y `crossprod` vs numpy/scipy | solo `blas.dgemm` Fortran y `blas.dsyrk` U+espejo coinciden |
| S8 | libm y `qnorm` | `np.tanh` 1995/10000 distintos, `math.tanh` 0; `ndtri` 676/999 distintos |
| S9 | Invariancias de Qn | `Qn(x)≠Qn(-x)` 86/2000; permutación 0/2000; traslación 611/2000 |
| S10 | `initset` con signos de `P` invertidos | `lambda` distinto en 4/20 (rel. ≤ 3.8e-8); orden final igual en 20/20 |
| S11 | `cov` (n=37, p=9, `rnorm`, seed 11) con y sin FMA vs R | secuencial sin FMA: 28/81 distintas; FMA en todo `k`: 39/81 distintas de `use="everything"`, 0 de `"complete.obs"`; `_rbase.r_cov` (bloques de 8 + cola FMA): 0/81 en ambas; `r_cor`: 0/81 |
| S12 | `eigen(cor(X), symmetric=TRUE)` de R vs `_rlinalg.r_eigen_sym` (scipy `dsyevr`, Accelerate), p ∈ {5,12,30,60,120} | p ≤ 30: idénticos en valores; p=60: 42/60 valores distintos (≤ 10 ulp del valor, ≤ 5.2·eps·λmax), 9 signos, vectores ≤ 2.6e-14 módulo signo; p=120: 95/120, ≤ 1.4·eps·λmax, 17 signos, ≤ 3.4e-14 |
| S13 | `v %*% B` (B 200×40) vs `blas.dgemv(trans=1)` con datos a `0,8,…,56 mod 64` bytes | solo `48 mod 64` coincide (0/40); otros 22–28/40 distintos; `_rlinalg.r_vecmat` 0/40 |
| S14 | LAPACK con `S = crossprod(Z)/300`, 80×80: `chol`, `chol2inv`, `determinant` | `scipy.linalg.lapack.dpotrf`: 2253/6400 distintas; port `_rlapack.dpotrf_upper`: 0. `dgetrf` de scipy: `modulus` distinto; port: idéntico. `dpotri` de scipy coincidió en este caso, pero no se acepta (otro algoritmo; el convertidor midió 1–2 ulp en fixtures); port: 0 |

---

## Decisiones del dueño (2026-10-06)

Cierran las preguntas abiertas de §12. Protocolo y plataforma: ver [ADR 0006](../adr/0006-libreria-pymrcd.md).

- **P1. Protocolo de fidelidad revisado: aprobado.** Por etapa; extremo a extremo con los 6 subconjuntos
  iniciales de R (prueba principal); desde cero, con p ≥ n solo el conjunto 6 exacto (el 5 como R1 si
  p ≥ ceil(n/2)) y con n > p los 6 y todo el resultado. Nunca se relaja una tolerancia.
- **P2. Álgebra lineal.** Helpers sobre `scipy.linalg.blas`/`lapack` con operandos Fortran, en lugar de
  `@`/`np.linalg`, para replicar las llamadas de R (S7). Sigue siendo solo numpy/scipy.
- **P3. `.MCDcons`.** Con scipy, rtol 1e-14 (S5 midió 6.5e-15); `qnorm` portado (AS241), porque `ndtri` difiere
  en 676/999 puntos (S8).
- **P4. Rendimiento.** Sin Numba ni Cython; Qn vectorizado en numpy según §7. **Acotada el 2026-10-07:** única excepción aprobada, la extensión C de §3.12.9 (ADR 0006, enmienda 2026-10-07); P1 = A, sin respaldo Python.
- **P5. `vdst` fiel** (producto completo). Si en producción n es muy grande, se revisa la memoria por bloques
  **sin cambiar el orden de operaciones**.
- **P6. Plataforma de referencia:** macOS arm64, R 4.5.2, BLAS Accelerate (vecLib), LAPACK Rlapack 3.12.1.
  Igualdad exacta solo ahí; en otras plataformas (p. ej. CI Linux con OpenBLAS) rigen las tolerancias de §11,
  declaradas antes de comparar.
- **P7. Fallos de R** (columna constante, p=1 con equicorrelación, matriz no definida positiva): el port lanza un
  error equivalente, sin *fallback*.
- **P8. `target`** distinto de `identity`/`equicorrelation`: error en el port (R lo trata como equicorrelación).
  Diferencia de API documentada.
- **Diferencias de API del port respecto de `rrcov` oficial** (validaciones del port; no cambian números cuando
  R termina con resultado):
  - `target` fuera de `{identity, equicorrelation}`: error (P8, T24); R lo trata como equicorrelación.
  - `n = 0` tras el filtro de filas no finitas: el port lanza `"All observations have missing values!"`; el R
    oficial termina con `"provide better scale; must be all positive"`. Mismo fallo, otro mensaje.
  - `init_hsets` se valida como enteros; R no lo hace.
  - Entrada 0-d (escalar) rechazada; R la convierte en una matriz 1×1.
  - Índices en **base 0** (`best`, `i_best`, `init_hsets`); en R son base 1.
- **Casos aceptados.** C9/C10 desplazan +5 en todas las coordenadas las primeras `ceiling(frac·n)` filas
  (20 % y 10 %); C7 con Σ = I.
