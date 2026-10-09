# ADR 0006 — MRCD como librería propia `pymrcd`

- **Estado:** Aceptado — enmendado el 2026-10-06 y el 2026-10-07 (extensión C; el punto 7 queda acotado)
- **Fecha:** 2026-10-06
- **Concreta:** [ADR 0002](0002-mrcd-sin-aproximaciones.md) (el port propio de `rrcov::CovMrcd`) y respeta
  [ADR 0004](0004-cartas-y-estimadores-extensibles.md) (estimadores independientes).

## Contexto

El ADR 0002 decidió un port propio a Python de `rrcov::CovMrcd()`, pero no dónde vive. Si el port se escribe
dentro de `domain/estimators/mrcd/`, queda atado a la arquitectura hexagonal de `voracious` y a su licencia, y
no puede probarse ni reutilizarse por separado. Además, el port es un derivado de código GPL (rrcov y
robustbase), lo que conviene aislar para no mezclar licencias con el resto del backend.

Dos hechos condicionan el diseño:

- **Riesgo R1 (corregido según el análisis F1b sobre `rrcov` oficial).** Con p ≥ n, `rrcov` depende del
  redondeo en los subconjuntos iniciales **1 a 5**, no solo en `tanh` y `SCM`; el 5 (BACON/`covx`) ya desde
  p ≥ ceil(n/2). Solo el conjunto 6 (OGK) es estable. Una perturbación de 1e-16 puede cambiar `rho` y `cov` de
  forma macroscópica (p. ej. `rho` 0.1044→0.1031, |Δcov| hasta 0.80; en C5 AR(1) 50×200, |Δcov| 0.32). Dos
  implementaciones correctas pueden no coincidir, así que la fidelidad exige un protocolo explícito y no una
  única comparación final. Evidencia: sonda S3b de `docs/metodos/mrcd-especificacion.md`.
- **Existe una variante de pruebas** del dueño: un `rrcov` modificado con `ogkU.c`, que usa MAD en lugar de Qn
  en OGK cuando p > 45, y cambios en `eigen()`. Se hizo para pruebas en paralelo. Cambia el método.

## Decisión

1. **MRCD se porta primero como librería `pymrcd`**, paquete dentro del repo en `packages/pymrcd/`, miembro del
   workspace de uv. **No depende de `voracious`**; su runtime es solo `numpy` y `scipy`.
2. **R es solo el oráculo de los tests.** Los fixtures van versionados en
   `packages/pymrcd/tests/golden/fixtures/` como `.csv.gz` con 17 dígitos significativos. La compuerta y la CI
   **no necesitan R**; R solo se usa para regenerar fixtures.
3. **Referencia fijada:** `rrcov` 1.7-7 oficial de CRAN (tarball verificado; MD5 de `R/detmrcd.R`
   `d56485337b83f927bba70002357be341`), `robustbase` 0.99-6 y R 4.5.2 (`zeroin`, `cov`, `nmath`). El oráculo usa
   el `rrcov` oficial en una **librería aislada** (`referencias/R-lib/`), nunca el instalado en el sistema.
   Las citas archivo:línea de cada default viven en `docs/metodos/` (ver ADR 0002) y se verifican contra esa versión.
4. **La variante modificada no se porta.** Cambia el método (MAD en vez de Qn), lo que el ADR 0002 prohíbe dentro
   de MRCD. Si algún día se quisiera, entraría como **estimador propio** según el ADR 0004, con su documento de
   fidelidad y sus golden tests.
5. **Licencia GPL-3.0-or-later.** `pymrcd` es obra derivada de `rrcov` (`GPL (>= 3)`) y `robustbase`
   (`GPL (>= 2)`). Créditos: V. Todorov (rrcov); M. Maechler y colaboradores (robustbase); y Boudt, Rousseeuw,
   Vanduffel y Verdonck (2020) por el método. El uso es **privado** (SaaS sin distribuir). GPL-3 (no AGPL) no
   obliga a publicar código por uso en red; **distribuir `voracious` o `pymrcd` a terceros arrastraría la GPL-3**.
   *Esto no es asesoría legal.*
