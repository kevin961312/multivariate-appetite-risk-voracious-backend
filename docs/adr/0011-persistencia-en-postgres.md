# ADR 0011 — Persistencia en Postgres

- **Estado:** Propuesto (redactado por el documentador el 2026-10-09; lo acepta el dueño)
- **Fecha:** 2026-10-09
- **Relacionado:** [ADR 0001](0001-hexagonal.md) (un adaptador nuevo + una variable),
  [ADR 0003](0003-api-asincrona.md), [ADR 0008](0008-ciclo-de-vida-de-la-carta.md) (append-only, CAS, D6),
  [ADR 0009](0009-api-por-pasos-encadenables.md) (`claim`), [ADR 0010](0010-empaquetado-docker-y-ci.md)
  (un solo worker de uvicorn, Compose, CI). Esquema tabla por tabla en
  [`../arquitectura.md`](../arquitectura.md) (sección «Persistencia»).

## Contexto

Hasta el Paso 4.1 los repositorios y la cola vivían en el proceso: reiniciar el servicio perdía todo el
estado (modelos, versiones, observaciones, anotaciones). Para una demo con datos reales, y para que el ciclo de
vida de la carta (ADR 0008) tenga sentido, el estado tiene que sobrevivir. Los puertos ya existían y su
contrato (atomicidad, `get` con `tenant_id`, registros codificados) estaba pensado para este adaptador, así que
la decisión no toca `domain/` ni `application/` salvo la recuperación al arrancar (punto 6).

## Decisión

### 1. Postgres 17, sin TimescaleDB por ahora

La imagen es `postgres:17-trixie` fijada por digest. TimescaleDB era el objetivo de la arquitectura, pero hoy
no hay volumen de series que lo justifique: las observaciones se consultan por modelo y fecha con índices
normales. Añadirlo después es una migración (hipertabla sobre `observations`), no un cambio de diseño.

### 2. `payload TEXT` con el JSON exacto del codec, y columnas tipadas solo para consultar

Cada registro se guarda como el JSON que ya produce su `RecordCodec` (M1 del Paso 2b.2: arreglos en base64 con
dtype y forma, estrictos, con `format_version`). Las demás columnas son **copias** del payload para filtrar,
ordenar y garantizar invariantes en la base; **siempre se lee del payload**, nunca de las columnas, así que la
ida y vuelta es la del codec.

**Por qué `TEXT` y no `JSONB`:** JSONB rechaza `NaN` e infinitos y normaliza los números (pierde `-0`). Los
registros llevan `NaN`, `±Inf` y `-0.0` legítimos (resultados numéricos del método) y la propiedad que se
protege es la igualdad **en bits** de lo guardado con lo calculado (la que vigilan los tests de equivalencia).
Un JSONB rompería esa propiedad sin avisar. Tampoco se pierde nada que se necesite: no se consulta dentro del
payload.

### 3. Atomicidad la da la base, no la aplicación

| Operación del puerto | Mecanismo |
| --- | --- |
| `claim` (`queued → running`) | `UPDATE … SET status='running' WHERE … AND status='queued' RETURNING`: de dos trabajadores, gana uno |
| D6: una propuesta de versión sin resolver por modelo (`add_proposal_if_none`) | índice único parcial `model_versions_one_proposal` + `INSERT … ON CONFLICT DO NOTHING` |
| D6: una recalibración en curso por modelo (`add_if_none_in_progress`) | índice único parcial `recalibrations_one_in_progress` + `ON CONFLICT DO NOTHING` |
| CAS de versiones, pasos de tubería y propuestas de recalibración | `SELECT … FOR UPDATE` en una transacción |
| Observaciones, anotaciones, eventos estructurales, filas base de versión | solo `INSERT` (append-only, sin `UPDATE`) |

Los identificadores de tabla son constantes del código compuestas con `psycopg.sql.Identifier`; los valores
van siempre como parámetros ligados. Los repositorios en memoria y los de Postgres pasan la **misma** suite de
contrato (`tests/unit/infrastructure/test_repository_contract.py`).

