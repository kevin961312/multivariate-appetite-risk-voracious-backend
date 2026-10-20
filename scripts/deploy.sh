#!/usr/bin/env bash
# Despliegue de la demo con secretos SOPS + age y Compose secrets (seguridad mínima, ADR 0012) y,
# desde el paso E, la puerta del borde público (Caddy en el 443, perfil «public» de Compose).
#
#   scripts/deploy.sh                      # descifra, valida, despliega y verifica
#   scripts/deploy.sh --decrypt-only DIR   # solo descifra los secretos en DIR (pruebas)
#
# Modo público si existe DEPLOY_DIR/proxy.env (PROXY_PUBLIC_HOST y PROXY_TLS_MODE=acme|internal);
# si no, privado. En los dos modos el proxy se para antes de tocar la API, y solo en el público se
# arranca, después de comprobar que ninguna ruta de negocio responde sin token
# (scripts/check_auth_surface.py dentro del contenedor api). Si algo falla con el proxy ya
# arrancado, se vuelve a parar antes de salir: el 443 nunca queda abierto tras una verificación
# fallida. COMPOSE_PROFILES no se admite (se ignora el del entorno y se rechaza el de .env).
#
# Variables (todas opcionales):
#   DEPLOY_DIR          configuración versionada de la demo (por defecto deploy/demo):
#                       secrets.enc.yaml (cifrado), jwks.json, auth.env, api.env y, para el
#                       modo público, proxy.env (públicos).
#   DEPLOY_SECRETS_DIR  secretos descifrados, FUERA del repo (por defecto
#                       ${XDG_STATE_HOME:-$HOME/.local/state}/voracious/demo/secrets): directorio
#                       0700 con ficheros 0444 que Compose monta en /run/secrets (P1 = A: se quedan
#                       ahí porque un reinicio del contenedor o del servidor los vuelve a leer).
#   SOPS_AGE_KEY_FILE   llave age privada (por defecto ~/.config/sops/age/keys.txt; modo 600).
#   DEPLOY_TIMEOUT      segundos máximos de espera a /ready y, aparte, al /health del proxy
#                       (por defecto 300; la primera emisión del certificado cabe de sobra).
#   DEPLOY_API_URL      URL local de la API (por defecto http://127.0.0.1:8000).
#   DEPLOY_ENV_FILE     .env que se revisa antes de desplegar (por defecto el de la raíz).
#
# Nunca imprime un valor secreto ni usa «set -x». Los temporales viven dentro de
# DEPLOY_SECRETS_DIR y se borran al salir (trap). Compatible con bash 3.2 (macOS) y 5 (Ubuntu).
# Códigos de salida: 0 bien; 1 el despliegue o una verificación falló; 2 precondición no cumplida.
set -euo pipefail
umask 077

SECRET_KEYS="postgres_password database_url"
MIN_SOPS_MAJOR=3
MIN_SOPS_MINOR=9

die() {
    # die CÓDIGO MENSAJE: mensaje por stderr (nunca con valores secretos) y salida.
    local code="$1"
    shift
    printf 'deploy.sh: %s\n' "$*" >&2
    exit "${code}"
}

info() {
    printf 'deploy.sh: %s\n' "$*"
}

usage() {
    # La cabecera de comentarios del script (de la línea 2 a la primera que no es comentario).
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

repo_root=$(cd "$(dirname "$0")/.." && pwd -P)
# El perfil «public» solo lo activa la puerta de este script, nunca el entorno de quien lo lanza
# (tampoco por un fichero de entorno de Compose que lo defina).
unset COMPOSE_PROFILES COMPOSE_ENV_FILES

decrypt_only=""
case "${1:-}" in
    "") ;;
    --decrypt-only)
        [ -n "${2:-}" ] || die 2 "--decrypt-only necesita un directorio"
        decrypt_only="$2"
        [ -z "${3:-}" ] || die 2 "argumento de más: $3"
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    *) die 2 "argumento desconocido: $1 (usa --help)" ;;
esac

