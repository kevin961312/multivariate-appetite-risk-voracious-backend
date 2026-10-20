#!/usr/bin/env bash
# Comprobación del borde público de Voracious desde fuera (paso E): lo que ve un cliente de internet.
#
#   scripts/check_public.sh [--resolve IP] [--cacert F] [--cors-origin O] [--min-days N] URL
#   scripts/check_public.sh --cors-origin http://localhost:5173 https://api.voracious.cloud
#
#   URL             https://<host>, sin ruta ni puerto.
#   --resolve IP    usa esa IP sin preguntar al DNS (CI); los puertos se prueban en ella.
#   --cacert F      raíz de confianza para TLS (CI: la CA interna de Caddy); nunca se desactiva.
#   --cors-origin O origen de navegador que la API debe admitir (ACAO igual a O o «*»).
#   --min-days N    días mínimos de validez del certificado (14 por defecto; Caddy renueva unos 30
#                   días antes, así que menos de 14 significa que la renovación está atascada).
#
# El token, solo por VORACIOUS_API_TOKEN (nunca como argumento ni en la línea de órdenes de curl);
# sin él, la comprobación con token se omite y se dice. /health se reintenta 3 veces con 20 s de
# espera (un despliegue reinicia la API). Comprueba: DNS sin AAAA, TLS válido y su caducidad, TLS
# <= 1.1 rechazado, HTTP/2, /health 200, cabeceras de seguridad sin Server ni Via, 401 con
# WWW-Authenticate, 404 DATASET_NOT_FOUND con token, rutas cerradas en el borde, CORS, puertos 80,
# 8000, 5432 y 2019 cerrados en la IP, y que la IP sin SNI no sirve certificado.
# Una línea OK, FALLO u OMITIDO por comprobación; nunca imprime el token. Necesita bash (3.2 de
# macOS o 5 de Linux), curl y openssl; dig, si está, para comprobar que no hay AAAA.
# Códigos de salida: 0 todo bien (lo omitido no falla); 1 alguna comprobación falló; 2 uso.
set -euo pipefail
umask 077

HEALTH_TRIES=3
HEALTH_WAIT_SECONDS=20
CLOSED_PORTS="80 8000 5432 2019"
CLOSED_PATHS="/ready /docs /redoc /docs/oauth2-redirect /openapi.json /"

usage() {
    # La cabecera de comentarios del script (de la línea 2 a la primera que no es comentario).
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

die() {
    printf 'check_public.sh: %s\n' "$*" >&2
    exit 2
}

resolve_ip=""
cacert=""
cors_origin=""
min_days=14
url=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --resolve | --cacert | --cors-origin | --min-days)
            [ "$#" -ge 2 ] || die "$1 necesita un valor"
            case "$1" in
                --resolve) resolve_ip="$2" ;;
                --cacert) cacert="$2" ;;
                --cors-origin) cors_origin="$2" ;;
                --min-days) min_days="$2" ;;
            esac
            shift 2
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        -*) die "opción desconocida: $1 (usa --help)" ;;
        *)
            [ -z "${url}" ] || die "argumento de más: $1"
            url="$1"
            shift
            ;;
    esac
done
[ -n "${url}" ] || die "falta la URL (usa --help)"
host="${url#https://}"
host="${host%/}"
[ "https://${host}" = "${url%/}" ] || die "la URL debe ser https://<host>"
printf '%s\n' "${host}" |
    grep -Eqx '[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+' ||
    die "host no válido en ${url} (nombre DNS en minúsculas, sin puerto ni ruta)"
case "${min_days}" in
    "" | *[!0-9]*) die "--min-days debe ser un entero >= 0" ;;
esac
[ -z "${cacert}" ] || [ -f "${cacert}" ] || die "no existe --cacert ${cacert}"
command -v curl > /dev/null 2>&1 || die "falta curl"
command -v openssl > /dev/null 2>&1 || die "falta openssl"

work=$(mktemp -d "${TMPDIR:-/tmp}/check_public.XXXXXX")
trap 'rm -rf "${work}"' EXIT
trap 'exit 130' INT TERM

failures=0
ok() { printf 'OK      %s\n' "$*"; }
fail() {
    printf 'FALLO   %s\n' "$*"
    failures=$((failures + 1))
}
skip() { printf 'OMITIDO %s\n' "$*"; }

