# MRCD — especificación exacta del port de `rrcov::CovMrcd` (F1b)

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
  (`:154-156`). Port **iteración por iteración** de `R_zeroin2` (`zeroin.c:89-194`), con la envoltura `fcn2`
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
**[S3]** la versión secuencial sin FMA reproduce `cov()` de R **bit a bit**.

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
| `v %*% B` | `dgemv('T')` sobre `B` (`array.c:834-838`) | `dgemv(1.0, F(B), v, trans=1)` |
| cualquier operando con NaN/Inf | `simple_matprod` (`array.c:734-740`, `:806-811`) | triple bucle con acumulación secuencial |
| `crossprod(X)` | `dsyrk('U','T')` + espejo (`array.c:983-1020`) | `scipy.linalg.blas.dsyrk(1.0, F(X), trans=1, lower=0)` + copiar triángulo superior al inferior |
| `eigen(A, symmetric=TRUE)` | `dsyevr(jobz='V', range='A', uplo='L', abstol=0)` con consulta previa de `lwork`/`liwork` óptimos (`Lapack.c:166-237`); orden decreciente (`eigen.R:59-62`) | `scipy.linalg.lapack.dsyevr(A, compute_v=1, range='A', lower=1, abstol=0.0, lwork=…, liwork=…)` con `lwork`/`liwork` de `dsyevr_lwork`; invertir orden de valores y columnas |
| `eigen(A)` sin `symmetric` | `isSymmetric.matrix` (`eigen.R:22-43`, `all.equal.R:99-174`) ⇒ casi siempre `La_rs` con `jobz='V'` (T13) | idem fila anterior, previa réplica del test de simetría |
| `chol(A)` | `dpotrf('U')` (`Lapack.c:1090-1104`); error si no DP | `scipy.linalg.lapack.dpotrf(A, lower=0)`; `info>0` ⇒ error |
| `chol2inv(R)` | `dpotri('U')` + espejo superior→inferior (`Lapack.c:1162-1178`) | `dpotri(c, lower=0)` + espejo |
| `determinant(A)$modulus` | `dgetrf`, `Σ log|U_ii|` secuencial (`Lapack.c:1415-1436`) | `scipy.linalg.lapack.dgetrf` + `math.log` y suma secuencial |

**[S7]** `mE %*% t(mE)` con `p=5, h=15`: R **no** es simétrica exacta; numpy `mE @ mE.T` usa `syrk` (simétrica,
≠ R); `mE @ copia(mE.T)` tampoco coincide; `dgemm(1.0, F(mE), F(t(mE)))` de scipy **coincide bit a bit**.
`crossprod`: `dsyrk` U + espejo coincide bit a bit; `x.T @ x` no.

#### 3.12.7 libm y `qnorm`

- `tanh`, `sin`, `log`, `exp`, `pow`: usar `math.*` por elemento (libm de la plataforma, la misma que usa R).
  **[S8]** `np.tanh` difiere de R en 1995/10000 casos (1 ulp); `math.tanh` en 0. `np.sin`, `np.log`, `np.exp`
  coinciden aquí, pero su implementación SIMD depende de la CPU: se exige `math.*`.
- `sqrt`, `+ − × ÷`: IEEE correctamente redondeados ⇒ numpy vale.
- `qnorm` (`qnorm.c:47-…`, AS241 de Wichura): **portar literalmente** `qnorm5`. **[S8]** `scipy.special.ndtri`
  difiere en 676/999 puntos `(i-1/3)/(n+1/3)` (≤ 6.4e-16 relativo).
- `x^y` ⇒ `r_pow` (§3.2); `x^2` ⇒ `x*x`; `x^(-1)` ⇒ `math.pow(x, -1.0)`.

---

## 4. Trampas de exactitud

