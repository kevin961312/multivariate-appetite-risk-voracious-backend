# Estado del proyecto

Última actualización: 2026-10-07 (Paso 2b.1, dominio, implementado y pendiente de commit).

**Siguiente hito:** commit del 2b.1 (tras el «sí» del dueño), luego 2b.2 (aplicación: ciclo de vida) y
luego el Paso 3 (adaptadores, `container.py`, tenant y rutas, incluidas las del ciclo de vida).

| Paso | Descripción | Estado |
| --- | --- | --- |
| 0 | Fundaciones del repo: docs, ADR, `CLAUDE.md`, equipo de agentes | **hecho** |
| 1 | Esqueleto: `pyproject`/uv, ruff, mypy, pytest, import-linter (6 contratos), `config`, app factory, `/health`, `/ready`, structlog, `scripts/gate.sh` y hook pre-commit | **hecho** |
| 2 | Dominio extensible, puertos y casos de uso (ver abajo) | **hecho** (veredicto LT-QA: LISTO CON DEUDA); commiteado (`b73dcf6`) |
| 2b | Fase II y recalibración de T²MRCD ([ADR 0008](adr/0008-ciclo-de-vida-de-la-carta.md)). **2b.1 dominio:** dos límites (Fase I y Fase II por OOB), pool, error Monte Carlo, depuración, comparación S/μ. **2b.2 aplicación:** puertos y casos de uso del ciclo de vida, estrategias persistidas por nombre (M1) | **2b.1 hecho, pendiente de commit** (2026-10-07); 2b.2 pendiente |
| 3 | Adaptadores mínimos, `container.py`, tenant, rutas por carta Fase I/II, errores uniformes | pendiente |
| 4 | Dockerfile, docker-compose (perfiles distribuidos comentados), CI | pendiente |
| 5 | Andamiaje golden **por método**: `generate_golden.R`, fixtures, tests `xfail(strict=True)` | pendiente |

## Ajuste de plan aprobado: ADR 0004 y 0005

El dueño aprobó que las cartas y estimadores sean extensibles e independientes
([ADR 0004](adr/0004-cartas-y-estimadores-extensibles.md)) y que la API sea por carta con Fase I y Fase II,
ambas asíncronas ([ADR 0005](adr/0005-api-fase-i-fase-ii.md)). Por eso el plan original de los Pasos 2, 3 y 5
(un único `/v1/analyses`) queda redefinido así:

- **Paso 2 (hecho):** `domain/estimators/mrcd/` (adaptador sobre `pymrcd`: `MRCDParams`, `fit_mrcd`, `MRCDFit`),
  `domain/charts/t2mrcd/` (parámetros, estadística, bootstrap, `fit_phase1`/`score_phase2`),
  `domain/common/` (`ControlChart`, `TaskMapper`, errores), 13 contratos de import-linter (los `independence`
  ya existen), los puertos de `application` (`ModelRepository`, `MonitoringRepository`, `JobQueue`/`JobRequest`,
  `IdGenerator`, `Clock`), los casos de uso `TrainModel`, `GetModel`, `MonitorObservations`, `GetMonitoring`
  y los jobs `RunTrainingJob`/`RunMonitoringJob`, y `docs/metodos/` completado.
- **Paso 2b (en curso):** ver arriba.
- **Paso 3:** rutas `/v1/charts/t2mrcd/models…` y `…/monitorings…` más los endpoints del ciclo de vida (ADR 0005,
  enmienda 2026-10-07); test de que la Fase I termina en `failed / T2MRCD_DECISION_PENDING` si un campo decisivo se
  pasa como `None`; aislamiento por tenant.
- **Paso 5:** golden tests por método (MRCD contra `rrcov`; T²MRCD contra su propia referencia).

## Paso 2b: decisiones del dueño (2026-10-07)

Diseño del dueño para Fase II y recalibración; detalle en el [ADR 0008](adr/0008-ciclo-de-vida-de-la-carta.md),
la enmienda del [ADR 0007](adr/0007-limites-t2mrcd-por-bootstrap.md) y la del [ADR 0005](adr/0005-api-fase-i-fase-ii.md).

- **El backend es dueño del ciclo de vida** (versiones inmutables, observaciones, anotaciones, eventos,
  propuesta/aprobación, avisos); el front solo muestra y pide.
