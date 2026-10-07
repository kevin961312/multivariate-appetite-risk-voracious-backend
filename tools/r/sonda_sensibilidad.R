## Sonda de sensibilidad del oráculo (rrcov oficial aislado): perturba x en 1e-14 relativo
## (x * (1 + 1e-14 * u), u ~ U(-1,1)) y mide cuántos de los 6 subconjuntos iniciales cambian
## (como conjuntos), el solapamiento mínimo, Delta rho y max|Delta cov| (y si 'best' cambia).
## Los subconjuntos iniciales se obtienen con rrcov:::.detmrcd(save.hsets=TRUE) -> $initHsets
## (no se modifica ninguna lógica). 5 perturbaciones por caso, semillas 7001..7005.
## Uso: Rscript tools/r/sonda_sensibilidad.R [CASO ...]   (desde la raíz del repo; sin args = C1,C5,C7,C8;
## con args solo recalcula esos casos y fusiona sus filas en sonda_sensibilidad.csv sin tocar las demás)
source("tools/r/casos.R")
suppressMessages(library(rrcov, lib.loc = LIB_RRCOV))
RNGkind("Mersenne-Twister", "Inversion", "Rejection")
EPS <- 1e-14; NREP <- 5
correr <- function(x) rrcov:::.detmrcd(x, alpha = 0.5, h = NULL, rho = NULL, maxcond = 50,
                                       target = 0, maxcsteps = 200, hsets.init = NULL,
                                       save.hsets = TRUE, trace = 0L)
filas <- list()
args <- commandArgs(TRUE); sonda_casos <- if (length(args)) args else c("C1", "C5", "C7", "C8")
for (nm in sonda_casos) {
  x <- leer_csv_gz(file.path(RAIZ_FIXTURES, nm, "x.csv.gz"))
  r0 <- correr(x); h <- r0$h
  for (rep in seq_len(NREP)) {
    set.seed(7000 + rep)
    xp <- x * (1 + EPS * runif(length(x), -1, 1))
    r1 <- correr(xp)
    solap <- vapply(1:6, function(k) length(intersect(r0$initHsets[, k], r1$initHsets[, k])) / h, 0)
    cambia <- vapply(1:6, function(k) !setequal(r0$initHsets[, k], r1$initHsets[, k]), NA)
    filas[[length(filas) + 1]] <- data.frame(
      caso = nm, rep = rep, max_rel_pert = max(abs(xp / x - 1)),
      n_subconj_cambian = sum(cambia), solape_min = min(solap),
      solape_por_subconj = paste(sprintf("%.3f", solap), collapse = "/"),
      d_rho = r1$rho - r0$rho, max_abs_d_cov = max(abs(r1$initcovariance - r0$initcovariance)),
      max_rel_d_cov = max(abs(r1$initcovariance - r0$initcovariance)) / max(abs(r0$initcovariance)),
      best_igual = identical(r0$best, r1$best), iBest_igual = identical(r0$iBest, r1$iBest))
  }
}
res <- do.call(rbind, filas)
options(width = 250)
print(res, digits = 4, row.names = FALSE)
fcsv <- file.path(RAIZ_FIXTURES, "sonda_sensibilidad.csv")
if (length(args) && file.exists(fcsv)) {
  prev <- read.csv(fcsv, stringsAsFactors = FALSE)
  res <- rbind(prev[!prev$caso %in% args, ], res)
}
write.csv(res, fcsv, row.names = FALSE)
