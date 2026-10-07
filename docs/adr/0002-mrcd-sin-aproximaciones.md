# ADR 0002 — MRCD exacto, sin aproximaciones ni sustitutos

- **Estado:** Aceptado — acotado por [0004](0004-cartas-y-estimadores-extensibles.md)
- **Fecha:** 2026-10-06

## Contexto

El valor comercial de Voracious es la carta de control T²MRCD. Frente a Shewhart, EWMA o Hotelling clásico,
el estimador MRCD (Boudt, Rousseeuw, Vanduffel y Verdonck, 2020) no asume normalidad, resiste outliers y el
efecto de enmascaramiento, y funciona cuando p > n. Esas propiedades son las de **MRCD tal como está definido**;
cualquier atajo cambia la probabilidad de señal de la carta.

## Decisión

- El núcleo es un **port propio a Python de `rrcov::CovMrcd()`**, fiel a su código fuente.
- La referencia es el **código de `rrcov`** (`CovMrcd.R`, `CovControlMrcd`), no la memoria ni otras
  implementaciones. Cada default y paso del algoritmo cita archivo:línea en [`../metodos/mrcd.md`](../metodos/mrcd.md).
- La fidelidad se demuestra con **tests golden** contra salidas de R con tolerancia declarada.
- Mientras el port no exista, `MRCD.fit` lanza `NotImplementedError` y el análisis falla con
  `MRCD_NOT_IMPLEMENTED`. **No hay placeholder estadístico.**
- Si hay problemas de rendimiento se optimiza la implementación (vectorización, Numba/Cython, paralelismo
  entre portafolios), nunca el método.

## Alternativas descartadas

| Alternativa | Por qué no |
| --- | --- |
| **KMRCD** (kernel MRCD) | No conserva las propiedades de MRCD; su probabilidad de señal en la carta no es eficiente (análisis estadístico del dueño del producto). |
| **`sklearn.covariance.MinCovDet`** | Es MCD sin regularización: no funciona con p > n y no reproduce `rrcov`. |
| **Ledoit-Wolf / shrinkage clásico** | No es robusto: un outlier contamina la estimación; pierde la resistencia al enmascaramiento. |
| **Covarianza clásica como placeholder** | Produciría resultados plausibles pero falsos; un cliente podría tomar decisiones de riesgo sobre ellos. |
| **Llamar a R desde Python (rpy2) en producción** | Dependencia operativa pesada en workers; R queda solo como oráculo de los tests golden. |

## Consecuencias

- Implementar MRCD es más lento que adoptar una librería, pero el resultado es auditable línea a línea.
- `validador-estadistico` revisa todo cambio en `domain/mrcd/` y `domain/charts/`.
