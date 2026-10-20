# ADR 0013 — Exposición pública de la API por HTTPS detrás de Caddy

- **Estado:** Propuesto (redactado por el documentador el 2026-10-20; lo acepta el dueño)
- **Fecha:** 2026-10-20
- **Relacionado:** [ADR 0012](0012-seguridad-minima-sops-jwt.md) (JWT, roles, secretos; este ADR supera su «la API no
  se expone»), [ADR 0010](0010-empaquetado-docker-y-ci.md) (imagen, Compose, CI),
  [ADR 0011](0011-persistencia-en-postgres.md) (Postgres, red interna), [ADR 0005](0005-api-fase-i-fase-ii.md)
  (catálogo de códigos, enmienda de esta fecha) y [ADR 0003](0003-api-asincrona.md) (carriles de cómputo).

La API pasa de `127.0.0.1` y túnel SSH a responder en **`https://api.voracious.cloud`**, con el 443 como único puerto
público. Es una exposición **de pruebas**, no la del banco: lo que cierra este ADR no es el «paso grande de
seguridad» de [`ESTADO.md`](../ESTADO.md) (OIDC, Row-Level Security, auditoría completa, instalación dedicada).

## Contexto

- **El criterio anterior era «hasta tener HTTPS y el login del banco»** (ADR 0012, `ESTADO.md`). El dueño lo cambió
  el 2026-10-20 al pedir exponer la API para probar contra un front real. La condición «login del banco» sigue
  vigente para **datos del banco**, no para una demo con datos de prueba (P1).
- **El front va en otro repositorio y aún no está pensado.** Este repositorio no lo construye ni decide dónde se
  aloja. Lo único que necesita del backend es poder llamar a la API desde un navegador (CORS) y saber cómo tratar el
  token. Las pautas para cualquier front están al final de este ADR.
- **El servidor es pequeño** (2 vCPU, 3.7 GiB) y los cálculos duran minutos (una Fase I ≈ 6 min, `ESTADO.md`). Con
  la API en internet, lo que antes acotaba el túnel (quién llega) lo tienen que acotar el cortafuegos, el tope de
  peticiones y un cupo de trabajos.
- **T16 está hecho** (2026-10-20): la demo corre `74aae38` con SOPS + age + JWT, y sin él `deploy.sh` no puede
  descifrar secretos ni abrir el 443. Era el prerrequisito duro de este paso.
- **Incidencia de CI heredada de T16:** con `a34bb70` la compuerta de `main` quedó en rojo porque el `.sops.yaml` de
  la raíz (receptor: el servidor) hacía fallar el `_encrypt` de `tests/integration/test_deploy_sops.py` (sops no
  encontraba regla para `/dev/stdin`). Se corrige en este paso: los tests cifran con `sops --config <tmp>` y el
  trabajo `image` aísla su configuración en `RUNNER_TEMP`. **Lección:** ningún test ni paso de CI depende del
  `.sops.yaml` ni de los cifrados reales del repo.

## Decisiones del dueño (2026-10-20)

El dueño aprobó «como recomiendas» el plan del arquitecto (P1–P6) y las mejoras M1, M2, M3 y M4. Después fijó dos
cosas que mandan sobre el plan.

- **P1. Solo datos sintéticos o de prueba.** Cita: «esto no es para el banco o necesita actualmente seguridad formal
  no, es para yo hacer pruebas quiero conectar a la pagina web y una ruta ya con un front formal hacer las cosas y que
  se comunique con el servidor». Por qué importa: siguen sin existir OIDC, Row-Level Security, auditoría completa ni
  copia de seguridad fuera del servidor. Aceptarlo es aceptar un riesgo; cuesta rehacerlo si luego entran datos
  reales sin haber cerrado ese paso.
- **P2. Puerto 80 cerrado.** **P3. Documentación cerrada en el borde.** **P4. 600 peticiones/min por IP, ráfaga de
  120.** **P5. SSH (22) abierto, con solo llave.** **P6. `api.voracious.cloud` es la URL permanente.**
- **CORS abierto a cualquier origen.** Cita: «lo que debe permitir el backend es que yo pueda hacer los llamados de
  las apis desde el front que yo quiera». Sustituye a la propuesta del arquitecto (lista de orígenes, la mejora M9 del
  ADR 0012, que había pasado a ser la tarea obligatoria E14).
