#!/usr/bin/env bash
# Compuerta de calidad de Voracious (= CI = pre-commit).
# Corre todas las etapas aunque falle alguna; cada salida queda en .gates/<etapa>.log.
# Exige Postgres (Paso 4.2): usa VORACIOUS_TEST_DATABASE_URL si está definida (CI: services) y,
# si no, levanta uno desechable con Docker (compose.test.yaml) y lo baja al terminar. Sin URL ni
# Docker la etapa postgres-up sale en rojo y los tests de Postgres fallan: no se saltan.
set -u

cd "$(dirname "$0")/.." || exit 1
mkdir -p .gates

failed=0

run_stage() {
    local stage="$1"
    shift
    "$@" > ".gates/${stage}.log" 2>&1
    local code=$?
    echo "${stage} EXIT=${code}"
    if [ "${code}" -ne 0 ]; then
        failed=1
    fi
}

# Postgres de prueba (compose.test.yaml): credenciales de PRUEBA, no secretas, de un contenedor
# efímero en un puerto aleatorio de 127.0.0.1 que se destruye con su volumen al salir.
pg_project=""

postgres_down() {
    if [ -n "${pg_project}" ]; then
        docker compose -f compose.test.yaml -p "${pg_project}" down -v --remove-orphans \
            > .gates/postgres-down.log 2>&1
        pg_project=""
    fi
}
trap postgres_down EXIT
trap 'exit 130' INT TERM

postgres_up() {
    if [ -n "${VORACIOUS_TEST_DATABASE_URL:-}" ]; then
        echo "Postgres de prueba: VORACIOUS_TEST_DATABASE_URL del entorno"
        return 0
    fi
    if ! command -v docker > /dev/null 2>&1; then
        echo "sin VORACIOUS_TEST_DATABASE_URL ni Docker: la compuerta exige Postgres"
        return 1
    fi
    pg_project="voracious-gate-$$"
    docker compose -f compose.test.yaml -p "${pg_project}" up -d --wait || return 1
    local address
    address=$(docker compose -f compose.test.yaml -p "${pg_project}" port postgres 5432) || return 1
    # Credenciales de prueba, no secretas (compose.test.yaml).
    export VORACIOUS_TEST_DATABASE_URL="postgresql://voracious_test:voracious_test@${address}/voracious_test"
    echo "Postgres de prueba en ${address} (proyecto ${pg_project})"
}

run_stage postgres-up postgres_up

# pymrcd (especificación §3.12.9): la extensión C se recompila antes de todo lo que importa
# pymrcd, y su binario no puede tener instrucciones FMA.
run_stage build-pymrcd uv sync --reinstall-package pymrcd
run_stage fma-pymrcd scripts/check_pymrcd_fma.sh
run_stage ruff uv run ruff check .
run_stage format uv run ruff format --check .
run_stage mypy uv run mypy src
run_stage imports uv run lint-imports
run_stage pytest uv run pytest --cov=voracious --cov-fail-under=80
# pymrcd (ADR 0006): config propia de mypy, pytest y coverage en packages/pymrcd/pyproject.toml.
run_stage mypy-pymrcd uv run mypy --config-file packages/pymrcd/pyproject.toml \
    packages/pymrcd/src packages/pymrcd/setup.py
run_stage pytest-pymrcd env COVERAGE_FILE=.coverage.pymrcd uv run pytest \
    -c packages/pymrcd/pyproject.toml --rootdir packages/pymrcd \
    --cov=pymrcd --cov-config=packages/pymrcd/pyproject.toml --cov-fail-under=90 \
    packages/pymrcd/tests

exit "${failed}"
