# Estado del proyecto

Última actualización: 2026-10-06 (Paso 0).

**Siguiente hito:** Paso 1, esqueleto del proyecto y compuerta.

| Paso | Descripción | Estado |
| --- | --- | --- |
| 0 | Fundaciones del repo: docs, ADR, `CLAUDE.md`, equipo de agentes | **hecho** |
| 1 | Esqueleto (`pyproject`, uv, ruff, mypy, pytest, import-linter, `config`, app factory, `/health`, `/ready`, structlog, pre-commit) | pendiente |
| 2 | Dominio y puertos: `MRCDParams`, `MRCD.fit` → `NotImplementedError`, `MRCDResult`, T², puertos, casos de uso, `fidelidad.md` | pendiente |
| 3 | Adaptadores mínimos, `container.py`, tenant, `POST`/`GET /v1/analyses`, errores uniformes | pendiente |
| 4 | Dockerfile, docker-compose (perfiles distribuidos comentados), CI | pendiente |
| 5 | Andamiaje golden: `generate_golden.R`, fixtures, test `xfail(strict=True)` | pendiente |

## Decisiones abiertas

- Límites de control T²MRCD (Fase I): fuente exacta en el artículo. Ver [`mrcd/fidelidad.md`](mrcd/fidelidad.md).

## Notas del entorno

- R y Rscript disponibles en la máquina de desarrollo; falta confirmar que `rrcov` está instalado (Paso 2/5).
