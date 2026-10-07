# Estado del proyecto

Última actualización: 2026-10-06 (cierre del Paso 1; ajuste por ADR 0004 y 0005).

**Siguiente hito:** terminar el port de MRCD (bloque 2) y luego el Paso 2, dominio extensible y puertos.

| Paso | Descripción | Estado |
| --- | --- | --- |
| 0 | Fundaciones del repo: docs, ADR, `CLAUDE.md`, equipo de agentes | **hecho** |
| 1 | Esqueleto: `pyproject`/uv, ruff, mypy, pytest, import-linter (6 contratos), `config`, app factory, `/health`, `/ready`, structlog, `scripts/gate.sh` y hook pre-commit | **hecho** |
| 2 | Dominio extensible y puertos (ver abajo) | pendiente |
| 3 | Adaptadores mínimos, `container.py`, tenant, rutas por carta Fase I/II, errores uniformes | pendiente |
| 4 | Dockerfile, docker-compose (perfiles distribuidos comentados), CI | pendiente |
| 5 | Andamiaje golden **por método**: `generate_golden.R`, fixtures, tests `xfail(strict=True)` | pendiente |

## Ajuste de plan aprobado: ADR 0004 y 0005

El dueño aprobó que las cartas y estimadores sean extensibles e independientes
([ADR 0004](adr/0004-cartas-y-estimadores-extensibles.md)) y que la API sea por carta con Fase I y Fase II,
ambas asíncronas ([ADR 0005](adr/0005-api-fase-i-fase-ii.md)). Por eso el plan original de los Pasos 2, 3 y 5
(un único `/v1/analyses`) queda redefinido así:

- **Paso 2:** `domain/estimators/mrcd/` (`MRCDParams`, `MRCD.fit` → `NotImplementedError`, `MRCDResult`),
  `domain/charts/t2mrcd/`, `domain/common/`, el `Protocol` de carta (`fit_phase1`/`score_phase2`), los
  contratos `independence` de import-linter (cartas entre sí; estimadores entre sí) más `forbidden`
  `estimators ↛ charts` y `common ↛ charts|estimators`, los puertos de persistencia de modelos y de monitoreos,
  los casos de uso `TrainModel`, `GetModel`, `MonitorObservations`, `GetMonitoring`, y `docs/metodos/`
  completado con lo que se pueda citar de `rrcov`.
- **Paso 3:** rutas `/v1/charts/t2mrcd/models…` y `…/monitorings…`; test de que la Fase I termina en
  `failed / MRCD_NOT_IMPLEMENTED`; aislamiento por tenant.
- **Paso 5:** golden tests por método (MRCD contra `rrcov`; T²MRCD contra su propia referencia).

## Port de MRCD a `pymrcd` (antes del Paso 2) — en curso

El dueño decidió portar primero `rrcov::CovMrcd` **1.7-7 oficial de CRAN** como librería propia
`packages/pymrcd` (GPL-3, uso privado, solo numpy/scipy); ver [ADR 0006](adr/0006-libreria-pymrcd.md) y
[`metodos/mrcd-especificacion.md`](metodos/mrcd-especificacion.md). El rrcov modificado del dueño (ogkU.c con
MAD, hecho para pruebas en paralelo) no se porta.

| Fase | Estado |
| --- | --- |
| Especificación línea a línea (analista-port) | hecha; pendiente corregir supuestos que el bloque 1 refutó (FMA, eigen, alineación BLAS) |
| Oráculo R aislado, simulación C1–C10 + variantes, intermedios y primitivas (ingeniero-r) | hecho; fixtures reducidos versionados (~50 MB), el resto se regenera con `tools/r/` |
| Workspace uv, esqueleto y compuerta de 7 etapas | hecho |
| Bloque 1: primitivas de R, Qn, doScale, `.MCDcons`, `uniroot` | hecho, bit a bit con R salvo `eigen` (1–4 ulp, signo) y un punto de borde de `.MCDcons` |
| Bloque 2: OGK, r6pack, selección de ρ, C-steps, final, extremo a extremo | pendiente |

Decisiones pendientes del dueño: aceptar `eigen` con las tolerancias declaradas (tipo B) y portar
`qchisq`/`pgamma` de nmath para `.MCDcons`. Decisión abierta: versión canónica determinista de la
inicialización para p > n (opción `init="canonical"`, con piloto y Monte Carlo antes de un ADR).

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

- Límites de control T²MRCD (Fase I), regla de señal de Fase II y cita del artículo:
  ver [`metodos/t2mrcd.md`](metodos/t2mrcd.md).
- Versión de `rrcov` y defaults de `CovMrcd`: ver [`metodos/mrcd.md`](metodos/mrcd.md).
- Código de HTTP de `/ready` cuando un check falle (hoy `checks` va vacío): ver
  [`arquitectura.md`](arquitectura.md).
- Nombres definitivos de los puertos de persistencia (`ModelRepository`/`MonitoringRepository` son
  orientativos): se fijan en el Paso 2.

## Deuda técnica

- Contratos `workers ↛ infrastructure` y `workers ↛ config` (Paso 3, cuando `workers` tenga contenido).
- Decidir si hace falta `infrastructure ↛ config` (Paso 3).
- `StarletteDeprecationWarning` por el cambio `httpx` → `httpx2` (Paso 4).
- **Riesgo de diseño:** el `Protocol` de carta puede chocar con los contratos `independence` según dónde viva.
  El arquitecto del Paso 2 decide si va en `domain/charts/__init__.py` o en `domain/common/`.

## Notas del entorno

- R y Rscript disponibles en la máquina de desarrollo; falta confirmar que `rrcov` está instalado (Paso 2/5).
- Siempre `uv run …` (el `python` del PATH es de pyenv y no es el del proyecto).
