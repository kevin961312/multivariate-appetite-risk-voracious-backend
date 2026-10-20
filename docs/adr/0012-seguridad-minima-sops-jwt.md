# ADR 0012 — Seguridad mínima: secretos con SOPS + age y autenticación JWT con roles

- **Estado:** Propuesto — acotado por [ADR 0013](0013-exposicion-publica-https.md) en «la API no se expone» (la demo ya se publica por HTTPS)
- **Fecha:** 2026-10-20

Cierra la parte más urgente del «paso de seguridad antes de vender» ([`ESTADO.md`](../ESTADO.md)): que los
secretos dejen de vivir en un `.env` y que la API deje de fiarse de una cabecera. **No** es todo ese paso: OIDC/SSO,
Row-Level Security, HTTPS, auditoría completa y `users`/`memberships` siguen pendientes (ver «Deuda»).

## Contexto

- **El tenant era una cabecera sin autenticar** (`X-Tenant-ID`): cualquiera que llegara a la API era cualquier
  tenant. Se salvaba solo porque la API no se expone (`127.0.0.1` y túnel SSH). Además el actor de anotaciones,
  eventos y decisiones lo escribía el cliente en el cuerpo (`actor`): suplantable aun con autenticación.
- **Los secretos vivían en el `.env` del servidor** y llegaban a los contenedores por `env_file`, así que se veían
  en `docker inspect`; no había copia cifrada ni forma de llevarlos de una máquina a otra sin copiar texto en claro.
- **El puerto `TenantContext` nunca existió.** `CLAUDE.md`, `arquitectura.md` y el ADR 0001 lo nombraban, pero el
  tenant era una dependencia de FastAPI (`api/tenant.py`) que pasaba un `str` a los casos de uso. Aquí se crea el
  puerto de verdad (`TokenVerifier`) y se corrigen los documentos.
- **Hay que poder pasar a integrarse con el IdP del banco sin reescribir.** La autenticación de hoy («nivel A») es
  un JWT que emitimos nosotros; el «nivel B» es el que emite el IdP del cliente.

### Amenazas y qué cubre cada medida

| Amenaza | Medida | ¿Cubierta? |
| --- | --- | --- |
| Secreto en claro en git, en el historial o en un tar/copia del repo | SOPS + age: el repo solo tiene `*.enc.yaml` | Sí |
| Traslado de secretos entre máquinas en claro | El cifrado viaja; el descifrado ocurre en el servidor | Sí |
| Secretos visibles en `docker inspect` o en el entorno del proceso | Compose secrets (ficheros) + `*_FILE`; `deploy.sh` comprueba `docker inspect` | Sí |
| Llamante sin token, o con el token de otro tenant | Middleware JWT de falla cerrada; el tenant sale del token | Sí |
| Analista que aprueba versiones o suplanta a otro en un registro | Matriz de roles (D7) y actor = `sub` (M1) | Sí |
| Token robado de vida larga | TTL máximo de 7 días en CLI **y** API (M4); sin revocación individual | Parcial (rotar la llave) |
| Registro de acceso con query o token | `--no-access-log` y registro propio por plantilla (M2) | Sí |
| **Servidor comprometido** | Nada de este ADR | **No** |

**SOPS protege el repositorio y el traslado; no protege un servidor comprometido.** Quien tenga root en el servidor
tiene la llave age y los ficheros descifrados (`DEPLOY_SECRETS_DIR`, P1 = A) y puede firmar tokens con la llave de
firma. Para eso hacen falta otras defensas (HTTPS, endurecimiento del anfitrión, un gestor de secretos con
auditoría) que están fuera de este paso.

## Decisión

### Decisiones del dueño (2026-10-20)

El dueño aprobó D1–D15 «como recomiendas» con **P1 = A** (los secretos descifrados se quedan en disco en
`DEPLOY_SECRETS_DIR`, fuera del repo, directorio 0700 y ficheros 0444, porque un reinicio del contenedor o del
servidor los vuelve a leer) y las mejoras **M1, M2, M4 y M7**. Después decidió **no instalar sops, age ni shellcheck
en su Mac**: ver «Herramientas solo en el servidor». Quedan **sin aprobar** M3 (cuatro ojos), M5 (secretos en tmpfs),
M6 (recarga del JWKS sin reiniciar), M8 (copia de seguridad cifrada fuera del servidor), M9 (documentación de la API
tras autenticación) y M10 (firma cosign de sops).

