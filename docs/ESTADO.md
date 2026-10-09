# Estado del proyecto

Última actualización: 2026-10-09 (Paso 4: 4.0 y 4.1 hechas; eliminada la depuración automática y medidos los tiempos de Fase I en el servidor).

**Siguiente hito:** 4.2 (Postgres/TimescaleDB, demo y backup), y a continuación el Paso 5 (golden por método).

| Paso | Descripción | Estado |
| --- | --- | --- |
| 0 | Fundaciones del repo: docs, ADR, `CLAUDE.md`, equipo de agentes | **hecho** |
| 1 | Esqueleto: `pyproject`/uv, ruff, mypy, pytest, import-linter (6 contratos), `config`, app factory, `/health`, `/ready`, structlog, `scripts/gate.sh` y hook pre-commit | **hecho** |
| 2 | Dominio extensible, puertos y casos de uso (ver abajo) | **hecho** (veredicto LT-QA: LISTO CON DEUDA); commiteado (`b73dcf6`) |
| 2b | Fase II y recalibración de T²MRCD ([ADR 0008](adr/0008-ciclo-de-vida-de-la-carta.md)). **2b.1 dominio:** dos límites (Fase I y Fase II por OOB), pool, error Monte Carlo, comparación S/μ (la depuración automática se eliminó el 2026-10-09). **2b.2 aplicación:** puertos y casos de uso del ciclo de vida, estrategias persistidas por nombre (M1) | **hecho.** 2b.1 commiteado (`c44f86d`); 2b.2 hecho y commiteado (2026-10-07). Validador: APROBADO CON OBSERVACIONES, ya aplicadas |
| M5 | Optimizar `pymrcd`: `Qn` y pares de OGK en C ([ADR 0006](adr/0006-libreria-pymrcd.md), enmienda 2026-10-07; [especificación §3.12.9](metodos/mrcd-especificacion.md)) | **hecho.** Validador: APROBADO CON OBSERVACIONES. Criterio «≥ 10× con 1 hilo» **no cumplido** (4.1×); ver abajo |
| 3 | Adaptadores, `container.py`, tenant, errores uniformes y API por pasos independientes encadenables por id ([ADR 0009](adr/0009-api-por-pasos-encadenables.md)); 3.1 infraestructura, 3.2 dominio en piezas, 3.3 Fase I por API, 3.4 Fase II y recalibración por API | **hecho** (14 contratos de import-linter). Validador: APROBADO CON OBSERVACIONES en 3.2 y 3.4, ya aplicadas. Ver «Paso 3» abajo |
| 4 | Docker, CI y Postgres. 4.0 y 4.1 hechas (Dockerfile, compose, CI, validación en Linux; [ADR 0010](adr/0010-empaquetado-docker-y-ci.md)); 4.2 (Postgres, demo, backup) pendiente | **en curso** |
| 5 | Andamiaje golden **por método**: `generate_golden.R`, fixtures, tests `xfail(strict=True)` | pendiente |

## Paso 4: Docker, CI y validación en Linux (2026-10-09)

Por qué: el C de `pymrcd` solo se había ejecutado en macOS arm64 y su igualdad en bits con R depende del
compilador. Decisiones y alternativas en el [ADR 0010](adr/0010-empaquetado-docker-y-ci.md) (propuesto); las
tolerancias D1–D3 en la enmienda del [ADR 0006](adr/0006-libreria-pymrcd.md) y la
[especificación](metodos/mrcd-especificacion.md).

- **4.0 y 4.1: hecho.** Dockerfile de tres etapas, `.dockerignore`, `docker-compose.yml`, CI de cuatro trabajos,
  Dependabot, `check_pymrcd_fma.sh` con traza, `pymrcd_poison_sweep.py`, `httpx2` y avisos como error.
- **Validación en el servidor** (Ubuntu 26.04, AMD EPYC-Rome 2 vCPU con fma/avx2, 3.7 GiB, Docker 29.9; gcc 14.2.0 en
  Debian trixie): build de la etapa gate 32–56 s; compuerta completa en el contenedor EXIT=0 en 267 s (voracious
  552 passed / 1 skipped, cobertura 97 %; pymrcd 1405 passed / 304 skipped; 14 contratos). FMA 0 y conversiones 4/4
  en `qn0`. Con `-march=x86-64-v3`: 0 FMA y 688 tests de Qn pasan. Prueba negativa (`-ffp-contract=fast` en
  `setup.py`): 5 FMA (`vfmadd132sd`) y el check falla como debe. Imagen runtime: 490 MB.
