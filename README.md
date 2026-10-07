# Voracious — backend

Backend de una plataforma SaaS para monitorear el **apetito de riesgo multivariado** de portafolios
financieros con la carta de control robusta **T²MRCD** (Minimum Regularized Covariance Determinant).

El núcleo es un port propio a Python de `rrcov::CovMrcd()` (Boudt, Rousseeuw, Vanduffel y Verdonck, 2020),
sin aproximaciones ni sustitutos dentro de T²MRCD (ver [ADR 0002](docs/adr/0002-mrcd-sin-aproximaciones.md)).

Las cartas y estimadores son **extensibles e independientes**: otra carta entra como método propio, con su
referencia, su documento, sus golden tests y su API, sin tocar las demás
([ADR 0004](docs/adr/0004-cartas-y-estimadores-extensibles.md)). La API se organiza por carta, con Fase I
(entrenar) y Fase II (monitorear), ambas asíncronas ([ADR 0005](docs/adr/0005-api-fase-i-fase-ii.md)).

## Estado

**Cascarón.** Esqueleto, cableado y compuerta de calidad listos (Paso 1); ni el estimador MRCD ni la API de cartas existen todavía.
El avance por paso está en [`docs/ESTADO.md`](docs/ESTADO.md).

## Cómo levantarlo

```bash
uv python install 3.12                    # Python del proyecto
uv sync                                   # instala dependencias fijadas en uv.lock
git config core.hooksPath .githooks       # una vez por clon: activa el pre-commit (corre la compuerta)
uv run uvicorn voracious.api.app:create_app --factory --reload
```

Usa siempre `uv run`: el `python` del PATH (p. ej. pyenv) no es el del proyecto.

Configuración: solo variables `VORACIOUS_*`; plantilla en [`.env.example`](.env.example). La aplicación **no**
lee `.env` por sí misma (local, CI y producción se configuran igual); cárgalo en el entorno, p. ej.
`uv run --env-file .env uvicorn voracious.api.app:create_app --factory`.

Compuerta de calidad (la misma que CI y el pre-commit; cada etapa deja su log en `.gates/<etapa>.log`):

```bash
scripts/gate.sh; echo "EXIT=$?"
```

> Docker se completa en el Paso 4.

## Documentación

- [Arquitectura](docs/arquitectura.md)
- [Decisiones (ADR)](docs/adr/)
- [Documentos de método](docs/metodos/README.md): [MRCD](docs/metodos/mrcd.md) y [T²MRCD](docs/metodos/t2mrcd.md)
- [Reglas para el equipo y agentes](CLAUDE.md)