deploy_dir="${DEPLOY_DIR:-deploy/demo}"
case "${deploy_dir}" in
    /*) ;;
    *) deploy_dir="${repo_root}/${deploy_dir}" ;;
esac
[ -d "${deploy_dir}" ] || die 2 "no existe DEPLOY_DIR (${deploy_dir})"
deploy_dir=$(cd "${deploy_dir}" && pwd -P)

if [ -n "${decrypt_only}" ]; then
    secrets_dir="${decrypt_only}"
else
    secrets_dir="${DEPLOY_SECRETS_DIR:-${XDG_STATE_HOME:-${HOME}/.local/state}/voracious/demo/secrets}"
fi
export SOPS_AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-${XDG_CONFIG_HOME:-${HOME}/.config}/sops/age/keys.txt}"

# --- precondiciones ---------------------------------------------------------------------------

require_command() {
    command -v "$1" > /dev/null 2>&1 || die 2 "falta la orden '$1' ($2)"
}

check_sops_version() {
    local version major minor
    version=$(sops --disable-version-check --version 2> /dev/null | sed -n 's/^sops \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1)
    [ -n "${version}" ] || die 2 "no se pudo leer la versión de sops"
    major=${version%%.*}
    minor=${version#*.}
    if [ "${major}" -lt "${MIN_SOPS_MAJOR}" ] ||
        { [ "${major}" -eq "${MIN_SOPS_MAJOR}" ] && [ "${minor}" -lt "${MIN_SOPS_MINOR}" ]; }; then
        die 2 "sops ${version} es antiguo: hace falta >= ${MIN_SOPS_MAJOR}.${MIN_SOPS_MINOR}"
    fi
}

check_key_file() {
    # Modo 600 o más estricto: ningún permiso para el grupo ni para otros (find -perm -NNN es POSIX).
    local open
    [ -f "${SOPS_AGE_KEY_FILE}" ] || die 2 "no existe la llave age (SOPS_AGE_KEY_FILE=${SOPS_AGE_KEY_FILE})"
    open=$(find "${SOPS_AGE_KEY_FILE}" -prune \( -perm -040 -o -perm -020 -o -perm -010 \
        -o -perm -004 -o -perm -002 -o -perm -001 \) -print)
    [ -z "${open}" ] || die 2 "la llave age debe tener modo 600 o más estricto: chmod 600 ${SOPS_AGE_KEY_FILE}"
}

check_env_file() {
    # El .env del servidor no puede traer secretos (D10): solo se informa el NOMBRE de la variable.
    local env_file="${DEPLOY_ENV_FILE:-${repo_root}/.env}" names
    [ -f "${env_file}" ] || return 0
    names=$(grep -E '^[[:space:]]*(export[[:space:]]+)?(POSTGRES_PASSWORD|VORACIOUS_DATABASE_URL|PGPASSWORD|[A-Za-z0-9_]*PRIVATE[A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*[^[:space:]#]' "${env_file}" |
        sed -E 's/^[[:space:]]*(export[[:space:]]+)?([A-Za-z0-9_]+).*/\2/' | sort -u | tr '\n' ' ' || true)
    [ -z "${names}" ] || die 2 ".env trae secretos (${names% }): quítalos; ahora van cifrados en ${deploy_dir}/secrets.enc.yaml"
}

check_compose_profiles() {
    # Compose lee COMPOSE_PROFILES del .env del proyecto: con «public» arrancaría el proxy en el
    # primer «up», antes de la puerta. Se revisan el .env revisado (DEPLOY_ENV_FILE) y el del proyecto.
    local file
    for file in "${DEPLOY_ENV_FILE:-${repo_root}/.env}" "${repo_root}/.env"; do
        [ -f "${file}" ] || continue
        if grep -Eq '^[[:space:]]*(export[[:space:]]+)?COMPOSE_PROFILES[[:space:]]*=' "${file}"; then
            die 2 "${file} define COMPOSE_PROFILES: quítalo (el perfil public solo lo activa deploy.sh tras su puerta)"
        fi
    done
}

proxy_env_value() {
    # proxy_env_value CLAVE: último valor de CLAVE en proxy.env (configuración pública, no secreta).
    sed -n "s/^[[:space:]]*$1=\(.*\)$/\1/p" "${proxy_env}" | tail -n 1
}