- **Validación local previa:** Linux arm64 nativo y amd64 emulado EXIT=0; Mac sin cambios (bit a bit).
- **Clon limpio:** pymrcd 1400 passed / 299 skipped, cobertura 98.17 %: no hace falta versionar los ~145 MiB de
  intermedios.
- **Nota de proceso:** el primer intento en el servidor dio rojo por archivos AppleDouble `._*` del tar de macOS;
  se copia con `COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata`.
- **Deudas cerradas:** validación de gcc/objdump en Linux, sanitizers en CI, aviso de `httpx`, empaquetado de
  `pymrcd` en la imagen.
- **Abiertas:** 4.2 (Postgres/TimescaleDB, demo, backup); huellas de composición solo en Darwin arm64; `/ready` sin
  checks hasta 4.2; consecuencia de producto con p ≥ n en Linux (D1–D3); tiempos de recalibración completa y caso
  p > n sin medir (Fase I 200×300 medida: ver «Sin depuración automática»).

## Sin depuración automática y tiempos medidos (2026-10-09)

Decisión del dueño: no hay depuración automática iterativa. **Por qué:** con MRCD nunca converge (no es «de
composición»: cada vuelta deja fuera otro 25 % del nuevo total y el límite se calcula siempre sobre el 75 %
sobrante). Medido en el servidor, 200 × 300, B = 100, 2 vCPU: 200 → 150 → 113 → 85 → 64 → 48 → 36 filas en 6
rondas, 18,3 min, sin converger. Estado: **hecho**. Detalle en [`metodos/t2mrcd.md`](metodos/t2mrcd.md), la
enmienda del [ADR 0008](adr/0008-ciclo-de-vida-de-la-carta.md) (supera Q3 y Q5), la del
[ADR 0007](adr/0007-limites-t2mrcd-por-bootstrap.md) y la del [ADR 0005](adr/0005-api-fase-i-fase-ii.md) (contratos).

- **Flujos:** Fase I = exclusión humana opcional → ajuste → límites → modelo, una pasada. Recalibración =
  candidatas → exclusión humana desde anotaciones → ajuste → límites → comparación (o versión directa) → si
  EXTEND, ajuste y límites de la extensión → versión.
- **Tiempos (servidor, 200×300, B = 100, 2 procesos × 1 hilo):** una calibración 5,5 min; Fase I ≈ 6 min
  (estimado de la ronda 0 medida); memoria pico 245 MB.
- **Confirmado por el dueño:** cuantil por pool, grupo de Fase I = toda la muestra sorteada, sin estudio de
  simulación del sesgo.
- **Falsa alarma real** (12 réplicas, n = 200, p = 3, B = 50, 20 000 nuevas): Fase I media 2.29 % [0.96–3.77],
  Fase II 2.10 % [0.91–2.82]; medias entre semillas (~1–3.8 %). **No medido:** p > n.
- **Compatibilidad:** formatos de modelo, informe y metadatos de dataset = 2; el 1 se rechaza, sin migración.
- **Equivalencia de la recalibración por HTTP:** cubiertos en bits los cuatro casos (EXTEND, REPLACE no forzado,
  REPLACE forzado e INSUFFICIENT); REPLACE reutiliza el hueco `(1, 0)` (`test_recalibration_chain.py`).

## Paso 3: API por pasos (2026-10-07)

Requisito del dueño: APIs independientes por paso, encadenables por id, para avanzar, mantener y depurar cada una
sin que «todo en un solo API» colapse. Decisión y alternativas en el [ADR 0009](adr/0009-api-por-pasos-encadenables.md);
rutas y códigos en la enmienda del [ADR 0005](adr/0005-api-fase-i-fase-ii.md); carriles en la del
[ADR 0003](adr/0003-api-asincrona.md).

- **3.1 Infraestructura:** repositorios en memoria thread-safe con `claim` y altas atómicas (D6), `InlineJobQueue`
  por carriles, `ProcessPoolTaskMapper` (idéntico en bits a serie), reloj, ids, tenant, errores uniformes,
  contrato 14 `workers ↛ infrastructure|config`, stub `typings/threadpoolctl.pyi`.