### 4. Migraciones SQL versionadas con ejecutor propio

Ficheros `NNNN_nombre.sql` en `infrastructure/postgres/migrations/`; los aplica `python -m voracious.cli
migrate`. Cada una corre en su propia transacción junto con su fila en `schema_migrations(version, checksum,
applied_at)`: o se aplica entera o no se aplica. Todo bajo un `pg_advisory_lock`, de modo que dos `migrate`
simultáneos se esperan y la migración se aplica una vez. **Una migración aplicada no se edita nunca**: el
ejecutor compara su checksum SHA-256 y, si cambió, aborta sin aplicar nada; el cambio va en una migración
nueva. En Compose, el servicio `migrate` termina antes de que arranque la API.

### 5. `repository=postgres` exige `storage=local`

La matriz de cada dataset sigue en el almacén de ficheros (`.npy` con huella, M6); en Postgres van sus
metadatos y las fechas por fila. Guardar matrices grandes en la base no aporta (no se consultan) y encarece
backups. La combinación `postgres` + `memory` se rechaza al arrancar (`ConfigurationError`): un reinicio dejaría
metadatos que apuntan a matrices que ya no existen.

### 6. Recuperación tras un reinicio: `failed / JOB_INTERRUPTED`

La cola sigue en el proceso. Si el servicio se reinicia, un registro `queued` o `running` ya no lo ejecutará
nadie y, persistido, bloquearía para siempre (p. ej. D6 impediría pedir otra recalibración). Al arrancar, antes
de aceptar tráfico, `RecoverInterruptedJobs` los cierra `failed / JOB_INTERRUPTED` (HTTP 503 en el catálogo,
solo en el cuerpo de un trabajo `failed`; el cliente lo vuelve a pedir). **Excepción:** una recalibración
`stepwise` abierta sin propuesta en curso es una sesión que espera pasos del cliente, no un trabajo de la cola:
se respeta. Por esto sigue siendo **un solo worker de uvicorn**: con varios, el arranque de uno cerraría como
interrumpidos los trabajos vivos de otro. Escalar exige la cola distribuida (deuda).

**Conciliación de escrituras a medias.** Algunos cierres escriben dos registros en dos transacciones (la versión
`proposed` y el cierre de la recalibración; la versión 0 y el cierre del modelo). Si el proceso cae entre ambas,
la recuperación concilia en vez de añadir una operación atómica al puerto (no cambia ningún puerto ni adaptador,
vale igual en memoria y en Postgres y reutiliza el CAS de versiones): las versiones `proposed` de una
recalibración interrumpida pasan a `rejected` con nota `job_interrupted` (ya no bloquean `PROPOSAL_PENDING` ni
se pueden aprobar), y un modelo cuya versión 0 ya existe se completa `succeeded` con ese modelo (la versión 0 es
el modelo ya ensamblado; `rejected`/`superseded` no aplican según ADR 0008). Solo se concilia lo que sigue en
curso al arrancar. Lo prueba `tests/integration/test_recovery_crash.py` con una caída simulada entre las dos
escrituras, en memoria y en Postgres.

### 7. Salud: `/health` sin dependencias, `/ready` con checks

`/health` (liveness) no consulta nada, para que una caída de la base no reinicie un proceso sano. `/ready`
comprueba `database` (`SELECT 1` con tiempo máximo de 2 s; solo con `repository=postgres`) y `storage`
(directorio escribible; solo con `storage=local`), y responde `503 {status: not_ready, checks}` si alguno falla.
Cierra la decisión abierta del código HTTP de `/ready`. El pool no espera a la base al abrir: reintenta en
segundo plano y `/ready` da 503 hasta que responda.

### 8. Copia de seguridad diaria

El servicio `backup` de Compose hace `pg_dump --format=custom` cada 24 h al volumen `pgbackups`, escribe en un
`.part` y lo renombra al terminar (nunca queda un volcado a medias con nombre válido) y conserva 7 días.
Restaurar:

```bash
docker compose exec backup pg_restore --clean --if-exists -d "$PGDATABASE" /backups/<fichero>
```

