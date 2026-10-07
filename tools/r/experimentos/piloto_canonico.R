## PILOTO (rama experimento/mrcd-canonico): inicialización canónica determinista de MRCD vs rrcov oficial.
## Ver docs/experimentos/2026-10-06-mrcd-canonico-piloto.md y tools/r/experimentos/r6pack_canonico.R.
##
## Para cada configuración y réplica se ajusta MRCD (CovMrcd, defaults de rrcov 1.7-7, target identity) con
##   - oficial:   correr_instrumentado(x, save.hsets=TRUE)  (r6pack oficial dentro de rrcov)
##   - canónico:  initHsets_canonico(x)  +  correr_instrumentado(x, initHsets=H)  (resto de MRCD oficial)
## y se mide determinismo ante perturbación 1e-14 relativa, objetivo, distancia entre soluciones, calidad en
## contaminados, sensibilidad al umbral (kappa 0.1 y 10) y tiempos.
## Las perturbaciones inyectan los initHsets de la copia oficial (bit a bit idénticos a rrcov, verificado en
## cada réplica sobre x y en verificar_canonico.R; inyectar == calcular dentro, verificado en C1-C10).
##
## Paralelismo: cluster PSOCK de 8 procesos (parallel::parLapply). parallel::mclapply (fork) aborta con
## segfault en eigen() en este Mac (Accelerate/vecLib tras fork), ver verificar_canonico.R.
## Semillas: réplica r de la configuración c -> 20262000 + 1000*c + r; perturbación j -> esa + 100000*j.
## Uso: Rscript tools/r/experimentos/piloto_canonico.R [NREP] [configs separadas por coma]
##      (desde la raíz del repo; por defecto NREP=50 y todas las configuraciones)
args <- commandArgs(TRUE)
NREP <- if (length(args) >= 1) as.integer(args[1]) else 50L
CFG_SEL <- if (length(args) >= 2) as.integer(strsplit(args[2], ",")[[1]]) else NULL
SALIDA <- if (length(args) >= 3) args[3] else "tools/r/experimentos/resultados/piloto_canonico.csv"
SEMILLA_BASE <- 20262000L
NPERT <- 3L
EPS_PERT <- 1e-14

