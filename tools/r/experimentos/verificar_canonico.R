## Verifica que la copia r6pack_canonico.R sin el cambio (kappa = NA, sin signo) reproduce BIT A BIT
## los initHsets oficiales de rrcov 1.7-7 (referencias/R-lib), que inyectarlos en CovMrcd da el mismo
## objeto que CovMrcd desde cero, y que un proceso hijo de mclapply (fork) da el mismo resultado.
## Uso: Rscript tools/r/experimentos/verificar_canonico.R   (desde la raíz del repo)
source("tools/r/casos.R"); source("tools/r/instrumentacion.R")
source("tools/r/experimentos/r6pack_canonico.R")
RNGkind("Mersenne-Twister", "Inversion", "Rejection")
ok_total <- TRUE
for (nm in names(casos)) {
  x <- leer_csv_gz(file.path(RAIZ_FIXTURES, nm, "x.csv.gz"))
  of <- rrcov:::.detmrcd(x, alpha = 0.5, h = NULL, rho = NULL, maxcond = 50, target = 0,
                         maxcsteps = 200, hsets.init = NULL, save.hsets = TRUE, trace = 0L)
  V <- initHsets_variantes(x, variantes = list(VAR_OFICIAL, VAR_CANON(1)))
  r0 <- CovMrcd(x); r1 <- CovMrcd(x, initHsets = V[[1]])
  s4 <- all(comparar_s4(r0, r1))
  idh <- identical(V[[1]], of$initHsets)
  ncan <- sum(vapply(1:6, function(k) !setequal(V[[2]][, k], V[[1]][, k]), NA))
  cat(sprintf("%-4s n=%3d p=%3d  initHsets(copia)==oficial: %s  CovMrcd(initHsets)==CovMrcd: %s  conjuntos canonicos distintos: %d (6 igual: %s)\n",
              nm, nrow(x), ncol(x), idh, s4, ncan, identical(V[[2]][, 6], V[[1]][, 6])))
  ok_total <- ok_total && idh && s4
}
## worker PSOCK vs proceso padre. Nota: mclapply (fork) aborta con segfault en eigen() en este Mac
## (Accelerate/vecLib no es seguro tras fork una vez usado en el padre), por eso el piloto usa PSOCK.
x <- leer_csv_gz(file.path(RAIZ_FIXTURES, "C1", "x.csv.gz"))
E <- cargar_instrumentado()
a <- correr_instrumentado(x, E = E)$res
cl <- parallel::makeCluster(2, type = "PSOCK")
invisible(parallel::clusterEvalQ(cl, { setwd(getwd()); source("tools/r/casos.R"); source("tools/r/instrumentacion.R"); TRUE }))
parallel::clusterExport(cl, "x")
invisible(parallel::clusterEvalQ(cl, NULL))
b <- parallel::parLapply(cl, 1:2, function(i) correr_instrumentado(x, E = cargar_instrumentado())$res)
parallel::stopCluster(cl)
fk <- all(vapply(b, function(bb) all(comparar_s4(a, bb)), NA))
cat("worker PSOCK == padre (C1, instrumentado):", fk, "\n")
ok_total <- ok_total && fk
cat("VERIFICACION:", if (ok_total) "OK" else "FALLA", "\n")
if (!ok_total) quit(status = 1)