- **M1** cupo de trabajos por tenant; **M2** documentación apagable; **M3** registro CAA; **M4** vigilancia externa.
  M5 (`Idempotency-Key`), M6 (revocación por `jti`), M7 a M14 del plan: **no aprobadas**.
- **sudo:** el dueño no recuerda la contraseña de `kevin`. Consecuencia práctica: sops y age se instalaron sin sudo y
  el bloque con sudo del plan queda reducido (ver [`despliegue.md`](../despliegue.md)).

## Decisión

### 1. Proxy y TLS: Caddy 2 oficial, sin plugins

Servicio `proxy` de Compose, en el perfil `public`, con una imagen mínima propia (`deploy/proxy/Dockerfile`) sobre
`caddy:2.11.7-alpine` fijada por versión **y** digest, usuario 10002 y el Caddyfile dentro. No compila nada: se
construye en segundos y Dependabot sigue la base.

- **Por qué Caddy y no nginx + certbot:** trae la emisión y la renovación del certificado (con ARI) y, si una emisión
  falla, reintenta contra *staging* para no gastar el límite de producción. nginx necesitaría un contenedor de certbot,
  un cron, un *hook* de recarga y un webroot.
- **Endurecimiento:** no root, raíz de solo lectura, `cap_drop: ALL`, `no-new-privileges`, `admin off`,
  `persist_config off`. El binario oficial trae `cap_net_bind_service` como capacidad de fichero y con
  `cap_drop: ALL` el kernel se niega a ejecutarlo; la imagen se la quita (`setcap -r`) porque Docker (≥ 20.10) ya deja
  abrir el 443 sin capacidades en el espacio de red del contenedor.
- **Solo 443/TCP.** Sin HTTP/3 (`protocols h1 h2`), así que no se publica UDP.
- **El 80 está cerrado** y ACME usa **TLS-ALPN-01** en el 443 (`disable_http_challenge`). Por qué: un cliente
  configurado con `http://` mandaría su token en claro en la primera petición. Con una redirección 308 lo manda igual y
  además no se entera; con el 80 cerrado la conexión falla antes de enviar nada. Contradice el «HTTP→HTTPS» literal del
  pedido original; lo decidió el dueño (P2).
- **ACME sin correo:** no hay datos personales en el repo. Límite de emisiones y renovación: ver «Deuda» y
  [`despliegue.md`](../despliegue.md).
- **Modo `internal`** (`PROXY_TLS_MODE=internal`, CA propia de Caddy) solo para CI y pruebas; la demo usa `acme`.
  Un modo vacío o desconocido hace que el Caddyfile no se lea: el proxy no arranca (falla cerrado).
- **Límites:** 192 MiB, 0.5 CPU, 128 pids, `GOMEMLIMIT=160MiB`, `GOMAXPROCS=1`.

### 2. Límites de tamaño, tiempo y peticiones

- **Cuerpo:** `request_body max_size 51MiB` en todo el sitio = `VORACIOUS_MAX_UPLOAD_MB` + 1 MiB para el multipart. Es
  también **el único tope de las rutas con cuerpo JSON**, que la app lee enteras. Entre 50 y 51 MiB en
  `POST /v1/datasets` responde la API con su 413 detallado (`details.max_bytes`); por encima, el 413 del borde
  (`PAYLOAD_TOO_LARGE`, sin `details`). Un test (`tests/unit/test_proxy_config.py`) vigila que ambos valores coincidan:
  **si se sube `VORACIOUS_MAX_UPLOAD_MB`, hay que subir también el `max_size` del Caddyfile.**
- **Tiempos del lado del cliente:** `read_header` 10 s (slowloris), `read_body` 2 min (50 MiB a ≥ 0.5 MB/s), `write`
  5 min (en Go cuenta desde las cabeceras e incluye leer el cuerpo y procesar), `idle` 2 min.
- **Hacia la API:** `dial` 5 s, `response_header` 2 min (cubre el parseo de un CSV grande y el paso síncrono
  `/extension`), `keepalive` 60 s —por debajo del `--timeout-keep-alive 75` de uvicorn para no recibir 502 por
  reutilizar una conexión ya cerrada— y `max_conns_per_host 64` como contrapresión hacia el único worker.
