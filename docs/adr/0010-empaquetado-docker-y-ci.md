# ADR 0010 — Empaquetado con Docker y CI que prueba el binario de `pymrcd` en Linux

- **Estado:** Propuesto (redactado por el documentador el 2026-10-09; lo acepta el dueño)
- **Fecha:** 2026-10-09
- **Relacionado:** [ADR 0001](0001-hexagonal.md), [ADR 0002](0002-mrcd-sin-aproximaciones.md),
  [ADR 0006](0006-libreria-pymrcd.md) (enmienda 2026-10-07 de la extensión C y enmienda de tolerancias D1–D3
  de esta vuelta; no se repite aquí),
  [`../metodos/mrcd-especificacion.md`](../metodos/mrcd-especificacion.md) §3.12.9 b (FMA) y las
  tolerancias D1–D3.

## Contexto

Hasta el Paso 3 el código solo se había ejecutado en macOS arm64. Pero `pymrcd` lleva una extensión C
(`Qn`, pares de OGK) cuyo resultado debe coincidir **en bits** con `qn0` de R, y eso depende de cosas que
cambian con la plataforma y el compilador: que el binario no contenga instrucciones FMA (una contracción
`a*b+c` cambia el último bit), que se conserven las conversiones `double → float → double` de `qn0`, y que
no haya lecturas fuera de rango. Además, el servidor de demo es un Linux x86-64 de 2 vCPU y 3.7 GiB, y la
licencia de `pymrcd` (GPL-3.0-or-later, ADR 0006) condiciona cómo se distribuye lo que lo contiene.

Hacía falta un empaquetado reproducible y una CI que **demuestre** esas propiedades en Linux, no que las
suponga.

## Decisión

### 1. Imagen en tres etapas sobre la misma base

- **`builder`**: lleva `gcc`, compila `pymrcd` y ejecuta `scripts/check_pymrcd_fma.sh`; **la build falla si el
  binario tiene una sola FMA** o le faltan las conversiones de `qn0`. Una imagen con una extensión que
  rompe la igualdad en bits nunca llega a existir.
- **`gate`**: `builder` más el grupo `dev` y lo versionado; su `CMD` es `scripts/gate.sh`. Es la misma
  compuerta que en local, ejecutada en Linux dentro del contenedor.
- **`runtime`**: sin compilador, solo el entorno virtual del `builder`. Usuario `uid 10001` sin shell,
  sistema de ficheros de solo lectura (bytecode precompilado en la build), `HEALTHCHECK` sobre `/health`.
  Un compilador en producción sería superficie de ataque sin función alguna.

### 2. Un solo worker de uvicorn

La cola (`InlineJobQueue`) y los repositorios en memoria viven dentro del proceso. Con varios workers cada
uno tendría su propio estado y un `GET` podría no ver el trabajo que creó el `POST`. Se escalará cuando
lleguen Postgres y la cola distribuida (ADR 0001: un adaptador nuevo y una variable).

### 3. La imagen no se publica

`pymrcd` es GPL-3.0-or-later (ADR 0006): publicar una imagen es distribuirlo. Se construye donde se usa
(`docker compose up --build`) y la CI no empuja a ningún registro ni sube artefactos distintos de los logs
de la compuerta.

### 4. Reproducibilidad de la cadena de suministro

La base (`python:3.12-slim-trixie`) y `uv` se fijan por versión **y digest**; las acciones de GitHub, por SHA
de commit. Dependabot (`.github/dependabot.yml`: acciones, docker y uv, semanal) propone las subidas y cada
propuesta pasa por la CI; nada se aplica solo. Subir `numpy`/`scipy` exige volver a pasar los golden de
`pymrcd` (cotas del ADR 0006).

### 5. Cuatro trabajos de CI y qué prueba cada uno