- **3.2 Dominio en piezas públicas** sin cambiar bits, codecs exactos y fixture de huellas.
- **3.3 Fase I por API:** datasets, `fits`, `limits`, `exclusions`, `models` (solo referencias), `pipelines`.
  Equivalencia en bits cadena HTTP = tubería = `fit_phase1`. Semilla deducida del linaje
  ([`metodos/t2mrcd.md`](metodos/t2mrcd.md)).
- **3.4 Fase II y recalibración por API:** `scores`, `recalibrations` (stepwise/pipeline, `cancel`), `comparisons`,
  `versions`, anotaciones por POST append-only. Equivalencia en bits con `recalibrate`.
- **Mejoras hechas:** M1 (estado codificado), M2 (CSV), M3 (`?include=`), M6 (`LocalDatasetStorage` con hash).

### Decisiones del dueño del Paso 3 (P1–P5 propias de este Paso)

- P1: una sola API de MRCD con `alpha` parametrizable (default 0.75); no hay «MRCD puro».
- P2: `/models` solo con referencias.
- P3: la comparación responde `RECALIBRATION_DECISION_PENDING` mientras no haya pruebas formales citadas.
- P4: anotaciones append-only por `POST`.
- P5: commit único al final del Paso.

### Deuda del Paso 3

- **Postgres/TimescaleDB, Celery y S3:** adaptadores reales (Paso 4+). Hoy los repositorios y la cola viven en el
  proceso: reiniciar pierde el estado.
- **M4** (`Idempotency-Key`), **M5** (progreso de los trabajos) y **M7** (webhooks): después.
- **Sesiones stepwise sin expiración automática:** una recalibración paso a paso queda abierta hasta `cancel`,
  aprobación o rechazo.
- **Pool de procesos por llamada** en `ProcessPoolTaskMapper`: el coste del `spawn` se paga en cada calibración.
- **Huellas de composición solo en Darwin arm64** (el C de `pymrcd` ya se validó en Linux en el Paso 4.1).
- **`/ready` sin checks** y su código HTTP cuando falle (decisión abierta).
- **Autenticación real** (JWT/OIDC) y roles (M4 antiguo); hoy solo `X-Tenant-ID`.
- **Coste no medido de extremo a extremo** de la Fase I con réplicas en procesos sobre la API.

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
- **Paso 3 (plan original; lo ejecutado está en «Paso 3: API por pasos»):** rutas `/v1/charts/t2mrcd/models…` y `…/monitorings…` más los endpoints del ciclo de vida (ADR 0005,
  enmienda 2026-10-07); test de que la Fase I termina en `failed / T2MRCD_DECISION_PENDING` si un campo decisivo se
  pasa como `None`; aislamiento por tenant.
- **Paso 5:** golden tests por método (MRCD contra `rrcov`; T²MRCD contra su propia referencia).

## M5: `Qn` de `pymrcd` en C (2026-10-07)

Por qué: la Fase I y la recalibración repiten cientos de ajustes MRCD y el cuello de botella era `Qn` (sobre todo
los `p(p−1)` pares de OGK). Decisiones del dueño: port literal en C de `qn0`/`whimed_i`/`R_qsort`/`rPsort` (P1 = A,
sin respaldo Python), setuptools ≥ 77 (P2), todos los núcleos más `VORACIOUS_MRCD_THREADS` (P3), pares de OGK en C
(P4), ante `±0` manda R (P5). Detalle y límites en el ADR 0006 (enmienda 2026-10-07) y la especificación §3.12.9.

Medido en un Mac M2 de 8 núcleos (antes → 1 hilo → 8 hilos):

| Caso | Antes | 1 hilo | 8 hilos |
| --- | --- | --- | --- |
| `cov_mrcd` 200×300, alpha 0.75 | 30.28 s | 7.76 s | 1.56 s (19.4×) |
| `cov_mrcd` 100×250 | 9.34 s | 2.16 s | 0.56 s |
| `ogk_u` 200×300 | 29.20 s | 7.05 s | 1.03 s |
| tests de `pymrcd` | 151 s | 38 s | — |

Fidelidad: `Qn` igual a R en bits (incluido el signo del cero); instantánea de 2933 claves de `cov_mrcd`, 0 diferencias.

