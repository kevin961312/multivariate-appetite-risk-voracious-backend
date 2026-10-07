# Método: T²MRCD (carta de control)

Tipo: **carta** (`domain/charts/t2mrcd/`). Es la carta por defecto del producto y usa el estimador
[MRCD](mrcd.md). Ver [ADR 0004](../adr/0004-cartas-y-estimadores-extensibles.md) y
[ADR 0005](../adr/0005-api-fase-i-fase-ii.md). Sin cita no hay default
([CLAUDE.md](../../CLAUDE.md), regla dura 3). Nada de lo siguiente está implementado todavía.

- **Estimador declarado:** MRCD, siempre. Sin *fallbacks* ni «modos rápidos» (ADR 0004, punto 5): si MRCD
  falla, la Fase I termina en `failed`.
- **Artículo de referencia:** _pendiente: cita exacta del artículo de T²MRCD (autores, año, revista)._

## Estadística

| Elemento | Definición | Fuente | Estado |
| --- | --- | --- | --- |
| Estadística T² por observación | Distancia de Mahalanobis al cuadrado respecto a la ubicación y dispersión MRCD | _pendiente (artículo T²MRCD, sección/ecuación)_ | pendiente |

## Fase I (ajuste y límites)

- Entrada: datos históricos n×p; observaciones individuales.
- Se ajusta MRCD ([`mrcd.md`](mrcd.md)) y se calculan los límites de control.
- **Decisión abierta:** fórmula y fuente exacta de los límites de Fase I (artículo, sección/ecuación).
  No se inventa ningún límite mientras no esté citado.

## Fase II (puntuación y señales)

- Entrada: observaciones nuevas contra un modelo de Fase I en `succeeded`.
- Salida: T² por observación y señal si supera el límite de Fase I.
- **Decisión abierta:** regla de señal exacta y fuente (depende de los límites de Fase I).

## Tests golden

Referencia de la carta (distinta de la del estimador). Mientras no exista implementación, `xfail(strict=True)`.

| Caso | n | p | Contaminación | Semilla | Tolerancia | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| Fase I: límites | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ | pendiente (Paso 5) |
| Fase II: T² y señales | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ | pendiente (Paso 5) |

## Decisiones abiertas

- Cita del artículo de T²MRCD.
- Límites de control de Fase I: fórmula y fuente.
- Regla de señal de Fase II.
- Fuente de referencia de los golden de la carta (¿código R existente o cálculo propio verificado contra el artículo?).
