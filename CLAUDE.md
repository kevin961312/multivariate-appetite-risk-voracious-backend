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
- **Prohibido sustituirlo** por KMRCD, `sklearn.covariance.MinCovDet`, Ledoit-Wolf ni ninguna aproximación
  «más rápida». KMRCD no conserva las propiedades de MRCD y su probabilidad de señal no es eficiente.
  Si algo es lento se optimiza la **implementación** (vectorización, Numba/Cython, paralelismo entre
  portafolios), nunca el **método**. Ver [ADR 0002](docs/adr/0002-mrcd-sin-aproximaciones.md).
- **La referencia es el código fuente de `rrcov`, no la memoria.** Parámetros de `CovMrcd`: `alpha`, `h`,
  `maxcsteps`, `rho`, `target` (`identity` | `equicorrelation`), `maxcond`. Defaults, estandarización
  inicial, subconjuntos iniciales deterministas, elección de `rho` por número de condición, C-steps y factor
  de consistencia se toman **leyendo `rrcov` (`CovMrcd.R`, `CovControlMrcd`)**, y cada decisión cita
  archivo y línea en [`docs/mrcd/fidelidad.md`](docs/mrcd/fidelidad.md).
- **La fidelidad se demuestra con tests golden**: salidas de `rrcov::CovMrcd` en R sobre conjuntos fijos
  (semilla fija; casos n > p, p > n y contaminado) guardadas como fixtures; el port debe coincidir dentro
  de una tolerancia declarada. En el cascarón: script R, carpeta de fixtures y test `xfail(strict=True)`.
- **Límites de control de T²MRCD**: salen del artículo de T²MRCD (Fase I, observaciones individuales).
  No se inventan: si un valor no está documentado en `docs/`, queda como **decisión abierta**.
- **Sin placeholders estadísticos.** `MRCD.fit` lanza `NotImplementedError` hasta que exista el port; un
  análisis termina en `failed / MRCD_NOT_IMPLEMENTED`. Nada de covarianza clásica «mientras tanto».

## 2. Arquitectura (hexagonal)

Detalle en [`docs/arquitectura.md`](docs/arquitectura.md). Cada pieza distribuida entra después como
**un adaptador nuevo + una variable de configuración**.

| Pieza | Puerto | Adaptador hoy | Adaptador después |
| --- | --- | --- | --- |
| Ejecución de análisis | `JobQueue` | `InlineJobQueue` | `CeleryJobQueue` |
| Persistencia de análisis | `AnalysisRepository` | `InMemoryAnalysisRepository` | `PostgresAnalysisRepository` (TimescaleDB) |
| Datos de entrada | `DatasetStorage` | `LocalDatasetStorage` | `S3DatasetStorage` |
| Tenant | `TenantContext` | cabecera `X-Tenant-ID` | JWT/OIDC |

API asíncrona desde el día uno: `POST /v1/analyses` → `202` + `analysis_id`;
`GET /v1/analyses/{id}` → `queued | running | succeeded | failed`.

### Dirección de dependencias (la verifica `import-linter`)

| Capa | Puede importar | No puede importar |
| --- | --- | --- |
| `voracious.domain` | stdlib, `numpy`, `scipy` | **nada del proyecto**; ni FastAPI, Pydantic, IO, red, config, logging de infraestructura |
| `voracious.application` | `domain` | `api`, `infrastructure`, `workers`, `config`, `container` |
| `voracious.infrastructure` | `application`, `domain` | `api` |
| `voracious.api` | `application`, `domain`, `container` | `infrastructure` (solo a través de `container.py`) |
| `voracious.workers` | `application`, `domain`, `container` | `api` |
| `voracious.container` | todo (es el cableado) | — |
| `voracious.config` | stdlib, `pydantic-settings` | `api`, `application`, `domain`, `infrastructure` |

Flujo: `api → application → domain` e `infrastructure → application → domain`.