| # | Trampa | Dónde | Cómo se replica |
| --- | --- | --- | --- |
| T1 | **Qn devuelve a veces un valor redondeado a float32** (rama `found`) | `qn_sn.c:195`, `:215`, `:224`, `:260-261` | Port literal con `f32()` en las tres comparaciones/asignaciones; oráculo M2 acepta `{d, f32(d)}` [S1] |
| T2 | **`Qn(-v) ≠ Qn(v)` y `Qn(v+c) ≠ Qn(v)-shift` bit a bit** (no es invariante a signo ni a traslación por T1) | `qn_sn.c:191-227` | Respetar orientación `Y_i − Y_j` con `i>j` (`detmrcd.R:94`), centrar antes de Qn donde R centra (`rb/detmcd.R:249-253`) y **no** centrar donde R no centra (`detmrcd.R:418`). **[S9]** 86/2000 casos `Qn(x)≠Qn(-x)`; 611/2000 con traslación |
| T3 | **El signo de los autovectores importa** (vía T2: `lambda = Qn(data %*% P)`) | `detmrcd.R:70` | Usar exactamente `dsyevr` con los mismos argumentos que R (§3.12.6). **[S10]** cambiar signos de columnas de `P` cambia `lambda` en 4/20 casos (rel. ≤ 3.8e-8) |
| T4 | Dos medianas distintas: `median()` (media de dos pasadas) vs `colMedians` (`(a+b)/2`) | `median.R:32` + `[tar]summary.c:479-518`; `rowMedians_TYPE-template.h:138` | `r_median` para `vmx`, `doScale`, `cutoffrho`; `r_colmedians` solo en `estloc` (`detmrcd.R:73`) |
| T5 | Sumas secuenciales (no por pares) en `rowMeans`, `rowSums`, `mean`, `cov/cor` | `array.c:2024-2098`; `[tar]summary.c:483-506`; `cov.c:201-219`, `:333` | `seqsum` / `np.cumsum`; nunca `np.sum`/`np.mean`/`np.cov`/`np.corrcoef` |
| T6 | Orden de las columnas de `hsets.init` = orden de distancia (no ordenado) y fija el orden de suma de `rowMeans` | `detmrcd.R:75`, `:459`, `:350`, `:467` | Conservar el orden de R al exportar/importar `initHsets` |
| T7 | Orden de `vals` en `upper.tri` (columna mayor) para `constcor` | `detmrcd.R:219` | `rows, cols = np.tril_indices(p,-1); cortmp[cols, rows]` |
| T8 | `%*%` = `dgemm('N','N')` en columna mayor; `crossprod` = `dsyrk('U')`+espejo; numpy `A@A.T` usa `syrk` | `array.c:788-843`, `:983-1020` | Helpers `r_matprod`, `r_matvec`, `r_vecmat`, `r_crossprod` con `scipy.linalg.blas` y operandos Fortran [S7] |
| T9 | Productos por matrices diagonales/identidad: R hace `dgemm` completo | `detmrcd.R:432`, `:313-316`, `:611-615` | Sustituir por escalado elemento a elemento es **bit a bit idéntico** (términos `0·a=0` exactos; un único redondeo `a·d`) mientras no haya NaN/Inf; conservar el orden `(d_i·M_ij)·d_j` y `1/vsd` multiplicado (`:614-615`) |
| T10 | Divisores distintos: `h` en `.RCOV`, `h-1` en selección de rho y en el final | `detmrcd.R:274`, `:280`, `:470`, `:579`, `:590` | Replicar literalmente |
| T11 | Umbral SMW distinto: `p > h` en C-steps, `p > n` en el final | `detmrcd.R:272-278` (n local = h), `:588` | Replicar literalmente |
| T12 | `tanh`, `sin`, `log`, `pow` de libm | `detmrcd.R:132`, `:218`; `Lapack.c:1434`; `[tar]arithmetic.c:225` | `math.*` por elemento [S8] |
| T13 | `eigen()` sin `symmetric=` en `:473`: rama `isSymmetric` ⇒ `La_rs` con **`jobz='V'`** (aunque solo se usen valores) | `detmrcd.R:473`, `eigen.R:57-62`, `Lapack.c:183` | `dsyevr` con vectores (`compute_v=1`), `lower=1`. **[S4]** valores `jobz='N'` ≠ `jobz='V'` (rel. 1.0e-15…3.2e-15); `mS` de `dgemm` puede no ser simétrica exacta pero pasa `isSymmetric` (tol `100·eps`). Si el test fallara, R usaría `La_rg` (`dgeev`, `eigen.R:63-66`): portar también esa rama |
| T14 | `uniroot` = `R_zeroin2` con `tol=2^-13`; errores ⇒ rejilla | `nlm.R:55-170`, `zeroin.c:89-194`, `detmrcd.R:495-514` | Port literal (brentq no sirve: otra interpolación y criterio) |
| T15 | `vdst = diag(t(D) %*% (mIS %*% D))` calcula el producto **n×n completo** | `detmrcd.R:360`, `:371` | Fiel: dos `dgemm` y diagonal (bit a bit con mismo BLAS). `einsum` cambia el orden de la reducción de longitud p (pregunta P5) |
| T16 | `rho` de la rejilla: `seq` = `from+(0:n)*by` y `pmin(·, to)`; `min(grid[og == min(og)])` con igualdad exacta | `seq.R:88-96`, `detmrcd.R:503-506` | Replicar [S4] |
| T17 | Con `rho` dado, el conjunto 1 se procesa dos veces; `iBest` puede repetir `1` | `detmrcd.R:536-539`, `:547`, `:551` | Replicar. **[S6]** `iBest = 1 1 2 3 4 5 6` |
| T18 | Sin convergencia en `maxcsteps`, `index` nuevo con `mu`/`cov` viejos; el final usa ese `mu` | `detmrcd.R:365-382`, `:578` | Replicar literalmente |
| T19 | `obj = det^(1/p)`: `det` puede subdesbordar a 0 (p grande) ⇒ todos empatan ⇒ gana `initV` e `iBest` acumula | `detmrcd.R:412`, `:564-572`, `det.R:25-29` | Calcular `det` como `sign·exp(modulus)` y luego `r_pow`; nunca en log |
| T20 | Columna constante ⇒ `cor` con NA ⇒ `eigen` lanza error y `CovMrcd` falla | `cov.c:358-360`, `eigen.R:55` | Lanzar error equivalente, sin *fallback*. **[S6]** `"infinite or missing values in 'x'"` |
| T21 | `scfac` vía scipy difiere ≤ 6.5e-15 relativo de nmath | `covMcd.R:602-607` | Aceptado con tolerancia (§11) o portar nmath (P3) |
| T22 | `dsyevr` depende de `lwork` (bloqueo de `dsytrd`) | `Lapack.c:203-218` | Consultar `lwork` óptimo como R (§3.12.6) |
| T23 | `mah` final se calcula sobre la `x` filtrada original, no sobre la reconstruida | `CovMrcd.R:46` vs `detmrcd.R:610`, `:618` | Usar `x` filtrada |
| T24 | `target` ≠ `"identity"` cualquier cadena ⇒ equicorrelación en `CovMrcd` | `CovMrcd.R:29` | La API del port valida `{identity, equicorrelation}`; documentado como validación, no cambia números |
| T25 | `alpha*n` y `ceiling`; `h/n` como `double` | `detmrcd.R:397`, `:460` | Mismo IEEE en Python |

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
   en valor absoluto aunque `best` coincida; con `n=60, p=40` nada cambia a esa escala.
