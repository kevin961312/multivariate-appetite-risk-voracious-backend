# ADR 0006 — MRCD como librería propia `pymrcd`

- **Estado:** Aceptado
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
