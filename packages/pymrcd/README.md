# pymrcd

Port propio a Python de `rrcov::CovMrcd()`: el estimador **MRCD** (*Minimum Regularized Covariance
Determinant*) de Boudt, Rousseeuw, Vanduffel y Verdonck (2020). Runtime: solo `numpy` y `scipy`; no depende
de `voracious`.

**Estado:** esqueleto. El algoritmo todavía no está portado.

## Referencia

- `rrcov` 1.7-7, versión oficial de CRAN (tarball verificado), con `robustbase` 0.99-6 y R 4.5.2.
- La fidelidad se demuestra con tests golden: salidas de `rrcov::CovMrcd` guardadas como fixtures en
  `tests/golden/fixtures/`. R solo se usa para regenerarlas; los tests no lo necesitan.
- Decisión y protocolo de fidelidad: ADR 0006 del repositorio (`docs/adr/0006-libreria-pymrcd.md`).

## Créditos

- V. Todorov, autor de `rrcov`.
- M. Maechler y colaboradores, autores de `robustbase`.
- K. Boudt, P. J. Rousseeuw, S. Vanduffel y T. Verdonck (2020), «The minimum regularized covariance
  determinant estimator», *Statistics and Computing* 30, 113-128. Autores del método.

## Licencia

GPL-3.0-or-later (texto completo en [`LICENSE`](LICENSE)). Es obra derivada de `rrcov` (`GPL (>= 3)`) y
`robustbase` (`GPL (>= 2)`). Uso **privado**: no se distribuye a terceros.