4. Además del espacio nulo, T3: el signo de cada autovector cambia `lambda` vía Qn (todo p).

Consecuencia para el protocolo aprobado:
- (i) y (ii) no cambian y son la prueba estricta de fidelidad.
- (iii) desde cero: con **p ≥ n** solo el conjunto **6** se puede exigir exacto; los conjuntos 1–5 son
  divergencia R1. Con **ceil(n/2) ≤ p < n**, el conjunto 5 es R1. Como `rho` es función de los seis conjuntos
  (`:518-519`), **`rho`, `best`, `cov`, `icov`, `center`, `mah` y `crit` desde cero no son comparables con p ≥
  ceil(n/2)** cuando algún conjunto R1 difiera. Pregunta P1.
- Lo anterior vale aunque Python y R usen el mismo BLAS: R usa Rlapack de referencia y scipy el LAPACK de
  Accelerate. **[S3]** En `cor` 12×12, valores propios bit a bit iguales, vectores a ≤1.7e-16 y mismos signos.

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

Numba/Cython no están permitidos hoy en el runtime de `pymrcd` (solo numpy y scipy, ADR 0006): pregunta P4.

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

## 11. Tolerancias propuestas

Tres clases. **E** (exacto, `rtol=atol=0`): operaciones escalares IEEE sin BLAS/LAPACK ni libm transcendental,
reproducibles en cualquier plataforma si el port sigue §3. **L**: dependen de libm. **B**: dependen de
BLAS/LAPACK (bit a bit en el Mac del oráculo si se usan los helpers §3.12.6; en Linux/OpenBLAS no).

