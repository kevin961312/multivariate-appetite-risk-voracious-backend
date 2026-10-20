#!/usr/bin/env bash
# Emite un token de la demo con la llave de firma cifrada (seguridad mínima, ADR 0012).
#
#   scripts/issue_token.sh --via uv|docker --tenant T --roles r1,r2 --subject S [--ttl 8h]
#   T=$(scripts/issue_token.sh --via docker --tenant demo --roles analyst --subject kevin --ttl 1h)
#
# Descifra kid y jwt_private_key de $DEPLOY_DIR/jwt-signing.enc.yaml con sops y pasa la llave por
# una tubería a «python -m voracious.cli issue-token --private-key-file -»: nunca toca el disco en
# claro. Por la salida estándar sale SOLO el token; el resumen (sin token) va por la de error.
#   --via docker  en el servidor (donde viven sops y la llave age): docker run --rm -i
#                 --network none --read-only con la imagen de la demo, auth.env y el JWKS montado
#                 en solo lectura.
#   --via uv      donde haya uv (además de sops y la llave age): uv run, con iss y aud de
#                 $DEPLOY_DIR/auth.env y el JWKS local para comprobar el token emitido.
# Variables: DEPLOY_DIR (deploy/demo), SOPS_AGE_KEY_FILE, VORACIOUS_IMAGE (voracious:local).
# Códigos de salida: los de la CLI (0 bien, 1 entrada no válida, 2 configuración) y 2 si falta
# una precondición. Nunca usa «set -x».
set -euo pipefail
umask 077

die() {
    local code="$1"
    shift
    printf 'issue_token.sh: %s\n' "$*" >&2
    exit "${code}"
}

repo_root=$(cd "$(dirname "$0")/.." && pwd -P)
via=""
tenant=""
roles=""
subject=""
ttl="8h"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --via | --tenant | --roles | --subject | --ttl)
            [ "$#" -ge 2 ] || die 2 "$1 necesita un valor"
            case "$1" in
                --via) via="$2" ;;
                --tenant) tenant="$2" ;;
                --roles) roles="$2" ;;
                --subject) subject="$2" ;;
                --ttl) ttl="$2" ;;
            esac
            shift 2
            ;;
        -h | --help)
            sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) die 2 "argumento desconocido: $1 (usa --help)" ;;
    esac
done
case "${via}" in
    uv | docker) ;;
    *) die 2 "--via debe ser uv o docker" ;;
esac
if [ -z "${tenant}" ] || [ -z "${roles}" ] || [ -z "${subject}" ]; then
    die 2 "hacen falta --tenant, --roles y --subject"
fi

deploy_dir="${DEPLOY_DIR:-deploy/demo}"
case "${deploy_dir}" in
    /*) ;;
    *) deploy_dir="${repo_root}/${deploy_dir}" ;;
esac
signing="${deploy_dir}/jwt-signing.enc.yaml"
auth_env="${deploy_dir}/auth.env"
jwks="${deploy_dir}/jwks.json"
for file in "${signing}" "${auth_env}" "${jwks}"; do
    [ -f "${file}" ] || die 2 "falta ${file}"
done
command -v sops > /dev/null 2>&1 || die 2 "falta sops"
command -v "${via}" > /dev/null 2>&1 || die 2 "falta ${via}"

env_value() {
    # env_value CLAVE: último valor de CLAVE en auth.env (configuración pública, no secreta).
    sed -n "s/^[[:space:]]*$1=\(.*\)$/\1/p" "${auth_env}" | tail -n 1
}

kid=$(sops --disable-version-check decrypt --extract '["kid"]' "${signing}") ||
    die 2 "sops no pudo descifrar el kid de ${signing}"
[ -n "${kid}" ] || die 2 "el kid de ${signing} está vacío"

private_key() {
    sops --disable-version-check decrypt --extract '["jwt_private_key"]' "${signing}"
}

cli_args=(issue-token --tenant "${tenant}" --roles "${roles}" --subject "${subject}"
    --kid "${kid}" --ttl "${ttl}" --private-key-file -)

if [ "${via}" = "uv" ]; then
    issuer=$(env_value VORACIOUS_JWT_ISSUER)
    audience=$(env_value VORACIOUS_JWT_AUDIENCE)
    private_key | (
        cd "${repo_root}"
        env VORACIOUS_JWT_ISSUER="${issuer}" VORACIOUS_JWT_AUDIENCE="${audience}" \
            VORACIOUS_JWT_JWKS_FILE="${jwks}" \
            uv run --quiet python -m voracious.cli "${cli_args[@]}"
    )
else
    private_key | docker run --rm -i --network none --read-only \
        --env-file "${auth_env}" \
        -v "${jwks}:/etc/voracious/jwks.json:ro" \
        "${VORACIOUS_IMAGE:-voracious:local}" \
        python -m voracious.cli "${cli_args[@]}"
fi