**Criterio ≥ 10× con un hilo: NO cumplido (4.1×).** Un `qn0` literal cuesta ≈ 66–70 µs por columna (n = 200)
frente a ≈ 77–82 µs de `.C(Qn0)` de R: el C ya es tan rápido como el de R. Llegar a 10× exigiría cambiar el
algoritmo, prohibido por la especificación §3.12.9 y el ADR 0002. La ganancia restante viene del paralelismo.

**Tiempos de la Fase I (estimación, no medida de extremo a extremo):** cada ajuste ≈ 1.6 s con 8 núcleos; el peor caso
(≈ 600 ajustes) ≈ 15 min en este Mac **sin** repartir réplicas entre procesos (`ProcessPoolTaskMapper` sigue
pendiente). Sustituye a la estimación de 20–70 min de 2b.

**Deuda de M5:**
- Fixtures R versionados de `R_qsort`, `rPsort` y `whimed_i` (hoy se prueban contra la transliteración literal; el
  contraste con R fue ad hoc).
- (Cerrado en el Paso 4.1) Trabajo de CI con ASan/UBSan y validación en Linux (gcc, `objdump`).
- Test versionado de la `U` de OGK completa con p > 60 (hoy compara un bloque de 60 columnas; la completa se
  cubrió con la instantánea no versionada).
- `assert_r_equal("E")` de los fixtures antiguos de `Qn` está limitado a la plataforma de referencia; la
  especificación pide exactitud en todas (el C no depende de libm ni BLAS).
- (Cerrado en el Paso 3) `VORACIOUS_MRCD_THREADS` cableada en `container`; el mapper por procesos fija `PYMRCD_NUM_THREADS`.
- (Cerrado en el Paso 4.1) Imagen: compilador solo en la etapa builder.

## Paso 2b: decisiones del dueño (2026-10-07)

Diseño del dueño para Fase II y recalibración; detalle en el [ADR 0008](adr/0008-ciclo-de-vida-de-la-carta.md),
la enmienda del [ADR 0007](adr/0007-limites-t2mrcd-por-bootstrap.md) y la del [ADR 0005](adr/0005-api-fase-i-fase-ii.md).

- **El backend es dueño del ciclo de vida** (versiones inmutables, observaciones, anotaciones, eventos,
  propuesta/aprobación, avisos); el front solo muestra y pide.
- **Límites:** remuestreo no paramétrico, nunca normal; Fase II por OOB (**revierte** la anulación del Paso 2);
  **Q1 pool** en ambas fases (sustituye el promedio de cuantiles; motivo: α efectivo ≈ 0.018 y ≈ 0.035 frente a 0.005);
  `phase2_alpha_limit` 0.005. Q2: v0 vigila con el límite de Fase I; las recalibradas con el de Fase II.
- **Recalibración:** Q3 ~~depuración humana + automática~~ (solo humana desde el 2026-10-09); Q4 Frobenius relativa, umbral 0.10 orientativo, reemplazar si
  cualquier señal de cambio; Q5 ~~máx. 5 vueltas~~ (superada: no hay depuración); Q6 `effective_from` no retroactivo; Q7 con «requiere nueva base» se
  sigue vigilando; Q8 hereda B, α y MRCD; Q9 «Fase II > Fase I» es diagnóstico; Q12 solo se anotan señales.
  Mínimo 25 observaciones.
- **Mejoras:** aprobadas M1 (estrategias por nombre, en 2b.2) y M6 (error Monte Carlo); M5 (optimizar `pymrcd`) antes de
  producción; M2 (ARL al 90 %), M3 (avisos activos), M4 (roles con JWT) después. Ojo: la numeración M1–M6 de 2b no
  coincide con la del Paso 2 (más abajo).
- **Coste:** `B` ajustes MRCD por calibración (v0: una; recalibración: filas nuevas, más una en EXTEND).
  Estimación previa del dueño: ≈ 300 ajustes, 20–70 min en 8 núcleos; medido en el servidor, ver abajo.
- **Prueba de calidad de la tubería:** estimador clásico + muestreador de muestras independientes (normal, solo en
  `tests/`) reproduce Beta (Fase I) y F (Fase II), n > p. No valida el OOB: con el clásico la Fase II sale ≈ +16 %
  sobre la F (efecto .632), conservadora.