| Cantidad | Clase | Tolerancia en tests por etapa (entradas de R) | Extremo a extremo | Justificación |
| --- | --- | --- | --- | --- |
| enteros (`h`, `hsets`, `index`, `best`, `iBest`, `n.csteps`, `numit`, `initV`, `setsV`, `ord`) | E | exacto | exacto (salvo R1, §6) | discretos |
| medianas (`vmx`, centros de `doScale`, `colMedians`, `cutoffrho`) | E | **exacto** | exacto | selección + media de 2 en IEEE |
| `Qn`, `vsd`, `r6.scale`, U de OGK | E | **exacto** (endurece 1e-14) | `vsd` y U exactos; `lambda` ver abajo | qn0 = restas, comparaciones, 2 operaciones finales |
| `lambda` de `initset` | E dada su entrada | exacto | **rtol 2^-23** (≈1.19e-7) si la proyección `data %*% P` no es bit a bit | T1/T2: Qn salta entre `d` y `f32(d)` ante cambios de 1 ulp; no es relajar el port sino la propiedad de qn0 |
| `mU`, `x` de `doScale`, `x.nrmd`, `znorm`, rangos | E | **exacto** (endurece 1e-13) | exacto | resta/división/sqrt IEEE |
| `y1`, `cortmp_sin`, `y3` | L | rtol 1e-15 (`math.*`, AS241 portado) | idem | ≤ 4 ulp entre libm |
| `R1`, `R2`, `R3`, `covx`, `constcor` | E (L si entra `y1`) | **exacto** sobre entradas de R (endurece 1e-12) | rtol 1e-12, atol 1e-14 | fórmula secuencial [S3] |
| `SCM` | B | rtol 1e-12, atol 1e-14 | idem | `dsyrk`; bit a bit con mismo BLAS |
| productos `dgemm` (`proj`, `sqrtcov`, `mS`, `W`, `G`…) | B | rtol 1e-12, atol `1e-14·max|ref|` | idem | error de `dgemm` ≤ k·eps·(|A||B|) |
| autovalores | B | atol `10·p·eps·λmax` (≤ 1e-10·λmax para p ≤ 4.5e4; endurece) | idem | `dsyevr` es estable hacia atrás: `O(p·eps·‖A‖)` |
| autovectores | B | solo autoespacios con gap relativo > 1e-8, módulo signo, `‖v−v_R‖ ≤ 10·p·eps·λmax/gap`; **además** comparar signos (T3) | idem | sensibilidad eps/gap |
| `scfac` | — | rtol 1e-14 | idem | medido 6.5e-15 [S5]; exacto si se porta nmath (P3) |
| `e1`, `ep` | B | atol `10·p·eps·λmax` | idem | autovalores |
| `rho_k`, `rho` (uniroot o rejilla) | E dada `(e1,ep)` | **exacto** (endurece 1e-12) | atol 1e-12 | `R_zeroin2` es escalar puro |
| `rcov`, `inv_rcov`, `vdst` de C-step | B | rtol 1e-12, atol `1e-14·max|ref|`; `vdst` rtol 1e-12 | idem | dgemm/dpotrf/dpotri con cond ≤ `maxcond` en espacio estandarizado |
| `obj`/`det` por conjunto | B | rtol 1e-12 | rtol 1e-12 | |
| `center` (target=0) | E dado `hindex` | **exacto** | exacto | `rowMeans` + escalado exacto (T9) |
| `center` (target=1), `cov`, `icov`, `target` | B | rtol 1e-9, atol 1e-11 | rtol 1e-9, atol 1e-11 | se mantiene el plan; ver nota |
| `mah` | B | rtol 1e-9 | rtol 1e-9 | |
| `crit` | B | atol 1e-9 | atol 1e-9 | log-det |