check_proxy_env() {
    # Modo público si existe proxy.env; entonces el host y el modo de TLS tienen que ser válidos (el
    # host entra en el Caddyfile: solo un nombre DNS en minúsculas, sin comillas ni espacios).
    [ -f "${proxy_env}" ] || return 0
    public_host=$(proxy_env_value PROXY_PUBLIC_HOST)
    tls_mode=$(proxy_env_value PROXY_TLS_MODE)
    [ -n "${public_host}" ] || die 2 "${proxy_env} no define PROXY_PUBLIC_HOST (sin host no hay modo público)"
    if [ "${#public_host}" -gt 253 ] ||
        ! printf '%s\n' "${public_host}" |
        grep -Eqx '[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+'; then
        die 2 "PROXY_PUBLIC_HOST de ${proxy_env} no es un nombre DNS válido en minúsculas"
    fi
    case "${tls_mode}" in
        acme | internal) ;;
        *) die 2 "PROXY_TLS_MODE de ${proxy_env} debe ser acme o internal" ;;
    esac
}

prepare_secrets_dir() {
    # Crea el directorio 0700 (si no existe) y se niega si cae dentro del repositorio.
    local created="" canonical
    if [ ! -d "${secrets_dir}" ]; then
        mkdir -p "${secrets_dir}" || die 2 "no se pudo crear el directorio de secretos (${secrets_dir})"
        created=1
    fi
    canonical=$(cd "${secrets_dir}" && pwd -P)
    case "${canonical}/" in
        "${repo_root}/"*)
            if [ -n "${created}" ]; then
                rmdir "${secrets_dir}" 2> /dev/null || true
            fi
            die 2 "el directorio de secretos (${canonical}) no puede estar dentro del repositorio"
            ;;
    esac
    secrets_dir="${canonical}"
    chmod 700 "${secrets_dir}"
}

require_command sops "instálala: >= ${MIN_SOPS_MAJOR}.${MIN_SOPS_MINOR}"
check_sops_version
check_key_file
encrypted="${deploy_dir}/secrets.enc.yaml"
proxy_env="${deploy_dir}/proxy.env"
auth_surface="${repo_root}/scripts/check_auth_surface.py"
public_host=""
tls_mode=""
[ -f "${encrypted}" ] || die 2 "falta ${encrypted} (secretos cifrados con sops)"
if [ -z "${decrypt_only}" ]; then
    require_command docker "Docker con el plugin compose"
    docker compose version > /dev/null 2>&1 || die 2 "falta 'docker compose'"
    require_command curl "para comprobar /ready"
    [ -f "${deploy_dir}/jwks.json" ] || die 2 "falta ${deploy_dir}/jwks.json (scripts/jwt_keygen.sh)"
    [ -f "${deploy_dir}/auth.env" ] || die 2 "falta ${deploy_dir}/auth.env"
    [ -f "${deploy_dir}/api.env" ] || die 2 "falta ${deploy_dir}/api.env (configuración pública de la API: CORS)"
    [ -f "${auth_surface}" ] || die 2 "falta ${auth_surface}"
    check_env_file
    check_compose_profiles
    check_proxy_env
fi
prepare_secrets_dir

# --- descifrado ---------------------------------------------------------------------------------