### D1–D15

- **D1. `X-Tenant-ID` se elimina por completo.** Sin modo `header` ni variable que apague la autenticación.
  Por qué: la regla de no dejar código zombie y que el sistema falle cerrado (una variable mal puesta no puede
  desactivar la seguridad). `api/tenant.py` y `TENANT_REQUIRED` desaparecen. La cabecera, si llega, se ignora.
- **D2. Firma EdDSA (Ed25519)** con lista de algoritmos permitidos configurable (`VORACIOUS_JWT_ALGORITHMS`;
  `EdDSA`, `ES256`, `RS256` o `PS256`; por defecto `EdDSA`). Nunca `none` ni `HS*`: una llave compartida permitiría
  firmar a quien solo debe verificar. En el nivel B, si el IdP usa RS256, cambia la lista, no el código.
- **D3. Las llaves públicas van en un JWKS en fichero** (`VORACIOUS_JWT_JWKS_FILE`), cada una con `kid` y `alg`.
  Es el formato que publica un IdP OIDC y permite rotar con dos `kid` vivos. Se rechazan `kty: oct`, llaves con
  miembros privados, `kid` repetidos y `alg` no permitido.
- **D4. PyJWT con el extra `crypto`.** Versiones fijadas en `uv.lock`: **PyJWT 2.15.1** y **cryptography 50.0.2**;
  mínimo declarado `pyjwt[crypto]>=2.10.1` por la CVE-2024-53861 (la 2.10.0 comparaba `iss` de forma parcial; hay
  una prueba de regresión con un `iss` que es prefijo del correcto). Solo vive en `infrastructure/auth/`
  (contrato 17). PyJWT es la que usa la documentación de FastAPI, está tipada y trae `PyJWK`/`PyJWKClient` (nivel B).
- **D5. Claims obligatorios:** `iss`, `aud`, `sub`, `jti`, `tenant`, `roles`, `iat` y `exp` (`nbf` si viene). `sub`
  se añadió al pedido original porque es estándar y alimenta los registros y M1; `jti` es obligatorio por M4.
  `tenant` cumple `^[A-Za-z0-9_-]{1,64}$`; `roles`, una lista no vacía de roles conocidos; `sub`, 1 a 256 caracteres
  imprimibles; `jti`, 1 a 128.
- **D6. Roles en inglés en el claim:** `analyst | approver | admin`. Cambiarlos más tarde solo cuesta reemitir tokens.
- **D7. La matriz de roles entra ahora, en la capa API** (`api/auth.py`; dominio y casos de uso no la conocen):
  - `Reader` (todos los `GET` de negocio): analyst, approver, admin.
  - `Operator` (subir datos, pedir ajustes, límites, exclusiones, modelos y tuberías, puntuar, anotar, registrar
    eventos, recalibrar, extender, cancelar y **proponer** versión): analyst, admin.
  - `Decider` (`…/versions/{n}/approve` y `…/reject`): approver, admin.
  - Un token puede llevar varios roles. `admin` lo es **de su tenant**: no hay superadministrador entre tenants.
  Por qué: sin matriz, un token de analista podría aprobar versiones.
- **D8. Se exige token en todo salvo una lista de rutas públicas**, con un middleware ASGI puro (no
  `BaseHTTPMiddleware`) que verifica antes de leer el cuerpo. Públicas, solo por HTTP y con coincidencia exacta:
  `/health`, `/ready`, `/docs`, `/docs/oauth2-redirect`, `/redoc` y `/openapi.json`. Una ruta nueva queda
  protegida aunque nadie se acuerde; una inexistente responde 401 sin token y 404 con él.
- **D9. Errores nuevos.** `401 UNAUTHENTICATED` con `details.reason` de un conjunto cerrado y `WWW-Authenticate`;
  `403 FORBIDDEN` con `details.required_roles`. Catálogo completo en la enmienda del ADR 0005.
