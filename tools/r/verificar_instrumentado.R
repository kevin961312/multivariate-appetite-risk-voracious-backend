## Verifica que la copia instrumentada es idéntica (identical) al oráculo oficial en los 13 casos:
##  (a) quitar líneas '# captura:' / '## [INSTR]' devuelve exactamente detmrcd.R + CovMrcd.R;
##  (b) CovMrcd instrumentado == rrcov::CovMrcd (todos los slots salvo 'call');
##  (c) .detmrcd instrumentado == rrcov:::.detmrcd (lista completa, save.hsets=TRUE);
##  (d) inyectando initHsets (los de R, leídos de fixtures) el resultado sigue idéntico.
## Uso: Rscript tools/r/verificar_instrumentado.R [CASO ...]
source("tools/r/casos.R"); source("tools/r/instrumentacion.R")
a <- readLines("tools/r/detmrcd_instrumentado.R")
a <- a[!grepl("# captura:", a, fixed = TRUE) & !grepl("^## \\[INSTR\\]", a)]
o <- c(readLines("referencias/rrcov-1.7-7/R/detmrcd.R"), readLines("referencias/rrcov-1.7-7/R/CovMrcd.R"))
cat("(a) sin capturas == original (detmrcd.R + CovMrcd.R):", identical(a, o), "\n")
stopifnot(identical(a, o))

args <- commandArgs(TRUE); todos <- c(names(casos), names(variantes)); if (length(args)) todos <- args
E <- cargar_instrumentado()
todo_ok <- TRUE
for (nm in todos) {
  base <- if (nm %in% names(variantes)) variantes[[nm]] else nm
  target <- if (nm %in% names(variantes)) "equicorrelation" else "identity"
  x <- leer_csv_gz(file.path(RAIZ_FIXTURES, base, "x.csv.gz"))
  of <- rrcov::CovMrcd(x, target = target)
  ri <- correr_instrumentado(x, target, E = E)
  b <- comparar_s4(of, ri$res)
  od <- rrcov:::.detmrcd(x, alpha = 0.5, h = NULL, rho = NULL, maxcond = 50,
                         target = if (target == "identity") 0 else 1, maxcsteps = 200,
                         hsets.init = NULL, save.hsets = TRUE, trace = 0L)
  reiniciar_captura(E, FALSE)
  id <- E$.detmrcd(x, alpha = 0.5, h = NULL, rho = NULL, maxcond = 50,
                   target = if (target == "identity") 0 else 1, maxcsteps = 200,
                   hsets.init = NULL, save.hsets = TRUE, trace = 0L)
  c_ok <- identical(od, id)
  hs <- leer_csv_gz(file.path(RAIZ_FIXTURES, nm, "hsets_init.csv.gz"))
  storage.mode(hs) <- "integer"
  hs_ok <- identical(hs, od$initHsets) && identical(hs, ri$cap$hs_init)
  rj <- correr_instrumentado(x, target, initHsets = hs, E = E)
  d_ok <- all(comparar_s4(of, rj$res))
  d_off <- all(comparar_s4(of, rrcov::CovMrcd(x, target = target, initHsets = hs)))
  cat(sprintf("%-6s CovMrcd=%s detmrcd=%s hsets_fixture=%s inyectado_instr=%s inyectado_oficial=%s%s\n",
              nm, all(b), c_ok, hs_ok, d_ok, d_off,
              if (!all(b)) paste(" DIF:", paste(names(b)[!b], collapse = ",")) else ""))
  todo_ok <- todo_ok && all(b) && c_ok && hs_ok && d_ok && d_off
}
cat("RESULTADO GLOBAL:", if (todo_ok) "TODO IDENTICO" else "HAY DIFERENCIAS (BLOQUEANTE)", "\n")
quit(status = if (todo_ok) 0 else 1)
