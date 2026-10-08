# CLAUDE.md — Voracious backend

Orquestador del proyecto. Todo agente o sesión lo lee **antes** de tocar nada. Si algo de aquí contradice
otra fuente, manda este archivo; si está desactualizado, se corrige aquí primero.

## Qué es

Backend SaaS para monitorear el **apetito de riesgo multivariado** de portafolios financieros con la carta
de control robusta **T²MRCD**. Hoy es un **cascarón**: estructura, cableado y compuertas, sin el algoritmo.
Tiene que poder crecer a la arquitectura distribuida **sin reescribir el dominio ni los casos de uso**.

## 1. Lo que no se negocia (producto)

- **El núcleo es MRCD, exactamente.** Port propio a Python de `rrcov::CovMrcd()` de R
  (Boudt, Rousseeuw, Vanduffel y Verdonck, 2020). Se comercializa porque, a diferencia de
  Shewhart/EWMA/Hotelling clásico, no asume normalidad, resiste outliers y enmascaramiento, y funciona con p > n.
- **Prohibido sustituirlo dentro de T²MRCD** por KMRCD, `sklearn.covariance.MinCovDet`, Ledoit-Wolf ni ninguna aproximación
  «más rápida». T²MRCD es la carta por defecto y MRCD su estimador de referencia. KMRCD no conserva las propiedades de MRCD y su probabilidad de señal no es eficiente.
  Si algo es lento se optimiza la **implementación** (vectorización, Numba/Cython, paralelismo entre
  portafolios), nunca el **método**. Otros métodos pueden entrar **como métodos propios**, nunca como sustitutos de MRCD
  en T²MRCD. Ver [ADR 0002](docs/adr/0002-mrcd-sin-aproximaciones.md) y
  [ADR 0004](docs/adr/0004-cartas-y-estimadores-extensibles.md).
- **La referencia es el código fuente de `rrcov`, no la memoria.** Parámetros de `CovMrcd`: `alpha`, `h`,
  `maxcsteps`, `rho`, `target` (`identity` | `equicorrelation`), `maxcond`. Defaults, estandarización
  inicial, subconjuntos iniciales deterministas, elección de `rho` por número de condición, C-steps y factor
  de consistencia se toman **leyendo `rrcov` (`CovMrcd.R`, `CovControlMrcd`)**, y cada decisión cita
  archivo y línea en [`docs/metodos/mrcd.md`](docs/metodos/mrcd.md).
- **La fidelidad se demuestra con tests golden, por método**: salidas de `rrcov::CovMrcd` en R sobre conjuntos fijos
  (semilla fija; casos n > p, p > n y contaminado) guardadas como fixtures; el port debe coincidir dentro
  de una tolerancia declarada. En el cascarón: script R, carpeta de fixtures y test `xfail(strict=True)`.
