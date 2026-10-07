## Exporta los intermedios de la especificación (docs/metodos/mrcd-especificacion.md §10) para
## los 13 casos/variantes, ejecutando la copia INSTRUMENTADA (verificada identical al oráculo).
## Contrato de formato: intermedios/<nombre>.csv.gz, sin cabecera, %.17g, matrices con filas = filas de R,
## vectores = una columna, escalares = 1x1, índices 1-based, enteros sin decimales, lógicos como 1/0.
## Sufijos _k<k> (subconjunto inicial 1..6) y _it<i> (iteración de C-step; 0 = paso inicial).
## intermedios/indice.json: nombre -> {forma, tipo, captura, descripcion, archivo, sha256}.
## Uso: Rscript tools/r/exportar_intermedios.R [CASO ...]   (sin args = todos)
source("tools/r/casos.R"); source("tools/r/instrumentacion.R")
suppressMessages({ library(jsonlite); library(digest) })
RNGkind("Mersenne-Twister", "Inversion", "Rejection")

escribir_entero_gz <- function(m, ruta) {
  if (is.null(dim(m))) m <- matrix(m, ncol = 1)
  con <- gzfile(ruta, "wb", compression = 9); on.exit(close(con))
  writeLines(apply(matrix(as.character(as.integer(m)), nrow(m), ncol(m)), 1, paste, collapse = ","), con)
}
sha <- function(f) digest(f, algo = "sha256", file = TRUE)

## escribe un objeto capturado; devuelve la entrada del índice
exportar_objeto <- function(nm, v, dir, meta) {
  tipo <- if (is.logical(v)) "logical" else if (is.integer(v)) "int" else "double"
  if (tipo != "double") {
    v <- if (is.logical(v)) as.integer(v) else v
    v[is.na(v)] <- -1L        # solo rs_Vsel: NA -> -1 (documentado en la descripción)
  }
  if (is.null(dim(v))) v <- matrix(v, ncol = 1) else v <- unname(v)
  f <- file.path(dir, paste0(nm, ".csv.gz"))
  if (tipo == "double") {
    stopifnot(all(is.finite(v)) || nm %in% c("rs_flower", "rs_fupper"))
    escribir_csv_gz(v, f)
  } else escribir_entero_gz(v, f)
  list(forma = dim(v), tipo = tipo, captura = meta$src,
       descripcion = meta$d, archivo = paste0(nm, ".csv.gz"), sha256 = sha(f))
}

args <- commandArgs(TRUE); todos <- c(names(casos), names(variantes)); if (length(args)) todos <- args
E <- cargar_instrumentado()
resumen <- list()
for (nm in todos) {
  base <- if (nm %in% names(variantes)) variantes[[nm]] else nm
  target <- if (nm %in% names(variantes)) "equicorrelation" else "identity"
  x <- leer_csv_gz(file.path(RAIZ_FIXTURES, base, "x.csv.gz"))
  t0 <- proc.time()[["elapsed"]]
  r <- correr_instrumentado(x, target, E = E)
  dir <- file.path(RAIZ_FIXTURES, nm, "intermedios")
  unlink(dir, recursive = TRUE); dir.create(dir, recursive = TRUE)
  cap <- r$cap; meta <- r$meta
  ## salidas del objeto S4 (CovMrcd.R:66-81)
  s4 <- list(out_center = r$res@center, out_cov = r$res@cov, out_icov = r$res@icov, out_rho = r$res@rho,
             out_target = r$res@target, out_cnp2 = r$res@cnp2, out_crit = r$res@crit,
             out_best = r$res@best, out_mah = as.numeric(r$res@mah), out_quan = r$res@quan,
             out_alpha = r$res@alpha, out_n_obs = r$res@n.obs)
  for (k in names(s4)) {
    cap[[k]] <- s4[[k]]
    meta[[k]] <- list(src = "CovMrcd.R:66-81", d = paste("slot", sub("^out_", "", k), "del objeto S4 CovMrcd"))
  }
  meta$rs_Vsel$d <- paste(meta$rs_Vsel$d, "(NA exportado como -1)")
  indice <- list()
  for (n in sort(names(cap))) indice[[n]] <- exportar_objeto(n, cap[[n]], dir, meta[[n]])
  write_json(indice, file.path(dir, "indice.json"), auto_unbox = TRUE, pretty = TRUE, digits = NA)
  bytes <- sum(file.size(list.files(dir, full.names = TRUE)))
  resumen[[nm]] <- list(archivos = length(indice), bytes = bytes)
  cat(sprintf("%-6s intermedios=%3d  %.2f MB  %.1fs\n", nm, length(indice), bytes / 1e6,
              proc.time()[["elapsed"]] - t0))
}
saveRDS(resumen, "/tmp/resumen_intermedios.rds")