6. **Protocolo de fidelidad por R1:**
   1. Tests **por etapa** con intermedios de R y tolerancias estrictas.
   2. Tests **extremo a extremo inyectando los 6 subconjuntos iniciales de R**, estrictos. Es la **prueba de
      fidelidad principal**.
   3. Tests **desde cero**: con p ≥ n solo se exige exacto el conjunto 6 (OGK); el 5 se registra como
      **divergencia R1 documentada** si p ≥ ceil(n/2). Con n > p se exigen exactos los 6 y todo el resultado.
   **Nunca se relaja una tolerancia.** Las tolerancias se declaran **antes de comparar** en
   `docs/metodos/mrcd-especificacion.md`.
   **Plataforma de referencia del oráculo:** macOS arm64, R 4.5.2, BLAS Accelerate (vecLib), LAPACK Rlapack
   3.12.1. La igualdad exacta se exige solo en esa plataforma; en otras (p. ej. CI Linux con OpenBLAS) se aplican
   las tolerancias numéricas declaradas de antemano en la especificación.
7. **Rendimiento:** se optimiza la implementación (p. ej. vectorizar OGK con Qn), nunca el método. Numba queda
   como posible extra opcional futuro; **no está aprobado**.
8. **Integración.** `pymrcd` entra ya en el grupo `dev` de la raíz. En el Paso 2 pasa a ser dependencia de
   `voracious`, y `domain/estimators/mrcd/` será un **adaptador fino** sobre `pymrcd`. Eso requerirá enmendar
   `CLAUDE.md` §2 (`domain` podrá importar `pymrcd`). Mientras tanto, `MRCD.fit` sigue como en el ADR 0002.
9. **Aislamiento verificado por `import-linter`:** `pymrcd` no importa `voracious` ni `pandas`, `rpy2`,
   `sklearn`, `statsmodels`, `fastapi`, `pydantic` ni `structlog`.

## Consecuencias

- `pymrcd` se puede probar, versionar y auditar sin levantar el backend ni tener R instalado.
- La licencia GPL queda confinada a un paquete identificable; el resto del repo decide aparte cómo la trata si
  alguna vez se distribuye.
- Hay un paso previo (la librería) antes del Paso 2; a cambio, el adaptador de `domain` será trivial.
- Una divergencia R1 en el conjunto 5 desde cero con p ≥ ceil(n/2) es un resultado aceptable si está
  documentada; relajar tolerancias para esconderla no lo es. La fidelidad se prueba de verdad inyectando los
  subconjuntos de R (punto 6.2).
- **Consecuencia de producto:** con p > n el propio `rrcov` no es reproducible entre plataformas (R en macOS vs
  Linux puede dar otro `cov`). Una versión canónica determinista sería una desviación de `rrcov` y requeriría su
  propio ADR. **Decisión abierta, no tomada.**
- Pendiente: enmienda de `CLAUDE.md` §2 y actualización de `docs/ESTADO.md` al cierre de la fase.
- Los textos del ADR 0002 que mencionan `domain/mrcd/` quedan como ubicación del adaptador, no del algoritmo.

## Alternativas descartadas

| Alternativa | Por qué no |
| --- | --- |
| **rpy2 en producción** | Dependencia operativa pesada en workers (ya descartada en el ADR 0002); R queda solo como oráculo. |
| **Usar la variante modificada de `rrcov`** | Cambia el método (MAD en lugar de Qn con p > 45, cambios en `eigen()`); contradice el ADR 0002. |
| **Implementar desde el artículo sin leer el código** | No garantiza coincidir con `rrcov` en defaults ni en detalles numéricos. |
| **Repo separado desde el inicio** | Más mantenimiento (versionado, CI, publicación) sin necesidad hoy; se puede extraer después porque `pymrcd` ya no depende de `voracious`. |
| **Meterlo en `domain/`** | Mezcla la licencia GPL con el código del backend y impide probarlo por separado. |

## Enmienda 2026-10-06

Este ADR aún no se había publicado como inmutable; la enmienda precisa tres puntos sin cambiar la decisión.