- **Peticiones por IP, en la app y no en el borde** (`api/rate_limit.py`): cubo de fichas en memoria, ASGI puro, antes
  de la autenticación (acota también las ráfagas de 401) y sin leer el cuerpo. 600 por minuto con ráfaga de 120
  (`VORACIOUS_RATE_LIMIT_PER_MINUTE`, `_BURST`; operativos, no estadísticos). Responde `429 RATE_LIMITED` con
  `Retry-After` y `details.retry_after_seconds`. Exentos 127.0.0.0/8 y `::1` (el `HEALTHCHECK` y la puerta de
  `deploy.sh` llaman desde dentro). Por qué en la app: se prueba en la compuerta, devuelve el formato uniforme de
  error, viaja con la app a una instalación dedicada y podrá limitar por tenant. Coste aceptado: la ráfaga llega a
  Python, aunque el rechazo cuesta microsegundos; lo volumétrico lo filtra Hetzner (capas 3 y 4).
- **Cómputo:** el límite por IP no acota el cálculo, así que se añade el **cupo por tenant (M1)**: 4 trabajos activos
  (`queued` o `running`) por tenant (`VORACIOUS_MAX_ACTIVE_JOBS_PER_TENANT`). Cuentan los ajustes y límites sueltos más
  las tuberías (Fase I y recalibración); los hijos de una tubería no. Al superarlo, `429 TOO_MANY_JOBS` con
  `details {max_active_jobs, active_jobs}` y **sin `Retry-After`** (no se sabe cuándo se libera un hueco). Se comprueba
  **después** de las validaciones síncronas: un error de la entrada se informa antes que el cupo. No limita
  exclusiones, ensamblado, puntuaciones, propuestas, extensión, subidas ni sesiones `stepwise` (ligeras o síncronas).
  Con un hilo de estimación y uno de calibración, 4 son unos 24 minutos de cola por tenant. **El cupo es blando**: ver
  «Deuda».

### 3. Cabeceras de seguridad, todas en Caddy

