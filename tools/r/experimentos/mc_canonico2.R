## MONTE CARLO PRE-REGISTRADO (rama experimento/mrcd-canonico): carta T2_MRCD con rrcov oficial vs canonical2.
## Protocolo: docs/experimentos/2026-10-07-mc-canonico2-protocolo.md (cualquier cambio de este script después
## de aprobado el protocolo debe declararse como desviación en el informe).
##
## Metodología de la carta (tesis del dueño; citas en el protocolo §2):
##   - Fase I, observaciones individuales: T2_i = (x_i - mu_MRCD)' Sigma_MRCD^-1 (x_i - mu_MRCD),
##     con CovMrcd(x, alpha = 0.75) y mahalanobis(x, center, cov) (notebook celda 5:205-211).
##   - UCL = cuantil empírico 1 - 0.05 (EnvStats::qemp) de los T2 de las observaciones del subconjunto
##     `best`, juntando todas las réplicas en control (celda 5:210-211, 236; celda 6:80).
##   - UCLmax = qemp(0.95) del máximo de T2 por réplica (celda 6:81).
##   - Fuera de control: floor(pi*n) atípicos ~ N(mu1, Sigma) añadidos al final (celda 5:261-269);
##     probabilidad de señal = fracción de T2 de los atípicos > UCL (celda 5:280, 327; SignalProbability).
##   - En control (delta = 0): fracción de T2 del subconjunto best > UCL (celda 5:277-278).
## Variantes: "off" = rrcov::CovMrcd oficial 1.7-7 (referencias/R-lib); "c2" = canonical2
##   (tools/r/experimentos/r6pack_canonico.R, VAR_CANON2(1, 1): V_r con lambda_1*max(n,p)*eps y complemento
##   con sigma_1(data)*sqrt(eps); umbrales FIJADOS, no se tocan). Los mismos datos alimentan a ambas (pareado).
##
## Uso (desde la raíz del repo; salida a fichero y EXIT, ver CLAUDE.md):
##   Rscript tools/r/experimentos/mc_canonico2.R --piloto              > log 2>&1; echo "EXIT=$?"
##   Rscript tools/r/experimentos/mc_canonico2.R                       (corrida completa: simular + analizar)
##   Rscript tools/r/experimentos/mc_canonico2.R --fase=simular        (solo simular; reanudable)
##   Rscript tools/r/experimentos/mc_canonico2.R --fase=analizar       (solo analizar los checkpoints)
##   Opciones: --configs=1,2,7  --nucleos=8  --salida=<dir>
## Reanudar: volver a lanzar el mismo comando; los bloques ya escritos (ck_*.rds) no se recalculan.
## Paralelismo: PSOCK (fork/mclapply aborta en eigen() con Accelerate en este Mac).

args <- commandArgs(TRUE)
opt <- function(nombre, defecto = NULL) {
  a <- grep(paste0("^--", nombre, "="), args, value = TRUE)
  if (length(a)) sub(paste0("^--", nombre, "="), "", a[1]) else defecto
}
PILOTO   <- "--piloto" %in% args
FASE     <- opt("fase", "todo")                     # simular | analizar | todo
NUCLEOS  <- as.integer(opt("nucleos", "8"))
CFG_SEL  <- { v <- opt("configs"); if (is.null(v)) NULL else as.integer(strsplit(v, ",")[[1]]) }
## definición del UCL que decide (supuesto S1 del protocolo, a confirmar por el dueño ANTES de la corrida):
##   best  = cuantil del T2 de las observaciones del subconjunto best (código de la tesis, celda 5:210-211)
##   todas = cuantil del T2 de las n observaciones (texto del artículo, Template.tex:158)
## Se calculan ambas; esta opción solo elige cuál alimenta la decisión.
UCL_PRIM <- match.arg(opt("ucl", "best"), c("best", "todas"))
SALIDA   <- opt("salida", if (PILOTO) "tools/r/experimentos/resultados/mc_canonico2_piloto"
                          else "tools/r/experimentos/resultados/mc_canonico2")