- **Límites de control de T²MRCD**: ningún estimador da un límite y no hay artículo de Fase II, así que los
  límites se calibran por **bootstrap no paramétrico** sobre las observaciones limpias del histórico
  ([ADR 0007](docs/adr/0007-limites-t2mrcd-por-bootstrap.md), con su enmienda del Paso 2b). Hay **dos límites**
  que comparten réplicas: Fase I (T² de la muestra) y Fase II (T² de las filas **OOB** con el ajuste de cada
  réplica). Ambos son el cuantil 1−α (tipo 7) del **pool** de T² de todas las réplicas, no el promedio de
  cuantiles por réplica (que infla el α efectivo cuando m·α < 1). B = `n_replicates` (100 por defecto, con cita),
  `alpha_limit` y `phase2_alpha_limit` = 0.005. **Límite operativo por régimen:** la v0 vigila con el de Fase I
  (provisional y fijo); las versiones recalibradas, con el de Fase II. **Se remuestrea solo `best` (alpha
  0.75)**: con todas las filas una contaminación no detectada inflaría el límite (enmascaramiento). **Falsa
  alarma real conocida:** frente a observaciones nuevas en control es ≈ 2.0–2.4 % en Fase I y ≈ 1.6–2.2 % en Fase
  II frente al 0.5 % nominal, porque `best` es el 75 % central; es una característica del diseño, no un error
  (estudio futuro: reponderado tipo MCD). El umbral Frobenius de la recalibración es parametrizable
  (`relative_change_threshold` 0.10; `threshold_decides = False`: solo informativo, deciden las pruebas formales
  de S y μ). El **ciclo de vida** (versiones inmutables
  propuestas y aprobadas, registro de observaciones, anotaciones, eventos estructurales, recalibración y
  revalidación) lo posee el backend: [ADR 0008](docs/adr/0008-ciclo-de-vida-de-la-carta.md) (dominio en 2b.1;
  aplicación en 2b.2). Pendientes: pruebas formales de cambio en S y μ, cita del bootstrap y de los umbrales (0.10, 6 meses),
  P6 (cita del artículo T²). Detalle en [`docs/metodos/t2mrcd.md`](docs/metodos/t2mrcd.md); lo que no esté
  documentado allí queda como **decisión abierta**.
- **Sin placeholders estadísticos.** MRCD se ajusta con `pymrcd` (el port de `rrcov::CovMrcd`, ADR 0006).
  Con los defaults decididos la Fase I se ejecuta completa; si un campo decisivo se pasa explícitamente como
  `None`, la Fase I de T²MRCD no se ejecuta: el dominio responde `T2MRCD_DECISION_PENDING` con `details.pending` (lista de
  campos pendientes), comprobado **antes** de ajustar nada (la API por pasos lo comprueba de forma síncrona, 422);
  la recalibración, mientras las pruebas formales de S y μ no tengan cita, responde
  `422 RECALIBRATION_DECISION_PENDING` salvo `force_replace`. Los valores «SOLO TEST» que permiten ejecutar la Fase I en pruebas viven únicamente en
  `tests/support/`, nunca en `src/`. Nada de covarianza clásica «mientras tanto».

## 2. Arquitectura (hexagonal)

Detalle en [`docs/arquitectura.md`](docs/arquitectura.md). Cada pieza distribuida entra después como
**un adaptador nuevo + una variable de configuración**.

| Pieza | Puerto | Adaptador hoy | Adaptador después |
| --- | --- | --- | --- |
| Ejecución de los pasos | `JobQueue` | `InlineJobQueue` (un hilo-pool por carril: estimation, calibration, light, orchestration) | `CeleryJobQueue` |
| Persistencia de pasos y modelos | `FitRepository`, `LimitsRepository`, `DepurationRepository`, `PipelineRepository`, `ModelRepository`, `MonitoringRepository`, `ComparisonRepository` | en memoria (seguros entre hilos, con `claim`) | Postgres (TimescaleDB) |
| Datos de entrada | `DatasetStorage` | `memory` o `LocalDatasetStorage` (`.npy` con hash) | `S3DatasetStorage` |
| Versiones, observaciones, anotaciones, eventos y recalibraciones | `ModelVersionRepository`, `ObservationRepository`, `SignalAnnotationRepository`, `StructuralEventRepository`, `RecalibrationRepository` | en memoria (altas atómicas) | Postgres (TimescaleDB) |
| Pasos por carta | `Phase1Steps`, `RecalibrationSteps` | `infrastructure/charts/t2mrcd_*.py` | un adaptador por carta |
| Reparto de réplicas | `TaskMapper` | `SerialTaskMapper` o `ProcessPoolTaskMapper` | Celery/Dask |
| Tenant | `TenantContext` | cabecera `X-Tenant-ID` (`400 TENANT_REQUIRED`) | JWT/OIDC |

