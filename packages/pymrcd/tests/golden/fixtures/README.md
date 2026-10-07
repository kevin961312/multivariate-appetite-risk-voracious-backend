# Fixtures golden de pymrcd

Salidas de **rrcov 1.7-7 oficial de CRAN** (oráculo aislado en `referencias/R-lib/`), generadas en la
plataforma de referencia (macOS arm64, R 4.5.2, Accelerate, Rlapack 3.12.1). Ver
[ADR 0006](../../../../../docs/adr/0006-libreria-pymrcd.md) y
[`mrcd-especificacion.md`](../../../../../docs/metodos/mrcd-especificacion.md).

Formato: `.csv.gz` sin cabecera, `%.17g`, índices 1-based como en R. Cada caso tiene `manifest.json`
(versiones, semilla, parámetros, tolerancias, SHA-256) e `intermedios/indice.json`.

## Qué está en git y qué no

Los intermedios completos pesan ~200 MB, casi todo matrices p×p de los casos con p = 200–250. Se versiona
solo lo necesario (~50 MB):

| Contenido | En git |
| --- | --- |
| Entradas `x.csv.gz`, salidas finales, `hsets_init` y manifiestos de los 14 casos | sí |
| `primitivas/` (funciones de R base, robustbase y LAPACK/BLAS) | sí |
| Intermedios completos de C1, C7, C8, C9, C11 y C8_eq | sí |
| Intermedios ligeros (índices, vectores, escalares) del resto de casos | sí |
| Intermedios p×p pesados del resto (`r6_P`, `r6_R`, `is_sqrtcov`, `rs_mS`, …; lista en `.gitignore`) | **no**, solo local |

Los tests que necesitan un intermedio que no está se **saltan con el motivo explícito** (no fallan en
silencio). Las pruebas de extremo a extremo (nivel ii y iii) solo usan lo versionado.

## Casos

Fuente: `tools/r/casos.R` y los `manifest.json` de cada caso. Σ es la identidad (I) o AR(1) con φ = 0,7.
Semilla = 20261000 + nº de caso; las variantes `_eq` reutilizan la entrada de su caso base y solo cambian
`target` a `equicorrelation`. La contaminación desplaza +5 en todas las coordenadas una fracción de las filas
(C9: 20 % = 20 filas; C10: 10 % = 5 filas).

| Caso | n | p | Σ | Contaminación | Target | Semilla | Intermedios completos en git |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 | 50 | 200 | I | no | identity | 20261001 | sí |
| C2 | 100 | 200 | I | no | identity | 20261002 | no (solo ligeros) |
| C3 | 50 | 250 | I | no | identity | 20261003 | no (solo ligeros) |
| C4 | 100 | 250 | I | no | identity | 20261004 | no (solo ligeros) |
| C5 | 50 | 200 | AR(1) | no | identity | 20261005 | no (solo ligeros) |
| C6 | 100 | 250 | AR(1) | no | identity | 20261006 | no (solo ligeros) |
| C7 | 100 | 20 | I | no | identity | 20261007 | sí |
| C8 | 200 | 40 | AR(1) | no | identity | 20261008 | sí |
| C9 | 100 | 20 | I | 20 % (+5) | identity | 20261009 | sí |
| C10 | 50 | 200 | I | 10 % (+5) | identity | 20261010 | no (solo ligeros) |
| C11 | 60 | 40 | I | no | identity | 20261011 | sí |
| C1_eq | 50 | 200 | I | no | equicorrelation | 20261001 (entrada de C1) | no (solo ligeros) |
| C5_eq | 50 | 200 | AR(1) | no | equicorrelation | 20261005 (entrada de C5) | no (solo ligeros) |
| C8_eq | 200 | 40 | AR(1) | no | equicorrelation | 20261008 (entrada de C8) | sí |

C11 cubre el régimen ceil(n/2) <= p < n (h = 31 <= p = 40 < n = 60).

## Regenerar (solo en la plataforma de referencia)

```bash
Rscript tools/r/simular.R
Rscript tools/r/generar_golden.R
Rscript tools/r/exportar_intermedios.R
Rscript tools/r/exportar_primitivas.R
Rscript tools/r/actualizar_manifests.R
```

Los datos descomprimidos son deterministas; los SHA-256 de los `.gz` cambian al regenerar (mtime de gzip).
Leer siempre las entradas en R con `leer_csv_gz()` de `tools/r/casos.R`: `as.numeric` de R no redondea
correctamente en arm64.