base="https://${host}"
curl_args=(-sS --connect-timeout 10 --max-time 60 --proto "=https")
[ -z "${resolve_ip}" ] || curl_args+=(--resolve "${host}:443:${resolve_ip}")
[ -z "${cacert}" ] || curl_args+=(--cacert "${cacert}")

edge() {
    # edge CABECERAS CUERPO RUTA [ARGS…]: petición al borde; imprime el código HTTP (000 si falló).
    local headers="$1" body="$2" path="$3"
    shift 3
    curl "${curl_args[@]}" -D "${headers}" -o "${body}" -w '%{http_code}' "$@" "${base}${path}" \
        2> "${work}/curl.err" || true
}

header_value() {
    # header_value FICHERO NOMBRE: valor de la cabecera (última aparición, sin \r; nombre sin mayúsculas).
    tr -d '\r' < "$1" | awk -v name="$2" '
        { i = index($0, ":") }
        i > 0 && tolower(substr($0, 1, i - 1)) == name { value = substr($0, i + 1); sub(/^[ \t]+/, "", value) }
        END { print value }'
}

has_header() {
    tr -d '\r' < "$1" | awk -v name="$2" '
        { i = index($0, ":") } i > 0 && tolower(substr($0, 1, i - 1)) == name { found = 1 }
        END { exit found ? 0 : 1 }'
}

list_has_all() {
    # list_has_all "a, B,c" "a b": todos los elementos (sin mayúsculas) están en la lista con comas.
    local list item
    list=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
    for item in $2; do
        case ",${list}," in
            *",${item},"*) ;;
            *) return 1 ;;
        esac
    done
}

json_code() {
    # json_code FICHERO: el campo «code» del formato uniforme de error (vacío si no lo hay).
    sed -n 's/.*"code" *: *"\([A-Z_]*\)".*/\1/p' "$1" | head -n 1
}

printf 'check_public.sh: %s%s\n' "${base}" "${resolve_ip:+ (--resolve ${resolve_ip})}"

# --- /health, TLS y DNS ---------------------------------------------------------------------------

attempt=1
while :; do
    result=$(curl "${curl_args[@]}" -D "${work}/health.h" -o "${work}/health.b" \
        -w '%{http_code} %{http_version} %{remote_ip}' "${base}/health" 2> "${work}/curl.err" || true)
    code="${result%% *}"
    [ "${code}" = "200" ] && break
    if [ "${attempt}" -ge "${HEALTH_TRIES}" ]; then
        fail "TLS válido y ${base}/health 200 (${HEALTH_TRIES} intentos; último: ${code:-000}; $(tail -n 1 "${work}/curl.err" 2> /dev/null))"
        printf 'check_public.sh: sin /health no tiene sentido seguir\n' >&2
        exit 1
    fi
    attempt=$((attempt + 1))
    sleep "${HEALTH_WAIT_SECONDS}"
done
rest="${result#* }"
http_version="${rest%% *}"
remote_ip="${rest#* }"
ok "TLS válido y /health 200 (intento ${attempt})"
if [ "${http_version}" = "2" ]; then ok "HTTP/2"; else fail "HTTP/2 (se negoció HTTP/${http_version})"; fi

ip="${resolve_ip:-${remote_ip}}"
if [ -n "${resolve_ip}" ]; then
    skip "DNS (--resolve ${resolve_ip})"
else
    ok "DNS: ${host} -> ${remote_ip}"
    # Solo IPv4 a propósito (sin AAAA: tras docker-proxy un cliente IPv6 perdería su IP). Con dig,
    # porque «curl -6» no sirve en macOS (resuelve a direcciones IPv4 mapeadas).
    if command -v dig > /dev/null 2>&1; then
        aaaa=$(dig +short AAAA "${host}" 2> /dev/null | grep ':' | tr '\n' ' ' || true)
        if [ -z "${aaaa}" ]; then ok "DNS sin AAAA"; else fail "DNS: ${host} tiene AAAA (${aaaa% })"; fi
    else
        skip "DNS sin AAAA (sin dig)"
    fi
fi
case "${ip}" in
    *:*) ip_url="[${ip}]" ;;
    *) ip_url="${ip}" ;;
esac