Nota: el `atol` absoluto de `cov`/`icov` depende de la escala de los datos (con retornos ~1e-2, `icov` ~1e4);
los fixtures deberían incluir datos de escala O(1) y otros de escala financiera, y el test debe informar el
error relativo a `max|ref|` además del absoluto.

## 12. Preguntas abiertas

- **P1 (R1).** ¿Se acepta que en el protocolo (iii) con p ≥ n solo el conjunto 6 se exija exacto y que `rho`,
  `best` y las salidas continuas desde cero no se comparen (solo se registra la divergencia R1), y que con
  ceil(n/2) ≤ p < n el conjunto 5 sea R1? La prueba estricta de extremo a extremo queda en (ii) con `initHsets`
  de R.
- **P2 (BLAS).** ¿Se aprueba que el port use helpers sobre `scipy.linalg.blas`/`lapack` (`dgemm`, `dgemv`,
  `dsyrk`, `dsyevr`, `dpotrf`, `dpotri`, `dgetrf`) con operandos Fortran, en lugar de `@`/`np.linalg`? Sin eso
  no hay coincidencia bit a bit ni siquiera en el Mac del oráculo [S7].
- **P3 (nmath).** ¿`scfac` vía scipy (≤ 6.5e-15 relativo) o portar `qchisq`/`pgamma` de nmath para exactitud? Lo
  mismo para `qnorm`: aquí se exige portar AS241 (pequeño), porque `ndtri` difiere en 2/3 de los puntos.
- **P4 (rendimiento).** El runtime de `pymrcd` es solo numpy y scipy (ADR 0006). ¿Se admite Numba/Cython para
  `qn0` por lotes, o se queda la vectorización en numpy de §7?
- **P5 (`vdst`).** El cálculo fiel es O(n²p) y O(n²) de memoria (n=10 000 ⇒ 800 MB). ¿Se mantiene fiel o se
  aprueba `einsum` (cambia el orden de una suma de longitud p y puede alterar empates en la frontera h)?
- **P6 (plataforma del oráculo).** Los fixtures se generan en arm64/Accelerate/Rlapack con `long double = double`.
  En x86-64 Linux, R usaría `long double` de 80 bits en `mean`, `rowMeans`, `cov` y daría otros bits. ¿Se fija
  esta plataforma como oráculo oficial (recomendado) y se anota en `docs/metodos/mrcd.md`?
- **P7 (errores de R).** Columna constante (T20), `p=1` con `target="equicorrelation"` (`mean` de vacío ⇒ NaN ⇒
  `if(NA)` en `detmrcd.R:222`, y `eigenEQ` con `2:1` en `:238`) y `dpotrf` no definida positiva hacen fallar a R.
  Propuesta: el port lanza un error tipado equivalente, sin *fallback*. Confirmar.