- **D10. `VORACIOUS_DATABASE_URL` directa se mantiene** para desarrollo, CI y tests y es excluyente con
  `VORACIOUS_DATABASE_URL_FILE`. Compose solo usa `_FILE`. `deploy.sh` se niega a desplegar si el `.env` del
  servidor trae `POSTGRES_PASSWORD`, `VORACIOUS_DATABASE_URL`, `PGPASSWORD` o algo `*PRIVATE*` con valor.
- **D11. La llave privada nunca entra en `Settings` ni en la API.** La CLI la lee de un fichero o de la entrada
  estándar (`-`); los scripts la pasan por una tubería desde `sops decrypt` sin escribirla en disco en claro.
- **D12. La llave de firma va en su propio fichero cifrado** (`deploy/demo/jwt-signing.enc.yaml`, claves `kid` y
  `jwt_private_key`). `deploy.sh` no lo descifra nunca: solo lo hace `issue_token.sh`.
- **D13. Duración:** 8 h por defecto y 7 días como máximo; margen de reloj de 30 s (0 a 300). La única revocación es
  rotar la llave.
- **D14. El JWKS (`deploy/demo/jwks.json`) y `deploy/demo/auth.env` (`iss`, `aud` y la ruta del JWKS) se versionan en
  claro:** no son secretos.
- **D15. Cada despliegue recrea `api` y `backup`** para que lean los secretos y el JWKS vigentes (un fichero
  reemplazado es otro inodo; el montaje viejo seguiría viendo el anterior). Interrumpe los trabajos en curso
  (`JOB_INTERRUPTED`), igual que cualquier reinicio.

### Mejoras aprobadas

- **M1. El actor sale del `sub` del token.** `actor` desaparece de los cuerpos de anotaciones, eventos
  estructurales, aprobación, rechazo y recalibración; enviarlo da `422` (campo extra). Por qué: con JWT el cuerpo
  seguía permitiendo suplantar a otro en `decided_by`/`actor`. Es un cambio de contrato, barato mientras el único
  cliente es `demo_seed`.
- **M2. Registro de acceso con identidad** (`api/access_log.py`): una línea `http_request` por petición con método,
  **plantilla** de la ruta (sin identificadores), estado, duración y, si hubo token válido, `sub`, `tenant` y `jti`;
  si no, `auth_failure` con el motivo. Nunca token, query, cabeceras ni cuerpos. Es una auditoría ligera, no la
  completa. Las rutas públicas van a nivel `debug` (el `HEALTHCHECK` pediría `/health` cada 30 s).
- **M4. La API rechaza `exp − iat` > 7 días** (`lifetime_too_long`) y exige `jti`: un token robado de vida larga
  no sirve aunque lo hubiera firmado una versión antigua de la CLI.
- **M7. CI con sops, age y shellcheck.** Corre el test opcional de cifrado y la etapa `shellcheck` de la compuerta.

### Verificación de tokens

`JwtTokenVerifier` (puerto `TokenVerifier` en `application/ports.py`) sigue este orden y nunca registra el token ni
el texto de la excepción de la librería (cada motivo tiene un mensaje fijo):

1. Forma: ≤ 8192 bytes y tres segmentos (`malformed`).
2. Cabecera sin verificar: `alg` permitido, `kid` presente y en el JWKS, `alg` igual al de la llave de ese `kid`
   (impide la confusión de algoritmo) y **sin `crit` ni `b64`** (extensiones que la librería no gestiona del todo y
   que no se necesitan).
3. Firma y claims registrados con PyJWT: `aud` y `iss` se comparan **enteros**, con longitud mínima de llave
   exigida por la librería al verificar.
4. Claims propios (D5) y vida máxima (M4).

**`aud` estricto:** se compara con la audiencia configurada. *A revisar en el nivel B*: algunos IdP mandan una lista.

**Los 12 motivos de 401** (`details.reason`): `missing_token`, `malformed`, `unknown_key`, `algorithm_not_allowed`,
`bad_signature`, `expired`, `not_yet_valid`, `wrong_issuer`, `wrong_audience`, `missing_claim`, `invalid_claim` y
`lifetime_too_long`. Internamente `NO_CREDENTIALS` viaja como `missing_token` (el nombre evita la regla S105 de
ruff, que toma por contraseña todo identificador con «token»). `WWW-Authenticate: Bearer realm="voracious"`; con
token presentado y rechazado se añade `error="invalid_token"`.

