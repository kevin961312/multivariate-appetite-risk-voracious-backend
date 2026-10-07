## PILOTO 2 (rama experimento/mrcd-canonico): rrcov oficial vs canonical (truncada, piloto 1) vs canonical2
## (V_r + complemento con variación real), más el control canonical2 con umbral eps (el inicialmente propuesto).
## Ver docs/experimentos/2026-10-06-mrcd-canonico-piloto2.md y tools/r/experimentos/r6pack_canonico.R.
## Mismas configuraciones 1-8, semillas y réplicas que el piloto 1, más la 9 (contaminación difícil).
## Semillas: réplica r de la configuración c -> 20262000 + 1000*c + r; perturbación j (1..5) -> esa + 100000*j
## (las perturbaciones 1-3 coinciden con las del piloto 1).
## Paralelismo: cluster PSOCK de 8 procesos (mclapply/fork aborta en eigen() con Accelerate en este Mac).
## Uso: Rscript tools/r/experimentos/piloto_canonico2.R [NREP] [configs] [salida.csv]
args <- commandArgs(TRUE)
NREP <- if (length(args) >= 1) as.integer(args[1]) else 50L
CFG_SEL <- if (length(args) >= 2 && nzchar(args[2])) as.integer(strsplit(args[2], ",")[[1]]) else NULL
SALIDA <- if (length(args) >= 3) args[3] else "tools/r/experimentos/resultados/piloto_canonico2.csv"
SEMILLA_BASE <- 20262000L
NPERT <- 5L
EPS_PERT <- 1e-14

configs <- list(
  list(id = 1, nombre = "I_50x200",    n = 50,  p = 200, sigma = "I",   contam = 0),
  list(id = 2, nombre = "I_100x200",   n = 100, p = 200, sigma = "I",   contam = 0),
  list(id = 3, nombre = "I_50x250",    n = 50,  p = 250, sigma = "I",   contam = 0),
  list(id = 4, nombre = "I_100x250",   n = 100, p = 250, sigma = "I",   contam = 0),
  list(id = 5, nombre = "AR1_50x200",  n = 50,  p = 200, sigma = "AR1", contam = 0),
  list(id = 6, nombre = "CONT_50x200", n = 50,  p = 200, sigma = "I",   contam = 0.10),
  list(id = 7, nombre = "I_100x20",    n = 100, p = 20,  sigma = "I",   contam = 0),
  list(id = 8, nombre = "AR1_200x40",  n = 200, p = 40,  sigma = "AR1", contam = 0),
  ## contaminación difícil: 10 % de filas (las primeras 5) desplazadas +1.5 solo en las 10 primeras coordenadas
  list(id = 9, nombre = "CONTD_50x200", n = 50, p = 200, sigma = "I",  contam = 0.10, shift = 1.5, ncoord = 10)
)
if (!is.null(CFG_SEL)) configs <- configs[vapply(configs, function(c) c$id %in% CFG_SEL, NA)]

iniciar_worker <- function() {
  source("tools/r/casos.R"); source("tools/r/instrumentacion.R")
  source("tools/r/experimentos/r6pack_canonico.R")
  RNGkind("Mersenne-Twister", "Inversion", "Rejection")
  assign("E_INS", cargar_instrumentado(), envir = globalenv())
  TRUE
}