- **P8.** Validación de `target` (T24): el port rechaza valores fuera de `{identity, equicorrelation}` donde R los
  trataría como equicorrelación. Confirmar que se documenta como diferencia de API.

---

## Anexo A. Sondas ejecutadas (R 4.5.2 oficial, `rrcov` de `referencias/R-lib`)

| Id | Qué se comprobó | Resultado |
| --- | --- | --- |
| S0 | Entorno | arm64, Accelerate BLAS, Rlapack 3.12.1, `long.double=FALSE`, `sizeof.longdouble=8`; rrcov 1.7.7 oficial cargado |
| S1 | `qn0` vs oráculo O(n²), 3000 casos, n ∈ {2..30, 50, 100, 101, 200} | 2736 exacto `d`, 264 `f32(d)`, 0 otros |
| S1b | `Qn = (2.21914·raw)/fc` (n>12) y `·TAB` (n≤12); `median` par con dos pasadas | idénticos; `0.40000000000000002` |
| S2 | Sensibilidad de `hsets` a perturbación `1e-14·max` en `eigen` | ver §6 |
| S3 | numpy/scipy vs R en el Mac: `matmul` 40×12·12×9, `cov` secuencial, `eigh(evr)` | bit a bit; vectores ≤ 1.7e-16, sin cambio de signo |
| S3b | `CovMrcd` con `initHsets` perturbados `1e-16·max` | p>n: cambian 1–4 conjuntos, `rho` y `cov` (hasta 0.80); n=60,p=40: idénticos |
| S4 | `eigen(scfac·mS)`: simetría exacta, `isSymmetric`, `jobz V` vs `N`; rejilla `seq` | `dgemm` no simétrica exacta (p=5,h=15) pero `isSymmetric=TRUE`; V≠N (1.0e-15…3.2e-15); rejilla idéntica |
| S5 | `.MCDcons` R vs scipy | rel. máx 6.5e-15 |
| S6 | Casos de control | `iBest`, `n.csteps` con 0 en `initV`; `rho` dado ⇒ `iBest=1 1 2 3 4 5 6`; columna constante ⇒ error; 60 % ceros ⇒ OK; iid n=100,p=5 ⇒ `rho=1e-6`; n=40,p=600 ⇒ 6.9 s |
| S7 | `mE %*% t(mE)` y `crossprod` vs numpy/scipy | solo `blas.dgemm` Fortran y `blas.dsyrk` U+espejo coinciden |
| S8 | libm y `qnorm` | `np.tanh` 1995/10000 distintos, `math.tanh` 0; `ndtri` 676/999 distintos |
| S9 | Invariancias de Qn | `Qn(x)≠Qn(-x)` 86/2000; permutación 0/2000; traslación 611/2000 |
| S10 | `initset` con signos de `P` invertidos | `lambda` distinto en 4/20 (rel. ≤ 3.8e-8); orden final igual en 20/20 |

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
- **P4. Rendimiento.** Sin Numba ni Cython por ahora; Qn vectorizado en numpy según §7.
- **P5. `vdst` fiel** (producto completo). Si en producción n es muy grande, se revisa la memoria por bloques
  **sin cambiar el orden de operaciones**.
- **P6. Plataforma de referencia:** macOS arm64, R 4.5.2, BLAS Accelerate (vecLib), LAPACK Rlapack 3.12.1.
  Igualdad exacta solo ahí; en otras plataformas (p. ej. CI Linux con OpenBLAS) rigen las tolerancias de §11,
  declaradas antes de comparar.
- **P7. Fallos de R** (columna constante, p=1 con equicorrelación, matriz no definida positiva): el port lanza un
  error equivalente, sin *fallback*.
- **P8. `target`** distinto de `identity`/`equicorrelation`: error en el port (R lo trata como equicorrelación).
  Diferencia de API documentada.
- **Casos aceptados.** C9/C10 desplazan +5 en todas las coordenadas las primeras `ceiling(frac·n)` filas
  (20 % y 10 %); C7 con Σ = I.
