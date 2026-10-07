# ADR 0004 — Cartas y estimadores extensibles e independientes

- **Estado:** Aceptado
- **Fecha:** 2026-10-06
- **Acota:** [ADR 0002](0002-mrcd-sin-aproximaciones.md). La prohibición de sustituir MRCD sigue vigente
  **dentro de T²MRCD**; este ADR permite **otras cartas y estimadores como métodos propios**.

## Contexto

T²MRCD es el producto principal, pero la plataforma tiene que poder ofrecer otras cartas de control
(y otros estimadores) sin reescribir lo existente. El ADR 0002 y la regla dura 2 decían «ninguna aproximación
ni sustituto de MRCD», lo que bloqueaba cualquier otro método en `domain/`. Hay que separar dos cosas:

- **Sustituir** MRCD por algo más rápido o «parecido» dentro de T²MRCD → sigue **prohibido**.
- **Ofrecer** otro método como opción explícita, con su propia identidad, validación y API → **permitido**.

## Decisión

1. **T²MRCD es la carta por defecto** y MRCD el estimador de referencia. Su fidelidad a `rrcov::CovMrcd` no cambia.
2. **Cada carta es un método independiente**, con:
   - su propio paquete de dominio `domain/charts/<carta>/`: parámetros, estadística, Fase I (ajuste y límites)
     y Fase II (puntuación y señales);
   - su propia API `/v1/charts/<carta>/…` con sus propios schemas, router y tests;
   - su propio documento de fidelidad `docs/metodos/<carta>.md`, con las citas a su artículo o a su
     implementación de referencia;
   - sus propios golden tests contra esa referencia, con tolerancia declarada.
3. **Cada estimador es independiente**: `domain/estimators/<estimador>/`, con su `docs/metodos/<estimador>.md`
   y sus golden tests. Una carta puede usar uno o varios estimadores; un estimador no conoce las cartas.
4. **Independencia verificada por `import-linter`** (contratos `independence`):
   - una carta no importa a otra carta;
   - un estimador no importa a otro estimador ni a ninguna carta;
   - lo común (tipos de resultado, errores, utilidades numéricas puras) vive en `domain/common/` y no
     contiene lógica estadística de ningún método.
5. **Nada de sustituciones silenciosas.** Una carta usa siempre el estimador que declara. Prohibidos los
   *fallbacks* («si MRCD no converge, usar covarianza clásica»), los «modos rápidos» que cambien el método y
   cualquier placeholder estadístico. Si un método falla, el análisis termina en `failed` con su código.
6. **El cliente elige la carta de forma explícita** por la ruta (`/v1/charts/<carta>/…`). Ninguna ruta
   cambia de método por su cuenta.
7. **Requisitos para que entre un método nuevo** (los vigila `validador-estadistico`):
   referencia citada (artículo o código fuente), `docs/metodos/<método>.md` con cada default citado, golden
   tests con tolerancia declarada (en `xfail(strict=True)` mientras no exista la implementación), router
   y schemas propios con tests y aislamiento por tenant.
8. **Contrato común de una carta** (en `domain/charts/` como `Protocol`, sin estado):
   - `fit_phase1(X, params) -> PhaseIModel`: ajusta con datos históricos y calcula los límites de control.
   - `score_phase2(model, X_new) -> PhaseIIResult`: puntúa observaciones nuevas contra el modelo y marca señales.
   Las capas `application` e `infrastructure` trabajan contra este contrato; cada carta lo implementa con su
   propia lógica.

## Consecuencias

- Añadir una carta = un paquete de dominio + un router + su documento de fidelidad + sus golden tests +
  registrarla en `container.py`. No se tocan las demás cartas.
- `validador-estadistico` deja de rechazar «cualquier otro estimador»: rechaza sustituciones dentro de un
  método, fallbacks silenciosos y métodos sin cita, sin documento de fidelidad o sin golden tests.
- `docs/mrcd/fidelidad.md` pasa a `docs/metodos/mrcd.md` (estimador) y `docs/metodos/t2mrcd.md` (carta).
- La API del Paso 3 cambia de `/v1/analyses` a rutas por carta (ver [ADR 0005](0005-api-fase-i-fase-ii.md)).

## Alternativas descartadas

- **Un único endpoint con `chart=` y `estimator=` en el cuerpo:** mezcla los parámetros y la validación de
  métodos distintos en un solo schema, y acopla la evolución de unas cartas a la de otras.
- **Mantener la prohibición total:** impide crecer el producto con otros métodos.
- **Cartas que heredan unas de otras:** acopla la lógica estadística; un cambio en una carta rompe a otra.