# Caducidad del certificado que sirve el borde para este nombre (SNI = host).
if openssl s_client -connect "${ip_url}:443" -servername "${host}" < /dev/null 2> /dev/null |
    openssl x509 -noout -enddate > "${work}/enddate" 2> /dev/null; then
    end=$(sed -n 's/^notAfter=//p' "${work}/enddate")
    if openssl s_client -connect "${ip_url}:443" -servername "${host}" < /dev/null 2> /dev/null |
        openssl x509 -noout -checkend $((min_days * 86400)) > /dev/null 2>&1; then
        ok "certificado válido al menos ${min_days} días (caduca ${end})"
    else
        fail "certificado: caduca antes de ${min_days} días (${end}); la renovación de Caddy está atascada"
    fi
else
    fail "certificado: openssl no pudo leerlo en ${ip_url}:443"
fi

tls_old=0
curl "${curl_args[@]}" -o /dev/null --tlsv1.0 --tls-max 1.1 "${base}/health" 2> /dev/null || tls_old=$?
if [ "${tls_old}" -ne 0 ]; then ok "TLS <= 1.1 rechazado"; else fail "TLS <= 1.1 aceptado"; fi

# --- cabeceras --------------------------------------------------------------------------------------

check_security_headers() {
    # check_security_headers FICHERO DESCRIPCIÓN: las cabeceras del borde, sin Server, Via ni Alt-Svc.
    local file="$1" what="$2" missing="" name expected
    while IFS='|' read -r name expected; do
        [ "$(header_value "${file}" "${name}")" = "${expected}" ] || missing="${missing} ${name}"
    done << 'EOF'
strict-transport-security|max-age=31536000; includeSubDomains
x-content-type-options|nosniff
referrer-policy|no-referrer
cache-control|no-store
x-frame-options|DENY
content-security-policy|default-src 'none'; frame-ancestors 'none'
EOF
    for name in server via alt-svc; do
        if has_header "${file}" "${name}"; then missing="${missing} (sobra ${name})"; fi
    done
    if [ -z "${missing}" ]; then ok "cabeceras de seguridad en ${what}, sin Server, Via ni Alt-Svc"; else fail "cabeceras en ${what}:${missing}"; fi
}
check_security_headers "${work}/health.h" "/health"

# --- autenticación ----------------------------------------------------------------------------------

code=$(edge "${work}/401.h" "${work}/401.b" /v1/datasets/check-public)
www=$(header_value "${work}/401.h" www-authenticate)
if [ "${code}" = "401" ] && [ "${www#Bearer}" != "${www}" ] && [ "$(json_code "${work}/401.b")" = "UNAUTHENTICATED" ]; then
    ok "sin token: 401 UNAUTHENTICATED con WWW-Authenticate: Bearer"
else
    fail "sin token: se esperaba 401 UNAUTHENTICATED con WWW-Authenticate: Bearer (llegó ${code}, '${www}')"
fi

if [ -n "${VORACIOUS_API_TOKEN:-}" ]; then
    # La cabecera entra por la entrada estándar (-H @-): el token no aparece en la línea de órdenes.
    code=$(printf 'Authorization: Bearer %s\n' "${VORACIOUS_API_TOKEN}" |
        edge "${work}/tok.h" "${work}/tok.b" /v1/datasets/check-public -H @-)
    if [ "${code}" = "404" ] && [ "$(json_code "${work}/tok.b")" = "DATASET_NOT_FOUND" ]; then
        ok "con token: 404 DATASET_NOT_FOUND"
    else
        fail "con token: se esperaba 404 DATASET_NOT_FOUND (llegó ${code} $(json_code "${work}/tok.b"))"
    fi
else
    skip "con token (sin VORACIOUS_API_TOKEN)"
fi

# --- rutas cerradas en el borde ---------------------------------------------------------------------

open_paths=""
for path in ${CLOSED_PATHS}; do
    code=$(edge "${work}/closed.h" "${work}/closed.b" "${path}")
    if [ "${code}" != "404" ] || [ "$(json_code "${work}/closed.b")" != "ROUTE_NOT_FOUND" ]; then
        open_paths="${open_paths} ${path}=${code}"
    fi
done
if [ -z "${open_paths}" ]; then ok "rutas cerradas en el borde (404 ROUTE_NOT_FOUND): ${CLOSED_PATHS}"; else fail "rutas que el borde no cierra:${open_paths}"; fi
check_security_headers "${work}/closed.h" "un 404 del borde"

# --- CORS -------------------------------------------------------------------------------------------