### Orden de middlewares y casos límite

- **Acceso → autenticación → aplicación.** El de acceso va fuera para registrar también los 401 (con su motivo).
- Las rutas públicas lo son **solo por HTTP**. Un WebSocket exige el mismo token y, si falla, se cierra con `1008`
  antes de aceptarlo; un scope de otro tipo se descarta. Hoy la API no tiene WebSockets: es falla cerrada.
- El token se lee **solo** de `Authorization: Bearer` (nunca de la query); varias cabeceras, espacios internos o
  más de 8192 bytes son `malformed`.
- Los `scopes` desconocidos del token se descartan; solo cuentan los `roles` del claim.
- **La autorización por rol ocurre después de leer el cuerpo en las rutas con cuerpo Pydantic**: FastAPI resuelve el
  cuerpo y las dependencias juntos, así que con un JSON mal formado y un rol insuficiente la respuesta es `422`
  antes que `403`. La autenticación (401) sí va antes de leer nada. Se acepta (ver «Deuda»).
  **Corrección (2026-10-20, verificada por el revisor):** la frase anterior es imprecisa. El rol se comprueba
  después de decodificar el JSON y antes de validarlo contra el esquema: un JSON sintácticamente inválido responde
  `422` aunque el rol no baste; un JSON válido que no cumple el esquema responde `403` si el rol no basta.
- **`uvicorn --no-access-log`** en el `CMD` de la imagen. Por qué: el registro de acceso de uvicorn escribe la ruta
  cruda **con la query** (p. ej. `?access_token=…`, que la API ignora pero el cliente podría mandar) y duplicaría el
  propio. El CI comprueba que una marca puesta en la query no llega a los logs.

### Secretos: SOPS + age + Compose secrets

- `deploy/**/*.enc.yaml` se versionan cifrados con SOPS y age; `.sops.yaml` (con **un solo receptor**, el servidor)
  dice con qué. Los nombres de las claves quedan en claro y los valores van `ENC[AES256_GCM,…]` con MAC.
- `scripts/deploy.sh` descifra `postgres_password` y `database_url` de `deploy/demo/secrets.enc.yaml` a
  `DEPLOY_SECRETS_DIR` (por defecto `${XDG_STATE_HOME:-$HOME/.local/state}/voracious/demo/secrets`; se niega a usar un
  directorio dentro del repo), con `umask 077`, `mv` atómico y limpieza de temporales por `trap`. Compose los monta
  en `/run/secrets/…`; las imágenes los leen con `*_FILE`. `backup` lee la contraseña del fichero dentro de su
  `sh -c`: ya no está en su entorno.
- Fuera de Swarm Compose **ignora `uid`, `gid` y `mode`** de los secretos; por eso los ficheros son 0444 dentro de un
  directorio 0700 y no se depende de esos campos.
- `scripts/deploy.sh` verifica al final que `docker inspect` de los contenedores del proyecto no contiene ningún
  valor secreto, que la API solo está en `127.0.0.1` y que Postgres no publica puertos.
- Aviso de operación: `POSTGRES_PASSWORD_FILE` solo se usa en el `initdb`. Con un volumen `pgdata` existente, el
  secreto cifrado **tiene que ser la contraseña actual** de la base, o `migrate` y `api` no conectarán.

### Herramientas solo en el servidor (decisión del dueño, 2026-10-20)

El dueño no quiere sops, age ni shellcheck en su Mac. Consecuencias:

- **sops y age viven solo en el servidor y en CI.** La llave age privada nace en el servidor y no sale de él.
  `.sops.yaml` tiene un único receptor (el servidor). Cifrar, emitir tokens y generar llaves JWT se hace allí, con
  `--via docker` (la CLI de la imagen `voracious:local`, `--network none --read-only`), sin `uv` en el servidor.