Puertos auxiliares: `IdGenerator` y `Clock` (`UuidIdGenerator`, `SystemClock`). El `JobQueue` recibe un
`JobRequest` con solo identificadores. Variables: `VORACIOUS_LOG_LEVEL`, `_MRCD_THREADS`, `_JOB_BACKEND`,
`_REPOSITORY`, `_STORAGE` (`memory|local`), `_STORAGE_DIR`, `_REPLICATE_PROCESSES`,
`_QUEUE_WORKERS_{ESTIMATION,CALIBRATION,LIGHT,ORCHESTRATION}` y `_MAX_UPLOAD_MB` (tabla en
[`docs/arquitectura.md`](docs/arquitectura.md)).

API **por pasos independientes, encadenables por id** ([ADR 0009](docs/adr/0009-api-por-pasos-encadenables.md);
rutas y catálogo de códigos en la enmienda del Paso 3 del [ADR 0005](docs/adr/0005-api-fase-i-fase-ii.md)),
asíncrona ([ADR 0003](docs/adr/0003-api-asincrona.md)): `/v1/datasets`, `/v1/charts/t2mrcd/{fits,limits,depurations,models,pipelines}`
y, bajo `…/models/{id}`, `scores`, `observations`, `structural-events`, `recalibrations`, `comparisons` y `versions`.
Cada `POST` de cómputo responde `202 {id, status:"queued"}`. Estados `queued | running | succeeded | failed`.
Encadenar los pasos, la tubería y `fit_phase1`/`recalibrate` dan el mismo modelo **en bits**; no se rompe esa
equivalencia al tocar un paso. MRCD se expone bajo la carta con `alpha` parametrizable (default 0.75); no hay «MRCD puro».

Dominio extensible ([ADR 0004](docs/adr/0004-cartas-y-estimadores-extensibles.md)): `domain/charts/<carta>/`,
`domain/estimators/<estimador>/` y `domain/common/`. Cada carta implementa el `Protocol` `ControlChart`
(`domain/common/chart.py`): `fit_phase1`, `validate_phase2_input` y `score_phase2`.

### Dirección de dependencias (la verifica `import-linter`)

| Capa (de arriba abajo) | Puede importar | No puede importar |
| --- | --- | --- |
| `voracious.api`, `voracious.workers` | `application`, `domain`, `container` | `infrastructure` y `config` directos (solo vía `container`); `api` ↛ `workers` y viceversa |
| `voracious.container` | todo (es el cableado) | — |
| `voracious.infrastructure` | `application`, `domain` | `api`, `workers`, `container` |
| `voracious.application` | `domain` | `api`, `infrastructure`, `workers`, `config`, `container`, frameworks web/logging |
| `voracious.domain` | stdlib, `numpy`, `scipy`, `pymrcd` (solo en `domain/estimators/mrcd/`) | **nada del proyecto**; ni FastAPI, Pydantic, IO, red, config, logging |
| `voracious.config` | stdlib, `pydantic-settings` | cualquier capa del proyecto |

Orden real de capas (contrato `layers`): `api | workers` → `container` → `infrastructure` → `application`
→ `domain`; `config` queda fuera del orden. Hay **14 contratos vigentes** en `pyproject.toml`
(`[tool.importlinter]`):

1. capas;
2. `domain` limpio (sin `config`, `container`, frameworks ni IO; M1 añade `multiprocessing`, `concurrent`,
   `threading`, `socket`, `io`, `pathlib` y `os`: el reparto en procesos es un adaptador de `infrastructure`);
3. `application` limpia;
4. `config` aislada;
5. `api ↛ config`;
6. `api ↛ infrastructure`;
7. `pymrcd ↛ voracious`;
8. `pymrcd` solo importa `numpy`/`scipy`;
9. `independence` entre cartas;
10. `independence` entre estimadores;
11. `estimators ↛ charts`;
12. `common ↛ charts|estimators`;
13. solo `domain.estimators.mrcd` importa `pymrcd`;
14. `workers ↛ infrastructure|config` (solo vía `container`).

