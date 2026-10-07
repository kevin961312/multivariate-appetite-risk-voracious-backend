## Genera las salidas finales del oráculo (rrcov OFICIAL 1.7-7 aislado) para cada caso/variante.
## Versión inicial F1a: solo salidas finales + iBest/n.csteps/subconjuntos iniciales; los
## intermedios llegan en F2 (con la especificación).
## Uso: Rscript tools/r/generar_golden.R [CASO ...]   (desde la raíz del repo; sin args = todos)
source("tools/r/casos.R")
suppressMessages({
  library(rrcov, lib.loc = LIB_RRCOV)
  library(jsonlite); library(digest)
})
stopifnot(normalizePath(find.package("rrcov")) == normalizePath(file.path(LIB_RRCOV, "rrcov")),
          !exists("ogkU_C", envir = asNamespace("rrcov")))
RNGkind("Mersenne-Twister", "Inversion", "Rejection")

args <- commandArgs(TRUE)
todos <- c(names(casos), names(variantes))
if (length(args)) todos <- args

sha <- function(f) digest(f, algo = "sha256", file = TRUE)
vers <- list(
  R = R.version.string,
  rrcov = as.character(packageVersion("rrcov", lib.loc = LIB_RRCOV)),
  rrcov_ruta = normalizePath(find.package("rrcov")),
  robustbase = as.character(packageVersion("robustbase")),
  robustbase_ruta = normalizePath(find.package("robustbase")),
  plataforma = R.version$platform,
  BLAS = sessionInfo()$BLAS, LAPACK = sessionInfo()$LAPACK,
  LAPACK_version = La_version(),
  La_library = La_library(), RNGkind = RNGkind()
)
tol <- "pendiente de especificación"
resumen <- list()

for (nm in todos) {
  base <- if (nm %in% names(variantes)) variantes[[nm]] else nm
  cs <- casos[[base]]
  target <- if (nm %in% names(variantes)) "equicorrelation" else "identity"
  dir <- file.path(RAIZ_FIXTURES, nm); dir.create(dir, recursive = TRUE, showWarnings = FALSE)
  fx <- file.path(RAIZ_FIXTURES, base, "x.csv.gz")
  x <- leer_csv_gz(fx)
  stopifnot(nrow(x) == cs$n, ncol(x) == cs$p)

  t_cov <- system.time(res <- rrcov::CovMrcd(x, target = target))[["elapsed"]]
  t_det <- system.time(det <- rrcov:::.detmrcd(x, alpha = 0.5, h = NULL, rho = NULL, maxcond = 50,
                          target = if (target == "identity") 0 else 1, maxcsteps = 200,
                          hsets.init = NULL, save.hsets = TRUE, trace = 0L))[["elapsed"]]
  ## coherencia CovMrcd vs .detmrcd (misma llamada interna)
  ## cov/icov/center deben ser idénticos; mah difiere por redondeo: CovMrcd la recalcula con
  ## mahalanobis(x, ...) (CovMrcd.R:46) y .detmrcd con la X reconstruida (detmrcd.R:~640)
  dif <- max(abs(res@cov - det$initcovariance), abs(res@icov - det$icov),
             abs(res@center - det$initmean), abs(res@rho - det$rho))
  dif_mah <- max(abs(res@mah - det$mah))

  sal <- list(
    center = as.numeric(res@center), cov = res@cov, icov = res@icov, rho = res@rho,
    best = res@best, mah = as.numeric(res@mah), mah_detmrcd = as.numeric(det$mah), crit = res@crit,
    h = res@quan, alpha = res@alpha, calpha = res@cnp2,
    iBest = det$iBest, n_csteps = det$n.csteps, hsets_init = det$initHsets
  )
  archivos <- character()
  for (k in names(sal)) {
    f <- file.path(dir, paste0(k, ".csv.gz"))
    v <- sal[[k]]
    if (is.integer(v) || k %in% c("best", "iBest", "n_csteps", "hsets_init", "h")) {
      con <- gzfile(f, "wb", compression = 9)
      writeLines(apply(matrix(as.integer(v), ncol = if (is.matrix(v)) ncol(v) else 1), 1, paste, collapse = ","), con)
      close(con)
    } else escribir_csv_gz(v, f)
    archivos[[basename(f)]] <- sha(f)
  }
  ## verificación de relectura de salidas en coma flotante
  for (k in c("cov", "icov", "center", "mah")) {
    y <- leer_csv_gz(file.path(dir, paste0(k, ".csv.gz")))
    stopifnot(identical(as.numeric(y), as.numeric(sal[[k]])))
  }

  ent <- list(archivo = file.path("..", base, "x.csv.gz"), sha256 = sha(fx))
  man <- list(
    caso = nm, caso_base = base, variante_target = target,
    entorno = vers, semilla = semilla(base), n = cs$n, p = cs$p,
    sigma = if (cs$sigma == "I") "identidad" else sprintf("AR(1) phi=%g", PHI),
    contaminacion = if (cs$contam > 0) list(fraccion = cs$contam, filas = ceiling(cs$contam * cs$n),
                                            desplazamiento = SHIFT) else NULL,
    parametros = list(funcion = "rrcov::CovMrcd(x, target=)", alpha = 0.5, h = res@quan,
                      maxcsteps = 200, rho = "NULL (calculado)", target = target, maxcond = 50,
                      defaults = "CovControlMrcd() de rrcov 1.7-7"),
    entrada = ent, salidas_sha256 = archivos,
    convenciones = "CSV sin cabecera, 17 cifras significativas (%.17g), filas = observaciones; indices 1-based",
    tolerancias = tol,
    tiempo_CovMrcd_s = t_cov, tiempo_detmrcd_s = t_det,
    max_dif_CovMrcd_vs_detmrcd = dif,
    max_dif_mah_CovMrcd_vs_detmrcd = dif_mah,
    resultado = list(rho = res@rho, h = res@quan, iBest = det$iBest, n_csteps = det$n.csteps,
                     crit = res@crit)
  )
  write_json(man, file.path(dir, "manifest.json"), auto_unbox = TRUE, digits = NA, pretty = TRUE, null = "null")
  cat(sprintf("%-7s n=%3d p=%3d rho=%.17g h=%d iBest=%s iter=%s crit=%.10g t=%.2fs dif=%g dif_mah=%g\n",
              nm, cs$n, cs$p, res@rho, res@quan, paste(det$iBest, collapse = "/"),
              paste(det$n.csteps, collapse = "/"), res@crit, t_cov, dif, dif_mah))
}