work=$(mktemp -d "${secrets_dir}/.work.XXXXXX")
proxy_started=""
deploy_ok=""
cleanup() {
    if [ -n "${proxy_started}" ] && [ -z "${deploy_ok}" ]; then
        # Una verificación falló con el proxy ya arrancado: se para (443 cerrado) antes de salir.
        # Parado así, «restart: unless-stopped» lo deja parado también tras reiniciar el servidor.
        compose_public stop proxy > /dev/null 2>&1 || true
        printf 'deploy.sh: proxy parado: el 443 queda cerrado hasta un despliegue en verde\n' >&2
    fi
    rm -rf "${work}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

for key in ${SECRET_KEYS}; do
    # El error de sops nunca lleva el valor (si falla, no lo tiene): se muestra su última línea.
    if ! sops --disable-version-check decrypt --extract "[\"${key}\"]" "${encrypted}" \
        > "${work}/${key}" 2> "${work}/sops.err"; then
        die 1 "sops no pudo descifrar '${key}' de ${encrypted}: $(tail -n 1 "${work}/sops.err")"
    fi
    [ -s "${work}/${key}" ] || die 1 "el secreto '${key}' está vacío en ${encrypted}"
    chmod 0444 "${work}/${key}"
    mv -f "${work}/${key}" "${secrets_dir}/${key}"
done
info "secretos descifrados en ${secrets_dir} ($(echo "${SECRET_KEYS}" | tr ' ' ','))"

if [ -n "${decrypt_only}" ]; then
    exit 0
fi

# --- despliegue ---------------------------------------------------------------------------------

export DEPLOY_DIR="${deploy_dir}"
export DEPLOY_SECRETS_DIR="${secrets_dir}"
api_url="${DEPLOY_API_URL:-http://127.0.0.1:8000}"
timeout="${DEPLOY_TIMEOUT:-300}"
compose() {
    docker compose --project-directory "${repo_root}" -f "${repo_root}/docker-compose.yml" "$@"
}
compose_public() {
    compose --profile public "$@"
}

compose config --quiet || die 1 "docker-compose.yml no es válido con esta configuración"
# Primero se construye todo (un fallo de build no toca lo que está corriendo) y después se para el
# proxy en los dos modos: también en el privado el 443 queda cerrado.
compose build || die 1 "docker compose build falló"
if [ -n "${public_host}" ]; then
    compose_public build proxy || die 1 "no se pudo construir la imagen del proxy"
fi
compose_public stop proxy || die 1 "no se pudo parar el proxy"
compose up -d || die 1 "docker compose up falló"
# D15: api y backup se recrean siempre para que lean los secretos y el JWKS nuevos (un fichero
# reemplazado es otro inodo: el montaje viejo seguiría viendo el anterior).
compose up -d --no-deps --force-recreate api backup || die 1 "no se pudieron recrear api y backup"

migrate_id=$(compose ps -a -q migrate)
[ -n "${migrate_id}" ] || die 1 "no hay contenedor migrate"
deadline=$(($(date +%s) + timeout))
while :; do
    state=$(docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' "${migrate_id}")
    case "${state}" in
        "exited 0") break ;;
        exited*) die 1 "migrate terminó con error (${state}); mira: docker compose logs migrate" ;;
    esac
    [ "$(date +%s)" -lt "${deadline}" ] || die 1 "migrate no terminó en ${timeout} s"
    sleep 2
done
info "migraciones aplicadas"

while :; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "${api_url}/ready" || true)
    [ "${code}" = "200" ] && break
    [ "$(date +%s)" -lt "${deadline}" ] || die 1 "/ready no respondió 200 en ${timeout} s (último: ${code})"
    sleep 2
done
info "/ready 200"

# --- verificación -------------------------------------------------------------------------------

headers="${work}/headers"
code=$(curl -s -D "${headers}" -o /dev/null -w '%{http_code}' "${api_url}/v1/datasets/deploy-check")
[ "${code}" = "401" ] || die 1 "una ruta de negocio sin token respondió ${code} (se esperaba 401)"
grep -qi '^www-authenticate: Bearer' "${headers}" || die 1 "el 401 no trae WWW-Authenticate"
info "sin token: 401 con WWW-Authenticate"

# Todas las operaciones no públicas del OpenAPI, sin token, desde dentro del contenedor (solo
# stdlib; sale con 0 si todas dan 401, 1 si alguna responde sin token y 2 por uso o conexión).
surface=0
compose exec -T api python - --base-url http://127.0.0.1:8000 < "${auth_surface}" || surface=$?
[ "${surface}" -eq 0 ] ||
    die 1 "la API responde sin token o no se pudo comprobar (check_auth_surface.py salió con ${surface}): no se abre el 443"
info "superficie de autenticación: ninguna ruta de negocio responde sin token"

published=$(compose port api 8000)
case "${published}" in
    127.0.0.1:*) ;;
    *) die 1 "la API está publicada en ${published}: debe ser solo 127.0.0.1" ;;
esac
postgres_id=$(compose ps -q postgres)
[ -n "${postgres_id}" ] || die 1 "no hay contenedor postgres"
bindings=$(docker inspect --format '{{len .HostConfig.PortBindings}}' "${postgres_id}")
[ "${bindings}" = "0" ] || die 1 "postgres publica un puerto: no debe exponerse"
info "puertos: API solo en ${published}, Postgres sin publicar"

containers=()
while IFS= read -r id; do
    [ -n "${id}" ] && containers+=("${id}")
done < <(compose ps -a -q)
[ "${#containers[@]}" -gt 0 ] || die 1 "no hay contenedores del proyecto"
docker inspect "${containers[@]}" > "${work}/inspect.json"
patterns="${work}/patterns"
: > "${patterns}"
for key in ${SECRET_KEYS}; do
    cat "${secrets_dir}/${key}" >> "${patterns}"
    printf '\n' >> "${patterns}"