## ---------------- Parámetros pre-registrados (protocolo §4-§7) ----------------
SEMILLA_BASE <- 20263000L
ALPHA_MRCD   <- 0.75          # notebook celda 6:21; artículo Template.tex:138 (h = 75 %)
ALPHA_PFA    <- 0.05          # celda 6:22; Template.tex:158
EPS_PERT     <- 1e-14
R_CAL        <- if (PILOTO) 5L    else 1000L   # réplicas de calibración (Fase I en control)
R_EVAL_100   <- if (PILOTO) 5L    else 1000L   # réplicas por escenario de evaluación con n >= 100
R_EVAL_50    <- if (PILOTO) 5L    else 2000L   # ídem con n = 50 (DE por réplica del piloto ~2x: protocolo §7)
R_PERT       <- if (PILOTO) 2L    else 200L    # réplicas (las primeras) en las que se re-ajusta rrcov perturbado
R_PERT_C2    <- if (PILOTO) 1L    else 50L     # ídem canonical2 perturbado (confirmación del determinismo)
TAM_BLOQUE   <- if (PILOTO) 5L    else 25L     # réplicas por checkpoint
B_BOOT       <- if (PILOTO) 200L  else 2000L   # remuestreos del bootstrap pareado en dos etapas
MARGEN_SP    <- 0.02          # |Delta prob. de señal|
MARGEN_FA    <- 0.01          # |Delta prob. de falsa alarma|
ALFA_TEST    <- 0.05
SEMILLA_BOOT <- SEMILLA_BASE + 999L

CONFIGS <- list(
  list(id = 1, nombre = "I_50x200",     n = 50,  p = 200, sigma = "I"),
  list(id = 2, nombre = "I_100x200",    n = 100, p = 200, sigma = "I"),
  list(id = 3, nombre = "I_50x250",     n = 50,  p = 250, sigma = "I"),
  list(id = 4, nombre = "I_100x250",    n = 100, p = 250, sigma = "I"),
  list(id = 5, nombre = "AR07_50x200",  n = 50,  p = 200, sigma = "AR", phi = 0.7),
  list(id = 6, nombre = "I_100x20",     n = 100, p = 20,  sigma = "I"),             # control n > p
  list(id = 7, nombre = "AR05_100x200", n = 100, p = 200, sigma = "AR", phi = 0.5)  # Sigma de la tesis
)
CFG_PRIMARIAS <- c(1, 2, 3, 4, 5, 7)     # p > n: familia de la decisión
CFG_CONTROL   <- 6                       # n > p: debe ser idéntica bit a bit

SETS <- list(
  list(id = 0, nombre = "CAL",      pi = 0,    tipo = "control"),                 # calibración del UCL
  list(id = 1, nombre = "IC",       pi = 0,    tipo = "control"),                 # falsa alarma
  list(id = 2, nombre = "M010",     pi = 0.10, tipo = "media", a = 0.10),         # mu1 = 0.10 * 1_p
  list(id = 3, nombre = "M025",     pi = 0.10, tipo = "media", a = 0.25),
  list(id = 4, nombre = "M050",     pi = 0.10, tipo = "media", a = 0.50),
  list(id = 5, nombre = "M025_P20", pi = 0.20, tipo = "media", a = 0.25),
  list(id = 6, nombre = "DIF",      pi = 0.10, tipo = "parcial", a = 1.5, q = 10),     # difícil: +1.5 en 10 variables
  list(id = 7, nombre = "COR",      pi = 0.10, tipo = "correlacion", phi_out = -0.9)  # atípicos de correlación
)
if (!is.null(CFG_SEL)) CONFIGS <- CONFIGS[vapply(CONFIGS, function(c) c$id %in% CFG_SEL, NA)]
r_eval_de <- function(cfg) if (cfg$n <= 50) R_EVAL_50 else R_EVAL_100
semilla_de <- function(c, s, r) SEMILLA_BASE + 100000L * c + 10000L * s + r   # r <= 9999
dir.create(SALIDA, recursive = TRUE, showWarnings = FALSE)
DIR_CK <- file.path(SALIDA, "checkpoints")
dir.create(DIR_CK, showWarnings = FALSE)
if (!file.exists(file.path(DIR_CK, ".gitignore"))) writeLines("*.rds", file.path(DIR_CK, ".gitignore"))

## ---------------- Worker ----------------
iniciar_worker <- function(wd) {
  setwd(wd)
  suppressMessages(library(rrcov, lib.loc = "referencias/R-lib"))
  stopifnot(normalizePath(find.package("rrcov")) == normalizePath("referencias/R-lib/rrcov"),
            as.character(packageVersion("rrcov")) == "1.7.7")
  source("tools/r/experimentos/r6pack_canonico.R")
  RNGkind("Mersenne-Twister", "Inversion", "Rejection")
  assign(".CHOL", new.env(), envir = globalenv())
  TRUE
}