| Trabajo | Qué prueba y por qué |
| --- | --- |
| `gate` (ubuntu-24.04) | `scripts/gate.sh` completo con gcc de Linux x86-64. Es la compuerta del Paso 1 en otra plataforma; deja `.gates/` como artefacto (`include-hidden-files: true`, porque `upload-artifact` ignora por defecto los directorios que empiezan por punto y el artefacto salía vacío). |
| `image` | Valida `docker-compose.yml`, construye `runtime` (la etapa `builder` ya falla con FMA), arranca en solo lectura y comprueba `/health`, `/ready`, `HEALTHCHECK` sano, uid distinto de 0 y ausencia de `gcc`/`cc`. |
| `sanitizers` | Compila la extensión con ASan y UBSan (`-fno-sanitize-recover=all`: cualquier aviso aborta) y corre los tests de `Qn` y el barrido `scripts/pymrcd_poison_sweep.py` (modo *poison*: basura en el espacio de trabajo antes de cada columna; si `qn0` leyera una celda sin escribirla, cambiarían los bits). Exige `LD_PRELOAD` con `libasan`, porque el intérprete no está instrumentado. Se **excluye** `test_import_without_extension_fails_explicitly`: lanza un intérprete hijo y con `LD_PRELOAD` de ASan el hijo muere con SIGILL antes de ejecutar nada (visto en Linux aarch64 con gcc 14). No ejercita el C y ya corre en `gate`. |
| `fma-strict` | Compila con `CFLAGS=-march=x86-64-v3`, es decir, con FMA disponible para el compilador, y exige **0 FMA** en el binario y los mismos bits en los tests de `Qn`. Luego una **autoprueba negativa**: edita `setup.py` (`-ffp-contract=off` → `fast`) en la copia del runner y exige que `check_pymrcd_fma.sh` dé rojo. Sin ella, una comprobación que nunca falla pasaría por buena. |

La autoprueba negativa edita `setup.py` y no pasa `CFLAGS=-ffp-contract=fast` porque `setup.py` añade
`-ffp-contract=off` **al final** de la línea de compilación, por lo que anula las `CFLAGS` externas. Es el
mismo mecanismo que hace valer las opciones obligatorias en los otros trabajos: el entorno no puede
reactivar la contracción por accidente. Esa misma propiedad limita `sanitizers` y `fma-strict`: prueban que
las opciones de `setup.py` prevalecen, no que el compilador "no sepa" hacer FMA.

### 6. Hallazgo: setuptools reutiliza `.o` aunque cambien las CFLAGS

`setuptools` decide si recompilar por la fecha de las **fuentes**, no por las banderas. Si queda
`packages/pymrcd/build/`, un `--reinstall-package` con otras `CFLAGS` enlaza los objetos viejos y el trabajo
"con sanitizadores" o "con `-march=x86-64-v3`" probaría un binario que no es el suyo. Por eso los trabajos
hacen `rm -rf packages/pymrcd/build` antes de reinstalar, y `.dockerignore` excluye `**/build` para que un
directorio de build local no entre al contexto y contamine la imagen.

### 7. Pila de pruebas web: `httpx2` y avisos como error (M9)

El `TestClient` de Starlette pasó a preferir `httpx2`; con `httpx` emite `StarletteDeprecationWarning`. Se
sustituyó `httpx` por `httpx2` en el grupo `dev` (y se añadió a los módulos prohibidos de `domain` y
`application`). Los avisos de obsolescencia de `starlette`, `fastapi` y `httpx2` son **error** en pytest
para enterarse al subir versiones. Detalle que importa: `StarletteDeprecationWarning` es subclase de
`UserWarning`, no de `DeprecationWarning`, así que el filtro necesita su propia línea
(`error::starlette.exceptions.StarletteDeprecationWarning`); los filtros por `DeprecationWarning` no lo
atrapan.

## Alternativas descartadas

- **Publicar *wheels* o la imagen en un registro.** La GPL de `pymrcd` convertiría la publicación en
  distribución. Además compilar en el destino con `gcc` es lo que permite comprobar el binario real.
- **Runner autoalojado en el servidor de demo.** Un runner que ejecuta código de PRs en la máquina que sirve
  la demo es un riesgo de seguridad y de disponibilidad (2 vCPU). La validación en el servidor se hizo a mano
  (resultados en [`../ESTADO.md`](../ESTADO.md)); la CI corre en runners efímeros de GitHub.
- **Imagen con compilador en `runtime`.** Más superficie y más tamaño sin beneficio: el `builder` ya
  produce el entorno completo.

## Consecuencias

- Un binario con FMA o sin las conversiones de `qn0` es **imposible de construir** como imagen y rompe CI.
- La igualdad en bits de `Qn` queda demostrada en Linux x86-64 (gcc 14.2) y arm64, no solo en el Mac.
- Siguen siendo deuda (en `ESTADO.md`): las huellas de composición de T²MRCD solo existen para Darwin arm64, y
  la consecuencia de producto con p ≥ n en Linux (tolerancias D1–D3 de la enmienda del ADR 0006) queda por decidir.
- Las pruebas de rendimiento en el servidor y el perfil 2 vCPU (`docs/arquitectura.md`) son orientativos.
