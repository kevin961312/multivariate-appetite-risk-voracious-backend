# pymrcd

Port propio a Python de `rrcov::CovMrcd()`: el estimador **MRCD** (*Minimum Regularized Covariance
Determinant*) de Boudt, Rousseeuw, Vanduffel y Verdonck (2020). Runtime: solo `numpy` y `scipy`; no depende
de `voracious`.

**Estado (2026-10-06):** port completo de `CovMrcd` → `.detmrcd` (estandarización, `.TargetCorr` y
equicorrelación, `r6pack` con los seis subconjuntos iniciales, selección de `rho`, C-steps, estimación final y
retro-transformación, `.MCDcons` con nmath portado). Validado contra 14 casos golden de R (C1–C11 y variantes
`_eq`) en tres niveles: (i) por etapa con los intermedios de R, (ii) de extremo a extremo con los `initHsets` de
R y (iii) desde cero. La única divergencia aceptada es `eigen` (`dsyevr`/`dgeev` de Accelerate en lugar de
Rlapack, decisión D9 de la especificación, tolerancia B); con `p >= ceil(n/2)` hace que algunos subconjuntos
iniciales calculados desde cero puedan diferir de R (riesgo R1).

## Uso mínimo

```python
import numpy as np
from pymrcd import cov_mrcd

x = np.random.default_rng(1).standard_normal((50, 200))
res = cov_mrcd(x, alpha=0.75, target="identity")
res.center, res.cov, res.icov, res.rho, res.mah  # nombres de los slots de rrcov
res.best  # subconjunto óptimo, base 0
```

API pública: `cov_mrcd(x, alpha=0.5, h=None, maxcsteps=200, rho=None, target="identity", maxcond=50,
init_hsets=None) -> MrcdResult` y la excepción `RError` (errores de R con su mensaje). Los valores por
defecto son los de `CovControlMrcd()` de rrcov 1.7-7. `MrcdResult` lleva `center`, `cov`, `icov`, `rho`,
`target`, `cnp2`, `crit`, `best`, `mah`, `alpha`, `quan`/`h`, `n_obs`, `x`, `ok`, `i_best`, `n_csteps`,
`init_hsets` y `detail` (intermedios de `.detmrcd`).

## Diferencias de API con R

- **Índices en base 0**: `best`, `i_best`, `init_hsets` (entrada y salida). En R son base 1.
- **`target` no válido** (fuera de `{"identity", "equicorrelation"}`) → `RError` (decisión P8). R lo trataría
  como equicorrelación.
- **`n = 0` tras filtrar** filas no finitas → `RError("All observations have missing values!")`. R falla más
  adelante con otro mensaje (`"provide better scale; must be all positive"`).
- **`init_hsets` se valida como enteros**: valores no enteros → `RError`; en R se truncarían al indexar.
- **Entrada 0-d** (escalar) → `RError`; un vector 1-d se trata como matriz de una columna, como en R.
- Los demás fallos de R (columna constante, `p == 1` con equicorrelación, matriz no definida positiva) lanzan
  `RError` con el mensaje de R, sin *fallback* (decisión P7).

## Plataforma de referencia

La plataforma de referencia (macOS arm64, Accelerate, Rlapack 3.12.1) exige igualdad bit a bit con R. Fuera de
ella se aplican las tolerancias de §11 de
[`mrcd-especificacion.md`](../../docs/metodos/mrcd-especificacion.md).

## Dependencias acotadas

`numpy>=2.5.3,<3` y `scipy>=1.18.1,<1.19`: pymrcd llama por puntero a las cápsulas internas de Cython de
`scipy.linalg.cython_blas` (firma verificada al importar) y la fidelidad bit a bit está validada con esas
versiones. Subir una cota exige volver a pasar los golden.

## Referencia

- `rrcov` 1.7-7, versión oficial de CRAN (tarball verificado), con `robustbase` 0.99-6 y R 4.5.2.
- La fidelidad se demuestra con tests golden: salidas de `rrcov::CovMrcd` guardadas como fixtures en
  `tests/golden/fixtures/`. R solo se usa para regenerarlas; los tests no lo necesitan.
- Decisión y protocolo de fidelidad: ADR 0006 del repositorio (`docs/adr/0006-libreria-pymrcd.md`);
  especificación del port en `docs/metodos/mrcd-especificacion.md`.

## Créditos

- V. Todorov, autor de `rrcov`.
- M. Maechler y colaboradores, autores de `robustbase`.
- K. Boudt, P. J. Rousseeuw, S. Vanduffel y T. Verdonck (2020), «The minimum regularized covariance
  determinant estimator», *Statistics and Computing* 30, 113-128. Autores del método.

## Licencia

GPL-3.0-or-later (texto completo en [`LICENSE`](LICENSE)). Es obra derivada de `rrcov` (`GPL (>= 3)`) y
`robustbase` (`GPL (>= 2)`). Uso **privado**: no se distribuye a terceros.
