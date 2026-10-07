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
| Entradas `x.csv.gz`, salidas finales, `hsets_init` y manifiestos de los 13 casos | sí |
| `primitivas/` (funciones de R base, robustbase y LAPACK/BLAS) | sí |
| Intermedios completos de C1, C7, C8, C9 y C8_eq | sí |
| Intermedios ligeros (índices, vectores, escalares) del resto de casos | sí |
| Intermedios p×p pesados del resto (`r6_P`, `r6_R`, `is_sqrtcov`, `rs_mS`, …; lista en `.gitignore`) | **no**, solo local |

Los tests que necesitan un intermedio que no está se **saltan con el motivo explícito** (no fallan en
silencio). Las pruebas de extremo a extremo (nivel ii y iii) solo usan lo versionado.

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