- Para traer al repo los cifrados y el JWKS se copian desde el servidor (`scp`) y se commitean con `/commit-seguro`.
  El Mac no puede descifrar: no hay un segundo receptor. Es una pérdida deliberada de comodidad; el riesgo es que
  **perder la llave age del servidor sin copia fuera es perder los secretos cifrados** (ver «Recuperación» en
  [`despliegue.md`](../despliegue.md)).
- **shellcheck en la compuerta**: la etapa `shellcheck` de `scripts/gate.sh` usa el del `PATH` y, si no hay, la
  imagen `koalaman/shellcheck:v0.11.0@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d`
  con `--network none --read-only --cap-drop ALL` y el repo montado en solo lectura. Sin shellcheck ni Docker, la
  etapa sale en rojo. **Dependabot no ve ese digest** (está en un script, no en un Dockerfile ni en un workflow):
  se actualiza a mano.
- **Versiones de las herramientas** (tres contextos, tres versiones, aceptado): sops **3.13.3** en CI, fijado por
  SHA-256 `e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b` del binario `linux.amd64` de la release
  (en el servidor se instala igual, comprobando el `checksums.txt`); age por `apt` en CI y en el servidor;
  shellcheck **0.9.0** en CI (Ubuntu 24.04), **0.10.0** en la imagen `gate` (Debian) y **0.11.0** por Docker.

### Nivel B (IdP del banco)

Cambian: la fuente del JWKS (de fichero a URL, con caché y, probablemente, M6), `iss`/`aud`, la lista de
algoritmos y quizá un mapeo de claims (el IdP no escribirá `tenant` y `roles` con esos nombres). **Se quedan:** el
puerto `TokenVerifier`, el middleware, la matriz de roles y los códigos de error. A revisar entonces: `aud` como
lista, longitud mínima de llaves RSA al cargar el JWKS (hoy solo la comprueba PyJWT al verificar) y el aislamiento
de tenants si el IdP es compartido.

## Alternativas descartadas

- **Docker/Swarm secrets.** Exige Swarm; fuera de Swarm los secretos de Compose son ficheros, que es lo que ya se usa.
- **Vault / OpenBao.** Servicio que operar y proteger; desproporcionado con un solo servidor.
- **Doppler / Infisical.** Dependencia de un tercero y de red para arrancar.
- **git-crypt.** Cifra ficheros enteros, sin diff por clave ni varios receptores razonables.
- **Secretos en variables de entorno.** Se ven en `docker inspect` y heredan a los procesos hijos.
- **HS256 (secreto compartido).** Quien verifica podría firmar; además el secreto viviría en la API.
- **API keys opacas en la base.** Reinventa roles, caducidad y rotación y no migra al IdP del banco.
- **Keycloak propio.** Un IdP completo que operar antes de que exista el cliente que lo pida.
- **python-jose** (abandonada y con CVE), **authlib** (pesada; mezcla cliente y servidor OAuth) y **joserfc**
  (válida pero con menos adopción).
- **Modo `header` (conservar `X-Tenant-ID` para desarrollo).** Código zombie y un interruptor que apaga la seguridad.
- **Autorización en los casos de uso.** Mezcla una política de acceso con reglas de la aplicación; la matriz es del
  borde HTTP y se sustituye cuando haya un IdP.
- **sops, age y shellcheck instalados en el Mac.** Rechazado por el dueño (ver arriba).

## Consecuencias

- Rompe el contrato: toda ruta de negocio exige `Authorization: Bearer`; `X-Tenant-ID` se ignora; `actor` en el
  cuerpo da 422. `demo_seed.py` usa `VORACIOUS_API_TOKEN` o `--token-file`.
- La API **no arranca sin** `VORACIOUS_JWT_JWKS_FILE`, `_ISSUER` y `_AUDIENCE` (`ConfigurationError`).
- `docker-compose.yml` ya no arranca sin `DEPLOY_SECRETS_DIR`. CI ganó pasos y el trabajo `image` levanta la pila
  Compose completa con secretos de prueba.
- 17 contratos de `import-linter`: el 17 prohíbe `jwt` y `cryptography` fuera de `infrastructure/auth`, y se añaden
  a los contratos 2, 3 y 8.