configs <- list(
  list(id = 1, nombre = "I_50x200",    n = 50,  p = 200, sigma = "I",   contam = 0),
  list(id = 2, nombre = "I_100x200",   n = 100, p = 200, sigma = "I",   contam = 0),
  list(id = 3, nombre = "I_50x250",    n = 50,  p = 250, sigma = "I",   contam = 0),
  list(id = 4, nombre = "I_100x250",   n = 100, p = 250, sigma = "I",   contam = 0),
  list(id = 5, nombre = "AR1_50x200",  n = 50,  p = 200, sigma = "AR1", contam = 0),
  list(id = 6, nombre = "CONT_50x200", n = 50,  p = 200, sigma = "I",   contam = 0.10),
  list(id = 7, nombre = "I_100x20",    n = 100, p = 20,  sigma = "I",   contam = 0),
  list(id = 8, nombre = "AR1_200x40",  n = 200, p = 40,  sigma = "AR1", contam = 0)
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
  if (cfg$contam > 0) {                           # como C10: primeras ceiling(frac*n) filas +5 en todo
    atip <- seq_len(ceiling(cfg$contam * n)); x[atip, ] <- x[atip, ] + SHIFT
  }
  ## ---- ajustes sobre x ----
  t0 <- proc.time()[["elapsed"]]
  ro <- correr_instrumentado(x, save.hsets = TRUE, full = FALSE, E = E_INS)
  t_off <- proc.time()[["elapsed"]] - t0
  t0 <- proc.time()[["elapsed"]]
  Hc <- initHsets_canonico(x)
  t_can_r6 <- proc.time()[["elapsed"]] - t0
  rc <- correr_instrumentado(x, initHsets = Hc, full = FALSE, E = E_INS)
  t_can <- proc.time()[["elapsed"]] - t0
  Ho <- ro$cap$hs_init
  ## copia oficial == rrcov (bit a bit) y sensibilidad al umbral
  V <- initHsets_variantes(x, variantes = list(VAR_OFICIAL, VAR_CANON(0.1), VAR_CANON(10)), diag = TRUE)
  ver_oficial <- identical(V$hsets[[1]], Ho)
  ncamb <- function(A, B) sum(vapply(1:6, function(k) !setequal(A[, k], B[, k]), NA))
  rk <- function(kappa) vapply(1:5, function(k) {
    ev <- V$diag[[k]]$ev; sum(ev > ev[1] * max(n, p) * .Machine$double.eps * kappa) }, 0L)
  r1 <- rk(1); r01 <- rk(0.1); r10 <- rk(10)
  ## ---- objetivo en el espacio estandarizado (detmrcd.R:416-422; obj = det(.)^(1/p), :409, :548) ----
  vmx <- apply(x, 2, median); vsd <- apply(x, 2, Qn); vsd[vsd < 0.001] <- 0.001
  Z <- scale(x, center = vmx, scale = vsd)
  scfac <- ro$cap$scfac
  logobj <- function(B, rho) {               # log(det(rho*I + (1-rho)*scfac*S_B)^(1/p)), S_B con /h (.RCOV :273)
    Zb <- Z[B, , drop = FALSE]; E <- sweep(Zb, 2, colMeans(Zb))
    as.numeric(determinant(rho * diag(p) + (1 - rho) * scfac * crossprod(E) / h, logarithm = TRUE)$modulus) / p
  }
  Ro <- ro$res; Rc <- rc$res
  bo <- sort(Ro@best); bc <- sort(Rc@best)
  relF <- function(A, B) norm(A - B, "F") / norm(B, "F")
  ## comprobación de logobj contra la captura cs_obj (si no hay subdesbordamiento)
  kb <- ro$cap$sel_best6pack[1]; ck <- ro$cap[[paste0("cs_obj_k", kb)]]
  chk_obj <- if (is.finite(log(ck)) && ck > 0) logobj(bo, Ro@rho) - log(ck) else NA_real_
  auc <- function(m) {
    if (!length(atip)) return(NA_real_)
    rg <- rank(m); na <- length(atip)
    (sum(rg[atip]) - na * (na + 1) / 2) / (na * (n - na))
  }
  ## sensibilidad al umbral: si los initHsets con kappa 0.1 o 10 difieren de kappa 1, ajustar
  sens <- function(H) {
    nc <- ncamb(H, Hc)
    if (nc == 0) return(c(nc, 0, 0))
    rs <- correr_instrumentado(x, initHsets = H, full = FALSE, E = E_INS)$res
    c(nc, as.numeric(!setequal(rs@best, Rc@best)), relF(rs@cov, Rc@cov))
  }
  s01 <- sens(V$hsets[[2]]); s10 <- sens(V$hsets[[3]])
  ## ---- perturbaciones 1e-14 relativas ----
  pt <- lapply(seq_len(NPERT), function(j) {
    set.seed(seed + 100000L * j, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
    xp <- x * (1 + EPS_PERT * runif(length(x), -1, 1))
    Vp <- initHsets_variantes(xp, variantes = list(VAR_OFICIAL, VAR_CANON(1)))
    rop <- correr_instrumentado(xp, initHsets = Vp[[1]], full = FALSE, E = E_INS)$res
    rcp <- correr_instrumentado(xp, initHsets = Vp[[2]], full = FALSE, E = E_INS)$res
    data.frame(
      off_ns = ncamb(Vp[[1]], Ho), can_ns = ncamb(Vp[[2]], Hc),
      off_best = !setequal(rop@best, Ro@best), can_best = !setequal(rcp@best, Rc@best),
      off_drho = abs(rop@rho - Ro@rho), can_drho = abs(rcp@rho - Rc@rho),
      off_relF = relF(rop@cov, Ro@cov), can_relF = relF(rcp@cov, Rc@cov),
      off_maxabs = max(abs(rop@cov - Ro@cov)), can_maxabs = max(abs(rcp@cov - Rc@cov)),
      off_dcrit = abs(rop@crit - Ro@crit), can_dcrit = abs(rcp@crit - Rc@crit))
  })
  pt <- do.call(rbind, pt)
  TOL_RHO <- 1e-10; TOL_COV <- 1e-8
  data.frame(
    config = cfg$nombre, cfg_id = cfg$id, n = n, p = p, h = h, rep = r, seed = seed,
    ver_hsets_oficial = ver_oficial,
    r_set1 = r1[1], r_set2 = r1[2], r_set3 = r1[3], r_set4 = r1[4], r_set5 = r1[5],
    r_k01_igual = identical(r01, r1), r_k10_igual = identical(r10, r1),
    nsets_can_vs_off = ncamb(Hc, Ho),
    t_off = t_off, t_can = t_can, t_can_r6 = t_can_r6,
    rho_off = Ro@rho, rho_can = Rc@rho, crit_off = Ro@crit, crit_can = Rc@crit,
    iBest_off = paste(ro$cap$sel_best6pack, collapse = "|"), iBest_can = paste(rc$cap$sel_best6pack, collapse = "|"),
    logobj_off = logobj(bo, Ro@rho), logobj_can = logobj(bc, Rc@rho), logobj_can_rhooff = logobj(bc, Ro@rho),
    chk_logobj = chk_obj,
    best_igual = identical(bo, bc), solape_best = length(intersect(bo, bc)) / h,
    relF_can_off = relF(Rc@cov, Ro@cov), maxabs_can_off = max(abs(Rc@cov - Ro@cov)),
    cov_identica = identical(Rc@cov, Ro@cov), rho_identico = identical(Rc@rho, Ro@rho),
    n_atip = length(atip),
    atip_en_best_off = if (length(atip)) sum(atip %in% bo) / length(atip) else NA_real_,
    atip_en_best_can = if (length(atip)) sum(atip %in% bc) / length(atip) else NA_real_,
    auc_off = auc(Ro@mah), auc_can = auc(Rc@mah),
    sens01_nsets = s01[1], sens01_best = s01[2], sens01_relF = s01[3],
    sens10_nsets = s10[1], sens10_best = s10[2], sens10_relF = s10[3],
    off_pert_hsets = sum(pt$off_ns > 0), off_pert_nsets = sum(pt$off_ns),
    off_pert_best = sum(pt$off_best), off_pert_rho = sum(pt$off_drho > TOL_RHO),
    off_pert_cov = sum(pt$off_relF > TOL_COV), off_pert_maxdrho = max(pt$off_drho),
    off_pert_maxrelF = max(pt$off_relF), off_pert_maxabs = max(pt$off_maxabs), off_pert_maxdcrit = max(pt$off_dcrit),
    can_pert_hsets = sum(pt$can_ns > 0), can_pert_nsets = sum(pt$can_ns),
    can_pert_best = sum(pt$can_best), can_pert_rho = sum(pt$can_drho > TOL_RHO),
    can_pert_cov = sum(pt$can_relF > TOL_COV), can_pert_maxdrho = max(pt$can_drho),
    can_pert_maxrelF = max(pt$can_relF), can_pert_maxabs = max(pt$can_maxabs), can_pert_maxdcrit = max(pt$can_dcrit),
    stringsAsFactors = FALSE)
}

tareas <- unlist(lapply(configs, function(cfg) lapply(seq_len(NREP), function(r) list(cfg = cfg, rep = r))),
                 recursive = FALSE)
## las tareas más caras (p grande, n grande) primero para equilibrar la carga
coste <- vapply(tareas, function(t) t$cfg$p^2 * t$cfg$n, 0)
tareas <- tareas[order(-coste)]
cat(sprintf("Piloto: %d configuraciones x %d réplicas = %d tareas, 8 procesos PSOCK\n", length(configs), NREP, length(tareas)))
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
cat(sprintf("Tiempo total: %.1f s; filas: %d; verificación copia oficial == rrcov en todas: %s\n",
            proc.time()[["elapsed"]] - t_ini, nrow(D), all(D$ver_hsets_oficial)))
