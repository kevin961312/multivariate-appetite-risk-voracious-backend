# Despliegue y operación de la demo

Guía de operación del servidor de demo (`kevin@128.140.75.161`, Ubuntu, 2 vCPU, Docker + Compose; carpeta
`~/voracious-demo`). Explica **cómo** se despliega y se opera; el **porqué** de cada decisión está en el
[ADR 0012](adr/0012-seguridad-minima-sops-jwt.md) (secretos y JWT), el [ADR 0010](adr/0010-empaquetado-docker-y-ci.md)
(imagen, CI) y el [ADR 0011](adr/0011-persistencia-en-postgres.md) (Postgres, backup).

> **Estado.** Los scripts y el código de este documento existen en el árbol de trabajo pero **aún no están
> commiteados**, y el redespliegue con secretos cifrados y JWT (T16) **todavía no se ha hecho**: la demo que corre hoy
> es la del 2026-10-20 sobre `ec05eee`, con `.env` y sin autenticación. Las secciones de «redespliegue» son un
> procedimiento por ejecutar.

## Principios

- **sops y age viven solo en el servidor y en CI**, no en el Mac del dueño (decisión del 2026-10-20). La llave age
  privada nace en el servidor y no sale de él; `.sops.yaml` tiene un único receptor, el servidor.
- Cifrar, generar llaves JWT y emitir tokens se hace **en el servidor**, con `--via docker` (la CLI de la imagen
  `voracious:local`). Los ficheros resultantes se traen al Mac con `scp` y se commitean con `/commit-seguro`.
- La API **no se expone**: `127.0.0.1:8000` y túnel SSH (`ssh -L 8000:127.0.0.1:8000 kevin@128.140.75.161`) hasta
  tener HTTPS y el login del banco. Postgres no publica ningún puerto.
- **Nunca `docker compose down -v`**: borra los volúmenes (`pgdata`, `datasets`, `pgbackups`) y con ellos la base de
  la demo. Para parar, `docker compose down` a secas.

## Requisitos del servidor

- Docker y el plugin `docker compose`; `curl`; `python3` (solo para el redespliegue inicial).
- **sops 3.13.3**, instalado desde el binario oficial de la release y comprobado contra su checksum:

  ```bash
  v=3.13.3
  curl -fsSLO "https://github.com/getsops/sops/releases/download/v${v}/sops-v${v}.linux.amd64"
  echo "e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b  sops-v${v}.linux.amd64" | sha256sum -c -
  sudo install -m 0755 "sops-v${v}.linux.amd64" /usr/local/bin/sops
  ```

  (El mismo SHA-256 que fija `ci.yml`; `deploy.sh` exige sops ≥ 3.9. Otra versión pide recalcular el SHA-256 contra el
  `checksums.txt` de la release **y** cambiarlo en `ci.yml`.)
- **age**: `sudo apt-get install -y age`.
- La imagen `voracious:local` construida **antes** de emitir tokens o generar llaves (ver T16, paso 5).

## Variables de despliegue

No son de la aplicación: las leen `docker-compose.yml` y los scripts. Todas opcionales salvo donde se dice.

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `DEPLOY_SECRETS_DIR` | `${XDG_STATE_HOME:-$HOME/.local/state}/voracious/demo/secrets` | Dónde deja `deploy.sh` los secretos descifrados (directorio 0700, ficheros 0444, **fuera del repo**; se niega si cae dentro). Compose **no arranca** sin ella; ponerla también en el `.env` (es una ruta, no un secreto) permite usar `docker compose ps/logs` a mano. **Debe ser la misma** que usa `deploy.sh`. |
| `DEPLOY_DIR` | `deploy/demo` | Configuración versionada: `secrets.enc.yaml`, `jwt-signing.enc.yaml`, `jwks.json`, `auth.env`. |
| `DEPLOY_TIMEOUT` | `300` | Segundos máximos de espera a `migrate` y a `/ready`. |
| `DEPLOY_API_URL` | `http://127.0.0.1:8000` | URL local con la que `deploy.sh` comprueba la API. |
| `DEPLOY_ENV_FILE` | `.env` de la raíz | `.env` que `deploy.sh` revisa en busca de secretos. |
| `SOPS_AGE_KEY_FILE` | `~/.config/sops/age/keys.txt` | Llave age privada (modo 600). |
| `SOPS_CONFIG` | `.sops.yaml` de la raíz | Reglas y receptores de sops (lo usa `jwt_keygen.sh`). |
| `VORACIOUS_IMAGE` | `voracious:local` | Imagen que usan `--via docker` en `issue_token.sh` y `jwt_keygen.sh`. |

## T16: redespliegue de la demo con secretos cifrados y JWT (por ejecutar)

Se hace **entero en el servidor**, migrando desde el `.env` actual **sin perder la base**. Por qué cada cosa:
`POSTGRES_PASSWORD_FILE` solo se usa al crear la base (`initdb`) y el volumen `pgdata` ya existe, así que el secreto
cifrado tiene que ser **la contraseña actual**; si no, `migrate` y `api` no conectan. El proyecto de Compose se
llama `voracious` (`name:` en el YAML), así que mover la carpeta reutiliza los volúmenes `voracious_pgdata`,
`voracious_datasets` y `voracious_pgbackups`.

1. **Copia previa** (con la pila actual en marcha, desde `~/voracious-demo`):

   ```bash
   docker compose exec backup sh -c 'pg_dump --format=custom --file=/backups/pre-sops-$(date -u +%Y%m%dT%H%M%SZ).dump'
   docker compose exec backup ls -l /backups     # el volcado pre-sops-… existe y no está vacío
   ```

2. **Instalar herramientas**: sops y age como en «Requisitos». Crear la llave age del servidor:

   ```bash
   install -d -m 700 ~/.config/sops/age
   age-keygen -o ~/.config/sops/age/keys.txt && chmod 600 ~/.config/sops/age/keys.txt
   age-keygen -y ~/.config/sops/age/keys.txt     # receptor público (age1…): es el que va en .sops.yaml
   ```

3. **Mover la carpeta y extraer la release** (empaquetada en el Mac con
   `COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata`):

   ```bash
   mv ~/voracious-demo ~/voracious-demo.prev
   mkdir ~/voracious-demo && tar -xzf <release>.tar.gz -C ~/voracious-demo
   install -m 600 ~/voracious-demo.prev/.env ~/voracious-demo/.env.pre-sops
   cd ~/voracious-demo
   ```

4. **`.sops.yaml`** en la raíz de `~/voracious-demo`, con un solo receptor (el del paso 2):

   ```yaml
   creation_rules:
     - path_regex: ^deploy/demo/.*\.enc\.yaml$
       age: age1…   # salida de age-keygen -y
   ```

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

13. **Limpieza tras unos días en verde**:
    `shred -u ~/voracious-demo/.env.pre-sops ~/voracious-demo.prev/.env`.

## Emitir tokens

En el servidor (donde viven sops y la llave age), desde `~/voracious-demo`:

```bash
scripts/issue_token.sh --via docker --tenant <tenant> --roles analyst[,approver,admin] --subject <quién> [--ttl 8h]
```

Por la salida estándar sale **solo** el token; el resumen (sin token) va por la de error. Roles: `analyst` (lee y
opera), `approver` (lee y decide) y `admin` (todo, **dentro de su tenant**). `--ttl`: `^\d+[mhd]$`, máximo 7 d, por
defecto 8 h. El `sub` pasa a ser el actor de anotaciones, eventos y decisiones. Un token no se revoca: solo caduca o
se rota la llave.

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
