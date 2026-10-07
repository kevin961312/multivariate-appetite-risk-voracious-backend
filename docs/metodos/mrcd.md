# Método: MRCD (estimador) — fidelidad del port a `rrcov::CovMrcd`

Tipo: **estimador** (`domain/estimators/mrcd/`). Lo usa la carta [T²MRCD](t2mrcd.md). Ver [ADR 0004](../adr/0004-cartas-y-estimadores-extensibles.md).

Cada decisión del port a Python cita su origen en el código fuente de `rrcov`. Sin cita no hay default
([CLAUDE.md](../../CLAUDE.md), regla dura 3).

- **Versión de referencia:** `rrcov` 1.7-7 oficial de CRAN (con `robustbase` 0.99-6, R 4.5.2) en la plataforma
  macOS arm64 / Accelerate / Rlapack 3.12.1; ver [ADR 0006](../adr/0006-libreria-pymrcd.md).
- **Especificación completa** (pasos, trampas, tolerancias): [`mrcd-especificacion.md`](mrcd-especificacion.md).
  Este documento resume parámetros y validaciones; no repite los pasos.
- **Artículo:** Boudt, K., Rousseeuw, P. J., Vanduffel, S., & Verdonck, T. (2020). *The minimum regularized
  covariance determinant estimator.* Statistics and Computing, 30, 113–128.
- Los límites de control y la estadística T² no son de este documento: ver [`t2mrcd.md`](t2mrcd.md).
- Implementación: `pymrcd.cov_mrcd` (`packages/pymrcd/`), integrada en `domain/estimators/mrcd/` (Paso 2).
  `pymrcd` pasó de dependencia de desarrollo a **dependencia de runtime** de `voracious`; solo la importa
  `domain/estimators/mrcd/` (contrato de `import-linter`).

## Parámetros

Copia de la §2 de la especificación (archivos de `rrcov` 1.7-7).

| Parámetro | Default en `rrcov` | Origen (archivo:línea) | `pymrcd.cov_mrcd` | Validación |
| --- | --- | --- | --- | --- |
| `alpha` | `0.5` | `CovControl.R:22`; `AllClasses.R:138` | `alpha=0.5` | `0.5 ≤ alpha ≤ 1` (`detmrcd.R:400-401`) |
| `h` | `NULL` | `CovControl.R:23` | `h=None`; si se da, `alpha = h/n` (`detmrcd.R:396`) | la de `alpha` sobre `h/n` |
| `maxcsteps` | `200` | `CovControl.R:24` | `maxcsteps=200` | ninguna en rrcov |
| `rho` | `NULL` (selección automática, `detmrcd.R:465`) | `CovControl.R:25` | `rho=None` | ninguna en rrcov |
| `target` | `"identity"` | `CovControl.R:26,:34` | `target="identity"` | `identity` \| `equicorrelation`; otro valor es error en el port (R lo trata como equicorrelación, `CovMrcd.R:29`): diferencia de API, P8 |
| `maxcond` | `50` | `CovControl.R:27` | `maxcond=50` | **ninguna**: ni rrcov ni el port validan `maxcond` (fidelidad) |
| `minscale` | `0.001` | `detmrcd.R:27` | no expuesto (igual que `CovMrcd`) | — |

Otras diferencias de API del port (base 0, `init_hsets` validado como enteros, entrada 0-d rechazada, mensaje
de `n = 0`): ver `mrcd-especificacion.md` §12, «Decisiones del dueño».

## API pública de `pymrcd`: `mahalanobis`

Además de `cov_mrcd`, `pymrcd.mahalanobis(x, center, icov)` expone la rutina con la que `cov_mrcd` calcula `mah`
(`stats::mahalanobis(x, center, cov, inverted=TRUE)`, R 4.5.2, `mahalanobis.R:31-47`; usada en `CovMrcd.R:46`).
Por qué existe: la carta necesita el T² de filas **nuevas** y no debe reimplementar la fórmula; así
`mahalanobis(x[ok], center, icov)` es igual bit a bit a `mah`.

- Un vector es **una fila** (`mahalanobis.R:33`); el centro se resta por columnas (`:36`); el resultado es
  `rowSums(x %*% cov * x)` (`:46`).
- `icov` debe ser p×p, con los mensajes de R: `non-conformable arguments` si `nrow != p` y
  `non-conformable arrays` si `nrow == p` pero `ncol != p`. Sin la comprobación, el *broadcasting* de numpy
  daría un número equivocado sin avisar.
- **Divergencia deliberada con R:** si `length(center) != p`, R solo avisa (`sweep`, `:36`) y recicla el
  centro; `pymrcd` lanza `RError`. Un centro reciclado no tiene sentido estadístico.

## Adaptador `domain/estimators/mrcd`

Capa fina sobre `pymrcd`, para que ninguna carta dependa de la librería (ADR 0006, punto 8).

- **`MRCDParams`** (`alpha`, `h`, `maxcsteps`, `rho`, `target`, `maxcond`): los mismos defaults de la tabla
  «Parámetros», con su cita en el docstring. No valida: las validaciones son las de `rrcov` y llegan vía
  `pymrcd`.
- **`MRCDFit`**: slots de `CovMrcd` (`center`, `cov`, `icov`, `rho`, `cnp2`, `crit`, `best`, `mah`, `alpha`,
  `h`, `n_obs`, `ok`) más los diagnósticos `i_best` y `n_csteps`. **No guarda `x`**: el histórico ya vive en
  el registro del modelo (`training_data`), así que el ajuste no lo duplica. Los índices (`best`, `i_best`) son **base 0**.
  `distances(x)` usa `pymrcd.mahalanobis`.
- **Errores:** un `pymrcd.RError` (lo mismo que haría `rrcov`) se convierte en `EstimationError` con código
  `MRCD_FIT_FAILED` y `details.r_message`. Sin *fallback* a otro estimador.
- Las filas no finitas las descarta `cov_mrcd` como `rrcov` (`CovMrcd.R:19-20`) y su máscara queda en `ok`;
  cada carta decide si las admite (T²MRCD las rechaza, ver [`t2mrcd.md`](t2mrcd.md)).
- Los subconjuntos iniciales los calcula `pymrcd` (no se inyectan).

## Pasos del algoritmo

Ver [`mrcd-especificacion.md`](mrcd-especificacion.md) §3 (cada paso con su archivo:línea de `rrcov`) y §3.12
(replicación bit a bit: BLAS, LAPACK, FMA, nmath).

## Tests golden

Fixtures versionados en `packages/pymrcd/tests/golden/fixtures/` (14 casos: C1–C11 y variantes `_eq`; C11, 60×40,
cubre el régimen ceil(n/2) ≤ p < n). Los 14 casos, con su (n, p), Σ, contaminación, target y semilla, están en la tabla «Casos» de
`packages/pymrcd/tests/golden/fixtures/README.md`; las tolerancias por cantidad, en `mrcd-especificacion.md`
§11, y el protocolo (i)–(iii), en el ADR 0006 y su enmienda.

## Decisiones abiertas

- Ninguna sobre defaults de `CovMrcd`: todos citan `rrcov` 1.7-7. Las decisiones D9 y D10 están cerradas
  (`mrcd-especificacion.md` §12).