**(a) Decisiones D9 y D10 y «nunca se relaja una tolerancia».**
- **D9:** `eigen` (`dsyevr`) y también `dgeev` se llaman a través de Accelerate (scipy), no del Rlapack de
  referencia de R. La divergencia se acepta con tolerancia clase B también en la plataforma de referencia; el
  signo de los autovectores se informa pero no hace fallar el test. Motivo: Accelerate vs Rlapack.
- **D10:** `qchisq`/`pgamma`/`qgamma` se portan de nmath con las FMA del binario; `.MCDcons` coincide bit a bit
  en la plataforma de referencia.
- No contradicen el punto 6 («nunca se relaja una tolerancia»). D9 se tomó **después de observar** la
  divergencia sistemática de Accelerate frente a Rlapack (sonda S12 del bloque 1), pero como decisión del dueño,
  registrada y **anterior a los tests vigentes** (`docs/metodos/mrcd-especificacion.md` §11 y §12); no se ajustó
  para hacer pasar ningún caso concreto. D10 endurece la tolerancia (de rtol 1e-14 a bit a bit).

**(b) Uso de `ctypes`.** El runtime sigue siendo «solo numpy/scipy» porque no añade dependencias, pero usa
`ctypes` (stdlib) en dos sitios: sobre las cápsulas de `scipy.linalg.cython_blas.__pyx_capi__` para llamar BLAS
en sitio con la `lda` real (es un detalle interno de Cython, **no API pública** de scipy), y sobre `lgamma` de la
libm del sistema (`math.lgamma` de CPython es otra implementación).
- Mitigaciones: verificación de firmas LP64 al importar; asserts de límites; scipy acotado `<1.19` y numpy
  `<3`; error explícito si no hay libm. Aplicado en `packages/pymrcd/pyproject.toml`
  (`numpy>=2.5.3,<3`, `scipy>=1.18.1,<1.19`) y cubierto por `tests/test_salvaguardas.py`.
- Riesgo de portabilidad: Windows no está soportado; fuera de macOS el `lgamma` es el de otra libm (clase L de
  §11 de la especificación).

**(c) Protocolo nivel (iii) por régimen (n, p)**, que precisa el punto 6.3:
- p ≥ n: solo el conjunto 6 exacto.
- ceil(n/2) ≤ p < n: 1–4 y 6 exactos; el 5 es R1.
- p < ceil(n/2): los 6.
- Con D9, un conjunto exigido que difiera por `eigen` se registra con la diferencia de `P` medida, sin relajar
  tolerancias. Se añade el golden **C11 (60×40)** para el régimen intermedio.

## Enmienda 2026-10-07: extensión C para `Qn` y OGK (M5)

Decisión del dueño. Precisa los puntos 1, 5 y 7 sin cambiar el método.

**Por qué.** `Qn` (`qn0`) es el cuello de botella de MRCD: se evalúa por columna en la estandarización, en los
seis subconjuntos iniciales y, sobre todo, en los `p(p−1)` pares de OGK. Con p grande, `cov_mrcd` 200×300
(alpha 0.75) tardaba 30 s, y la Fase I y la recalibración repiten cientos de ajustes (ADR 0007, ADR 0008). La
versión numpy ya no podía acelerarse sin tocar el método ni la fidelidad bit a bit: además daba otro **signo de
cero** que R y no era determinista (`np.sort(axis=0)`; especificación §3.12.9 c).

**Decisión.**
1. **`pymrcd` deja de ser Python puro.** `Qn` y los pares de OGK se calculan en una extensión C propia,
   `pymrcd._qn_ext` (`packages/pymrcd/src/pymrcd/_ext/`), **port literal** de `qn0` y `whimed_i` de robustbase
   (`qn_sn.c`, `wgt_himed_templ.h`) y de `R_qsort` y `rPsort` de R 4.5.2. Literal incluye `goto`, el alias de `p`
   como `w_cand` y las conversiones `(float)`: ninguna ordenación o selección «equivalente» es admisible
   (§3.12.9 a y c). Es una optimización de la **implementación**, no del método (ADR 0002).