origin_allowed() {
    # origin_allowed FICHERO: Access-Control-Allow-Origin es el origen pedido o «*».
    local acao
    acao=$(header_value "$1" access-control-allow-origin)
    [ "${acao}" = "${cors_origin}" ] || [ "${acao}" = "*" ]
}

if [ -n "${cors_origin}" ]; then
    code=$(edge "${work}/pre.h" /dev/null /v1/datasets -X OPTIONS -H "Origin: ${cors_origin}" \
        -H "Access-Control-Request-Method: POST" \
        -H "Access-Control-Request-Headers: authorization,content-type")
    problems=""
    [ "${code}" = "200" ] || problems="${problems} estado=${code}"
    origin_allowed "${work}/pre.h" || problems="${problems} allow-origin"
    list_has_all "$(header_value "${work}/pre.h" access-control-allow-methods)" "get post" ||
        problems="${problems} allow-methods"
    list_has_all "$(header_value "${work}/pre.h" access-control-allow-headers)" "authorization content-type" ||
        problems="${problems} allow-headers"
    [ "$(header_value "${work}/pre.h" access-control-max-age)" = "600" ] || problems="${problems} max-age"
    if has_header "${work}/pre.h" access-control-allow-credentials; then problems="${problems} allow-credentials"; fi
    if [ -z "${problems}" ]; then ok "CORS: preflight desde ${cors_origin} admitido"; else fail "CORS: preflight desde ${cors_origin}:${problems}"; fi

    code=$(edge "${work}/pre-bad.h" /dev/null /v1/datasets -X OPTIONS -H "Origin: ${cors_origin}" \
        -H "Access-Control-Request-Method: POST" \
        -H "Access-Control-Request-Headers: authorization,x-voracious-no-admitida")
    if [ "${code}" = "400" ]; then ok "CORS: preflight con una cabecera no admitida da 400"; else fail "CORS: preflight con una cabecera no admitida dio ${code} (se esperaba 400)"; fi

    code=$(edge "${work}/cors401.h" /dev/null /v1/datasets/check-public -H "Origin: ${cors_origin}")
    problems=""
    [ "${code}" = "401" ] || problems="${problems} estado=${code}"
    origin_allowed "${work}/cors401.h" || problems="${problems} allow-origin"
    list_has_all "$(header_value "${work}/cors401.h" access-control-expose-headers)" "www-authenticate retry-after" ||
        problems="${problems} expose-headers"
    if [ -z "${problems}" ]; then ok "CORS: el 401 lleva Allow-Origin y expone WWW-Authenticate y Retry-After"; else fail "CORS: el 401 desde ${cors_origin}:${problems}"; fi
else
    skip "CORS (sin --cors-origin)"
fi

# --- puertos y SNI en la IP -------------------------------------------------------------------------

open_ports=""
for port in ${CLOSED_PORTS}; do
    # num_connects es 1 solo si la conexión TCP se estableció (abierto); 0 si se rechazó o no hubo
    # respuesta (cerrado o filtrado por el cortafuegos).
    connects=$(curl -s -o /dev/null --connect-timeout 5 --max-time 6 -w '%{num_connects}' \
        "telnet://${ip_url}:${port}" < /dev/null 2> /dev/null || true)
    [ "${connects:-0}" = "0" ] || open_ports="${open_ports} ${port}"
done
if [ -z "${open_ports}" ]; then ok "puertos cerrados en ${ip}: ${CLOSED_PORTS}"; else fail "puertos abiertos en ${ip}:${open_ports}"; fi

# Sin SNI no hay certificado. -k a propósito: con él, cualquier certificado que sirviera el borde
# completaría la conexión, que es justo lo que no debe pasar (código 35: no hubo apretón TLS).
no_sni=0
curl -sk -o /dev/null --connect-timeout 5 --max-time 10 "https://${ip_url}/" 2> /dev/null || no_sni=$?
case "${no_sni}" in
    35) ok "https://${ip_url} sin SNI: no hay certificado (la conexión TLS falla)" ;;
    0) fail "https://${ip_url} sin SNI sirve un certificado" ;;
    *) fail "https://${ip_url} sin SNI: curl salió con ${no_sni} (se esperaba 35, fallo del apretón TLS)" ;;
esac

if [ "${failures}" -eq 0 ]; then
    printf 'check_public.sh: todo OK\n'
else
    printf 'check_public.sh: %s comprobaciones fallaron\n' "${failures}"
    exit 1
fi