done
grep -v '^$' "${patterns}" > "${patterns}.clean" || die 1 "no hay valores secretos que buscar"
if grep -F -q -f "${patterns}.clean" "${work}/inspect.json"; then
    die 1 "docker inspect contiene un valor secreto (no se muestra): revisa el entorno de los servicios"
fi
info "docker inspect sin secretos"

if [ -z "${public_host}" ]; then
    info "desplegado en modo privado (sin ${proxy_env} el 443 queda cerrado)"
    exit 0
fi

# --- borde público (solo con proxy.env) -----------------------------------------------------------

proxy_started=1
compose_public up -d --no-deps --force-recreate proxy || die 1 "no se pudo arrancar el proxy"
public_url="https://${public_host}"
cacert=""
edge_curl() {
    # curl a través del proxy local con el nombre público y verificación TLS real (nunca -k): en
    # modo internal, contra la raíz de la CA de Caddy copiada del contenedor.
    if [ -n "${cacert}" ]; then
        curl --resolve "${public_host}:443:127.0.0.1" --cacert "${cacert}" "$@"
    else
        curl --resolve "${public_host}:443:127.0.0.1" "$@"
    fi
}
deadline=$(($(date +%s) + timeout))
if [ "${tls_mode}" = "internal" ]; then
    until compose_public exec -T proxy cat /data/caddy/pki/authorities/local/root.crt \
        > "${work}/root.crt" 2> /dev/null && [ -s "${work}/root.crt" ]; do
        [ "$(date +%s)" -lt "${deadline}" ] || die 1 "el proxy no creó su CA interna en ${timeout} s"
        sleep 2
    done
    cacert="${work}/root.crt"
fi
while :; do
    code=$(edge_curl -s -o /dev/null -w '%{http_code}' "${public_url}/health" || true)
    [ "${code}" = "200" ] && break
    [ "$(date +%s)" -lt "${deadline}" ] ||
        die 1 "${public_url}/health no respondió 200 por TLS en ${timeout} s (último: ${code}); mira: docker compose --profile public logs proxy"
    sleep 3
done
info "proxy: ${public_url}/health 200 con TLS verificado (modo ${tls_mode})"

code=$(edge_curl -s -D "${headers}" -o /dev/null -w '%{http_code}' "${public_url}/v1/datasets/deploy-check")
[ "${code}" = "401" ] || die 1 "por el proxy, una ruta de negocio sin token respondió ${code} (se esperaba 401)"
grep -qi '^www-authenticate: Bearer' "${headers}" || die 1 "por el proxy, el 401 no trae WWW-Authenticate"
grep -qi '^strict-transport-security: max-age=' "${headers}" || die 1 "por el proxy falta Strict-Transport-Security"
if grep -qi '^server:' "${headers}"; then
    die 1 "por el proxy la respuesta anuncia Server"
fi
for path in /ready /docs /openapi.json; do
    code=$(edge_curl -s -o /dev/null -w '%{http_code}' "${public_url}${path}")
    [ "${code}" = "404" ] || die 1 "por el proxy ${path} respondió ${code} (se esperaba 404: no se publica)"
done
info "por el proxy: 401 con WWW-Authenticate y HSTS, sin Server; /ready, /docs y /openapi.json en 404"

proxy_id=$(compose_public ps -q proxy)
[ -n "${proxy_id}" ] || die 1 "no hay contenedor proxy"
ports=$(docker inspect --format '{{range $port, $_ := .HostConfig.PortBindings}}{{$port}} {{end}}' "${proxy_id}")
[ "${ports}" = "443/tcp " ] || die 1 "el proxy publica ${ports% }: solo debe publicar 443/tcp"
proxy_uid=$(compose_public exec -T proxy id -u)
[ "${proxy_uid}" != "0" ] || die 1 "el proxy corre como root"
networks_of() {
    docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "$1"
}
case " $(networks_of "${proxy_id}")" in
    *_backend\ *) die 1 "el proxy está en la red backend (vería Postgres)" ;;
esac
case " $(networks_of "${postgres_id}")" in
    *_edge\ *) die 1 "postgres está en la red edge (lo vería el proxy)" ;;
esac
info "proxy: solo 443/tcp, uid ${proxy_uid}, fuera de backend; postgres fuera de edge"

deploy_ok=1
info "desplegado; público en ${public_url}"
