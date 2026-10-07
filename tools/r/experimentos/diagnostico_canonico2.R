## Comprobaciones previas de canonical2 (piloto 2) en un caso de fixtures (por defecto C1):
## (a) por conjunto 1-5: r (autovalores significativos), s (direcciones del complemento con variación real),
##     valores singulares de Z alrededor del corte, y fracción de la distancia que aportan V_r y W;
##     además, cuántas direcciones s se conservarían con un umbral relativo a sigma_1(Z) (no usado);
## (b) sensibilidad a kappa (autovalores) y kappa2 (complemento) en {0.1, 1, 10}: initHsets frente a (1, 1);
## (c) perturbación 1e-14 relativa (5 veces): conjuntos que cambian en oficial, canonical y canonical2;
## (d) n > p: identidad bit a bit con rrcov (initHsets y CovMrcd completo).
## Uso: Rscript tools/r/experimentos/diagnostico_canonico2.R [caso]
source("tools/r/casos.R"); source("tools/r/instrumentacion.R")
source("tools/r/experimentos/r6pack_canonico.R")
RNGkind("Mersenne-Twister", "Inversion", "Rejection")
caso <- commandArgs(TRUE)[1]; if (is.na(caso)) caso <- "C1"
x0 <- leer_csv_gz(file.path(RAIZ_FIXTURES, caso, "x.csv.gz"))
n <- nrow(x0); p <- ncol(x0); h <- as.integer(ceiling(0.5 * n)); me <- max(n, p) * .Machine$double.eps
R <- initHsets_variantes(x0, variantes = list(VAR_OFICIAL), diag = TRUE)
xs <- R$x; sref <- svd(xs, nu = 0, nv = 0)$d[1]
ns <- asNamespace("rrcov"); Qn_ <- get("Qn", ns)
fijar <- get("fijar_signo", .ENV_CANON)
cat(sprintf("Caso %s: n=%d p=%d h=%d  sigma_1(data)=%.4g  umbral complemento sqrt(eps)=%.3g (max(n,p)eps=%.3g)\n\n", caso, n, p, h, sref, sref * sqrt(.Machine$double.eps), sref * me))
nombres <- c("R1 tanh", "R2 Spearman", "R3 normal scores", "SCM", "covx BACON")
filas <- list()
for (k in 1:5) {
  P <- R$diag[[k]]$P; ev <- R$diag[[k]]$ev
  r <- sum(ev > ev[1] * me); V <- fijar(P[, seq_len(r), drop = FALSE])
  Z <- xs - (xs %*% V) %*% t(V); sv <- svd(Z, nu = 0)
  s <- sum(sv$d > sref * sqrt(.Machine$double.eps)); sZ <- sum(sv$d > sv$d[1] * me); sE <- sum(sv$d > sref * me)
  W <- if (s > 0) fijar(sv$v[, seq_len(s), drop = FALSE]) else matrix(0, p, 0)
  PP <- cbind(V, W)
  pr <- xs %*% PP
  lam <- get("doScale", ns)(pr, center = median, scale = Qn_)$scale
  sc <- PP %*% (lam * t(PP)); si <- PP %*% (t(PP) / lam)
  est <- get("colMedians", ns)(xs %*% si) %*% sc
  cx <- (xs - rep(est, each = n)) %*% PP
  dd <- (cx / rep(lam, each = n))^2
  fW <- if (s > 0) median(rowSums(dd[, (r + 1):(r + s), drop = FALSE]) / rowSums(dd)) else 0
  filas[[k]] <- data.frame(conjunto = nombres[k], r = r, s = s, r_mas_s = r + s, s_umbral_eps = sE, s_umbral_sigma1Z = sZ,
    sigmaZ_1 = sv$d[1], sigmaZ_s = if (s > 0) sv$d[s] else NA, sigmaZ_s1 = if (s < length(sv$d)) sv$d[s + 1] else NA,
    med_Qn_V = median(lam[seq_len(r)]), med_Qn_W = if (s > 0) median(lam[(r + 1):(r + s)]) else NA,
    frac_dist_W = fW)
}
D <- do.call(rbind, filas); options(width = 250)
print(D, digits = 3, row.names = FALSE)
write.csv(D, sprintf("tools/r/experimentos/resultados/diagnostico_canonico2_%s.csv", caso), row.names = FALSE)
## (b) sensibilidad
grid <- expand.grid(k1 = c(0.1, 1, 10), k2 = c(0.1, 1, 10))
Vg <- initHsets_variantes(x0, variantes = c(list(VAR_OFICIAL, VAR_CANON(1)), lapply(seq_len(nrow(grid)), function(i) VAR_CANON2(grid$k1[i], grid$k2[i]))))
base <- Vg[[2 + which(grid$k1 == 1 & grid$k2 == 1)]]
ncamb <- function(A, B) sum(vapply(1:6, function(k) !setequal(A[, k], B[, k]), NA))
cat("\n(b) Sensibilidad (umbral complemento sigma_1*sqrt(eps)*kappa2): conjuntos distintos frente a (kappa=1, kappa2=1)\n")
for (i in seq_len(nrow(grid))) cat(sprintf("  kappa=%-4g kappa2=%-4g : %d\n", grid$k1[i], grid$k2[i], ncamb(Vg[[2 + i]], base)))
cat(sprintf("  canonical2 vs oficial: %d conjuntos distintos; canonical2 vs canonical: %d; conjunto 6 igual al oficial: %s\n",
            ncamb(base, Vg[[1]]), ncamb(base, Vg[[2]]), identical(base[, 6], Vg[[1]][, 6])))
## (c) perturbación
cat("\n(c) Perturbacion 1e-14 relativa (5 veces): conjuntos que cambian\n")
ch <- function(a, b) paste(which(vapply(1:6, function(k) !setequal(a[, k], b[, k]), NA)), collapse = ",")
for (j in 1:5) {
  set.seed(20262000 + j)
  xp <- x0 * (1 + 1e-14 * runif(length(x0), -1, 1))
  Vp <- initHsets_variantes(xp, variantes = list(VAR_OFICIAL, VAR_CANON(1), VAR_CANON2(1, 1), VAR_CANON2(1, 1, "eps")))
  cat(sprintf("  pert %d: oficial {%s}; canonical {%s}; canonical2 {%s}; canonical2 umbral eps {%s}\n", j, ch(Vg[[1]], Vp[[1]]), ch(Vg[[2]], Vp[[2]]), ch(base, Vp[[3]]), ch(Vg[[length(Vg)]], Vp[[4]])))
}
## (d) identidad con rrcov
of <- rrcov:::.detmrcd(x0, alpha = 0.5, h = NULL, rho = NULL, maxcond = 50, target = 0, maxcsteps = 200,
                       hsets.init = NULL, save.hsets = TRUE, trace = 0L)$initHsets
cat(sprintf("\n(d) initHsets canonical2 identicos bit a bit a rrcov: %s; CovMrcd(initHsets=canonical2) == CovMrcd(x): %s\n",
            identical(base, of), all(comparar_s4(CovMrcd(x0), CovMrcd(x0, initHsets = base)))))