Es un solo sitio y así cubre también los 404, 413 y 502 que genera el propio Caddy. `Strict-Transport-Security:
max-age=31536000; includeSubDomains` (sin *preload*, que exige el dominio raíz), `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `X-Frame-Options: DENY` y `Content-Security-Policy:
default-src 'none'; frame-ancestors 'none'`. Sin `Server` ni `Via`: Caddy los quita y uvicorn arranca con
`--no-server-header`. **Ninguna de ellas rompe a un front en otro origen:** CSP y `X-Frame-Options` solo actúan si la
respuesta se muestra como documento o en un iframe, no en `fetch`; `no-store` no afecta a la caché del *preflight*
(la rige `Access-Control-Max-Age`); HSTS con `includeSubDomains` sobre `api` solo cubre `*.api.voracious.cloud`, no la
raíz. No se añade `Cross-Origin-Resource-Policy`. Caddy no toca `Origin`, `Access-Control-*` ni `Vary`: los decide la
API.

### 4. Rutas públicas del borde

Caddy solo pasa `/health` y `/v1/*` (cualquier método: el *preflight* `OPTIONS` lo resuelve la API). Todo lo demás da
`404 ROUTE_NOT_FOUND` en JSON, también con otro `Host`. `/ready` **no se publica**: revela el estado de la base y del
almacenamiento y cada llamada gasta una conexión del pool; lo siguen usando el operador y `deploy.sh` por
`127.0.0.1:8000`. La documentación (`/docs`, `/redoc`, `/docs/oauth2-redirect`, `/openapi.json`) tampoco sale a
internet (P3): Swagger carga JS de un CDN, incompatible con la CSP, y el integrador recibe el `openapi.json` con la guía.
La puerta real sigue siendo la autenticación de la app: Caddy compara rutas ya normalizadas y cualquier ruta que no sea
pública exacta da 401 dentro de la app.

**M2:** `VORACIOUS_API_DOCS=false` apaga la documentación **dentro de la app** (`/docs`, `/redoc`,
`/openapi.json` y `/docs/oauth2-redirect` dejan de existir y las rutas públicas son solo `/health` y `/ready`).
`app.openapi()` sigue funcionando para la tabla de rutas del registro de acceso y para exportar el OpenAPI. En la demo
queda en `true` (el borde ya la bloquea y el operador la usa por el túnel); `false` es para instalaciones dedicadas.
Cierra la M9 del ADR 0012 (documentación tras autenticación o desactivable).

### 5. Cortafuegos: el de Hetzner, no ufw

Se gestiona desde la consola web, sin sudo, y filtra fuera de la VM, así que Docker no puede saltárselo (sí se salta
ufw en los puertos publicados). Aplicado hoy: `voracious-demo` con TCP 22, TCP 443 e ICMP desde cualquier IPv4/IPv6 y
sin reglas de salida (equivale a permitir toda salida: ACME, apt, imágenes). El cortafuegos previo del dueño,
`firewall-1` (22, 80 y 443), quedó **desvinculado** del servidor con su permiso, sin borrarlo: las reglas de varios
cortafuegos se **suman**, y mientras siguiera aplicado, el 80 habría estado abierto. Comprobado desde fuera: el 80 está
cerrado y SSH funciona. ufw no se toca (activarlo en remoto arriesga quedarse fuera); solo se diagnostica.

Una lista de IP en el 443 es posible pero rompe ACME TLS-ALPN-01 y HTTP-01 (Let's Encrypt valida desde varias IP que no
publica); exigiría DNS-01 con la API de Hostinger (no aprobado).

**Redes de Docker:** `backend` es `internal: true` (postgres, migrate, backup y api: sin salida a internet) y `edge`
(subred fija `DEPLOY_EDGE_SUBNET`, 172.29.80.0/24 por defecto) une `api` y `proxy`, que tiene la IP fija
`DEPLOY_PROXY_IP` (.10). El proxy no ve Postgres y Postgres no ve el proxy. La API sigue publicada en
`127.0.0.1:8000` para el operador. Nota de honestidad: como `edge` no es interna, **la API sí tiene salida a internet
por esa red**; hoy no la usa (no hay llamadas salientes) y no se ha restringido.

### 6. Cambios en la app

- **`VORACIOUS_TRUSTED_PROXIES`:** IP o CIDR validadas al arrancar. Se rechazan `*`, los nombres de host y `/0` (un
  valor que no es IP lo convertiría `ProxyHeadersMiddleware` en literal **sin avisar**; confiar en todo equivale a no
  filtrar). En Compose vale la IP fija de Caddy. La imagen añade `--no-proxy-headers` para que decida solo la app (uvicorn
  confiaría además en `127.0.0.1`).
- **Invariante que no se toca: Caddy no lleva `trusted_proxies`.** Es el primer salto y reescribe `X-Forwarded-For` con
  la IP real. El limitador exime a 127.0.0.0/8 y `::1`: si algún día se añadiera `trusted_proxies` a Caddy, un cliente
  podría mandar `X-Forwarded-For: 127.0.0.1` y quedar exento del límite. Caddy es el primer salto, así que un cliente
  no puede falsificarla. CI lo prueba, incluido `X-Forwarded-For: 127.0.0.1`, que de colarse eximiría del límite.
- **El registro de acceso gana el campo `client`** (IP sin puerto): ver «La IP como dato personal».
- **No hay `VORACIOUS_PUBLIC_BASE_URL`:** la app no genera URLs absolutas (ni `Location` ni `url_for`) y con
  `X-Forwarded-Proto` la redirección de barras sale en `https`.
- **`iss` se queda en `voracious-demo`:** cambiarlo invalidaría los tokens y no hace falta.
- **Caddy sin registro de acceso.** Su registro de errores va sin query ni cabeceras (la query podría llevar un
  token). CI lo comprueba con una marca en `?access_token=` y la API parada.

### 7. CI y pruebas

El trabajo `image` ejecuta el **`scripts/deploy.sh` real**, en modo público, con `tls internal` y el host
`api.voracious.test`, y después una batería a través del proxy (con `--resolve` a `127.0.0.1` y la raíz de la CA
interna; nunca `-k`): TLS 1.2/1.3 y h2, TLS ≤ 1.1 rechazado, sin UDP 443 ni TCP 80, 401 con `WWW-Authenticate`,
cabeceras sin `Server`, rutas cerradas, subidas y topes (1 MiB, 50–51 MiB, > 51 MiB), IP del cliente y
`X-Forwarded-For`, CORS, límite de peticiones, 502 JSON con la API parada y un **despliegue fallido a propósito que
debe dejar el 443 cerrado**. Además `caddy validate` en los dos modos, `caddy fmt`, `scripts/check_public.sh` y
`git diff --exit-code -- .sops.yaml deploy/demo`. Pytest cubre el limitador, las cabeceras de proxy, CORS, la
documentación apagable, el cupo, el comprobador de la superficie de autenticación y la coherencia de límites.

**La puerta de `deploy.sh`** es la pieza de seguridad de este paso: el 443 **no se abre** si alguna ruta de negocio
responde sin token (`scripts/check_auth_surface.py` dentro del contenedor `api`, que prueba cada operación del OpenAPI
sin token y exige 401 con `WWW-Authenticate`, más `OPTIONS` sin cabeceras de *preflight* → 401). El proxy se **para
siempre al empezar** (también en modo privado: el 443 queda cerrado) y una trampa `EXIT` lo vuelve a parar ante
cualquier fallo posterior; con `restart: unless-stopped`, un proxy parado así sigue parado tras reiniciar el servidor.
El modo público existe si y solo si hay `proxy.env`. Se rechazan `COMPOSE_PROFILES` (en el entorno se ignora; en el
`.env`, error) y un `api.env` ausente: el perfil `public` solo lo activa la puerta.

### 8. Documentación

Este ADR, las enmiendas a los ADR 0005, 0010, 0011 y 0012, `despliegue.md`, `arquitectura.md`, `CLAUDE.md` y
`ESTADO.md`. La guía de integración (`docs/guia/`) se actualiza **después** de un despliegue en verde, en su propio
commit, para que nunca prometa una URL que todavía no responde.

### 9. Riesgos aceptados

En «Amenazas» y «Deuda» más abajo.

## CORS abierto a cualquier origen

`VORACIOUS_CORS_ALLOWED_ORIGINS=*` en `deploy/demo/api.env` (versionado, público), **sin credenciales**.

**Por qué es seguro:** la autenticación es `Authorization: Bearer` y no hay cookies. El navegador nunca envía el token
por su cuenta (no hay *ambient authority*), así que una página ajena no puede llamar en nombre de nadie: necesita el
token, y para tenerlo ya tendría que haberlo robado. CORS, además, no es un control de acceso (cualquier cliente que no
sea un navegador lo ignora): la barrera sigue siendo el JWT. Con `*`, sin credenciales de CORS, el navegador tampoco
enviaría cookies aunque las hubiera.

- **Default de la app: `()`, CORS cerrado** (no se instala el middleware). `*` es una decisión de despliegue de la
  demo, no del código. El **modo lista** existe para instalaciones dedicadas: cada origen exactamente
  `esquema://host[:puerto]`; se rechazan al arrancar los comodines parciales (`https://*.x`), `null`, la ruta o la
  barra final, query, fragmento, credenciales, esquemas que no son http/https, `http` fuera de `localhost`,
  `127.0.0.1` y `[::1]`, los puertos por defecto, las IP no canónicas y los hosts que no son ASCII. `*` va solo.
- **Parámetros:** métodos `GET` y `POST` (los únicos de la API); cabeceras `Authorization` y `Content-Type`;
  `expose_headers` `Retry-After` y `WWW-Authenticate`; `max_age` 600; `allow_credentials=False`. Cualquier otra
  cabecera pedida en el *preflight* da 400.
- **Cómo restringirlo:** lista en `api.env`, commit y `deploy.sh` (ver [`despliegue.md`](../despliegue.md)).
- **Lo que CORS no cubre:** los errores que genera el propio borde (502/503/504, el 413 de más de 51 MiB, el 404 fuera
  de `/v1`) no llevan cabeceras CORS: el front los ve como «error de red». Como toda petición del front lleva
  `Authorization`, **siempre hay *preflight***, y con la API caída el *preflight* no puede tener éxito. El front debe
  tratar el «error de red» como «servicio no disponible» y reintentar con espera.

## Pila de middlewares y `ErrorBoundaryMiddleware`

De fuera adentro (`api/app.py`): **`ProxyHeaders`** (solo con proxies de confianza) → **`AccessLog`** (los *preflight*
a nivel `debug`) → **`CORS`** (solo con orígenes) → **`ErrorBoundary`** → **`RateLimit`** → **`Authentication`** →
app.

Por qué este orden:

- El *preflight* lo resuelve CORS **antes** del límite y de la autenticación: no gasta cupo ni pide token (un
  *preflight* no puede llevar `Authorization`).
- Los 401, 429 y 4xx de la app pasan por el `send` de CORS y llevan sus cabeceras; el registro de acceso queda fuera
  para ver también los 401 y 429.
- **Los 5xx necesitan una barrera propia.** Starlette instala el manejador de `Exception` en `ServerErrorMiddleware`,
  que queda **fuera** de los middlewares de usuario, así que un 500 saldría sin CORS y el front lo vería como «error
  de red». `ErrorBoundaryMiddleware` (ASGI puro, dentro de CORS) captura la excepción inesperada, registra
  `unhandled_exception` una vez y responde `500 INTERNAL_ERROR` en el formato uniforme si la respuesta no había
  empezado (si ya empezó, la relanza). Se quitó el manejador de `Exception` de `install_error_handlers` (sin código
  zombie); el resto de manejadores no cambia.
- El limitador va después de CORS y de la barrera: sus 429 llevan CORS y un fallo suyo sale como 500 uniforme.

## Amenazas y qué cubre cada medida

| Amenaza | Medida | ¿Cubierta? |
| --- | --- | --- |
| Interceptar el token o los datos en el camino | TLS 1.2/1.3 (Let's Encrypt), HSTS, **80 cerrado** (no hay petición en claro) | Sí |
| Cliente configurado con `http://` que manda el token en claro | El 80 no responde: la conexión falla antes de enviar nada | Sí |
| Ruta de negocio que respondiera sin token | Autenticación de falla cerrada + **puerta de `deploy.sh`** (no abre el 443 si alguna ruta responde sin token) | Sí |
| Descubrir la base o el almacenamiento (`/ready`), documentación pública | No se publican en el borde | Sí |
| Inundar la API con peticiones | Límite por IP en la app; Hetzner filtra capas 3 y 4; la vuelta atrás es cerrar el 443 | Parcial (ver «Deuda») |
| Acaparar el servidor con cálculos de minutos | Carriles serializados, rol de operador, **cupo por tenant (M1)** | Parcial (cupo blando) |
| Falsificar la IP del cliente con `X-Forwarded-For` | Caddy es el primer salto y la reescribe; la app solo cree al proxy de la lista; `--no-proxy-headers` | Sí |
| Escaneo directo a la IP (el origen no se oculta) | Sin SNI no hay certificado; el 8000 solo en loopback; el 5432 no se publica; 80 cerrado | Sí |
| Cuerpo enorme o lento (slowloris) | `max_size` 51 MiB y tiempos de lectura en Caddy | Sí |
| Fuga de la query (token en `?access_token=`) en los registros | Sin registro de acceso en Caddy, registro de errores sin query, `--no-access-log` en uvicorn; CI lo prueba | Sí |
| Una página ajena que use la API en nombre de un usuario | Sin cookies: el navegador no manda el token; CORS `*` sin credenciales | Sí |
| **El token pegado en un front queda expuesto a un XSS de ese front** | Pautas de almacenamiento y TTL (más abajo); el backend no puede evitarlo | **Parcial: depende del front** |
| Comprometer la cuenta de Hostinger y redirigir el nombre | 2FA y CAA en `api` (solo `letsencrypt.org`) | Parcial |
| Caída de Caddy | `restart: unless-stopped`, healthcheck y `deploy.sh` lo recrea; el túnel del operador sigue | Sí |
| **Servidor comprometido** | Nada de este ADR (igual que el ADR 0012) | **No** |

## La IP como dato personal

El campo `client` del registro de acceso guarda la IP del cliente, que es un **dato personal** (Ley 1581 de 2012,
Colombia). Se registra porque sin ella no se puede investigar un abuso ni ajustar el límite. La retención la acota la
rotación de logs de Docker (5 ficheros de 10 MB por servicio, `json-file`): no hay una política de retención por
tiempo. Cuando entren datos reales habrá que decidir finalidad, plazo y aviso; hoy es una demo con datos sintéticos.

## Pautas para cualquier front en navegador

El front es de otro repositorio; estas pautas valen para el que sea.

- **Token:** en memoria o en `sessionStorage`, **nunca en `localStorage`**; TTL de 8 h o menos. Todavía no hay login:
  el token lo emite el operador con `issue_token.sh` y el front lo recibe por un canal seguro (ver «Consecuencias»).
- **CSP del front:** `connect-src https://api.voracious.cloud`.
- **Preflight:** toda petición lleva `Authorization`, así que siempre hay *preflight*; admite 600 s de caché.
- **Errores del borde** (502, 503, 504, el 413 de más de 51 MiB, el 404 fuera de `/v1`): sin cabeceras CORS, el front
  los ve como «error de red». Debe reintentar con espera (`Retry-After` cuando lo hay: `RATE_LIMITED`).
- **Subidas:** el límite es 50 MiB; el cliente puede comprobarlo antes de enviar.
- **429:** `RATE_LIMITED` trae `Retry-After`; `TOO_MANY_JOBS` no (esperar a que termine algún trabajo propio).

## Alternativas descartadas

- **nginx + certbot.** Más piezas (certbot, cron, *hook*, webroot) para lo que Caddy ya hace.
- **Traefik.** Trae límite de peticiones propio, pero su configuración es más pesada y el proveedor Docker pide montar
  el socket de Docker.
- **Caddy compilado con xcaddy y `caddy-ratelimit`.** Exige toolchain de Go en un servidor de 2 vCPU, un módulo que su
  autor declara en desarrollo y una versión que Dependabot no ve. Queda como mejora posible si aparecen ráfagas.
- **Cloudflare (proxy o *tunnel*).** Un tercero descifraría el tráfico, que mañana puede ser bancario.
- **Balanceador de Hetzner.** Coste y una pieza más sin necesidad con un solo servidor.
- **Lista de IP de integradores en el 443.** Rompe ACME (ver «Cortafuegos»).
- **Puerto 80 con redirección 308.** El cliente manda el token en claro en la primera petición y no se entera.
- **Documentación pública en el borde.** Swagger carga JS de un CDN (choca con la CSP) y expone la superficie.
- **`VORACIOUS_PUBLIC_BASE_URL`.** La app no genera URLs absolutas.
- **Lista de orígenes CORS como única opción** (propuesta del arquitecto, M9): sustituida por la decisión del dueño de
  abrir a `*`; el modo lista se conserva en el código.
- **Cortafuegos con ufw.** Docker se lo salta en los puertos publicados y activarlo en remoto arriesga el acceso.

## Consecuencias

- **La API responde en `https://api.voracious.cloud`.** El túnel SSH queda **solo para el operador** (`/ready`,
  documentación, `docker compose`). La «cuenta solo de túnel» para integradores desaparece de `despliegue.md`.
- **Supera «la API no se expone»** del ADR 0012 y de `ESTADO.md` para esta demo. Para datos del banco sigue valiendo el
  paso grande de seguridad.
- **El token entra por el front de forma provisional** (hasta OIDC): lo emite el operador y el desarrollador del front
  lo pega. Es la fila del XSS de la tabla de amenazas.
- La compuerta y el trabajo `image` crecen (ver [ADR 0010](0010-empaquetado-docker-y-ci.md), enmienda). Hay dos
  variables nuevas de despliegue (`DEPLOY_EDGE_SUBNET`, `DEPLOY_PROXY_IP`) y los ficheros públicos `proxy.env` y
  `api.env`.
- **La vigilancia (M4)** es `.github/workflows/vigilancia.yml`: cada 3 horas, desde fuera del servidor, la misma
  comprobación que tras un despliegue (`scripts/check_public.sh --cors-origin http://localhost:5173
  https://api.voracious.cloud`). Reintenta `/health` 3 veces con 20 s de espera (un despliegue reinicia la API) y falla
  si el certificado caduca en menos de 14 días (Caddy renueva unos 30 antes, así que ese fallo significa renovación
  atascada). GitHub avisa por correo, **a quien editó por última vez la línea `cron`**: el dueño debe tener activadas
  las notificaciones de Actions. Coste: ~240 minutos al mes, dentro de los 2000 gratuitos de un repositorio privado
  (cifra del plan, sin verificar contra la facturación). Sin token omite la comprobación con token y lo dice.
- **M3:** CAA `api.voracious.cloud CAA 0 issue "letsencrypt.org"`, **solo en `api` y no en la raíz**, para no
  condicionar dónde se aloje el front (un CAA en `voracious.cloud` restringiría también sus certificados).

## Deuda

- **Cupo por tenant blando:** contar y luego insertar no es atómico; con el pool de hilos, k peticiones simultáneas
  pueden pasarse del cupo. Aceptado.
- **Un `running` colgado ocupa su hueco hasta el reinicio** (`JOB_INTERRUPTED` lo libera).
- **Limitador en memoria:** exacto con 1 worker; se pierde al reiniciar y no se comparte entre procesos. Una IP
  compartida (NAT) comparte cubo. Con un cluster haría falta un almacén común.
- **El *preflight* no gasta cupo y se registra a nivel `debug`:** una avalancha de `OPTIONS` con `Origin` no se limita
  en la app ni deja rastro en el registro normal (respuesta trivial). Lo acota el cortafuegos y, en último caso, cerrar
  el 443.
- **Exención de loopback del limitador:** depende del invariante de Caddy sin `trusted_proxies` (ver decisión 6).
- **El trabajo `image` de CI está sin ejecutar:** se verifica en un PR desde la rama `paso-e` antes de desplegar.
- **La rama de la trampa `EXIT` de `deploy.sh`** (fallo después de arrancar el proxy) **no tiene test automático**; CI
  solo prueba un fallo antes de la puerta.
- **`deploy.sh` no admite `VORACIOUS_API_DOCS=false`:** `check_auth_surface.py` no recibe `--openapi`, sale con 2 y el
  despliegue falla cerrado. Se acepta porque la demo usa `true`; se pagará en una instalación dedicada.
- **Cuerpos JSON de hasta 51 MiB con cualquier token válido, de cualquier rol:** el cuerpo se lee antes de comprobar el
  rol. Con 64 conexiones podría superarse la memoria de `api` (2 GiB). Se acepta porque solo el dueño emite tokens y los
  datos son sintéticos. Se pagará con un `request_body` por ruta en Caddy (51 MiB solo en `/v1/datasets`).
- **IPv6 sin registro AAAA, a propósito:** sin red Docker con IPv6, `docker-proxy` esconde la IP real de los clientes
  v6 y el límite por IP los agruparía. Hoy el cortafuegos admite IPv6 por si se añade después.
- **SSH:** la contraseña de sudo de `kevin` no se recuerda y la configuración de `sshd` (solo llave) está pendiente de
  verificar y fijar con sudo. Se acepta el 22 abierto (P5).
- **Límites de Let's Encrypt** (cifras del plan, sin verificar contra su documentación en esta sesión): 50 certificados
  por dominio registrado y semana, 5 duplicados por semana y 5 validaciones fallidas por nombre y hora. Mitigaciones:
  `caddy_data` persiste (**nunca `down -v`**, que también borra los certificados), Caddy reintenta contra *staging* y
  `check_public.sh` avisa con menos de 14 días.
- **Memoria:** los topes suman 768 + 2048 + 256 + 192 = 3264 MiB de unos 3789; si hay presión se baja `api` a 1.5g
  (el pico medido fue 245 MB). Vigilar durante los `docker build` del despliegue.
- **La subred `edge`** (172.29.80.0/24) podría chocar con otra red del servidor: se cambia con `DEPLOY_EDGE_SUBNET`.
- **Cuenta de Hostinger:** si la comprometen, pueden redirigir el nombre; 2FA y CAA lo limitan.
- **Mejoras del plan no aprobadas:** `Idempotency-Key` (reintentar tras un timeout duplica trabajos), revocación por
  `jti`, compresión, cabeceras también en la app, IPv6, segunda capa de límite en el borde, etapa `caddy` en
  `gate.sh`, SSH solo desde la IP del dueño o tras WireGuard, lista de IP con DNS-01.
- **Pendiente de ejecutar** (ver [`ESTADO.md`](../ESTADO.md)): commit, CI en GitHub y despliegue público.
