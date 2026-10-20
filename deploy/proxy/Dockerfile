# Imagen del borde de Voracious (paso E): Caddy 2 oficial, sin plugins, delante de la API en el 443.
# No compila nada: añade la configuración (Caddyfile y los dos modos de TLS) y un usuario sin
# privilegios. Se construye donde se usa, como la de la API (docker compose --profile public build
# proxy, que hace scripts/deploy.sh en modo público):
#   docker build -t voracious-proxy:local deploy/proxy
# Variables obligatorias en el arranque (deploy/demo/proxy.env): PROXY_PUBLIC_HOST y PROXY_TLS_MODE.

# Base fijada por versión y digest; Dependabot propone las subidas (.github/dependabot.yml, /deploy/proxy).
FROM caddy:2.11.7-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f

# La base marca /usr/bin/caddy con la capacidad de fichero cap_net_bind_service: con cap_drop ALL el
# kernel se niega a ejecutarlo («operation not permitted»). Se quita, porque Docker (>= 20.10) ya
# deja abrir el 443 sin capacidades (net.ipv4.ip_unprivileged_port_start=0 en el espacio de red del
# contenedor). Usuario 10002 (la API es 10001), dueño de /data (certificados y llave de la cuenta
# ACME) y de /config.
RUN setcap -r /usr/bin/caddy \
    && addgroup -S -g 10002 caddy \
    && adduser -S -D -H -u 10002 -G caddy -h /nonexistent -s /sbin/nologin caddy \
    && chown -R 10002:10002 /data /config

COPY Caddyfile tls-acme.caddy tls-internal.caddy /etc/caddy/

# La build falla si el Caddyfile no se puede leer en alguno de los dos modos. «adapt» no arranca
# nada ni toca la red; «caddy validate» y «caddy fmt» van en CI (trabajo image).
RUN for mode in acme internal; do \
        PROXY_PUBLIC_HOST=build.invalid PROXY_TLS_MODE="${mode}" \
            caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile > /dev/null || exit 1; \
    done

USER 10002:10002