Límite conocido: el contenedor corre como root (imagen oficial) y los volcados viven en el mismo servidor, no
fuera de él. Ambos son deuda.

### 9. Seguridad de este paso

- La base **nunca se expone**: el servicio `postgres` no declara `ports`; solo lo ven los servicios de la red de
  Compose. La API tampoco: `127.0.0.1:8000` y túnel SSH.
- Los secretos (`POSTGRES_PASSWORD`, `VORACIOUS_DATABASE_URL`) viven **solo** en el `.env` del servidor, nunca
  versionado; `.env.example` lleva el formato sin valores. Formato de la URL:
  `postgresql://USUARIO:CONTRASEÑA@postgres:5432/BASE`, con la contraseña en **codificación URL** si tiene
  caracteres como `@ : / ? # %`. La URL es `SecretStr`: no aparece en `repr` ni en logs.
- Las credenciales de `compose.test.yaml` y de CI son de prueba, no secretas (contenedor efímero en puerto
  aleatorio de `127.0.0.1`, o servicio del job).
- **Fuera de este paso** (ver `ESTADO.md`): autenticación real, roles, Row-Level Security y HTTPS. Hoy el
  aislamiento por tenant lo hace la aplicación (todo `get`/consulta filtra por `tenant_id`) y el tenant llega en
  una cabecera sin autenticar: **no es apto para exponerse a un cliente**.

### 10. Fechas y nombres de variables (pedido del dueño)

Para trazabilidad y para recalibrar con datos de enero–septiembre más los nuevos, cada dataset puede traer el
nombre de cada variable y la fecha de cada fila: JSON `variables` y `observed_at`; CSV con cabecera y
`?date_column=` (por defecto `observed_at`). Se guardan en `datasets.variables` y `dataset_rows`. Heredan:

- el **modelo** y la **versión 0** (nombres y fecha de cada fila de la base, en `version_base_rows`);
- la **salida de una exclusión** (conserva nombres y fechas de las filas que quedan);
- las **candidatas** de una recalibración y el dataset de **extensión**;
- las **observaciones** puntuadas llevan su `observed_at` (ya existía).

Si el modelo tiene nombres, una puntuación o recalibración con otros (número u orden) responde
`422 VARIABLES_MISMATCH`. **Ninguno de estos datos entra en una estadística**: un test compara en bits el modelo
con y sin nombres/fechas. `dataset_rows.external_ref` queda **reservada** (siempre `NULL`) para una referencia
del cliente a su registro; no tiene uso hoy.

## Alternativas descartadas

- **JSONB para el payload.** Rompe `NaN`, `±Inf` y `-0` (punto 2). Su ventaja (consultar dentro) no se usa.
- **ORM (SQLAlchemy) y Alembic.** Los registros ya son datos codificados y las consultas son pocas y fijas;
  un ORM añadiría un mapeo entre objetos que no se necesita y una dependencia que `domain`/`application` no
  deben ver. El ejecutor propio son ~100 líneas con checksum y bloqueo; Alembic aporta autogeneración que no
  se usa.
- **TimescaleDB ya.** Sin volumen que lo pida (punto 1); complica la imagen y los backups.
- **Matrices en Postgres** (`bytea`). Encarece los volcados sin ganancia de consulta (punto 5).
- **Varios workers de uvicorn con estado compartido.** La cola sigue en el proceso (punto 6).

## Consecuencias

- Reiniciar ya no pierde modelos, versiones ni observaciones; sí pierde los trabajos en curso, que quedan
  `failed / JOB_INTERRUPTED` y se vuelven a pedir.
- La compuerta **exige Postgres** (ver ADR 0010, enmienda): sin Docker ni `VORACIOUS_TEST_DATABASE_URL`, rojo.
- Cambiar el esquema obliga a una migración nueva; los formatos de payload se versionan con `format_version`.
- Deuda: TimescaleDB, cola distribuida, backup fuera del servidor y sin root, `external_ref`, y todo lo de
  seguridad del punto 9.