## 3. Qué documento abrir para cada carpeta

| Si vas a tocar… | Abre primero |
| --- | --- |
| `src/voracious/domain/mrcd/` | [`docs/mrcd/fidelidad.md`](docs/mrcd/fidelidad.md), [ADR 0002](docs/adr/0002-mrcd-sin-aproximaciones.md) |
| `src/voracious/domain/charts/` | [`docs/mrcd/fidelidad.md`](docs/mrcd/fidelidad.md) (límites T²: decisiones abiertas) |
| `src/voracious/application/` | [`docs/arquitectura.md`](docs/arquitectura.md), [ADR 0001](docs/adr/0001-hexagonal.md) |
| `src/voracious/infrastructure/` | [`docs/arquitectura.md`](docs/arquitectura.md) (tabla de puertos), [ADR 0001](docs/adr/0001-hexagonal.md) |
| `src/voracious/api/` | [ADR 0003](docs/adr/0003-api-asincrona.md), [`docs/arquitectura.md`](docs/arquitectura.md) |
| `src/voracious/workers/` | [ADR 0003](docs/adr/0003-api-asincrona.md) |
| `src/voracious/config.py`, `container.py` | [`docs/arquitectura.md`](docs/arquitectura.md) (variables `VORACIOUS_*`) |
| `tests/golden/`, `tools/r/` | [`docs/mrcd/fidelidad.md`](docs/mrcd/fidelidad.md) |
| `docs/` | [`docs/README.md`](docs/README.md) |
| `.claude/` | este archivo, sección 5 |
| ¿Qué falta? | [`docs/ESTADO.md`](docs/ESTADO.md) |

## 4. Stack y compuerta

Python 3.12, `uv`, FastAPI, Pydantic v2, pydantic-settings, numpy, scipy, structlog (JSON),
pytest + pytest-cov + httpx, ruff, mypy `--strict` sobre `src/`, import-linter. Versiones en `uv.lock`.

Compuerta local (= CI = pre-commit):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src \
  && uv run lint-imports && uv run pytest --cov=voracious --cov-fail-under=80 > .gate.log 2>&1
echo "EXIT=$?"
```

Reglas: salida redirigida a fichero y `echo "EXIT=$?"` en la línea siguiente. **Nunca** `| tail` ni `| head`
(esconden el código de salida). Una compuerta roja se informa con `archivo:línea`; **no** se arregla
desactivando reglas.

Código: tipado estricto, docstrings en español estilo Google, nombres de código en inglés.

## 5. Equipo y flujo de trabajo

Agentes en `.claude/agents/`, comandos en `.claude/commands/`.

| Agente | Rol |
| --- | --- |
| `arquitecto` | Plan del paso en tareas autocontenidas; separa obligatorio de mejoras M1, M2… No escribe código. |
| `desarrollador-python` | Implementa respetando capas y tipado. No commitea. |
| `validador-estadistico` | Solo lectura; vigila fidelidad a `rrcov::CovMrcd`. |
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
2. Ninguna aproximación ni sustituto de MRCD, ni siquiera como placeholder.
3. Ningún default estadístico sin cita a rrcov en `docs/mrcd/fidelidad.md`.
4. Ningún secreto en el repo; configuración solo por variables `VORACIOUS_*`; `.env.example` sin valores reales.
5. Cada endpoint nuevo lleva test, schema Pydantic y respeta el aislamiento por tenant.
6. Compuerta roja → no hay commit. Se informa con `archivo:línea`, no se desactivan reglas.
7. Nunca `git push --force`, nunca push sin confirmación del dueño, nunca reescribir historia publicada.
   Nunca `git reset --hard`, `git stash`, `git clean`. Nunca commitear `.env` ni `plantilla-agentes/`.
8. Si se duda entre dos caminos que cuesten rehacer, se pregunta; si es reversible, se decide y se anota
   en el informe.
