# Despliegue y operación de la demo

Guía de operación del servidor de demo (`kevin@128.140.75.161`, Ubuntu, 2 vCPU, Docker + Compose; carpeta
`~/voracious-demo`). Explica **cómo** se despliega y se opera; el **porqué** de cada decisión está en el
[ADR 0012](adr/0012-seguridad-minima-sops-jwt.md) (secretos y JWT), el [ADR 0010](adr/0010-empaquetado-docker-y-ci.md)
(imagen, CI), el [ADR 0011](adr/0011-persistencia-en-postgres.md) (Postgres, backup) y el
[ADR 0013](adr/0013-exposicion-publica-https.md) (exposición pública por HTTPS).

> **Estado (2026-10-20).** **T16 está hecho:** la demo corre con SOPS + age + JWT (`deploy.sh` terminó en
> verde y las filas de las 16 tablas quedaron idénticas); los artefactos cifrados, el JWKS y `.sops.yaml` están en
> `origin/main` (`a34bb70`, y la guía en `addb026`). La **exposición pública** (sección «Exposición pública») está
> **desplegada y verificada**: la API responde en `https://api.voracious.cloud` y `127.0.0.1:8000` queda para el
> operador por SSH.

## Principios

- **sops y age viven solo en el servidor y en CI**, no en el Mac del dueño (decisión del 2026-10-20). La llave age
  privada nace en el servidor y no sale de él; `.sops.yaml` tiene un único receptor, el servidor.
- Cifrar, generar llaves JWT y emitir tokens se hace **en el servidor**, con `--via docker` (la CLI de la imagen
  `voracious:local`). Los ficheros resultantes se traen al Mac con `scp` y se commitean con `/commit-seguro`.
- La API se publicará **solo por HTTPS** en `https://api.voracious.cloud` (Caddy, 443/TCP, ADR 0013; **objetivo hasta
  que se despliegue el paso E**: hoy sigue en `127.0.0.1:8000`) y **solo con datos sintéticos o de prueba**; para datos
  del banco hace falta antes el paso grande de seguridad (OIDC, RLS, auditoría). El **túnel SSH** (`ssh -L 8000:127.0.0.1:8000 kevin@128.140.75.161`) queda **solo para el operador**: `/ready`, la
  documentación y `docker compose` no salen a internet. Postgres no publica ningún puerto.
- **Nunca `docker compose down -v`**: borra los volúmenes (`pgdata`, `datasets`, `pgbackups`, y con el paso E
  `caddy_data`, los certificados) y con ellos la base de la demo. Para parar, `docker compose down` a secas.

## Requisitos del servidor

- Docker y el plugin `docker compose`; `curl`; `python3` (solo para el redespliegue inicial).
- **sops 3.13.3 y age v1.3.2, en `~/.local/bin` y sin sudo.** El dueño no recuerda la contraseña de `sudo` de `kevin`,
  así que se instalaron como usuario: sops desde el binario oficial de la release y age desde la suya, ambos
  verificados contra su SHA-256 y contra el `digest` que publica GitHub (el SHA-256 de sops es
  `e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b`, el mismo que fija `ci.yml`):

  ```bash
  install -d ~/.local/bin
  v=3.13.3
  curl -fsSLO "https://github.com/getsops/sops/releases/download/v${v}/sops-v${v}.linux.amd64"
  echo "e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b  sops-v${v}.linux.amd64" | sha256sum -c -
  install -m 0755 "sops-v${v}.linux.amd64" ~/.local/bin/sops
  # age: tarball de la release de FiloSottile/age; el SHA-256 es el «digest» que GitHub publica para el asset
  a=v1.3.2
  curl -fsSLO "https://github.com/FiloSottile/age/releases/download/${a}/age-${a}-linux-amd64.tar.gz"
  echo "cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10  age-${a}-linux-amd64.tar.gz" | sha256sum -c -
  tar -xzf "age-${a}-linux-amd64.tar.gz"
  install -m 0755 age/age age/age-keygen ~/.local/bin/
  sops --version     # 3.13.3
  age --version      # v1.3.2
  age-keygen --version
  ```

  `deploy.sh` exige sops ≥ 3.9. Otra versión pide recalcular el SHA-256 contra el `checksums.txt` de la release **y**
  cambiarlo en `ci.yml`.

  **PATH por ssh sin terminal.** Una orden `ssh servidor 'scripts/deploy.sh'` no carga `~/.profile`, así que no ve
  `~/.local/bin` y los scripts fallan con «falta la orden sops». Hay que anteponerlo a cada orden remota:

  ```bash
  ssh kevin@128.140.75.161 'export PATH="$HOME/.local/bin:$PATH"; cd ~/voracious-demo && scripts/deploy.sh'
  ```

  (o poner ese `export` al principio de `~/.bashrc`, antes de la guarda de sesión interactiva).