- **Límites:** remuestreo no paramétrico, nunca normal; Fase II por OOB (**revierte** la anulación del Paso 2);
  **Q1 pool** en ambas fases (sustituye el promedio de cuantiles; motivo: α efectivo ≈ 0.018 y ≈ 0.035 frente a 0.005);
  `phase2_alpha_limit` 0.005. Q2: v0 vigila con el límite de Fase I; las recalibradas con el de Fase II.
- **Recalibración:** Q3 depuración humana + automática; Q4 Frobenius relativa, umbral 0.10 orientativo, reemplazar si
  cualquier señal de cambio; Q5 máx. 5 vueltas; Q6 `effective_from` no retroactivo; Q7 con «requiere nueva base» se
  sigue vigilando; Q8 hereda B, α y MRCD; Q9 «Fase II > Fase I» es diagnóstico; Q12 solo se anotan señales.
  Mínimo 25 observaciones.
- **Mejoras:** aprobadas M1 (estrategias por nombre, en 2b.2) y M6 (error Monte Carlo); M5 (optimizar `pymrcd`) antes de
  producción; M2 (ARL al 90 %), M3 (avisos activos), M4 (roles con JWT) después. Ojo: la numeración M1–M6 de 2b no
  coincide con la del Paso 2 (más abajo).
- **Coste:** la v0 hasta `(1 + max_depuration_rounds)·B` ajustes MRCD; una recalibración hasta `(1 + rondas)·B`
  más B en EXTEND (estimación previa del dueño: ≈ 300 ajustes, 20–70 min en 8 núcleos con `pymrcd` actual).
- **Prueba de calidad de la tubería:** estimador clásico + muestreador de muestras independientes (normal, solo en
  `tests/`) reproduce Beta (Fase I) y F (Fase II), n > p. No valida el OOB: con el clásico la Fase II sale ≈ +16 %
  sobre la F (efecto .632), conservadora.

### Decisiones nuevas del dueño (2026-10-07, 2b.1)

- **Remuestreo solo sobre `best` (0.75)** para ambos límites: evita que una contaminación no detectada infle el
  límite (enmascaramiento). Consecuencia medida: falsa alarma real ≈ 2.0–2.4 % (Fase I) y ≈ 1.6–2.2 % (Fase II)
  frente al 0.5 % nominal (≈ 0.4 % con todas las filas); la depuración automática puede quitar 1–10 filas buenas.
  Característica del diseño, no error.
- **Umbral Frobenius parametrizable:** `relative_change_threshold` 0.10 y `threshold_decides = False` (informativo;
  deciden las pruebas formales de S y μ). Motivo: con datos estables la Frobenius de MRCD sale ≈ 0.25–0.5. Sin
  pruebas citadas, la recalibración responde `T2MRCD_DECISION_PENDING` salvo `force_replace`, en ambos modos.
- **Error MC con B = 1:** `None` (no disponible).
- **Pendiente 2b.2:** hash del contenido de la base al persistir.

## Paso 2: decisiones del dueño (2026-10-07)

- **P1:** MRCD se ajusta con `pymrcd`. Desaparece la regla `MRCD.fit` → `NotImplementedError` /
  `MRCD_NOT_IMPLEMENTED`; la regla de «sin placeholders» pasa a `failed / T2MRCD_DECISION_PENDING` con
  `details.pending` (enmienda del [ADR 0002](adr/0002-mrcd-sin-aproximaciones.md)).
- **P2 (cerrada):** filas limpias = subconjunto `best` de MRCD con alpha 0.75 (`h = ceiling(0.75·n)`).
- **P3 (cerrada):** B = `n_replicates`, default 100, citado (Heng, Shen y Lange, 2026, JCGS 35(1):27–39).
- **P4 (cerrada):** `alpha_limit = 0.005` (cuantil 0.995), cuantil tipo 7. *Agregación: promedio de cuantiles por réplica, **sustituida por pool en el Paso 2b**.*
- **P5 (modificada):** remuestreo con reemplazo de tamaño `h`; *un único límite para Fase I y Fase II
  (anulación de la parte out-of-bag), **revertida en el Paso 2b**: dos límites*; señal `t2 > límite` estricta
  ([ADR 0007](adr/0007-limites-t2mrcd-por-bootstrap.md)).