- **La API sigue sin exponerse** (`127.0.0.1` y túnel SSH) hasta tener HTTPS y el login del banco.

## Deuda

- Longitud mínima de llaves RSA al cargar el JWKS (hoy la comprueba PyJWT al verificar): nivel B.
- Autorización después de decodificar el cuerpo en rutas con cuerpo Pydantic: un JSON sintácticamente inválido da 422 antes que 403 (ver la corrección del 2026-10-20 más arriba).
- `docker run` de los scripts sin endurecer del todo: montar solo `scripts/`, `--user`, `no-new-privileges` y
  `--cap-drop ALL` en keygen y emisión de tokens.
- Tres versiones de shellcheck; digest de shellcheck y SHA-256 de sops (repetido en `ci.yml`) a actualizar a mano.
- `mv` no atómicos entre los dos ficheros de `jwt_keygen.sh`.
- Trabajo `image` de CI sin ejecutar aún en GitHub.
- SC2155 previo en el trabajo `sanitizers`.
- Sin revocación por token (solo rotar la llave); el resto del paso grande y las mejoras M3, M5, M6, M8, M9 y M10
  están en [`ESTADO.md`](../ESTADO.md).

## Enmienda 2026-10-20 (paso E): HTTPS hecho y la API ya se expone (demo)

El texto original no se reescribe. Decisiones y alternativas en el [ADR 0013](0013-exposicion-publica-https.md).

- **HTTPS, hecho** (Caddy con Let's Encrypt delante de la API). Sale del paso grande de seguridad. **«La API sigue sin
  exponerse» (Consecuencias, `ESTADO.md`) queda superado** para la demo: `https://api.voracious.cloud`, solo con datos
  sintéticos o de prueba (P1 del dueño). La condición «login del banco» sigue vigente para datos del banco. Sigue
  pendiente del paso grande: OIDC/SSO, Row-Level Security, auditoría completa, `users`/`memberships` e
  instalación dedicada vs. SaaS compartido.
- **El token entra por el front de forma provisional, hasta OIDC.** Todavía no hay login: lo emite el operador con
  `issue_token.sh` y el front lo pega. Un XSS del front lo expone; mitigación: memoria o `sessionStorage` (nunca
  `localStorage`) y TTL de 8 h o menos. Es una fila nueva de la tabla de amenazas (parcial, depende del front).
- **Filas nuevas de amenazas:** interceptación en el camino (TLS, HSTS, 80 cerrado; cubierta), ruta de negocio sin token
  (puerta de `deploy.sh`; cubierta), inundación (límite por IP, parcial), acaparar cómputo (cupo por tenant, parcial).
- **IP en el registro de acceso (M2):** el campo `client` guarda la IP del cliente (dato personal, Ley 1581). La línea
  `http_request` sigue sin token, query, cabeceras ni cuerpos. Retención: la rotación de Docker (5 × 10 MB). Los
  *preflight* de CORS van a nivel `debug`.
- **Orden de middlewares** (D8): ya no es «acceso → autenticación → aplicación». De fuera adentro: proxy headers →
  acceso → CORS → barrera de errores → límite de peticiones → autenticación → aplicación. El 401 sigue saliendo antes de
  leer el cuerpo.
- **D8, rutas públicas:** `/health` y `/ready` siempre; la documentación solo con `VORACIOUS_API_DOCS=true` (por
  defecto). En el borde público solo se publica `/health`.
- **M9 (documentación tras autenticación o desactivable), cerrada** como la M2 del ADR 0013: `VORACIOUS_API_DOCS=false`.
- **CORS:** `VORACIOUS_CORS_ALLOWED_ORIGINS=*` en la demo. Es seguro porque el token va en `Authorization` y no hay
  cookies; el navegador nunca lo manda por su cuenta.
- **Versiones de las herramientas:** sops 3.13.3 y age v1.3.2 se instalaron en el servidor **sin sudo**, en
  `~/.local/bin`, verificados contra el SHA-256 y el `digest` de GitHub (la contraseña de sudo no se recuerda). Una
  orden por ssh sin terminal no carga ese PATH: ver [`despliegue.md`](../despliegue.md).