sigma_ar <- function(p, phi) phi^abs(outer(seq_len(p), seq_len(p), "-"))
chol_de <- function(clave, p, phi) {
  if (is.null(.CHOL[[clave]])) .CHOL[[clave]] <- if (is.na(phi)) diag(p) else chol(sigma_ar(p, phi))
  .CHOL[[clave]]
}

generar <- function(cfg, st, seed) {
  set.seed(seed, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
  n <- cfg$n; p <- cfg$p
  m <- if (st$pi > 0) as.integer(floor(st$pi * n)) else 0L        # celda 5:261
  phi <- if (cfg$sigma == "AR") cfg$phi else NA_real_
  R <- chol_de(paste0("c", cfg$id), p, phi)
  x <- matrix(rnorm((n - m) * p), n - m, p) %*% R
  if (m > 0) {                                                     # celda 5:265-268: atípicos al final
    if (st$tipo == "correlacion") {
      Ro <- chol_de(paste0("o", p, "_", st$phi_out), p, st$phi_out); mu1 <- numeric(p)
    } else {
      Ro <- R; mu1 <- numeric(p)
      if (st$tipo == "media") mu1[] <- st$a else mu1[seq_len(st$q)] <- st$a
    }
    x1 <- matrix(rnorm(m * p), m, p) %*% Ro
    x <- rbind(x, sweep(x1, 2, mu1, "+"))
  }
  list(x = x, m = m)
}

ajustar <- function(x, variante) {
  el <- proc.time()[["elapsed"]]
  fit <- if (variante == "off") CovMrcd(x, alpha = ALPHA_MRCD) else {
    H <- initHsets_variantes(x, alpha = ALPHA_MRCD, variantes = list(VAR_CANON2(1, 1)))[[1]]
    CovMrcd(x, alpha = ALPHA_MRCD, initHsets = H)
  }
  t <- proc.time()[["elapsed"]] - el
  n <- nrow(x)
  list(T2 = mahalanobis(x, fit@center, fit@cov),               # celda 5:205-211
       best = seq_len(n) %in% fit@best, rho = fit@rho, crit = fit@crit, cov = fit@cov, t = t)
}

una_replica <- function(cfg, st, r) {
  seed <- semilla_de(cfg$id, st$id, r)
  d <- generar(cfg, st, seed); x <- d$x
  fo <- ajustar(x, "off"); fc <- ajustar(x, "c2")
  out <- list(r = r, seed = seed, m = d$m,
              T2_off = fo$T2, B_off = fo$best, T2_c2 = fc$T2, B_c2 = fc$best,
              rho_off = fo$rho, rho_c2 = fc$rho, crit_off = fo$crit, crit_c2 = fc$crit,
              t_off = fo$t, t_c2 = fc$t,
              best_igual = identical(fo$best, fc$best), rho_igual = identical(fo$rho, fc$rho),
              cov_igual = identical(fo$cov, fc$cov),
              relF = norm(fc$cov - fo$cov, "F") / norm(fo$cov, "F"))
  if (r <= R_PERT) {
    set.seed(seed + 50000000L, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
    xp <- x * (1 + EPS_PERT * runif(length(x), -1, 1))
    fp <- ajustar(xp, "off")
    out$T2_offp <- fp$T2; out$B_offp <- fp$best; out$t_offp <- fp$t; out$rho_offp <- fp$rho
    if (r <= R_PERT_C2) {
      fq <- ajustar(xp, "c2")
      out$T2_c2p <- fq$T2; out$B_c2p <- fq$best; out$t_c2p <- fq$t
    }
  }
  out
}

correr_bloque <- function(tarea) {
  cfg <- tarea$cfg; st <- tarea$st
  reps <- lapply(tarea$reps, function(r) tryCatch(una_replica(cfg, st, r),
                 error = function(e) list(r = r, error = conditionMessage(e))))
  tmp <- paste0(tarea$archivo, ".tmp")
  saveRDS(list(cfg = cfg$id, set = st$id, reps = reps), tmp)
  file.rename(tmp, tarea$archivo)                                   # escritura atómica: checkpoint
  sum(vapply(reps, function(z) !is.null(z$error), NA))
}

archivo_bloque <- function(c, s, b) file.path(DIR_CK, sprintf("ck_c%d_s%d_b%03d.rds", c, s, b))

## ---------------- Fase simular ----------------
simular <- function() {
  tareas <- list()
  for (cfg in CONFIGS) for (st in SETS) {
    R <- if (st$id == 0) R_CAL else r_eval_de(cfg)
    bloques <- split(seq_len(R), ceiling(seq_len(R) / TAM_BLOQUE))
    for (b in seq_along(bloques)) {
      f <- archivo_bloque(cfg$id, st$id, b)
      if (!file.exists(f)) tareas[[length(tareas) + 1]] <- list(cfg = cfg, st = st, reps = bloques[[b]], archivo = f)
    }
  }
  ## los más caros primero (n * p^2), la calibración antes que la evaluación
  coste <- vapply(tareas, function(t) t$cfg$n * t$cfg$p^2 * 10 - t$st$id, 0)
  tareas <- tareas[order(-coste)]
  cat(sprintf("[%s] simular: %d bloques pendientes, %d procesos PSOCK, salida %s\n",
              format(Sys.time()), length(tareas), NUCLEOS, SALIDA))
  if (!length(tareas)) return(invisible(0))
  t0 <- proc.time()[["elapsed"]]
  cl <- parallel::makeCluster(NUCLEOS, type = "PSOCK")
  on.exit(parallel::stopCluster(cl))
  parallel::clusterExport(cl, c("ALPHA_MRCD", "EPS_PERT", "R_PERT", "R_PERT_C2", "SEMILLA_BASE",
                                "semilla_de", "sigma_ar", "chol_de", "generar", "ajustar", "una_replica"),
                          envir = globalenv())
  invisible(parallel::clusterCall(cl, iniciar_worker, getwd()))
  nerr <- unlist(parallel::parLapplyLB(cl, tareas, correr_bloque, chunk.size = 1))
  cat(sprintf("[%s] simular: %.1f s, réplicas con error: %d\n", format(Sys.time()),
              proc.time()[["elapsed"]] - t0, sum(nerr)))
  invisible(sum(nerr))
}

## ---------------- Fase analizar ----------------
qucl <- function(v) EnvStats::qemp(p = 1 - ALPHA_PFA, obs = v)       # celda 6:80-81

cargar_cfg <- function(c) {
  fs <- list.files(DIR_CK, pattern = sprintf("^ck_c%d_s\\d+_b\\d+\\.rds$", c), full.names = TRUE)
  L <- lapply(fs, readRDS)
  por_set <- split(L, vapply(L, `[[`, 0, "set"))
  lapply(por_set, function(bl) { reps <- unlist(lapply(bl, `[[`, "reps"), recursive = FALSE)
                                 reps[order(vapply(reps, `[[`, 0, "r"))] })
}

## matriz réplicas x k de T2 de un grupo de observaciones
mat_t2 <- function(reps, v, grupo) {
  do.call(rbind, lapply(reps, function(z) {
    T2 <- z[[paste0("T2_", v)]]; n <- length(T2)
    switch(grupo,
           best   = T2[z[[paste0("B_", v)]]],
           todas  = T2,
           atip   = T2[seq.int(n - z$m + 1L, n)],
           limpia = T2[seq_len(n - z$m)])
  }))
}

## Clasificación de una celda (protocolo §6):
##   clase (IC al 90 %, prueba de intersección-unión, sin corrección): EQUIV | NO_INFERIOR (solo SP) | NO_DEMOSTRADA
##   falla (IC ajustado por Bonferroni con K comparaciones): TRUE si la diferencia desfavorable supera el margen
clasificar <- function(lo90, hi90, M, tipo) {
  if (lo90 > -M && hi90 < M) return("EQUIV")
  if (tipo == "SP" && lo90 > -M) return("NO_INFERIOR")
  "NO_DEMOSTRADA"
}
fallar <- function(loA, hiA, M, tipo) if (tipo == "SP") hiA < -M else (loA > M || hiA < -M)

analizar <- function() {
  set.seed(SEMILLA_BOOT, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
  K <- length(intersect(CFG_PRIMARIAS, vapply(CONFIGS, `[[`, 0, "id"))) * (length(SETS) - 1)
  z_adj <- qnorm(1 - ALFA_TEST / max(K, 1)); z_90 <- qnorm(1 - ALFA_TEST)
  filas_rep <- list(); filas_res <- list(); gates <- list()
  for (cfg in CONFIGS) {
    D <- cargar_cfg(cfg$id)
    errs <- sum(unlist(lapply(D, function(reps) vapply(reps, function(z) !is.null(z$error), NA))))
    D <- lapply(D, function(reps) Filter(function(z) is.null(z$error), reps))
    cal <- D[["0"]]
    if (is.null(cal)) { cat("config", cfg$id, "sin calibración; se omite\n"); next }
    ## --- calibración: dos definiciones del UCL por variante ---
    CM <- list(best  = list(off = mat_t2(cal, "off", "best"),  c2 = mat_t2(cal, "c2", "best")),
               todas = list(off = mat_t2(cal, "off", "todas"), c2 = mat_t2(cal, "c2", "todas")))
    UCL <- lapply(CM, function(L) vapply(L, function(M) qucl(as.vector(M)), 0))
    UCLMAX <- vapply(CM$best, function(M) qucl(apply(M, 1, max)), 0)          # celda 6:81
    ## UCL de rrcov con las réplicas perturbadas sustituidas (variabilidad propia en el límite)
    calp <- cal; for (i in seq_along(calp)) if (!is.null(calp[[i]]$T2_offp)) {
      calp[[i]]$T2_off <- calp[[i]]$T2_offp; calp[[i]]$B_off <- calp[[i]]$B_offp }
    UCL_offp <- c(best = qucl(as.vector(mat_t2(calp, "off", "best"))), todas = qucl(as.vector(mat_t2(calp, "off", "todas"))))
    ## índices bootstrap de calibración, comunes a todos los escenarios y definiciones de la configuración
    Rc <- length(cal)
    IC_BOOT <- replicate(B_BOOT, sample.int(Rc, Rc, replace = TRUE), simplify = FALSE)
    UCLb <- lapply(CM, function(L) lapply(L, function(M) vapply(IC_BOOT, function(ii) qucl(as.vector(M[ii, , drop = FALSE])), 0)))
    cat(sprintf("config %s: UCL(best) off = %.4f, c2 = %.4f; UCL(todas) off = %.2f, c2 = %.2f; UCLmax off = %.4f, c2 = %.4f\n",
                cfg$nombre, UCL$best["off"], UCL$best["c2"], UCL$todas["off"], UCL$todas["c2"], UCLMAX["off"], UCLMAX["c2"]))
    U <- UCL$best
    for (st in SETS) {
      reps <- D[[as.character(st$id)]]; if (is.null(reps)) next
      ## --- por réplica (UCL puntuales). met = métrica de la carta del código (UCL best) ---
      filas <- lapply(reps, function(z) {
        n <- length(z$T2_off); idx_m <- if (z$m > 0) seq.int(n - z$m + 1L, n) else integer(0)
        ev <- function(v, u, def) { T2 <- z[[paste0("T2_", v)]]
          if (z$m > 0) mean(T2[idx_m] > u) else if (def == "best") mean(T2[z[[paste0("B_", v)]]] > u) else mean(T2 > u) }
        dec <- function(T2, u) T2 > u
        fila <- list(config = cfg$nombre, cfg_id = cfg$id, set = st$nombre, set_id = st$id, rep = z$r,
                     seed = z$seed, m = z$m, rho_off = z$rho_off, rho_c2 = z$rho_c2,
                     crit_off = z$crit_off, crit_c2 = z$crit_c2, best_igual = z$best_igual,
                     rho_igual = z$rho_igual, cov_igual = z$cov_igual, relF = z$relF,
                     solape = sum(z$B_off & z$B_c2) / sum(z$B_off),
                     t_off = z$t_off, t_c2 = z$t_c2,
                     met_off = ev("off", U["off"], "best"), met_c2 = ev("c2", U["c2"], "best"),
                     metmax_off = ev("off", UCLMAX["off"], "best"), metmax_c2 = ev("c2", UCLMAX["c2"], "best"),
                     mettodas_off = ev("off", UCL$todas["off"], "todas"), mettodas_c2 = ev("c2", UCL$todas["c2"], "todas"),
                     ## limpias > UCL(best): en contaminados = swamping; en control = falsa alarma sobre las n
                     swamp_off = if (z$m > 0) mean(z$T2_off[-idx_m] > U["off"]) else mean(z$T2_off > U["off"]),
                     swamp_c2  = if (z$m > 0) mean(z$T2_c2[-idx_m]  > U["c2"])  else mean(z$T2_c2  > U["c2"]),
                     disc_c2_off = mean(dec(z$T2_c2, U["c2"]) != dec(z$T2_off, U["off"])))
        if (!is.null(z$T2_offp)) {
          fila$disc_offp_off <- mean(dec(z$T2_offp, U["off"]) != dec(z$T2_off, U["off"]))
          fila$met_offp <- if (z$m > 0) mean(z$T2_offp[idx_m] > U["off"]) else mean(z$T2_offp[z$B_offp] > U["off"])
          fila$best_offp_igual <- identical(z$B_offp, z$B_off)
          fila$t_offp <- z$t_offp
        } else { fila$disc_offp_off <- NA; fila$met_offp <- NA; fila$best_offp_igual <- NA; fila$t_offp <- NA }
        if (!is.null(z$T2_c2p)) {
          fila$c2p_det <- identical(z$B_c2p, z$B_c2) &&
            max(abs(z$T2_c2p - z$T2_c2)) <= 1e-8 * max(abs(z$T2_c2)) &&
            identical(dec(z$T2_c2p, U["c2"]), dec(z$T2_c2, U["c2"]))
          fila$t_c2p <- z$t_c2p
        } else { fila$c2p_det <- NA; fila$t_c2p <- NA }
        as.data.frame(fila, stringsAsFactors = FALSE)
      })
      fr_set <- do.call(rbind, filas)
      filas_rep[[length(filas_rep) + 1]] <- fr_set
      if (st$id == 0) next
      sub_p <- fr_set[!is.na(fr_set$disc_offp_off), ]
      tipo <- if (st$id == 1) "FA" else "SP"; Mg <- if (tipo == "FA") MARGEN_FA else MARGEN_SP
      for (def in c("best", "todas")) {
        ## --- métrica del escenario y bootstrap pareado en dos etapas (calibración y evaluación) ---
        grupo <- if (st$id == 1) def else "atip"
        M <- list(off = mat_t2(reps, "off", grupo), c2 = mat_t2(reps, "c2", grupo))
        met <- function(v, u, ii = seq_len(nrow(M[[v]]))) mean(M[[v]][ii, , drop = FALSE] > u)
        u0 <- UCL[[def]]
        est <- c(off = met("off", u0["off"]), c2 = met("c2", u0["c2"]))
        Re <- nrow(M$off)
        db <- vapply(seq_len(B_BOOT), function(b) {
          ie <- sample.int(Re, Re, replace = TRUE)
          met("c2", UCLb[[def]]$c2[b], ie) - met("off", UCLb[[def]]$off[b], ie) }, 0)
        delta <- unname(est["c2"] - est["off"]); se <- sd(db)
        lo90 <- delta - z_90 * se; hi90 <- delta + z_90 * se
        loA <- delta - z_adj * se; hiA <- delta + z_adj * se
        det <- function(v) rowSums(M[[v]] > u0[v]) > 0          # McNemar: al menos una señal en la réplica
        b01 <- sum(!det("off") & det("c2")); b10 <- sum(det("off") & !det("c2"))
        filas_res[[length(filas_res) + 1]] <- data.frame(
          config = cfg$nombre, cfg_id = cfg$id, set = st$nombre, tipo = tipo, def_ucl = def, R = Re,
          primaria = cfg$id %in% CFG_PRIMARIAS && def == UCL_PRIM,
          UCL_off = u0["off"], UCL_c2 = u0["c2"], met_off = est["off"], met_c2 = est["c2"],
          delta = delta, se_boot = se, ic90_lo = lo90, ic90_hi = hi90, icadj_lo = loA, icadj_hi = hiA,
          margen = Mg, clase = clasificar(lo90, hi90, Mg, tipo), falla = fallar(loA, hiA, Mg, tipo),
          ARL_off = 1 / est["off"], ARL_c2 = 1 / est["c2"],
          mcnemar_b01 = b01, mcnemar_b10 = b10,
          mcnemar_p = if (b01 + b10 > 0) binom.test(b01, b01 + b10)$p.value else 1,
          metmax_off = mean(fr_set$metmax_off), metmax_c2 = mean(fr_set$metmax_c2),
          swamp_off = mean(fr_set$swamp_off), swamp_c2 = mean(fr_set$swamp_c2),
          best_igual = mean(fr_set$best_igual), cov_igual = mean(fr_set$cov_igual), relF_med = median(fr_set$relF),
          n_pert = nrow(sub_p), best_offp_igual = mean(sub_p$best_offp_igual),
          disc_c2_off = mean(sub_p$disc_c2_off), disc_offp_off = mean(sub_p$disc_offp_off),
          delta_self = mean(sub_p$met_offp - sub_p$met_off),
          stringsAsFactors = FALSE, row.names = NULL)
      }
    }
    fr_cfg <- do.call(rbind, filas_rep[vapply(filas_rep, function(f) f$cfg_id[1] == cfg$id, NA)])
    sp <- fr_cfg[!is.na(fr_cfg$disc_offp_off), ]
    ## H2 (secundaria, descriptiva): discrepancia de decisiones canonical2-rrcov frente a rrcov-rrcov perturbado
    dd <- sp$disc_c2_off - sp$disc_offp_off
    gates[[length(gates) + 1]] <- data.frame(config = cfg$nombre, cfg_id = cfg$id, errores = errs,
      identidad_np = if (cfg$id == CFG_CONTROL) all(fr_cfg$best_igual & fr_cfg$rho_igual & fr_cfg$cov_igual) else NA,
      c2_determinista = all(fr_cfg$c2p_det, na.rm = TRUE), n_c2p = sum(!is.na(fr_cfg$c2p_det)),
      UCL_off = U["off"], UCL_c2 = U["c2"], UCL_off_pert = UCL_offp["best"],
      UCLtodas_off = UCL$todas["off"], UCLtodas_c2 = UCL$todas["c2"], UCLtodas_off_pert = UCL_offp["todas"],
      UCLMAX_off = UCLMAX["off"], UCLMAX_c2 = UCLMAX["c2"],
      se_UCL_off = sd(UCLb$best$off), se_dUCL = sd(UCLb$best$c2 - UCLb$best$off),
      H2_disc_c2_off = mean(sp$disc_c2_off), H2_disc_offp_off = mean(sp$disc_offp_off),
      H2_disc_offp_off_si_cambia = mean(sp$disc_offp_off[!sp$best_offp_igual]),
      H2_frac_rrcov_cambia = mean(!sp$best_offp_igual),
      H2_dif = mean(dd), H2_ic95_lo = mean(dd) - qnorm(0.975) * sd(dd) / sqrt(max(length(dd), 1)),
      H2_ic95_hi = mean(dd) + qnorm(0.975) * sd(dd) / sqrt(max(length(dd), 1)),
      t_off_med = median(fr_cfg$t_off), t_c2_med = median(fr_cfg$t_c2),
      t_offp_med = median(fr_cfg$t_offp, na.rm = TRUE), t_c2p_med = median(fr_cfg$t_c2p, na.rm = TRUE),
      stringsAsFactors = FALSE, row.names = NULL)
  }
  REP <- do.call(rbind, filas_rep); RES <- do.call(rbind, filas_res); G <- do.call(rbind, gates)
  num <- vapply(REP, is.double, NA); REP[num] <- lapply(REP[num], signif, digits = 7)
  write.csv(REP, file.path(SALIDA, "mc_canonico2_replicas.csv"), row.names = FALSE)
  write.csv(RES, file.path(SALIDA, "mc_canonico2_resumen.csv"), row.names = FALSE)
  write.csv(G, file.path(SALIDA, "mc_canonico2_gates.csv"), row.names = FALSE)
  ## --- decisión global pre-registrada (protocolo §6) ---
  P <- RES[RES$primaria, ]
  g_ok <- all(G$errores == 0) && all(G$c2_determinista) && isTRUE(all(G$identidad_np[!is.na(G$identidad_np)]))
  fa_ok <- all(P$clase[P$tipo == "FA"] == "EQUIV"); sp_ok <- all(P$clase[P$tipo == "SP"] %in% c("EQUIV", "NO_INFERIOR"))
  decision <- if (any(P$falla) || !g_ok) "NO ADOPTAR" else if (fa_ok && sp_ok) "ADOPTAR COMO MODO OPCIONAL" else "INCONCLUSO"
  if (decision == "ADOPTAR COMO MODO OPCIONAL" && any(P$clase == "NO_INFERIOR"))
    decision <- paste(decision, "(hay celdas NO_INFERIOR: diferencia favorable a canonical2; revisión del dueño)")
  sink(file.path(SALIDA, "mc_canonico2_decision.txt"))
  cat(sprintf("UCL que decide: %s; K = %d; z 90 %% = %.3f; z Bonferroni (unilateral %.5f) = %.3f; B = %d\n",
              UCL_PRIM, K, z_90, ALFA_TEST / max(K, 1), z_adj, B_BOOT))
  print(G, row.names = FALSE, digits = 5)
  print(RES[, c("config", "set", "def_ucl", "R", "met_off", "met_c2", "delta", "se_boot", "ic90_lo", "ic90_hi",
                "icadj_lo", "icadj_hi", "clase", "falla", "disc_c2_off", "disc_offp_off")], row.names = FALSE, digits = 4)
  cat("\nDECISIÓN:", decision, if (PILOTO) "(PILOTO: no válida para decidir)" else "", "\n")
  sink()
  cat(readLines(file.path(SALIDA, "mc_canonico2_decision.txt")), sep = "\n")
  ## --- estimación de duración de la corrida completa (tiempos medidos bajo carga de NUCLEOS procesos) ---
  if (PILOTO) {
    nse <- length(SETS) - 1
    est <- vapply(seq_len(nrow(G)), function(i) {
      g <- G[i, ]; cfg <- CONFIGS[[which(vapply(CONFIGS, `[[`, 0, "id") == g$cfg_id)]]
      re <- if (cfg$n <= 50) 2000 else 1000
      ((1000 + nse * re) * (g$t_off_med + g$t_c2_med) + length(SETS) * (200 * g$t_offp_med + 50 * g$t_c2p_med)) / NUCLEOS }, 0)
    cat("\nEstimación de la corrida completa (horas de reloj con", NUCLEOS, "procesos; tiempos por ajuste medidos bajo carga):\n")
    print(data.frame(config = G$config, t_off = G$t_off_med, t_c2 = G$t_c2_med, horas = round(est / 3600, 2)), row.names = FALSE)
    cat(sprintf("TOTAL estimado: %.1f h (más unos minutos de análisis)\n", sum(est) / 3600))
  }
}

## ---------------- Manifiesto ----------------
escribir_manifiesto <- function() {
  suppressMessages(library(rrcov, lib.loc = "referencias/R-lib"))
  m <- c(sprintf("fecha: %s", format(Sys.time())), sprintf("R: %s", R.version.string),
         sprintf("rrcov: %s (%s)", packageVersion("rrcov"), find.package("rrcov")),
         sprintf("robustbase: %s", packageVersion("robustbase")), sprintf("EnvStats: %s", packageVersion("EnvStats")),
         sprintf("BLAS: %s", extSoftVersion()[["BLAS"]]), sprintf("LAPACK: %s", La_version()),
         sprintf("plataforma: %s", R.version$platform),
         sprintf("piloto: %s; R_CAL=%d R_EVAL(n=50)=%d R_EVAL(n>=100)=%d R_PERT=%d R_PERT_C2=%d B=%d; UCL que decide: %s", PILOTO, R_CAL, R_EVAL_50, R_EVAL_100, R_PERT, R_PERT_C2, B_BOOT, UCL_PRIM),
         sprintf("semilla base: %d; alpha MRCD: %g; alpha PFA: %g", SEMILLA_BASE, ALPHA_MRCD, ALPHA_PFA),
         sprintf("md5 %s: %s", c("tools/r/experimentos/mc_canonico2.R", "tools/r/experimentos/r6pack_canonico.R",
                                 "referencias/rrcov-1.7-7/R/detmrcd.R"),
                 tools::md5sum(c("tools/r/experimentos/mc_canonico2.R", "tools/r/experimentos/r6pack_canonico.R",
                                 "referencias/rrcov-1.7-7/R/detmrcd.R"))))
  writeLines(m, file.path(SALIDA, "manifiesto.txt"))
}

escribir_manifiesto()
nerr <- 0
if (FASE %in% c("simular", "todo")) nerr <- simular()
if (FASE %in% c("analizar", "todo")) analizar()
if (nerr > 0) quit(status = 1)
