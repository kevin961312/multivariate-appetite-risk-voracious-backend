## Diagnóstico de la causa (R1) en C1 (n=50, p=200), rrcov oficial: por cada conjunto 1-5 de r6pack,
## cuántas direcciones tienen autovalor ~0, qué magnitud tienen las proyecciones de los datos y las escalas
## Qn en esas direcciones, cuánto pesan en la distancia, y si una rotación (o la perturbación 1e-14 de x)
## dentro del espacio nulo cambia el subconjunto inicial.
## Uso: Rscript tools/r/experimentos/diagnostico_causa.R  (desde la raíz del repo)
source("tools/r/casos.R"); source("tools/r/instrumentacion.R")
source("tools/r/experimentos/r6pack_canonico.R")
RNGkind("Mersenne-Twister", "Inversion", "Rejection")
caso <- commandArgs(TRUE)[1]; if (is.na(caso)) caso <- "C1"
x0 <- leer_csv_gz(file.path(RAIZ_FIXTURES, caso, "x.csv.gz"))
n <- nrow(x0); p <- ncol(x0); h <- as.integer(ceiling(0.5 * n))
R <- initHsets_variantes(x0, variantes = list(VAR_OFICIAL), diag = TRUE)
xs <- R$x                                   # datos que ve initset (doble estandarización, detmrcd.R:421 y :124)
stopifnot(identical(R$hsets[[1]], correr_instrumentado(x0, E = cargar_instrumentado())$cap$hs_init))
ns <- asNamespace("rrcov")
## réplica literal de initset oficial (detmrcd.R:70-75), solo para el diagnóstico
initset0 <- function(data, P) {
  lambda <- get("doScale", ns)(data %*% P, center = median, scale = get("Qn", ns))$scale
  sqrtcov <- P %*% (lambda * t(P)); sqrtinvcov <- P %*% (t(P) / lambda)
  estloc <- get("colMedians", ns)(data %*% sqrtinvcov) %*% sqrtcov
  cx <- (data - rep(estloc, each = nrow(data))) %*% P
  list(ord = sort.list(get("mahalanobisD", ns)(cx, FALSE, lambda))[1:h], lambda = lambda, cx = cx)
}
nombres <- c("R1 tanh", "R2 Spearman", "R3 normal scores", "SCM", "covx BACON")
set.seed(20262000)
cat(sprintf("Caso %s: n=%d p=%d h=%d  max(n,p)*eps=%.3g\n\n", caso, n, p, h, max(n, p) * .Machine$double.eps))
filas <- list()
for (k in 1:5) {
  P <- R$diag[[k]]$P; ev <- R$diag[[k]]$ev
  tol <- ev[1] * max(n, p) * .Machine$double.eps
  r <- c(k0.1 = sum(ev > 0.1 * tol), k1 = sum(ev > tol), k10 = sum(ev > 10 * tol))
  rr <- r[["k1"]]; nul <- (rr + 1):p
  I0 <- initset0(xs, P)
  proj <- xs %*% P
  stopifnot(identical(I0$ord, R$hsets[[1]][, k]))
  d_nul <- rowSums((I0$cx[, nul] / rep(I0$lambda[nul], each = n))^2)
  d_tot <- rowSums((I0$cx / rep(I0$lambda, each = n))^2)
  ## rotaciones aleatorias dentro del espacio nulo (5): ¿cambia el subconjunto?
  rot <- vapply(1:5, function(i) {
    Q <- qr.Q(qr(matrix(rnorm(length(nul)^2), length(nul))))
    P2 <- P; P2[, nul] <- P[, nul] %*% Q
    !setequal(initset0(xs, P2)$ord, I0$ord)
  }, NA)
  ## solo el subespacio significativo: ¿cambia ante rotación nula? (por construcción no)
  filas[[k]] <- data.frame(conjunto = nombres[k], lambda1 = ev[1], r_k0.1 = r[[1]], r_k1 = r[[2]], r_k10 = r[[3]],
    lambda_r = ev[rr], lambda_r1 = ev[rr + 1], max_abs_lambda_nulo = max(abs(ev[nul])),
    gap_log10 = log10(ev[rr] / max(abs(ev[nul]))),
    max_abs_proj_nulo = max(abs(proj[, nul])), med_abs_proj_nulo = median(abs(proj[, nul])),
    med_abs_proj_sig = median(abs(proj[, 1:rr])),
    med_Qn_nulo = median(I0$lambda[nul]), min_Qn_nulo = min(I0$lambda[nul]), max_Qn_nulo = max(I0$lambda[nul]),
    med_Qn_sig = median(I0$lambda[1:rr]),
    frac_dist_nulo = median(d_nul / d_tot), rotaciones_que_cambian = sum(rot))
}
D <- do.call(rbind, filas)
options(width = 250)
print(D, digits = 3, row.names = FALSE)
write.csv(D, sprintf("tools/r/experimentos/resultados/diagnostico_causa_%s.csv", caso), row.names = FALSE)
## Perturbación 1e-14 relativa de x (3 veces): conjuntos que cambian, oficial vs canónico
cat("\nPerturbacion 1e-14 relativa de x (3 veces): conjuntos (1-6) que cambian como conjunto\n")
V0 <- initHsets_variantes(x0, variantes = list(VAR_OFICIAL, VAR_CANON(1)))
for (j in 1:3) {
  set.seed(20262000 + j)
  xp <- x0 * (1 + 1e-14 * runif(length(x0), -1, 1))
  V1 <- initHsets_variantes(xp, variantes = list(VAR_OFICIAL, VAR_CANON(1)))
  ch <- function(a, b) paste(which(vapply(1:6, function(k) !setequal(a[, k], b[, k]), NA)), collapse = ",")
  cat(sprintf("  pert %d: oficial cambian {%s}; canonico cambian {%s}\n", j, ch(V0[[1]], V1[[1]]), ch(V0[[2]], V1[[2]])))
}