una_replica <- function(tarea) {
  cfg <- tarea$cfg; r <- tarea$rep
  n <- cfg$n; p <- cfg$p; h <- as.integer(ceiling(0.5 * n))
  seed <- SEMILLA_BASE + 1000L * cfg$id + r
  set.seed(seed, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
  x <- matrix(rnorm(n * p), n, p) %*% chol(sigma_de(cfg$sigma, p))
  atip <- integer(0)
  if (cfg$contam > 0) {
    atip <- seq_len(ceiling(cfg$contam * n))
    cols <- if (is.null(cfg$ncoord)) seq_len(p) else seq_len(cfg$ncoord)
    x[atip, cols] <- x[atip, cols] + (if (is.null(cfg$shift)) SHIFT else cfg$shift)
  }
  el <- function() proc.time()[["elapsed"]]
  ## ---- ajustes cronometrados sobre x ----
  t0 <- el(); ro <- correr_instrumentado(x, save.hsets = TRUE, full = FALSE, E = E_INS); t_off <- el() - t0
  t0 <- el(); H1 <- initHsets_canonico(x); fit1 <- correr_instrumentado(x, initHsets = H1, full = FALSE, E = E_INS); t_can <- el() - t0
  t0 <- el(); H2 <- initHsets_canonico2(x); fit2 <- correr_instrumentado(x, initHsets = H2, full = FALSE, E = E_INS); t_can2 <- el() - t0
  Ho <- ro$cap$hs_init
  ## ---- variantes en una pasada: verificación, control eps y sensibilidad ----
  grid2 <- expand.grid(k1 = c(0.1, 1, 10), k2 = c(0.1, 1, 10))
  grid2 <- grid2[!(grid2$k1 == 1 & grid2$k2 == 1), ]
  vars <- c(list(VAR_OFICIAL, VAR_CANON(1), VAR_CANON2(1, 1), VAR_CANON2(1, 1, "eps"), VAR_CANON(0.1), VAR_CANON(10)),
            lapply(seq_len(nrow(grid2)), function(i) VAR_CANON2(grid2$k1[i], grid2$k2[i])))
  V <- initHsets_variantes(x, variantes = vars, diag = TRUE)
  ncamb <- function(A, B) sum(vapply(1:6, function(k) !setequal(A[, k], B[, k]), NA))
  ver <- identical(V$hsets[[1]], Ho) && identical(V$hsets[[2]], H1) && identical(V$hsets[[3]], H2)
  ## r y s por conjunto (kappa = kappa2 = 1)
  fijar <- get("fijar_signo", .ENV_CANON)
  rs <- vapply(1:5, function(k) {
    ev <- V$diag[[k]]$ev; P <- V$diag[[k]]$P
    rr <- sum(ev > ev[1] * max(n, p) * .Machine$double.eps)
    Vr <- fijar(P[, seq_len(rr), drop = FALSE]); Z <- V$x - (V$x %*% Vr) %*% t(Vr)
    c(rr, sum(svd(Z, nu = 0, nv = 0)$d > V$sref * sqrt(.Machine$double.eps)))
  }, c(0, 0))
  ## ---- objetivo en el espacio estandarizado ----
  vmx <- apply(x, 2, median); vsd <- apply(x, 2, Qn); vsd[vsd < 0.001] <- 0.001
  Z <- scale(x, center = vmx, scale = vsd); scfac <- ro$cap$scfac
  logobj <- function(B, rho) {
    Zb <- Z[B, , drop = FALSE]; Ec <- sweep(Zb, 2, colMeans(Zb))
    as.numeric(determinant(rho * diag(p) + (1 - rho) * scfac * crossprod(Ec) / h, logarithm = TRUE)$modulus) / p
  }
  relF <- function(A, B) norm(A - B, "F") / norm(B, "F")
  Ro <- ro$res; R1 <- fit1$res; R2 <- fit2$res
  Re <- correr_instrumentado(x, initHsets = V$hsets[[4]], full = FALSE, E = E_INS)$res   # control eps
  auc <- function(m) {
    if (!length(atip)) return(NA_real_)
    rg <- rank(m); na <- length(atip); (sum(rg[atip]) - na * (na + 1) / 2) / (na * (n - na))
  }
  ## sensibilidad: initHsets distintos y, si los hay, efecto en la solución
  sens <- function(idx, ref, Rref) {
    nc <- vapply(idx, function(i) ncamb(V$hsets[[i]], ref), 0)
    bch <- 0; rf <- 0
    for (i in idx[nc > 0]) {
      rs_ <- correr_instrumentado(x, initHsets = V$hsets[[i]], full = FALSE, E = E_INS)$res
      bch <- max(bch, !setequal(rs_@best, Rref@best)); rf <- max(rf, relF(rs_@cov, Rref@cov))
    }
    c(sum(nc), sum(nc > 0), bch, rf)
  }
  s1 <- sens(5:6, H1, R1); s2 <- sens(6 + seq_len(nrow(grid2)), H2, R2)
  ## ---- perturbaciones ----
  bo <- sort(Ro@best)
  pt <- lapply(seq_len(NPERT), function(j) {
    set.seed(seed + 100000L * j, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
    xp <- x * (1 + EPS_PERT * runif(length(x), -1, 1))
    Vp <- initHsets_variantes(xp, variantes = list(VAR_OFICIAL, VAR_CANON(1), VAR_CANON2(1, 1), VAR_CANON2(1, 1, "eps")))
    refsH <- list(Ho, H1, H2, V$hsets[[4]]); refsR <- list(Ro, R1, R2, Re)
    out <- list()
    for (v in 1:4) {
      rp <- correr_instrumentado(xp, initHsets = Vp[[v]], full = FALSE, E = E_INS)$res
      out[[v]] <- c(ns = ncamb(Vp[[v]], refsH[[v]]), best = !setequal(rp@best, refsR[[v]]@best),
                    drho = abs(rp@rho - refsR[[v]]@rho), relF = relF(rp@cov, refsR[[v]]@cov),
                    dcrit = abs(rp@crit - refsR[[v]]@crit),
                    obj_own = if (v == 1) logobj(sort(rp@best), rp@rho) else NA,
                    obj_rhooff = if (v == 1) logobj(sort(rp@best), Ro@rho) else NA)
    }
    out
  })
  agg <- function(v, nm) vapply(pt, function(o) o[[v]][[nm]], 0)
  TOL_RHO <- 1e-10; TOL_COV <- 1e-8
  fila <- list(config = cfg$nombre, cfg_id = cfg$id, n = n, p = p, h = h, rep = r, seed = seed, ver_hsets = ver)
  for (k in 1:5) { fila[[paste0("r_set", k)]] <- rs[1, k]; fila[[paste0("s_set", k)]] <- rs[2, k] }
  fila <- c(fila, list(t_off = t_off, t_can = t_can, t_can2 = t_can2,
    sens_can_nsets = s1[1], sens_can_best = s1[3], sens_can_relF = s1[4],
    sens_can2_nsets = s2[1], sens_can2_ncomb = s2[2], sens_can2_best = s2[3], sens_can2_relF = s2[4],
    nsets_can_vs_off = ncamb(H1, Ho), nsets_can2_vs_off = ncamb(H2, Ho), nsets_can2_vs_can = ncamb(H2, H1)))
  objs_own <- agg(1, "obj_own"); objs_rho <- agg(1, "obj_rhooff")
  pctl <- function(v, ref) (sum(ref < v - 1e-12) + 0.5 * sum(abs(ref - v) <= 1e-12)) / length(ref)
  lo_off <- logobj(bo, Ro@rho)
  fila <- c(fila, list(rho_off = Ro@rho, crit_off = Ro@crit, logobj_off = lo_off,
    iBest_off = paste(ro$cap$sel_best6pack, collapse = "|"),
    rrcov_pert_obj_own_min = min(objs_own), rrcov_pert_obj_own_max = max(objs_own),
    rrcov_pert_obj_rho_min = min(objs_rho), rrcov_pert_obj_rho_max = max(objs_rho)))
  nm <- c("off", "can", "can2", "can2eps"); Rs <- list(Ro, R1, R2, Re)
  ib <- list(ro$cap$sel_best6pack, fit1$cap$sel_best6pack, fit2$cap$sel_best6pack, NA)
  for (v in 1:4) {
    R_ <- Rs[[v]]; b <- sort(R_@best); s <- nm[v]
    if (v > 1) {
      lo <- logobj(b, R_@rho); lr <- logobj(b, Ro@rho)
      fila[[paste0("rho_", s)]] <- R_@rho; fila[[paste0("crit_", s)]] <- R_@crit
      fila[[paste0("logobj_", s)]] <- lo; fila[[paste0("logobj_", s, "_rhooff")]] <- lr
      fila[[paste0("iBest_", s)]] <- paste(ib[[v]], collapse = "|")
      fila[[paste0("pctl_own_", s)]] <- pctl(lo, objs_own)
      fila[[paste0("pctl_rho_", s)]] <- pctl(lr, objs_rho)
      fila[[paste0("relF_", s, "_off")]] <- relF(R_@cov, Ro@cov)
      fila[[paste0("maxabs_", s, "_off")]] <- max(abs(R_@cov - Ro@cov))
      fila[[paste0("solape_", s)]] <- length(intersect(b, bo)) / h
      fila[[paste0("best_igual_", s)]] <- identical(b, bo)
      fila[[paste0("cov_identica_", s)]] <- identical(R_@cov, Ro@cov)
      fila[[paste0("rho_identico_", s)]] <- identical(R_@rho, Ro@rho)
    }
    fila[[paste0("atip_en_best_", s)]] <- if (length(atip)) sum(atip %in% b) / length(atip) else NA_real_
    fila[[paste0("auc_", s)]] <- auc(R_@mah)
    fila[[paste0("pert_hsets_", s)]] <- sum(agg(v, "ns") > 0)
    fila[[paste0("pert_nsets_", s)]] <- sum(agg(v, "ns"))
    fila[[paste0("pert_best_", s)]] <- sum(agg(v, "best"))
    fila[[paste0("pert_rho_", s)]] <- sum(agg(v, "drho") > TOL_RHO)
    fila[[paste0("pert_cov_", s)]] <- sum(agg(v, "relF") > TOL_COV)
    fila[[paste0("pert_maxdrho_", s)]] <- max(agg(v, "drho"))
    fila[[paste0("pert_maxrelF_", s)]] <- max(agg(v, "relF"))
    fila[[paste0("pert_maxdcrit_", s)]] <- max(agg(v, "dcrit"))
  }
  fila$n_atip <- length(atip)
  as.data.frame(fila, stringsAsFactors = FALSE)
}

tareas <- unlist(lapply(configs, function(cfg) lapply(seq_len(NREP), function(r) list(cfg = cfg, rep = r))), recursive = FALSE)
coste <- vapply(tareas, function(t) t$cfg$p^2 * t$cfg$n, 0)
tareas <- tareas[order(-coste)]
cat(sprintf("Piloto 2: %d configuraciones x %d réplicas = %d tareas, 8 procesos PSOCK\n", length(configs), NREP, length(tareas)))
t_ini <- proc.time()[["elapsed"]]
cl <- parallel::makeCluster(8, type = "PSOCK")
parallel::clusterExport(cl, c("SEMILLA_BASE", "NPERT", "EPS_PERT", "una_replica", "iniciar_worker"))
invisible(parallel::clusterCall(cl, function(wd) { setwd(wd); iniciar_worker() }, getwd()))
res <- parallel::parLapplyLB(cl, tareas, function(t) tryCatch(una_replica(t), error = function(e)
  data.frame(config = t$cfg$nombre, rep = t$rep, error = conditionMessage(e))))
parallel::stopCluster(cl)
errores <- Filter(function(d) "error" %in% names(d), res)
if (length(errores)) { print(do.call(rbind, errores)); stop("hubo errores en ", length(errores), " tareas") }
D <- do.call(rbind, res)
D <- D[order(D$cfg_id, D$rep), ]
num <- vapply(D, is.double, NA)
D[num] <- lapply(D[num], signif, digits = 10)
write.csv(D, SALIDA, row.names = FALSE)
cat(sprintf("Tiempo total: %.1f s; filas: %d; verificación (copia oficial == rrcov, variantes == atajos) en todas: %s\n",
            proc.time()[["elapsed"]] - t_ini, nrow(D), all(D$ver_hsets)))