### Decisiones nuevas del dueño (2026-10-07, 2b.1)

- **Remuestreo solo sobre `best` (0.75)** para ambos límites: evita que una contaminación no detectada infle el
  límite (enmascaramiento). Consecuencia medida: falsa alarma real ≈ 2.0–2.4 % (Fase I) y ≈ 1.6–2.2 % (Fase II)
  frente al 0.5 % nominal (≈ 0.4 % con todas las filas). Re-medida sin depuración: ver «Sin depuración automática».
  Característica del diseño, no error.
- **Umbral Frobenius parametrizable:** `relative_change_threshold` 0.10 y `threshold_decides = False` (informativo;
  deciden las pruebas formales de S y μ). Motivo: con datos estables la Frobenius de MRCD sale ≈ 0.25–0.5. Sin
  pruebas citadas, la recalibración responde `T2MRCD_DECISION_PENDING` salvo `force_replace`, en ambos modos.
- **Error MC con B = 1:** `None` (no disponible).
- **Hash del contenido de la base:** hecho en 2b.2 (`base_hash`, SHA-256).

### Decisión del dueño (2026-10-07, 2b.2): método del límite

El dueño propuso calcular el límite con bootstrap de los **valores** de T² de `best`. Se evaluó por simulación
(límite ≈ máximo de `best`; falsa alarma con nuevas 34–37 % con n = 200, p = 10 y 100 % con n = 100, p = 250) y
**el dueño decidió mantener lo implementado** (remuestrear filas y reajustar MRCD). Detalle en
[`metodos/t2mrcd.md`](metodos/t2mrcd.md) y la enmienda del [ADR 0007](adr/0007-limites-t2mrcd-por-bootstrap.md).

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

### Del Paso 2 que sigue abierto

- **Cita final del artículo T²MRCD** (P6): sustituir `STATISTIC_REFERENCE` cuando se publique (regla dura 3).
- **Citas de las pruebas formales de cambio en S y μ** (hoy sin cita; bloquean la recalibración sin `force_replace`).
- **Reponderado tipo MCD** (añadir a `best` las observaciones con distancia robusta no extrema): estudio futuro para
  acercar la falsa alarma real al 0.5 % nominal.
- **Bootstrap suavizado (kernel sobre el pool de T²)**: estudio futuro de baja prioridad (dueño, 2026-10-07: «no se
  gana mucho»). Un KDE sobre los T² de un solo ajuste **no** sustituye al bootstrap con reajuste: sobre `best` dio
  falsa alarma 27–30 % (p = 10) y 100 % (p = 250), y sobre todas las filas fue inestable (0.2–0.9 %) y expuesto al
  enmascaramiento; además ignora el error de estimación de μ y S. Solo podría suavizar el cuantil del pool
  (≈ 7 500 valores), con ganancia pequeña.
- (Cerrado en el Paso 4.1) Empaquetado de `pymrcd` en la imagen: ADR 0010.
- **Cerradas en el Paso 3:** persistencia del objeto modelo (M1, codecs), atomicidad de propuestas y recalibraciones
  (D6), `ProcessPoolTaskMapper`, `queued → running` atómico (`claim`), Fase I fuera del hilo de la API, contrato
  `workers ↛ infrastructure|config`, validación síncrona del histórico, `DatasetStorage` (M6), cableado de
  `VORACIOUS_MRCD_THREADS`.

### Anterior

- **M6 (hecho como M5, ver arriba):** optimizar `pymrcd` (era 2–3× más lento que R desde cero, sobre todo el Qn de OGK). Se
  hizo con la única excepción aprobada a «sin Numba/Cython»: la extensión C del ADR 0006 (enmienda 2026-10-07).
  Se optimiza la implementación, nunca el método.
- El comentario de `tools/r/experimentos/mc_canonico2.R:2` apunta al nombre antiguo del protocolo
  (`2026-10-07-…`); no se toca para no alterar el MD5 pre-registrado (ver nota de trazabilidad en el protocolo).
- (Cerrado en el Paso 4.1) `StarletteDeprecationWarning` por `httpx` → `httpx2`.

## Notas del entorno

- R y Rscript disponibles en la máquina de desarrollo; falta confirmar que `rrcov` está instalado (Paso 2/5).
- Siempre `uv run …` (el `python` del PATH es de pyenv y no es el del proyecto).