Los contratos 5, 6, 13 y 14 usan `allow_indirect_imports` porque `api|workers → container → config|infrastructure` y
`charts.t2mrcd → estimators.mrcd → pymrcd` son caminos legítimos.

Estructura de dominio: `domain/charts/<carta>/`, `domain/estimators/<estimador>/`, `domain/common/`
(`ControlChart` en `common/chart.py`, `TaskMapper` en `common/parallel.py`). Los contratos `independence` ya
existen y los verifica `import-linter`.

Flujo: `api|workers → container → infrastructure → application → domain`.

## 3. Qué documento abrir para cada carpeta

| Si vas a tocar… | Abre primero |
| --- | --- |
| `src/voracious/domain/estimators/<estimador>/` | `docs/metodos/<método>.md` (p. ej. [`mrcd.md`](docs/metodos/mrcd.md)), [ADR 0004](docs/adr/0004-cartas-y-estimadores-extensibles.md); para MRCD también [ADR 0002](docs/adr/0002-mrcd-sin-aproximaciones.md) |
| `src/voracious/domain/charts/<carta>/` | `docs/metodos/<método>.md` (p. ej. [`t2mrcd.md`](docs/metodos/t2mrcd.md): límites T² son decisiones abiertas), [ADR 0004](docs/adr/0004-cartas-y-estimadores-extensibles.md) |
| `src/voracious/domain/common/` | [ADR 0004](docs/adr/0004-cartas-y-estimadores-extensibles.md) (sin lógica estadística de ningún método), [`docs/arquitectura.md`](docs/arquitectura.md) |
| `src/voracious/application/` | [`docs/arquitectura.md`](docs/arquitectura.md), [ADR 0001](docs/adr/0001-hexagonal.md) |
| `src/voracious/infrastructure/` | [`docs/arquitectura.md`](docs/arquitectura.md) (tabla de puertos), [ADR 0001](docs/adr/0001-hexagonal.md) |
| `src/voracious/api/` | [ADR 0003](docs/adr/0003-api-asincrona.md), [ADR 0005](docs/adr/0005-api-fase-i-fase-ii.md), [`docs/arquitectura.md`](docs/arquitectura.md) |
| `src/voracious/workers/` | [ADR 0003](docs/adr/0003-api-asincrona.md), [ADR 0005](docs/adr/0005-api-fase-i-fase-ii.md) |
| `src/voracious/config.py`, `container.py` | [`docs/arquitectura.md`](docs/arquitectura.md) (variables `VORACIOUS_*`) |
| `tests/golden/`, `tools/r/` | `docs/metodos/<método>.md` del método probado ([índice](docs/metodos/README.md)) |
| `docs/` | [`docs/README.md`](docs/README.md) |
| `.claude/` | este archivo, sección 5 |
| ¿Qué falta? | [`docs/ESTADO.md`](docs/ESTADO.md) |

## 4. Stack y compuerta

Python 3.12, `uv`, FastAPI, Pydantic v2, pydantic-settings, numpy, scipy, structlog (JSON),
pytest + pytest-cov + httpx, ruff, mypy `--strict` sobre `src/`, import-linter. Versiones en `uv.lock`.

Compuerta local (= CI = pre-commit):

```bash
scripts/gate.sh; echo "EXIT=$?"
```

`scripts/gate.sh` corre todas las etapas (`build-pymrcd`, `fma-pymrcd`, ruff, format, mypy, import-linter, pytest
con cobertura ≥ 80 %, `mypy-pymrcd` y `pytest-pymrcd`) aunque falle alguna y deja cada salida en `.gates/<etapa>.log`; el `EXIT` final es 0 solo si todas pasan.
Las dos primeras etapas compilan y comprueban la extensión C de `pymrcd` ([ADR 0006](docs/adr/0006-libreria-pymrcd.md),
enmienda 2026-10-07): `build-pymrcd` (`uv sync --reinstall-package pymrcd`) y `fma-pymrcd`
(`scripts/check_pymrcd_fma.sh`: cero instrucciones FMA en el binario); `mypy-pymrcd` cubre también `setup.py`.
**Hace falta un compilador de C con pthreads** (Xcode Command Line Tools en macOS, `build-essential` en Linux).
Variable de rendimiento `VORACIOUS_MRCD_THREADS` (hilos de `pymrcd`; vacío = no definida; no cambia resultados).
Por clon hay que activar el hook: `git config core.hooksPath .githooks`. Siempre `uv run …` para ejecutar
Python o herramientas sueltas (el `python` del PATH es de pyenv, no el del proyecto).

