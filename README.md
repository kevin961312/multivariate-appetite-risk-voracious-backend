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

**Pasos 0–4 hechos (Docker, CI y Postgres) y seguridad mínima hecha (JWT con roles y secretos cifrados; pendiente de commit); siguiente: redespliegue de la demo con secretos cifrados y JWT.** Existen el port de MRCD (`pymrcd`, con
`Qn` y los pares de OGK en C), la carta T²MRCD (Fase I con límites por bootstrap, Fase II y ciclo de
vida con recalibración) y la API por pasos encadenables. Los repositorios
persisten en Postgres (con `VORACIOUS_REPOSITORY=postgres`; por defecto siguen en memoria), la cola vive en el
proceso (reiniciar cierra los trabajos en curso como `JOB_INTERRUPTED`) y la Fase I termina en `failed / T2MRCD_DECISION_PENDING` si un campo decisivo
queda pendiente. El avance por paso y la deuda están en [`docs/ESTADO.md`](docs/ESTADO.md).

## Cómo levantarlo

```bash
uv python install 3.12                    # Python del proyecto
uv sync                                   # instala dependencias fijadas en uv.lock
git config core.hooksPath .githooks       # una vez por clon: activa el pre-commit (corre la compuerta)
uv run uvicorn voracious.api.app:create_app --factory --reload
```

Usa siempre `uv run`: el `python` del PATH (p. ej. pyenv) no es el del proyecto.

La API **no arranca sin autenticación** (`VORACIOUS_JWT_JWKS_FILE`, `_ISSUER` y `_AUDIENCE`): para desarrollo, genera una
llave de prueba fuera del repo con `uv run python -m voracious.cli jwt-keygen --kid dev --jwks /tmp/dev/jwks.json > /tmp/dev/dev.pem`
(la privada sale por la salida estándar), apunta las tres variables a ese JWKS y emite tokens con `issue-token
--private-key-file /tmp/dev/dev.pem`. Los
tests usan una llave de sesión (`tests/support/auth.py`).

Configuración: solo variables `VORACIOUS_*`; plantilla en [`.env.example`](.env.example). La aplicación **no**
lee `.env` por sí misma (local, CI y producción se configuran igual); cárgalo en el entorno, p. ej.
`uv run --env-file .env uvicorn voracious.api.app:create_app --factory`.

Compuerta de calidad (la misma que CI y el pre-commit; cada etapa deja su log en `.gates/<etapa>.log`):

```bash
scripts/gate.sh; echo "EXIT=$?"
```

### Con Docker y Postgres

Compose levanta `postgres` (17), `migrate` (aplica las migraciones y termina), `api` y `backup` (`pg_dump`
diario, 7 días). **Los secretos no van en un `.env`**: están cifrados con SOPS + age (`deploy/demo/*.enc.yaml`) y
`scripts/deploy.sh` los descifra en el servidor y los monta como Compose secrets (`*_FILE`). La API **exige un JWT**
(`Authorization: Bearer`) y no arranca sin su JWKS, emisor y audiencia ([ADR 0012](docs/adr/0012-seguridad-minima-sops-jwt.md)).
Procedimiento completo, rotaciones y recuperación en [`docs/despliegue.md`](docs/despliegue.md):

```bash
scripts/deploy.sh                         # descifra, valida, construye, levanta, espera a /ready y verifica
docker compose ps                         # migrate termina «exited (0)»; el resto, healthy
docker compose run --rm migrate           # opcional: aplicar migraciones a mano (python -m voracious.cli migrate)
```

**Nunca `docker compose down -v`** (borra la base). La base de datos **no publica ningún puerto**.

**Emitir un token** (en el servidor, donde viven sops y la llave age; roles `analyst`, `approver`, `admin`; el tenant
va en el token, ya no hay cabecera de tenant):

```bash
scripts/issue_token.sh --via docker --tenant demo --roles analyst --subject kevin --ttl 1h
```

Demo con datos **simulados** (150 × 8 con fechas desde 2026-01-01; Fase I, 20 puntuaciones y una anotación). Lee el
token de `VORACIOUS_API_TOKEN` (o `--token-file PATH|-`), nunca de la línea de órdenes:

```bash
VORACIOUS_API_TOKEN=<token> uv run python scripts/demo_seed.py --base-url http://127.0.0.1:8000
```

La API escucha solo en `127.0.0.1:8000` del anfitrión. Para usarla desde otra máquina, túnel SSH:
`ssh -L 8000:127.0.0.1:8000 kevin@<servidor>`. La imagen se construye donde se usa y no se publica
(`pymrcd` es GPL-3.0-or-later; [ADR 0010](docs/adr/0010-empaquetado-docker-y-ci.md)).

La compuerta **exige Postgres**: usa `VORACIOUS_TEST_DATABASE_URL` si está definida y, si no, levanta uno desechable
con Docker (`compose.test.yaml`); sin ninguno, sale en rojo. También corre en Linux dentro de un contenedor, al que
hay que darle la URL de un Postgres de prueba alcanzable:

```bash
docker build --target gate -t voracious:gate . \
  && docker run --rm -e VORACIOUS_TEST_DATABASE_URL=postgresql://… voracious:gate
```

Con `VORACIOUS_REPOSITORY=postgres` hace falta `VORACIOUS_STORAGE=local`, y las migraciones se aplican con
`uv run python -m voracious.cli migrate`.

## Documentación

- [Arquitectura](docs/arquitectura.md)
- [Decisiones (ADR)](docs/adr/) (persistencia: [ADR 0011](docs/adr/0011-persistencia-en-postgres.md); seguridad: [ADR 0012](docs/adr/0012-seguridad-minima-sops-jwt.md))
- [Despliegue y operación](docs/despliegue.md)
- [Documentos de método](docs/metodos/README.md): [MRCD](docs/metodos/mrcd.md) y [T²MRCD](docs/metodos/t2mrcd.md)
- [Reglas para el equipo y agentes](CLAUDE.md)
