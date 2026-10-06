# Voracious — backend

Backend de una plataforma SaaS para monitorear el **apetito de riesgo multivariado** de portafolios
financieros con la carta de control robusta **T²MRCD** (Minimum Regularized Covariance Determinant).

El núcleo es un port propio a Python de `rrcov::CovMrcd()` (Boudt, Rousseeuw, Vanduffel y Verdonck, 2020),
sin aproximaciones ni sustitutos (ver [ADR 0002](docs/adr/0002-mrcd-sin-aproximaciones.md)).

## Estado

**Cascarón.** Estructura, cableado y compuertas de calidad; el estimador MRCD todavía no está implementado.
El avance por paso está en [`docs/ESTADO.md`](docs/ESTADO.md).

## Cómo levantarlo

> Se completa en el Paso 1 (entorno con `uv`) y el Paso 4 (Docker).

```bash
uv sync                                   # instala dependencias fijadas en uv.lock
uv run uvicorn voracious.api.app:create_app --factory --reload
```

Compuerta de calidad (la misma que CI y el pre-commit):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src \
  && uv run lint-imports && uv run pytest --cov=voracious --cov-fail-under=80
```

## Documentación

- [Arquitectura](docs/arquitectura.md)
- [Decisiones (ADR)](docs/adr/)
- [Fidelidad del port a rrcov](docs/mrcd/fidelidad.md)
- [Reglas para el equipo y agentes](CLAUDE.md)