- **P6 (cerrada):** `statistic_reference` = artículo T²MRCD del dueño, en proceso de publicación.
- **Mejoras aplicadas:** M1 (el dominio no importa IO, procesos ni hilos), M2, M4 (`TaskMapper` con contexto
  enviado una vez) y M5. **Aplazadas:** M3 (`DatasetStorage`, al Paso 3) y M6 (optimizar `pymrcd`).
- **Sin pendientes con los defaults:** la Fase I se ejecuta completa; `T2MRCD_DECISION_PENDING` solo aparece si
  alguien pasa un campo decisivo como `None`.
- El **Protocol de carta** quedó en `domain/common/chart.py` (riesgo anotado antes: resuelto).

## Port de MRCD a `pymrcd` (antes del Paso 2) — hecho

El dueño decidió portar primero `rrcov::CovMrcd` **1.7-7 oficial de CRAN** como librería propia
`packages/pymrcd` (GPL-3, uso privado, solo numpy/scipy); ver [ADR 0006](adr/0006-libreria-pymrcd.md) y
[`metodos/mrcd-especificacion.md`](metodos/mrcd-especificacion.md). El rrcov modificado del dueño (ogkU.c con
MAD, hecho para pruebas en paralelo) no se porta.

| Fase | Estado |
| --- | --- |
| Especificación línea a línea (analista-port) | hecha y corregida (FMA, eigen, alineación BLAS) |
| Oráculo R aislado, simulación C1–C10 + variantes, intermedios y primitivas (ingeniero-r) | hecho; fixtures reducidos versionados (~50 MB), el resto se regenera con `tools/r/` |
| Workspace uv, esqueleto y compuerta de 7 etapas | hecho |
| Bloque 1: primitivas de R, Qn, doScale, `.MCDcons`, `uniroot` | hecho, bit a bit con R salvo `eigen` (1–4 ulp, signo, D9); `.MCDcons` bit a bit con D10 |
| Bloque 2: OGK, r6pack, selección de ρ, C-steps, final, extremo a extremo (`cov_mrcd`) | hecho |
| Validación estadística | APROBADO CON OBSERVACIONES; observaciones resueltas (vueltas de corrección 1 y 2 cerradas) |
| LT-QA | hecho |

Decisiones del dueño D9 (`eigen` con tolerancias tipo B) y D10 (`qchisq`/`pgamma` de nmath para `.MCDcons`):
aprobadas el 2026-10-06 y recogidas en la enmienda del [ADR 0006](adr/0006-libreria-pymrcd.md).

## Versión determinista de la inicialización (aparcada)

Con p > n, rrcov no es reproducible: un cambio en el decimal 14 de los datos cambia los subconjuntos
iniciales y puede cambiar el resultado (y entre plataformas también). Se probó en R una inicialización
canónica que fija esa elección a partir de los propios datos (`canonical2`):
[piloto 1](experimentos/2026-10-06-mrcd-canonico-piloto.md) y
[piloto 2](experimentos/2026-10-06-mrcd-canonico-piloto2.md). Resultado: determinista en 1750/1750 pruebas,
idéntica a rrcov con n > p, objetivo igual o mejor que rrcov en el 81 % de los casos con p > n y mismo coste.

**Decisión del dueño (2026-10-06): aparcada.** Voracious usa el rrcov original. Adoptar `canonical2` (como
modo opcional, con ADR propio) exigiría antes el Monte Carlo de la carta T²MRCD ya pre-registrado en
[`experimentos/2026-10-06-mc-canonico2-protocolo.md`](experimentos/2026-10-06-mc-canonico2-protocolo.md)
(≈ 11 h en este Mac; la corrida se detuvo a los pocos minutos por decisión del dueño). Si se retoma, conviene
correrlo en un servidor con más núcleos.

## Paso 1: lo que quedó y por qué se desvió del plan

- **Orden de capas** `api | workers` → `container` → `infrastructure` → `application` → `domain`: el plan
  decía `api → application`, pero `api` importa `container` y `container` cablea `infrastructure`; el contrato
  `layers` tiene que reflejar el flujo real o no sirve como verificación.
- **6º contrato** `api ↛ infrastructure`: el contrato `layers` por sí solo permitiría a `api` saltarse
  `container` e importar adaptadores.
