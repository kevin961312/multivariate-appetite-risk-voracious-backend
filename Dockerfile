# Imagen de Voracious (Paso 4). Tres etapas sobre la misma base:
#   builder  compila la extensión C de pymrcd con gcc y comprueba que el binario no tiene FMA
#            (docs/metodos/mrcd-especificacion.md §3.12.9 b, punto 4); la build falla si la hay.
#   gate     builder + grupo dev + repositorio versionado: corre scripts/gate.sh (CI en Linux).
#   runtime  sin compilador, solo el entorno virtual del builder; usuario no root.
# La imagen no se publica en ningún registro (pymrcd es GPL-3.0-or-later): se construye donde se usa.
#
#   docker build --target runtime -t voracious:local .
#   docker build --target gate -t voracious-gate:local . && docker run --rm voracious-gate:local

# Base y uv fijados por versión y digest (M5); Dependabot propone las subidas (.github/dependabot.yml).
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS builder

COPY --from=uv /uv /uvx /bin/

# Python del sistema (nunca descarga otro), bytecode precompilado (la imagen corre en solo lectura),
# copias en lugar de enlaces (la caché de uv es un montaje) y entorno en /app/.venv.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# gcc para compilar pymrcd._qn_ext; binutils (objdump) para la comprobación de FMA.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY packages/pymrcd packages/pymrcd
COPY src src
COPY scripts/check_pymrcd_fma.sh scripts/check_pymrcd_fma.sh

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Imprime la traza (gcc, CFLAGS, build_info()) y falla la build si el binario tiene FMA o le faltan
# las conversiones (float) de qn0.
RUN scripts/check_pymrcd_fma.sh


FROM builder AS gate

# Grupo dev y todo lo versionado que deja pasar .dockerignore (tests, fixtures, configuración).
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

CMD ["scripts/gate.sh"]


FROM python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime

LABEL org.opencontainers.image.title="voracious" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Usuario sin privilegios; /data es suyo (VORACIOUS_STORAGE=local, volumen en docker-compose.yml).
RUN groupadd --system --gid 10001 voracious \
    && useradd --system --uid 10001 --gid 10001 --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin voracious \
    && mkdir -p /data/datasets \
    && chown -R 10001:10001 /data

COPY --from=builder /app/.venv /app/.venv

WORKDIR /app
USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; r = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4); sys.exit(0 if r.status == 200 else 1)"]

# Un solo worker de uvicorn: la cola de trabajos (InlineJobQueue) y los repositorios en memoria viven
# en el proceso; con varios workers cada uno tendría su propio estado y un GET podría no ver el
# trabajo que creó el POST. Se escala cuando lleguen Postgres y la cola distribuida.
CMD ["uvicorn", "voracious.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