2. **Sin respaldo en Python (P1 = A).** Sin la extensión, `import pymrcd` falla con un `ImportError` explícito
   (`_cext.py`). El `Qn` de numpy vive solo en `tests/` como **oráculo** de comparación; en `src/` no queda como
   alternativa, para que ninguna instalación ejecute en silencio un cálculo distinto.
3. **Licencias.** El C deriva de robustbase (GPL-2+; P. Rousseeuw dio permiso para publicar `qn0` bajo GPL) y de R
   (R Core Team, GPL-2+). «O posterior» es compatible con la GPL-3.0-or-later de `pymrcd` (punto 5). Las
   cabeceras de copyright se conservan en los fuentes y los créditos van en el README. *No es asesoría legal.*
4. **Runtime sin dependencias nuevas.** Sigue siendo `numpy` y `scipy`; la extensión usa la C-API de CPython con
   el protocolo de búfer (sin cabeceras de numpy). `types-setuptools` entra solo en el grupo `dev` de la raíz, para
   que mypy revise `setup.py`.
5. **Compilación.** `setuptools >= 77` (metadatos de licencia PEP 639) como backend, con un `setup.py` mínimo que
   solo declara `ext_modules`; sustituye a `hatchling`. Las opciones `-ffp-contract=off -fno-fast-math` van al
   final para prevalecer sobre las `CFLAGS` de CPython (que no desactivan la contracción FMA; el `clang` por
   defecto contrae `k_L` y `(s*s − d*d)/4`: §3.12.9 b). `cache-keys` de uv hace que se recompile al cambiar el C,
   `setup.py` o `pyproject.toml`. Hace falta un compilador de C con pthreads (Xcode CLT, `build-essential`).
6. **Hilos.** Paralelismo entre columnas (o pares de OGK) con pthreads y el GIL liberado. El número de hilos es
   un parámetro de **rendimiento**: `n_threads` en `cov_mrcd`; por defecto `PYMRCD_NUM_THREADS` y, si no, la
   afinidad de CPU o los núcleos en línea. El resultado es idéntico bit a bit con cualquier valor (§3.12.9 e). En
   producción se fija `n_threads` desde `VORACIOUS_MRCD_THREADS` (no se persiste con la versión de la carta; el
   cableado en `container` es del Paso 3), sobre todo si las réplicas bootstrap corren en procesos
   (procesos × hilos sobresuscribe los núcleos).
7. **Fidelidad.** `Qn` en C coincide con R en bits, incluido el signo del cero, y por no depender de libm ni de
   BLAS vale en **cualquier plataforma IEEE-754**: es la única pieza de `pymrcd` con esa propiedad (el resto
   sigue limitado a la plataforma de referencia, punto 6). La compuerta desensambla el binario y exige cero
   instrucciones FMA (`scripts/check_pymrcd_fma.sh`).

**Punto 7 de la decisión original, acotado.** «Sin Numba/Cython» se mantiene; la **única excepción aprobada** es
esta extensión C. Cualquier otro código compilado necesita su propia decisión.

**Consecuencias.**
- Instalar `pymrcd` exige un compilador; la imagen del Paso 4 deberá incluirlo o usar una *wheel* precompilada
  por plataforma (pendiente de decisión).
- Aparecen riesgos nuevos de código C (memoria, hilos). Mitigados con espacio de trabajo privado por hilo, una
  sola escritura por salida y una comprobación defensiva; las pruebas con sanitizers en CI son **deuda**.
- Defensa contra opciones de coma flotante peligrosas en `CFLAGS` externas (`-fno-signed-zeros`,
  `-fassociative-math`, `-freciprocal-math`): depende de que `-fno-fast-math` quede al final (riesgo bajo).
- Rendimiento medido: ver `docs/ESTADO.md` (M5). El objetivo de 10× con un hilo **no** se alcanzó (4.1×): exigiría
  cambiar el algoritmo, que la especificación prohíbe.

## Enmienda 2026-10-09 (Paso 4: validación en Linux)

