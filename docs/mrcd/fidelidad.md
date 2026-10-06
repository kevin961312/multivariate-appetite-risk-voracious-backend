# Fidelidad del port a `rrcov::CovMrcd`

Cada decisión del port a Python cita su origen en el código fuente de `rrcov`. Sin cita no hay default
([CLAUDE.md](../../CLAUDE.md), regla dura 3).

- **Versión de referencia de `rrcov`:** _pendiente (se fija en el Paso 2 al leer el código)_
- **Artículo:** Boudt, K., Rousseeuw, P. J., Vanduffel, S., & Verdonck, T. (2020). *The minimum regularized
  covariance determinant estimator.* Statistics and Computing, 30, 113–128.
- **Carta T²MRCD:** límites de Fase I (observaciones individuales) según el artículo de T²MRCD.
  _Referencia exacta pendiente._

## Parámetros

| Parámetro | Default en `rrcov` | Origen (archivo:línea) | Python (`MRCDParams`) | Validación |
| --- | --- | --- | --- | --- |
| `alpha` | _pendiente_ | _pendiente_ | _pendiente_ | `0.5 ≤ alpha ≤ 1` |
| `h` | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ |
| `maxcsteps` | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ |
| `rho` | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ |
| `target` | _pendiente_ | _pendiente_ | _pendiente_ | `identity` \| `equicorrelation` |
| `maxcond` | _pendiente_ | _pendiente_ | _pendiente_ | `maxcond > 1` |

## Pasos del algoritmo

| Paso | Origen (archivo:línea) | Python | Estado |
| --- | --- | --- | --- |
| Estandarización inicial | _pendiente_ | _pendiente_ | pendiente |
| Subconjuntos iniciales deterministas | _pendiente_ | _pendiente_ | pendiente |
| Matriz objetivo (`target`) | _pendiente_ | _pendiente_ | pendiente |
| Elección de `rho` por número de condición | _pendiente_ | _pendiente_ | pendiente |
| C-steps | _pendiente_ | _pendiente_ | pendiente |
| Factor de consistencia | _pendiente_ | _pendiente_ | pendiente |
| Distancias de Mahalanobis | _pendiente_ | _pendiente_ | pendiente |

## Tests golden

| Caso | n | p | Contaminación | Semilla | Tolerancia | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| n > p | _pendiente_ | _pendiente_ | no | _pendiente_ | _pendiente_ | pendiente (Paso 5) |
| p > n | _pendiente_ | _pendiente_ | no | _pendiente_ | _pendiente_ | pendiente (Paso 5) |
| contaminado | _pendiente_ | _pendiente_ | sí | _pendiente_ | _pendiente_ | pendiente (Paso 5) |

## Decisiones abiertas

- Límites de control de T²MRCD en Fase I: fórmula y fuente exacta (artículo, sección/ecuación).