- La imagen `voracious:local` construida **antes** de emitir tokens o generar llaves (ver T16, paso 5).

## Variables de despliegue

No son de la aplicación: las leen `docker-compose.yml` y los scripts. Todas opcionales salvo donde se dice.

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `DEPLOY_SECRETS_DIR` | `${XDG_STATE_HOME:-$HOME/.local/state}/voracious/demo/secrets` | Dónde deja `deploy.sh` los secretos descifrados (directorio 0700, ficheros 0444, **fuera del repo**; se niega si cae dentro). Compose **no arranca** sin ella; ponerla también en el `.env` (es una ruta, no un secreto) permite usar `docker compose ps/logs` a mano. **Debe ser la misma** que usa `deploy.sh`. |
| `DEPLOY_DIR` | `deploy/demo` | Configuración versionada: `secrets.enc.yaml`, `jwt-signing.enc.yaml`, `jwks.json`, `auth.env`, `api.env` (obligatorio) y `proxy.env` (su existencia activa el modo público). |
| `DEPLOY_TIMEOUT` | `300` | Segundos máximos de espera a `migrate` y a `/ready` y, aparte, al `/health` del proxy (cabe de sobra la primera emisión del certificado). |
| `DEPLOY_API_URL` | `http://127.0.0.1:8000` | URL local con la que `deploy.sh` comprueba la API. |
| `DEPLOY_ENV_FILE` | `.env` de la raíz | `.env` que `deploy.sh` revisa en busca de secretos. |
| `SOPS_AGE_KEY_FILE` | `~/.config/sops/age/keys.txt` | Llave age privada (modo 600). |
| `SOPS_CONFIG` | `.sops.yaml` de la raíz | Reglas y receptores de sops (lo usa `jwt_keygen.sh`). |
| `VORACIOUS_IMAGE` | `voracious:local` | Imagen que usan `--via docker` en `issue_token.sh` y `jwt_keygen.sh`. |
| `DEPLOY_EDGE_SUBNET` | `172.29.80.0/24` | Subred de la red `edge` (api y proxy). Cámbiala si choca con otra red del servidor. |
| `DEPLOY_PROXY_IP` | `172.29.80.10` | IP fija del proxy dentro de `edge`; es la única en la que la API cree `X-Forwarded-For` (`VORACIOUS_TRUSTED_PROXIES`). Debe caer dentro de `DEPLOY_EDGE_SUBNET`. |
| `PROXY_PUBLIC_HOST` | `api.voracious.cloud` (en `proxy.env`) | Nombre con certificado. Permanente: los integradores lo fijan en su código. Minúsculas, solo un nombre DNS. |
| `PROXY_TLS_MODE` | `acme` (en `proxy.env`) | `acme` (Let's Encrypt, la demo) o `internal` (CA propia de Caddy: CI y pruebas). Otro valor, el proxy no arranca. |
| `VORACIOUS_CORS_ALLOWED_ORIGINS` | `*` (en `api.env`) | Orígenes de navegador admitidos. Ver «Restringir CORS». |
| `VORACIOUS_API_TOKEN` | — | Solo para `check_public.sh` y `demo_seed.py`; nunca como argumento. |

## T16: redespliegue de la demo con secretos cifrados y JWT (hecho el 2026-10-20)

**Hecho:** la demo corre `74aae38` con SOPS + age + JWT, `deploy.sh` terminó en verde y las filas de las 16 tablas
quedaron idénticas. Los pasos siguientes se conservan como **procedimiento de referencia** (para una reconstrucción
desde cero), con las correcciones que salieron al ejecutarlos. Se hizo **entero en el servidor**, migrando desde el
`.env` anterior **sin perder la base**. Por qué cada cosa:
`POSTGRES_PASSWORD_FILE` solo se usa al crear la base (`initdb`) y el volumen `pgdata` ya existe, así que el secreto
cifrado tiene que ser **la contraseña actual**; si no, `migrate` y `api` no conectan. El proyecto de Compose se
llama `voracious` (`name:` en el YAML), así que mover la carpeta reutiliza los volúmenes `voracious_pgdata`,
`voracious_datasets` y `voracious_pgbackups`.

1. **Copia previa** (con la pila actual en marcha, desde `~/voracious-demo`). Por ssh sin terminal,
   `docker compose exec` necesita `-T`. **Antes de T16** el contenedor `backup` aún tiene `PGPASSWORD` en el entorno:

   ```bash
   docker compose exec -T backup sh -c 'pg_dump --format=custom --file=/backups/pre-sops-$(date -u +%Y%m%dT%H%M%SZ).dump'
   docker compose exec -T backup ls -l /backups     # el volcado pre-sops-… existe y no está vacío
   ```

   **Después de T16** `backup` ya no tiene `PGPASSWORD` (la lee del secreto), así que un volcado a mano es:

   ```bash
   docker compose exec -T backup sh -c 'PGPASSWORD="$(cat /run/secrets/postgres_password)" pg_dump --format=custom --file=/backups/<nombre>.dump'
   ```

   Los volcados previos a T16 son `/backups/pre-sops-20261020T191708Z.dump` y, justo antes del redespliegue,
   `/backups/pre-sops-20261020T220755Z.dump` (90 802 bytes). La rotación automática solo borra `voracious-*.dump`, de
   modo que los `pre-sops-*` se conservan.

2. **Instalar herramientas**: sops y age, sin sudo y en `~/.local/bin`, como en «Requisitos» (con el `PATH` por ssh sin
   terminal). Crear la llave age del servidor (`install -d -m 700` solo aplica el modo a la **última** carpeta; es
   inocuo, pero conviene comprobar que `~/.config/sops` no queda abierta):

   ```bash
   install -d -m 700 ~/.config/sops/age
   age-keygen -o ~/.config/sops/age/keys.txt && chmod 600 ~/.config/sops/age/keys.txt
   age-keygen -y ~/.config/sops/age/keys.txt     # receptor público (age1…): es el que va en .sops.yaml
   ```

3. **Mover la carpeta y copiar el código** con `git archive` desde el Mac: solo salen los ficheros versionados (nada de
   `.env`, `datos` ni `referencias`) y no hace falta empaquetar un `.tar.gz`. (Con `scp` de varios ficheros a la vez,
   `{a,b,c}` lo expande el shell **local**: no se entrecomilla.)

   ```bash
   # en el servidor
   mv ~/voracious-demo ~/voracious-demo.prev
   mkdir ~/voracious-demo
   # en el Mac, desde la raíz del repo
   git archive <commit> | ssh kevin@128.140.75.161 'tar -x -C ~/voracious-demo'
   # en el servidor
   install -m 600 ~/voracious-demo.prev/.env ~/voracious-demo/.env.pre-sops
   cd ~/voracious-demo
   ```

4. **`.sops.yaml`** en la raíz de `~/voracious-demo`, con un solo receptor (el del paso 2):

   ```yaml
   creation_rules:
     - path_regex: ^deploy/demo/.*\.enc\.yaml$
       age: age1…   # salida de age-keygen -y
   ```

   El `path_regex` relativo **casa también con la ruta absoluta** que `jwt_keygen.sh` pasa en `--filename-override`:
   sops 3.13.3 la hace relativa al directorio del `.sops.yaml`. No hace falta ninguna regla de respaldo ni el
   `(^|/)…` que se probó al principio. **Lección de CI (`a34bb70`):** este `.sops.yaml` solo sirve para los cifrados
   reales; ningún test ni paso de CI debe depender de él (por eso cifran con `sops --config <tmp>`).

5. **Construir la imagen antes**, porque `jwt_keygen.sh` e `issue_token.sh --via docker` usan `voracious:local`:

   ```bash
   docker build --target runtime -t voracious:local .
   ```

   (`docker compose build` también vale, pero Compose necesita entonces `DEPLOY_SECRETS_DIR` definida aunque no use los
   secretos: de ahí que `docker build` sea más directo.)

6. **Cifrar los secretos actuales sin imprimirlos.** Se leen de `.env.pre-sops` con `python3` (JSON, para evitar
   problemas de comillas; revisa antes si tu `.env` usa comillas) y se cifran por la tubería:

   ```bash
   python3 - <<'PY' | sops encrypt --filename-override deploy/demo/secrets.enc.yaml \
       --input-type json --output-type yaml /dev/stdin > deploy/demo/secrets.enc.yaml
   import json, sys
   env = {}
   for line in open(".env.pre-sops"):
       key, _, value = line.strip().partition("=")
       env[key] = value.strip("\"'")
   json.dump({"postgres_password": env["POSTGRES_PASSWORD"],
              "database_url": env["VORACIOUS_DATABASE_URL"]}, sys.stdout)
   PY
   ```

   **Comprobar con `cmp`, sin imprimir nada**, que el cifrado contiene exactamente la contraseña actual:

   ```bash
   value() { python3 -c 'import sys
   for l in open(".env.pre-sops"):
       k, _, v = l.strip().partition("=")
       if k == sys.argv[1]: sys.stdout.write(v.strip("\"\x27"))' "$1"; }
   cmp <(sops decrypt --extract '["postgres_password"]' deploy/demo/secrets.enc.yaml) <(value POSTGRES_PASSWORD) && echo igual
   cmp <(sops decrypt --extract '["database_url"]' deploy/demo/secrets.enc.yaml) <(value VORACIOUS_DATABASE_URL) && echo igual
   ```

7. **Llave JWT** (JWKS público + llave de firma cifrada), por la vía del servidor:

   ```bash
   scripts/jwt_keygen.sh --via docker demo-2026-10
   ```

   Crea `deploy/demo/jwks.json` y `deploy/demo/jwt-signing.enc.yaml`. La llave privada solo pasa por una tubería
   hacia sops: nunca toca el disco en claro. Si algo falla no cambia nada.

8. **`.env` nuevo, sin secretos**, y con `DEPLOY_SECRETS_DIR` igual al que usará `deploy.sh`:

   ```bash
   grep -vE '^(POSTGRES_PASSWORD|VORACIOUS_DATABASE_URL|PGPASSWORD)=' .env.pre-sops > .env && chmod 600 .env
   echo "DEPLOY_SECRETS_DIR=$HOME/.local/state/voracious/demo/secrets" >> .env   # o el valor que uses
   ```

   Quedan el perfil de 2 vCPU y `POSTGRES_USER`/`POSTGRES_DB`. `deploy.sh` **se niega a desplegar** si el `.env` trae
   `POSTGRES_PASSWORD`, `VORACIOUS_DATABASE_URL`, `PGPASSWORD` o algo `*PRIVATE*` con valor.

9. **Desplegar**: `scripts/deploy.sh`. Descifra los secretos, valida Compose, construye y levanta la pila, **recrea
   `api` y `backup`** (para que lean los secretos y el JWKS vigentes), espera a `migrate` y a `/ready` 200, y
   verifica: sin token, 401 con `WWW-Authenticate`; la API solo en `127.0.0.1`; Postgres sin puertos publicados;
   `docker inspect` sin ningún valor secreto. Un despliegue interrumpe los trabajos en curso (`JOB_INTERRUPTED`).

10. **Comprobar con el modelo de antes** (tenant `demo`; si no lo fuera, míralo con
    `docker compose exec postgres psql -U voracious -c 'select tenant_id from tenants'`):

    ```bash
    T=$(scripts/issue_token.sh --via docker --tenant demo --roles analyst --subject kevin --ttl 1h)
    curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $T" \
      http://127.0.0.1:8000/v1/charts/t2mrcd/models/1f573da9-554c-42e2-b961-683048c30e3c   # 200
    curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Tenant-ID: demo' \
      http://127.0.0.1:8000/v1/charts/t2mrcd/models/1f573da9-554c-42e2-b961-683048c30e3c   # 401
    ```

11. **Traer los cifrados y el JWKS al repo** (desde el Mac), comprobar que no hay nada en claro y commitear:

    ```bash
    scp kevin@128.140.75.161:voracious-demo/.sops.yaml .
    scp kevin@128.140.75.161:voracious-demo/deploy/demo/{secrets.enc.yaml,jwt-signing.enc.yaml,jwks.json} deploy/demo/
    uv run pytest tests/unit/test_repo_secrets.py     # debe estar en verde antes de commitear
    ```

    Luego `/commit-seguro`. **El Mac no puede descifrar** estos ficheros (único receptor: el servidor); no hace falta.
    `docs/guia/` va en su propio commit.

12. **Vuelta atrás** (antes de limpiar el paso 13): `docker compose down` (sin `-v`) en `~/voracious-demo`, y
    `cd ~/voracious-demo.prev && docker compose up -d --build`. Los volúmenes son los mismos.

13. **Limpieza tras unos días en verde — pendiente**:
    `shred -u ~/voracious-demo/.env.pre-sops ~/voracious-demo.prev/.env`. Mientras no se haga, el servidor guarda la
    contraseña de Postgres en claro en esos dos ficheros.

**Observaciones de la ejecución (inocuas):** `deploy.sh` recrea `backup` dos veces (el `up` general y la recreación
explícita) y salen dos volcados seguidos; T16 no creó `DEPLOYED_COMMIT`, y esa convención **no está documentada en el
repo** (decisión abierta: o se adopta y se escribe aquí, o se descarta).

## Nota de seguridad: el integrador no toca el servidor

El integrador (quien consume la API) **no** debe tener acceso al servidor ni a la llave de firma. La API le llega por
`https://api.voracious.cloud`: no necesita túnel ni cuenta SSH, y por eso desaparece la «cuenta solo de túnel». El
operador emite el token y se lo entrega por un canal seguro. Por qué: quien llegue al servidor llega a sops, a la
llave age y a la llave de firma JWT, y con ellas puede emitir tokens de cualquier tenant y rol. El túnel SSH es solo
para el operador.

## Exposición pública (paso E: desplegada y verificada el 2026-10-20)

Publica la API en `https://api.voracious.cloud` con Caddy delante (servicio `proxy`, perfil `public` de Compose, solo
443/TCP). Decisiones, amenazas y alternativas en el [ADR 0013](adr/0013-exposicion-publica-https.md). **Solo datos
sintéticos o de prueba** (decisión del dueño): sin OIDC, Row-Level Security, auditoría completa ni copia fuera del
servidor. **Estado:** desplegada el 2026-10-20 (ver «Resultado del despliegue» más abajo). Lo de abajo es el procedimiento,
que sirve para repetirla o para otra instalación. El trabajo `image` de CI (el mismo `deploy.sh` con `tls internal`)
pasó en verde en el PR #10 antes de llevar el cambio a `main`.

### Requisitos

1. **T16 hecho** (lo está): sin él `deploy.sh` no puede descifrar los secretos y la puerta no abre el 443.
2. **DNS (Hostinger).** `dig +short api.voracious.cloud A` debe dar `128.140.75.161` y
   `dig +short api.voracious.cloud AAAA` debe salir **vacío**: sin registro AAAA a propósito (sin red Docker con IPv6,
   `docker-proxy` esconde la IP real de los clientes v6 y el límite por IP los agruparía). Activa 2FA en la cuenta.
   - **CAA, solo en `api`:** `api.voracious.cloud. CAA 0 issue "letsencrypt.org"`. **No** en la raíz: un CAA en
     `voracious.cloud` también restringiría los certificados del front cuando se aloje allí (otro repositorio, sin
     decidir).
3. **Cortafuegos de Hetzner Cloud** (consola web; filtra fuera de la VM, así que Docker no lo salta). Tiene que estar
   hecho **antes** del despliegue: Let's Encrypt valida por el 443.
   - **`voracious-demo`**, aplicado al servidor: entrada TCP 22, TCP 443 e ICMP desde cualquier IPv4/IPv6; **sin** TCP 80
     y **sin reglas de salida** (equivale a permitir toda salida: ACME, apt, imágenes).
   - **`firewall-1`**, el previo del dueño (22, 80 y 443), quedó **desvinculado** del servidor con su permiso, sin
     borrarlo. **Las reglas de varios cortafuegos se suman**: mientras siguiera aplicado, el 80 estaría abierto aunque
     `voracious-demo` no lo permita. Comprobado desde fuera: el 80 está cerrado y SSH funciona.
   - Cambia reglas siempre con **otra** sesión SSH abierta; la consola web de Hetzner sigue disponible si te quedas fuera.
4. **Bloque con sudo, reducido y pendiente.** El dueño no recuerda la contraseña de `kevin`, así que no se ha podido
   ejecutar. Ya no instala sops ni age (se instalaron sin sudo): solo diagnostica y deja SSH solo con llave (P5).
   Cuando la recupere, en **una** sesión `ssh -t kevin@128.140.75.161`:

   ```bash
   sudo -v || exit 1
   . /etc/os-release; echo "== $PRETTY_NAME $(uname -r)"; timedatectl show -p NTPSynchronized
   id -nG | tr ' ' '\n' | grep -qx docker && echo "kevin en docker" || echo "AVISO: kevin no está en el grupo docker"
   echo "== ufw"; sudo ufw status verbose 2>/dev/null || echo "ufw no instalado"
   echo "== a la escucha"; sudo ss -tulpn
   echo "== DOCKER-USER"; sudo iptables -S DOCKER-USER 2>/dev/null || echo "sin DOCKER-USER"
   echo "== API de Docker por TCP"; sudo ss -tlnp | grep -E ':(2375|2376)\b' || echo "no (bien)"
   echo "== actualizaciones automáticas"; systemctl is-enabled unattended-upgrades 2>/dev/null || echo "no instalado"
   echo "== sshd"; sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|permitrootlogin) '
   # SSH solo con llave, únicamente si hoy acepta contraseña (10- gana a 50-cloud-init: en sshd manda el primer valor)
   if sudo sshd -T | grep -qiE '^(passwordauthentication|kbdinteractiveauthentication) yes'; then
     printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
       | sudo tee /etc/ssh/sshd_config.d/10-voracious.conf > /dev/null
     sudo sshd -t && { sudo systemctl reload ssh 2>/dev/null || true; } && echo "sshd: solo llave; prueba OTRA sesión antes de cerrar esta"
   fi
   ```

   Si aparece algo a la escucha en `0.0.0.0` aparte de `sshd`, se revisa antes de abrir el 443. **No bloquea el
   despliegue** (no requiere sudo), pero deja el SSH con contraseña como deuda mientras no se ejecute.

### Desplegar

Sin sudo. Desde el Mac, con el commit ya hecho, y en el servidor (con el `PATH` de `~/.local/bin`):

```bash
git archive <commit> | ssh kevin@128.140.75.161 'tar -x -C ~/voracious-demo'
ssh kevin@128.140.75.161 'export PATH="$HOME/.local/bin:$PATH"; cd ~/voracious-demo && scripts/deploy.sh'
```

Debe terminar con `desplegado; público en https://api.voracious.cloud`. El modo público existe si y solo si hay
`deploy/demo/proxy.env`. Lo que hace `deploy.sh` en ese modo, y por qué en este orden:

1. Se niega (salida 2, sin tocar Docker) si falta `api.env`, si `proxy.env` no tiene un host DNS válido o un modo
   `acme|internal`, o si hay `COMPOSE_PROFILES` en el `.env` (en el entorno, `deploy.sh` hace `unset COMPOSE_PROFILES COMPOSE_ENV_FILES`): el perfil `public` solo lo activa
   la puerta.
2. Construye todo y **para el proxy siempre**, también en modo privado: así el 443 queda cerrado antes de tocar la API.
3. Levanta la pila, recrea `api` y `backup`, espera a `migrate` y a `/ready`, y hace las comprobaciones de siempre.
4. **La puerta:** ejecuta `scripts/check_auth_surface.py` dentro del contenedor `api`. Prueba cada operación del
   OpenAPI sin token (debe dar 401 con `WWW-Authenticate`) y `OPTIONS` sin cabeceras de *preflight* (también 401). Si
   alguna ruta responde sin token, sale con 1 y **no abre el 443**.
5. Arranca el proxy y comprueba, con el nombre público, `--resolve` a `127.0.0.1` y TLS verificado de verdad: `/health`
   200, 401 con `WWW-Authenticate` y HSTS, sin `Server`, `/ready`, `/docs` y `/openapi.json` en 404, solo `443/tcp`
   publicado, proxy sin root y fuera de `backend`, y Postgres fuera de `edge`.
6. Una trampa `EXIT` **vuelve a parar el proxy** ante cualquier fallo después de arrancarlo. Con
   `restart: unless-stopped`, un proxy parado así sigue parado tras reiniciar el servidor.

Consecuencias que conviene tener presentes:

- **Cada despliegue corta la API pública** durante la construcción y el arranque (el proxy está parado y la API se
  recrea) y **interrumpe los trabajos en curso** (`JOB_INTERRUPTED`). Un despliegue no se lanza a mitad de una Fase I.
- **Un `api.env` que la API rechaza al arrancar deja la API pública caída**: el despliegue falla antes de la puerta y el
  proxy sigue parado. Es el comportamiento buscado (falla cerrado); la vuelta atrás es el commit anterior.
- La primera emisión del certificado ocurre al arrancar el proxy (TLS-ALPN-01 por el 443); `DEPLOY_TIMEOUT` la cubre.

### Comprobar desde el Mac

```bash
export VORACIOUS_API_TOKEN=$(ssh kevin@128.140.75.161 'export PATH="$HOME/.local/bin:$PATH"; cd ~/voracious-demo && scripts/issue_token.sh --via docker --tenant demo --roles analyst --subject check --ttl 15m')
scripts/check_public.sh --cors-origin http://localhost:5173 https://api.voracious.cloud
```

Una línea OK, FALLO u OMITIDO por comprobación; sale con 0 solo si ninguna falla. Comprueba DNS sin AAAA, TLS válido y
con al menos 14 días de caducidad, TLS ≤ 1.1 rechazado, HTTP/2, `/health` 200, cabeceras de seguridad sin `Server` ni
`Via`, 401 con `WWW-Authenticate`, 404 `DATASET_NOT_FOUND` con token, rutas cerradas (`/ready`, `/docs`, `/redoc`,
`/openapi.json`, `/`), CORS, y los puertos 80, 8000, 5432 y 2019 cerrados en la IP, además de que `https://IP` sin SNI no
sirva certificado. Sin `VORACIOUS_API_TOKEN` omite la comprobación con token y lo dice. El token no se pasa nunca como
argumento. Después, con el token, `GET /v1/charts/t2mrcd/models/1f573da9-554c-42e2-b961-683048c30e3c` debe dar 200, y
en el servidor `docker compose logs --since 5m api | grep http_request` debe mostrar como `client` la IP pública del Mac.

### Resultado del despliegue (2026-10-20)

`deploy.sh` terminó con «desplegado; público en https://api.voracious.cloud» y `scripts/check_public.sh` desde el Mac dio **todo OK**: TLS válido y HTTP/2, TLS ≤ 1.1 rechazado, DNS A sin AAAA, certificado de Let's Encrypt que caduca el 2027-01-18 y se renueva solo, cabeceras de seguridad sin `Server`, `401 UNAUTHENTICATED` con `WWW-Authenticate: Bearer`, con token `404 DATASET_NOT_FOUND` y `200` en el modelo de demo, `/ready`, `/docs`, `/redoc` y `/openapi.json` con `404 ROUTE_NOT_FOUND` en el borde, CORS (el preflight se admite, una cabecera no admitida da `400` y el `401` lleva `Allow-Origin` y expone `WWW-Authenticate` y `Retry-After`) y los puertos 80, 8000, 5432 y 2019 cerrados, sin certificado sin SNI. La API registra la IP real del cliente (campo `client`).

Este resultado es el estado real, no un objetivo: el procedimiento de arriba se ejecutó así y las comprobaciones se
hicieron desde fuera de la red del servidor. La guía de integración (`docs/guia/`) describe ya la URL pública.

### Vuelta atrás

- **Inmediata:** `docker compose --profile public stop proxy` en el servidor, o quitar la regla del 443 en Hetzner
  (al instante y sin SSH; útil si el servidor está saturado).
- **Completa:** desplegar el commit anterior con `deploy.sh`. Sin `proxy.env` el 443 queda cerrado.

### Renovación, límites de Let's Encrypt y `down -v`

- Caddy renueva solo, unos 30 días antes de caducar, y necesita el 443 abierto al mundo. Certificados y llave de la
  cuenta ACME viven en el volumen **`caddy_data`**: sobreviven a cada despliegue. **`docker compose down -v` los borra**
  (y la base, ver «Principios»): nunca. Perderlos obliga a emitir otros y gasta el límite de emisiones.
- Límites de Let's Encrypt (cifras del plan del arquitecto, **sin verificar contra su documentación**): 50
  certificados por dominio registrado y semana, 5 duplicados por semana y 5 validaciones fallidas por nombre y hora.
  Si una emisión falla, Caddy reintenta contra *staging* para no gastar el límite de producción.
- `check_public.sh` avisa con menos de 14 días; la vigilancia lo repite cada 3 horas (abajo).

### Restringir CORS

La demo admite cualquier origen: `deploy/demo/api.env` tiene `VORACIOUS_CORS_ALLOWED_ORIGINS=*`, sin credenciales
(seguro porque la autenticación es `Authorization: Bearer` y no hay cookies). Para limitarlo a unos orígenes: en
`api.env` pon una lista separada por comas, de la forma exacta `esquema://host[:puerto]`, sin barra final ni comodines
parciales (`https://front.example,http://localhost:5173`; `http` solo en `localhost`, `127.0.0.1` y `[::1]`), haz
commit y `scripts/deploy.sh`. No hay que tocar código. Un valor inválido hace que la API no arranque (ver el aviso de
arriba). Vacío cierra CORS del todo.

### Cambiar el tope de subida

`VORACIOUS_MAX_UPLOAD_MB` (50) y el `request_body max_size` del Caddyfile (51 MiB = el valor + 1 MiB para el multipart)
van juntos: si subes el primero, sube el segundo, o el borde cortará con su 413 antes de que la API decida.
`tests/unit/test_proxy_config.py` vigila la coherencia.

### Vigilancia (M4)

`.github/workflows/vigilancia.yml` corre cada 3 horas (y a mano con `workflow_dispatch`) desde un runner de GitHub,
fuera del servidor: `scripts/check_public.sh --cors-origin http://localhost:5173 https://api.voracious.cloud`, sin
token (omite esa comprobación). Reintenta `/health` 3 veces con 20 s de espera para no avisar por un reinicio de
despliegue, y falla si el certificado caduca en menos de 14 días (señal de renovación atascada). **Cómo te enteras:**
GitHub manda un correo por el fallo de un trabajo programado **a quien editó por última vez la línea `cron`**; hay
que tener activadas las notificaciones de Actions. Solo corre en la rama por defecto, así que no vigila nada hasta
que esté en `main`. Si no quieres depender de ello, la alternativa sin código es un monitor externo (UptimeRobot),
a costa de otra cuenta de un tercero.

### Registro de acceso y la IP

Para quien lea los registros:

- **Por el túnel SSH el operador sí está limitado** por el límite de peticiones y aparece con la IP de la puerta de
  enlace de `edge`, no con la suya.
- **Códigos del borde** (los genera Caddy, no están en el registro de la API): `ROUTE_NOT_FOUND` 404 también **sin token**
  para cualquier ruta fuera de `/v1` y `/health`, y `PAYLOAD_TOO_LARGE` 413 con `details: {}` en cualquier ruta por
  encima de 51 MiB.
- `deploy.sh` no funciona con `VORACIOUS_API_DOCS=false` hoy (ver ADR 0013, «Deuda»).

El registro de la API (`docker compose logs api`, líneas `http_request`) guarda el campo `client` con la IP del
cliente: es un dato personal (ADR 0013). Docker rota los logs en 5 ficheros de 10 MB por servicio; no hay otra
política de retención. Caddy no tiene registro de acceso.

## Emitir tokens

En el servidor (donde viven sops y la llave age), desde `~/voracious-demo`:

```bash
scripts/issue_token.sh --via docker --tenant <tenant> --roles analyst[,approver,admin] --subject <quién> [--ttl 8h]
```

Por la salida estándar sale **solo** el token; el resumen (sin token) va por la de error. Roles: `analyst` (lee y
opera), `approver` (lee y decide) y `admin` (todo, **dentro de su tenant**). `--ttl`: `^\d+[mhd]$`, máximo 7 d, por
defecto 8 h. El `sub` pasa a ser el actor de anotaciones, eventos y decisiones. Un token no se revoca: solo caduca o
se rota la llave.

Hoy **no hay login**: el token que usa un front lo emite el operador y se lo entrega por un canal seguro; el front
debe guardarlo en memoria o `sessionStorage` (nunca `localStorage`) y con TTL de 8 h o menos (ADR 0013).

**Sembrar la demo desde el Mac** (túnel abierto en otra terminal; el token se emite por SSH y no se escribe en
disco):

```bash
ssh -L 8000:127.0.0.1:8000 kevin@128.140.75.161         # terminal 1
export VORACIOUS_API_TOKEN=$(ssh kevin@128.140.75.161 'cd ~/voracious-demo && scripts/issue_token.sh --via docker --tenant demo --roles analyst --subject demo-seed --ttl 1h')
uv run python scripts/demo_seed.py --base-url http://127.0.0.1:8000
```

## Rotaciones

### Llave JWT, planificada

1. En el servidor: `scripts/jwt_keygen.sh --via docker demo-AAAA-MM`. El JWKS conserva el `kid` anterior y gana el
   nuevo; `jwt-signing.enc.yaml` pasa a tener solo la llave nueva.
2. Traer los dos ficheros al Mac, commitear y `scripts/deploy.sh` (recrea `api`).
3. Desde ahí se emite con el `kid` nuevo; los tokens viejos siguen valiendo hasta que caduquen.
4. Pasado el TTL máximo (7 d) desde el último token viejo, quitar el `kid` viejo de `jwks.json`, commitear y
   desplegar.

### Llave JWT, de emergencia

Los pasos 1 y 4 a la vez: generar la llave nueva, **quitar el `kid` comprometido** del JWKS y desplegar. Todos los
tokens firmados con la llave vieja dejan de valer al reiniciar la API.

### Contraseña de Postgres

1. `openssl rand -hex 32` (sin caracteres que haya que codificar en la URL).
2. Cambiarla en la base, de forma interactiva para que no quede en la línea de órdenes:
   `docker compose exec postgres psql -U voracious -d voracious -c '\password voracious'`.
3. `sops edit deploy/demo/secrets.enc.yaml` y cambiar **los dos** valores (`postgres_password` y la contraseña dentro de
   `database_url`).
4. `scripts/deploy.sh`.
5. Traer el cifrado al Mac y commitearlo.

### Receptores age

1. Editar `.sops.yaml`.
2. `sops updatekeys deploy/demo/*.enc.yaml` y `sops rotate -i …` en cada fichero.
3. Si la llave retirada pudo verse comprometida, **rotar también los secretos** (contraseña de Postgres y llave
   JWT): el historial de git sigue cifrado para ella.

## Recuperación si se pierde el servidor

Los volcados (`pgbackups`) viven **en el mismo servidor**: una copia fuera (cifrada) es deuda M8, sin aprobar. Lo
que sigue es lo que se puede hacer hoy.

- **Se pierde la llave age del servidor** (y no hay copia suya): los `*.enc.yaml` del repo ya no se pueden descifrar.
  No se recuperan, se **reemplazan**: llave age nueva y `.sops.yaml` nuevo; secretos nuevos
  (`openssl rand -hex 32`); llave JWT **nueva con otro `kid`** (la anterior no se puede reutilizar: su parte privada
  estaba en un cifrado perdido); recifrar todo y desplegar. Todos los tokens emitidos dejan de valer.
- **Sobrevive el volumen `pgdata`** (pero no los secretos): la base conserva su contraseña vieja, que ya no
  coincide con el secreto nuevo. Se cambia **dentro del contenedor `postgres`, por el socket local** (que no pide
  contraseña), antes de desplegar:

  ```bash
  docker compose exec postgres psql -U voracious -d voracious -c '\password voracious'
  ```

  y se pone esa misma contraseña en el secreto nuevo.
- **No sobrevive `pgdata`** pero sí un volcado: crear la pila con secretos nuevos y restaurar con
  `docker compose exec backup sh -c 'PGPASSWORD="$(cat /run/secrets/postgres_password)" pg_restore --clean --if-exists -d "$PGDATABASE" /backups/<fichero>'`.
- **Se pierde todo el servidor:** hay que reconstruir la demo desde el repo (código y cifrados inservibles sin la
  llave age) y volver a sembrar. Por eso conviene guardar una copia de la llave age fuera del servidor (por ejemplo en
  el gestor de contraseñas del dueño): es una decisión pendiente, porque implica sacar la llave del servidor.