**Decisión del dueño, 2026-10-09**, escrita **antes** de volver a comparar. Precisa el punto 6 («fuera de la
plataforma de referencia rigen las tolerancias declaradas») para tres casos que no tenían regla. En la plataforma
de referencia (macOS arm64; `REFERENCE_PLATFORM`, `packages/pymrcd/tests/fixtures_r.py:34`) **no cambia nada**:
se sigue exigiendo bit a bit donde la especificación lo dice. Detalle, evidencia y alcance exacto en
`docs/metodos/mrcd-especificacion.md` §6 («Segundo canal de R1») y §11.1.

**Origen.** Dictamen del validador estadístico sobre la etapa `gate` de la imagen Docker (Linux arm64 nativo y
amd64 emulado; gcc + OpenBLAS + glibc): **ningún defecto del port**. Dos fallos eran defectos del test y se
corrigen con clases ya declaradas en §11:
- `test_etapas_bloque2.py:115` aplicaba a `r6_R1` la clase L de `y1`; lo declarado es E sobre entradas de R
  (`r_cor(r6.y1 de R)`).
- `test_zeroin.py:61` comparaba `root` como E aunque la función de prueba depende de libm; es L (y queda en D3).

**D1 — R1 en los tests por etapa.** Con p ≥ n, `SCM` tiene espacio nulo estructural; `lambda` (Qn de las
proyecciones) vale ≈ 5e-16 en esas direcciones y `sqrtinvcov` ~1e15, así que 1 ulp de BLAS en
`x %*% sqrtinvcov`/`estloc` domina `dist` y cambia el orden de `initset` (C1-4, n = 50, p = 200: `dist` hasta
6.9 %, orden distinto en 20/25; amd64: `is_colmed` 13.8 relativo, `lambda` 0.195 en 150 columnas). Fuera de la
referencia, si y solo si el conjunto no es exigido (`required_sets(n, p)`) **y** `min(lambda)/max(lambda) ≤
10·p·eps` (C1-4: 1.7e-16), las etapas posteriores a `is_lambda` y el orden se registran como `DivergenciaR1` con
su medición en lugar de fallar; `is_proj`, `is_lambda`, `sqrtcov` y `sqrtinvcov` se siguen exigiendo.

**D2 — `target = equicorrelation`.** La entrada de `doScale` es `mW = mU %*% mQ` (`dgemm`, clase B); fuera de la
referencia `r6.center`, `r6.scale`, `r6.x` y la `U` de OGK calculadas desde cero heredan la clase B (rtol 1e-12,
atol `1e-14·max`), con rtol 2^-23 si un Qn salta a f32. Medido (amd64, C8_eq): `r6_x` 7.29e-16·max, `r6_U`
6.55e-15·max. Con entradas de R siguen siendo exactos.

**D3 — `uniroot` con funciones sintéticas de libm.** Los casos sintéticos de `test_zeroin.py` cuya función usa
`tanh`, `cos`, `exp` u otra función de libm son solo de la plataforma de referencia (bit a bit allí) y fuera de
ella se saltan con motivo explícito: `root` sería L y `f_root` sufre cancelación (5.4e-10 relativo con 1 ulp)
sin tolerancia declarada. La fidelidad de `R_zeroin2` fuera de la referencia la cubren los 38 casos `fncond`
reales (0 bits distintos en Linux) y los sintéticos aritméticos. Pendiente de confirmar: los casos con `x^3`
llaman a `pow` de libm y, por la letra de la regla, también quedan solo en la referencia.

**No contradice «nunca se relaja una tolerancia».** Ninguna tolerancia existente se afloja: D2 aplica una clase
ya declarada (B) a cantidades que dependen de una entrada B; D3 retira casos sin regla fuera de la referencia sin
tocar su exigencia en ella; D1 cambia el veredicto (fallo → aviso medido) solo cuando concurren el régimen R1 ya
declarado (punto 6.3, enmienda 2026-10-06 c) y la prueba numérica del espacio nulo.

**Consecuencia de producto (ya declarada en «Consecuencias»).** En Linux con p ≥ n el modelo ajustado puede
diferir del obtenido en macOS, igual que el propio `rrcov` entre plataformas. La decisión sobre una versión
canónica determinista sigue abierta.
