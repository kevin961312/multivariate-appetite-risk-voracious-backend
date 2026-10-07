#!/usr/bin/env bash
# Compuerta de calidad de Voracious (= CI = pre-commit).
# Corre todas las etapas aunque falle alguna; cada salida queda en .gates/<etapa>.log.
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