Reglas: `echo "EXIT=$?"` en la misma línea tras el script. **Nunca** `| tail` ni `| head` (esconden el código
de salida). Una compuerta roja se informa con `archivo:línea` leyendo `.gates/<etapa>.log`; **no** se arregla
desactivando reglas.

Código: tipado estricto, docstrings en español estilo Google, nombres de código en inglés.

## 5. Equipo y flujo de trabajo

Agentes en `.claude/agents/`, comandos en `.claude/commands/`.

| Agente | Rol |
| --- | --- |
| `arquitecto` | Plan del paso en tareas autocontenidas; separa obligatorio de mejoras M1, M2… No escribe código. |
| `desarrollador-python` | Implementa respetando capas y tipado. No commitea. |
| `validador-estadistico` | Solo lectura; vigila la fidelidad de cada método a su referencia, sin sustituciones ni fallbacks. |
| `ejecutor-gates` | Corre la compuerta; VERDE/ROJO con `archivo:línea`. |
| `lt-qa` | Informe final; veredicto `LISTO / LISTO CON DEUDA / REQUIERE CAMBIOS / BLOQUEADO`. |
| `documentador` | Actualiza `docs/` y `ESTADO.md` con el *por qué*. No toca `src/`. |

- `/equipo <paso|tarea>`: arquitecto → **aprobación humana** de mejoras → desarrollador → validador (si toca
  `domain/`) ∥ gates → lt-qa → documentador. Máximo dos vueltas de corrección; a la tercera se para y se
  presenta lo que sigue rojo. **La respuesta de un agente nunca cuenta como aprobación humana.**
- `/commit-seguro`: revisión del diff, búsqueda de secretos, compuerta, Conventional Commits en español
  **sin trailers de coautoría**, y **pregunta antes de cada `git push`**.

Cada paso termina en commit + push a `main` (tras el «sí» del dueño) y **para**.

## 6. Reglas duras

1. Nada en `domain/` importa FastAPI, Pydantic de la API, IO, red ni configuración.
2. Ninguna sustitución, aproximación ni fallback dentro de un método, ni como placeholder. En T²MRCD solo
   MRCD fiel a `rrcov`; otros métodos entran como métodos propios, con su referencia, su
   `docs/metodos/<método>.md`, sus golden tests y su API ([ADR 0004](docs/adr/0004-cartas-y-estimadores-extensibles.md)).
3. Ningún default estadístico sin cita a su referencia (`rrcov` archivo:línea y versión, o artículo) en
   `docs/metodos/<método>.md`.
4. Ningún secreto en el repo; configuración solo por variables `VORACIOUS_*`; `.env.example` sin valores reales.
5. Cada endpoint nuevo lleva test, schema Pydantic y respeta el aislamiento por tenant.
6. Compuerta roja → no hay commit. Se informa con `archivo:línea`, no se desactivan reglas.
7. Nunca `git push --force`, nunca push sin confirmación del dueño, nunca reescribir historia publicada.
   Nunca `git reset --hard`, `git stash`, `git clean`. Nunca commitear `.env` ni `plantilla-agentes/`.
8. Si se duda entre dos caminos que cuesten rehacer, se pregunta; si es reversible, se decide y se anota
   en el informe.
9. Una carta o estimador no importa a otra carta ni a otro estimador; lo común va en `domain/common/`
   (se verifica con los contratos `independence` de `import-linter`, ya vigentes).
