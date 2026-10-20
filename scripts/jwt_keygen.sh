#!/usr/bin/env bash
# Genera una llave de firma JWT nueva para la demo (seguridad mínima, ADR 0012, D12).
#
#   scripts/jwt_keygen.sh --via docker KID   # en el servidor, p. ej. ... --via docker demo-2026-10
#   scripts/jwt_keygen.sh --via uv KID       # donde haya uv (además de sops)
#
# Añade la parte pública a $DEPLOY_DIR/jwks.json (falla si el KID ya existe) y guarda la privada
# CIFRADA con sops en $DEPLOY_DIR/jwt-signing.enc.yaml ({kid, jwt_private_key}; receptores de
# .sops.yaml). La llave en claro solo pasa por una tubería (jwt-keygen → sops): nunca toca el
# disco. Todo se prepara en un temporal y solo si todo fue bien se mueven los dos ficheros a su
# sitio; si algo falla no cambia nada. Después: commit de ambos con /commit-seguro y despliegue.
# Rotación: el JWKS conserva los kid anteriores (los tokens viejos siguen valiendo hasta que se
# quiten); jwt-signing.enc.yaml pasa a tener solo la llave nueva.
#   --via docker  la CLI de la imagen de la demo: docker run --rm --network none --read-only con
#                 el usuario actual y solo el temporal montado (el servidor no necesita uv).
#   --via uv      la CLI del repositorio con uv run.
# Variables: DEPLOY_DIR (deploy/demo), SOPS_CONFIG (.sops.yaml de la raíz del repositorio),
# VORACIOUS_IMAGE (voracious:local, con --via docker).
# Códigos de salida: 0 bien; 1 la generación o el cifrado fallaron; 2 precondición no cumplida.
set -euo pipefail
umask 077

die() {
    local code="$1"
    shift
    printf 'jwt_keygen.sh: %s\n' "$*" >&2
    exit "${code}"
}

repo_root=$(cd "$(dirname "$0")/.." && pwd -P)
case "${1:-}" in
    -h | --help | "")
        sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
        [ -n "${1:-}" ] && exit 0
        exit 2
        ;;
    --via) ;;
    *) die 2 "falta --via uv|docker (usa --help)" ;;
esac
via="${2:-}"
case "${via}" in
    uv | docker) ;;
    *) die 2 "--via debe ser uv o docker" ;;
esac
kid="${3:-}"
[ -n "${kid}" ] || die 2 "falta el KID"
[ -z "${4:-}" ] || die 2 "argumento de más: $4"

deploy_dir="${DEPLOY_DIR:-deploy/demo}"
case "${deploy_dir}" in
    /*) ;;
    *) deploy_dir="${repo_root}/${deploy_dir}" ;;
esac
sops_config="${SOPS_CONFIG:-${repo_root}/.sops.yaml}"
[ -f "${sops_config}" ] || die 2 "falta ${sops_config} (reglas y receptores age de sops)"
command -v sops > /dev/null 2>&1 || die 2 "falta sops"
command -v "${via}" > /dev/null 2>&1 || die 2 "falta ${via}"
mkdir -p "${deploy_dir}"
deploy_dir=$(cd "${deploy_dir}" && pwd -P)
jwks="${deploy_dir}/jwks.json"
signing="${deploy_dir}/jwt-signing.enc.yaml"

work=$(mktemp -d "${TMPDIR:-/tmp}/voracious-keygen.XXXXXX")
cleanup() {
    rm -rf "${work}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

if [ -f "${jwks}" ]; then
    cp "${jwks}" "${work}/jwks.json"
fi

wrap_yaml() {
    # Envuelve el PEM de la entrada estándar en {kid, jwt_private_key} (bloque literal de YAML).
    printf 'kid: "%s"\njwt_private_key: |\n' "${kid}"
    sed 's/^/    /'
}

generate_key() {
    # El PEM sale por la salida estándar de la CLI; el JWKS ampliado se escribe en el temporal.
    if [ "${via}" = "uv" ]; then
        (
            cd "${repo_root}"
            uv run --quiet python -m voracious.cli jwt-keygen --kid "${kid}" --jwks "${work}/jwks.json"
        )
    else
        docker run --rm --network none --read-only --user "$(id -u):$(id -g)" \
            -v "${work}:/out" "${VORACIOUS_IMAGE:-voracious:local}" \
            python -m voracious.cli jwt-keygen --kid "${kid}" --jwks /out/jwks.json
    fi
}

if ! generate_key | wrap_yaml | sops --disable-version-check --config "${sops_config}" encrypt \
    --filename-override "${signing}" --input-type yaml --output-type yaml /dev/stdin \
    > "${work}/jwt-signing.enc.yaml"; then
    die 1 "no se generó la llave (nada ha cambiado en ${deploy_dir})"
fi
grep -q "\"kid\": \"${kid}\"" "${work}/jwks.json" || die 1 "el JWKS nuevo no tiene el kid ${kid}"
grep -q '^sops:' "${work}/jwt-signing.enc.yaml" || die 1 "sops no produjo un fichero cifrado"

chmod 0644 "${work}/jwks.json" "${work}/jwt-signing.enc.yaml"
mv -f "${work}/jwks.json" "${jwks}"
mv -f "${work}/jwt-signing.enc.yaml" "${signing}"
printf 'jwt_keygen.sh: kid %s añadido a %s y llave cifrada en %s\n' "${kid}" "${jwks}" "${signing}"