- **`allow_indirect_imports`** en `api ↛ config` y `api ↛ infrastructure`: el camino legítimo es
  `api → container → config|infrastructure`; sin esa opción import-linter lo marcaría como violación.
- **Test de `frozen` vía `model_config`**: el test comprueba que `Settings.model_config` declara
  `frozen=True` en lugar de intentar mutar una instancia; verifica la declaración de inmutabilidad, no su
  efecto en ejecución.
- **`ValueError` en `configure_logging`** ante un nivel inválido, en lugar de caer a un valor por defecto:
  un nivel mal escrito debe fallar al arrancar, no degradarse en silencio.

## Decisiones abiertas

- **Regla de cuantil** tipo 7 (`method="linear"`): elección técnica reversible; confirmar o cambiar.
- **Pruebas formales de cambio en S y en μ** (remuestreo) de la recalibración: pendientes de cita; sin ellas la
  recalibración termina en `failed / T2MRCD_DECISION_PENDING` salvo reemplazo forzado.
- Cita del umbral 0.10 y de la revalidación de 6 meses (hoy documento del dueño, orientativos).
- Cita del bootstrap de límites T² y de `alpha_limit = 0.005` (hoy decisiones del dueño).
- Fuente de los golden de la carta T²MRCD.
- Código de HTTP de `/ready` cuando un check falle (hoy `checks` va vacío): ver
  [`arquitectura.md`](arquitectura.md).

## Deuda técnica

### Del Paso 2, para el Paso 3

- **Cita final del artículo T²MRCD** (P6): sustituir `STATISTIC_REFERENCE` cuando se publique (regla dura 3).
- **Recalibración y ciclo de vida:** dominio implementado (2b.1, pendiente de commit); aplicación (2b.2) y luego Paso 3.
- **Citas de las pruebas formales de cambio en S y μ** (hoy sin cita; bloquean la recalibración sin `force_replace`).
- **Reponderado tipo MCD** (añadir a `best` las observaciones con distancia robusta no extrema): estudio futuro para
  acercar la falsa alarma real al 0.5 % nominal.
- **Hash del contenido de la base** al persistir (2b.2): la comprobación por T² con `rtol` no prueba identidad.
- **Persistencia de estrategias por nombre** (M1 de 2b, en 2b.2): `clean_criterion` y `aggregation` son *callables*
  dentro de los parámetros; un repositorio real no puede guardarlos tal cual.
- **Coste de la recalibración** (cientos de ajustes por las rondas de depuración): M5, optimizar `pymrcd`, **más
  urgente**, antes de producción.
- **Mejoras posteriores:** M2 (ARL al 90 %), M3 (avisos activos), M4 (roles con JWT).
- **Fase I fuera del hilo de la API:** tarda minutos (ver ADR 0007); `InlineJobQueue` la ejecutaría dentro de la petición.
- **`ProcessPoolTaskMapper`** en `infrastructure`, con BLAS a 1 hilo por proceso y una prueba de que los límites
  no cambian respecto al reparto en serie.
- **Transición de estado atómica** `queued → running`: hoy la idempotencia de los jobs no cubre dos workers a la vez.
- **Contrato `workers ↛ infrastructure|config`** (cuando `workers` tenga contenido) y decidir si hace falta
  `infrastructure ↛ config`.
- **Empaquetado de `packages/pymrcd` en la imagen** (Paso 4, pero afecta al diseño del Dockerfile).
- **Validación síncrona del histórico** de Fase I (hoy solo se valida la de Fase II antes de encolar).
- **M3:** `DatasetStorage`.

### Anterior

- **M6:** optimizar `pymrcd` antes de producción (2–3× más lento que R desde cero, sobre todo el Qn de OGK; sin
  Numba por ahora). Se optimiza la implementación, nunca el método.
- El comentario de `tools/r/experimentos/mc_canonico2.R:2` apunta al nombre antiguo del protocolo
  (`2026-10-07-…`); no se toca para no alterar el MD5 pre-registrado (ver nota de trazabilidad en el protocolo).
- `StarletteDeprecationWarning` por el cambio `httpx` → `httpx2` (Paso 4).

## Notas del entorno

- R y Rscript disponibles en la máquina de desarrollo; falta confirmar que `rrcov` está instalado (Paso 2/5).
- Siempre `uv run …` (el `python` del PATH es de pyenv y no es el del proyecto).
