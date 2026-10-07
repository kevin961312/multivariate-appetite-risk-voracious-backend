## Actualiza los manifest.json de los 13 casos (tolerancias declaradas por cantidad, copiadas de
## docs/metodos/mrcd-especificacion.md §11; nota de plataforma; descriptor de intermedios) y crea
## primitivas/manifest.json. Idempotente. Uso: Rscript tools/r/actualizar_manifests.R
source("tools/r/casos.R")
suppressMessages({ library(jsonlite); library(digest) })
sha <- function(f) digest(f, algo = "sha256", file = TRUE)

nota_plataforma <- paste(
  "Igualdad exacta (rtol=atol=0, bit a bit) SOLO en la plataforma de referencia del oraculo:",
  "arm64 (aarch64-apple-darwin20) + BLAS Accelerate/vecLib + LAPACK Rlapack 3.12.1 de R + long double == double (R 4.5.2).",
  "En otras plataformas (p. ej. x86-64 Linux con OpenBLAS y long double de 80 bits) aplican las tolerancias numericas",
  "declaradas por cantidad (columnas tol_etapa y tol_extremo); las cantidades de clase E (enteros, medianas, Qn, rho dado e1/ep...)",
  "deben seguir siendo exactas si el port sigue el pseudocodigo de la especificacion, salvo donde dependan de BLAS/LAPACK/libm.",
  "Fuente: seccion 11 de docs/metodos/mrcd-especificacion.md.")
fila <- function(cantidad, intermedios, clase, tol_etapa, tol_extremo, justificacion)
  list(cantidad = cantidad, intermedios = as.list(intermedios), clase = clase,
       tol_etapa = tol_etapa, tol_extremo = tol_extremo, justificacion = justificacion)
tabla <- list(
  fila("enteros (h, hsets, index, best, iBest, n.csteps, numit, initV, setsV, ord)",
       c("pre_n", "pre_p", "pre_h", "in_ok", "hs_init", "is_ord_k*", "r6_ind5", "r6_Hinit", "rs_Vsel", "rs_initV", "rs_setsV", "rs_path_k*", "rs_iter_k*",
         "cs_index_k*_it*", "cs_nndex_k*_it*", "cs_numit_k*", "sel_best6pack", "sel_hindex", "sel_n_csteps", "out_iBest", "out_n_csteps", "out_best", "out_quan", "out_n_obs"),
       "E", "exacto", "exacto (salvo divergencia R1, seccion 6)", "discretos"),
  fila("medianas (vmx, centros de doScale, colMedians, cutoffrho)", c("std_vmx", "r6_center", "is_colmed_k*", "rs_cutoff"),
       "E", "exacto", "exacto", "seleccion + media de 2 en IEEE"),
  fila("Qn, vsd, r6.scale, U de OGK", c("std_vsd_raw", "std_vsd", "r6_scale", "r6_U"),
       "E", "exacto (endurece 1e-14)", "vsd y U exactos; lambda ver abajo", "qn0 = restas, comparaciones, 2 operaciones finales"),
  fila("lambda de initset", c("is_lambda_k*"), "E dada su entrada", "exacto",
       "rtol 2^-23 (~1.19e-7) si la proyeccion data %*% P no es bit a bit", "T1/T2: Qn salta entre d y f32(d) ante cambios de 1 ulp"),
  fila("mU, x de doScale, x.nrmd, znorm, rangos", c("std_mU", "r6_x", "r6_xnrmd", "r6_znorm", "r6_rank"),
       "E", "exacto (endurece 1e-13)", "exacto", "resta/division/sqrt IEEE"),
  fila("y1, cortmp_sin, y3 (libm / AS241)", c("r6_y1", "tgt_cortmp_sin", "r6_y3"), "L", "rtol 1e-15", "rtol 1e-15", "math.* y AS241 portado: <= 4 ulp entre libm"),
  fila("R1, R2, R3, covx, constcor, cortmp, R target", c("r6_R1", "r6_R2", "r6_R3", "r6_covx", "tgt_cortmp_rank", "tgt_constcor", "tgt_R"),
       "E (L si entra y1)", "exacto sobre entradas de R (endurece 1e-12)", "rtol 1e-12, atol 1e-14", "formula secuencial [S3]"),
  fila("SCM", c("r6_SCM"), "B", "rtol 1e-12, atol 1e-14", "rtol 1e-12, atol 1e-14", "dsyrk; bit a bit con mismo BLAS"),
  fila("productos dgemm (proj, sqrtcov, mS, W, G...)",
       c("is_proj_k*", "is_sqrtcov_k*", "is_sqrtinvcov_k*", "is_estloc_k*", "is_centeredx_k*", "is_dist_k*", "rs_mS_k*", "fin_W", "fin_mE", "cs_mS_k*_it*",
         "cs_smwG_k*_it*", "fin_smwG", "eq_mW"),
       "B", "rtol 1e-12, atol 1e-14*max|ref|", "rtol 1e-12, atol 1e-14*max|ref|", "error de dgemm <= k*eps*(|A||B|)"),
  fila("autovalores", c("r6_ev1", "r6_ev2", "r6_ev3", "r6_ev4", "r6_ev5", "r6_ev6", "rs_veigen_k*", "rs_e1_k*", "rs_ep_k*", "eq_values"),
       "B", "atol 10*p*eps*lambda_max (<= 1e-10*lambda_max para p <= 4.5e4)", "idem", "dsyevr es estable hacia atras: O(p*eps*||A||)"),
  fila("autovectores", c("r6_P1", "r6_P2", "r6_P3", "r6_P4", "r6_P5", "r6_P6", "eq_mQ"),
       "B", "solo autoespacios con gap relativo > 1e-8, modulo signo, ||v-v_R|| <= 10*p*eps*lambda_max/gap; ademas comparar signos (T3)", "idem", "sensibilidad eps/gap"),
  fila("scfac", c("scfac", "scfac_q", "scfac_pg", "out_cnp2"), "-", "rtol 1e-14", "rtol 1e-14", "medido 6.5e-15 [S5]; exacto si se porta nmath (P3)"),
  fila("rho_k, rho (uniroot o rejilla)", c("rs_rhok_k*", "rs_root_k*", "rs_irho_k*", "rs_estimprec_k*", "rs_flower_k*", "rs_fupper_k*", "rs_rho6", "rs_rho", "out_rho"),
       "E dada (e1, ep)", "exacto (endurece 1e-12)", "atol 1e-12", "R_zeroin2 es escalar puro"),
  fila("medias por rowMeans (vMu, mu_std)", c("rs_mu_k*", "cs_vMu_k*_it*", "fin_mu_std"), "E dado el indice", "exacto", "exacto", "suma secuencial"),
  fila("rcov, inv_rcov, vdst de C-step; cov/inv estandarizados",
       c("cs_rcov_k*_it*", "cs_inv_k*_it*", "cs_vdst_k*_it*", "cs_smwTemp_k*_it*", "fin_smwTemp", "fin_cov_std", "fin_icov_std"),
       "B", "rtol 1e-12, atol 1e-14*max|ref|; vdst rtol 1e-12", "idem", "dgemm/dpotrf/dpotri con cond <= maxcond en espacio estandarizado"),
  fila("obj / det por conjunto", c("cs_obj_k*", "cs_det_k*"), "B", "rtol 1e-12", "rtol 1e-12", ""),
  fila("center (target=0)", c("out_center", "fin_center"), "E dado hindex", "exacto", "exacto", "rowMeans + escalado exacto (T9)"),
  fila("center (target=1), cov, icov, target", c("out_center", "out_cov", "out_icov", "out_target", "fin_center", "fin_cov", "fin_icov", "fin_target"),
       "B", "rtol 1e-9, atol 1e-11", "rtol 1e-9, atol 1e-11", "se mantiene el plan; informar error relativo a max|ref|"),
  fila("mah", c("out_mah", "fin_dist_detmrcd"), "B", "rtol 1e-9", "rtol 1e-9", ""),
  fila("crit", c("out_crit", "fin_crit"), "B", "atol 1e-9", "atol 1e-9", "log-det"),
  fila("alpha", c("pre_alpha", "out_alpha"), "E", "exacto", "exacto", "IEEE"))
tolerancias <- list(
  fuente = "docs/metodos/mrcd-especificacion.md seccion 11 (propuestas del analista-port; pendientes de aprobacion del dueño)",
  nota_plataforma = nota_plataforma,
  clases = list(E = "exacto (rtol=atol=0): escalar IEEE sin BLAS/LAPACK ni libm transcendental",
                L = "dependen de libm", B = "dependen de BLAS/LAPACK (bit a bit solo en la plataforma de referencia)"),
  por_cantidad = tabla,
  nota_escala = "El atol absoluto de cov/icov depende de la escala de los datos; informar tambien el error relativo a max|ref|.")

for (nm in c(names(casos), names(variantes))) {
  f <- file.path(RAIZ_FIXTURES, nm, "manifest.json")
  m <- read_json(f, simplifyVector = FALSE)
  m$tolerancias <- tolerancias
  di <- file.path(RAIZ_FIXTURES, nm, "intermedios")
  fi <- file.path(di, list.files(di, pattern = "\\.csv\\.gz$"))
  m$intermedios <- list(
    directorio = "intermedios", indice = "intermedios/indice.json", sha256_indice = sha(file.path(di, "indice.json")),
    n_archivos = length(fi), bytes = sum(file.size(fi)),
    metodo = "tools/r/exportar_intermedios.R sobre tools/r/detmrcd_instrumentado.R (copia de rrcov 1.7-7 con capturas; identical a rrcov::CovMrcd, ver tools/r/verificar_instrumentado.R)",
    nota = "sha256 de cada archivo en intermedios/indice.json",
    matrices_pxp_de_csteps = if (m$p > 40) "no exportadas (p > 40, especificacion seccion 10: solo fixtures pequenos); si los vectores/indices de cada paso" else "exportadas (p <= 40)")
  m$convenciones <- "CSV sin cabecera, 17 cifras significativas (%.17g), filas = filas de R; vectores = 1 columna; escalares 1x1; indices 1-based; enteros sin decimales; logicos 1/0"
  m$salidas_inyeccion_initHsets <- list(archivo = "hsets_init.csv.gz", uso = "pasar como initHsets a CovMrcd (h x 6, base 1) para pruebas extremo a extremo nivel (ii); tools/r/instrumentacion.R::correr_instrumentado(initHsets=)")
  write_json(m, f, auto_unbox = TRUE, digits = NA, pretty = TRUE, null = "null")
}

## manifest de primitivas
vers <- read_json(file.path(RAIZ_FIXTURES, "C1", "manifest.json"))$entorno
pi_idx <- list.files(file.path(RAIZ_FIXTURES, "primitivas"), pattern = "^indice\\.json$", recursive = TRUE)
tol_prim <- list(
  exacto_en_plataforma_referencia = "todas las salidas (rtol=atol=0)",
  fuera_de_plataforma = list(
    E = c("median", "colMedians", "Qn", "doScale", "rank", "order", "scale", "mean", "rowMeans", "rowSums", "cor_pearson", "cor_spearman", "cor_complete_obs", "cov",
          "quantile7", "uniroot", "rho_rejilla", "mahalanobisD", "sqrt"),
    "L: rtol 1e-15" = c("tanh", "sin", "log", "exp", "r_pow", "qnorm"),
    "scfac: rtol 1e-14" = c("MCDcons", "qchisq", "pgamma"),
    "B: rtol 1e-12, atol 1e-14*max|ref|" = c("matprod", "matvec", "vecmat", "crossprod", "chol", "chol2inv_chol", "determinant", "mahalanobis"),
    "B autovalores: atol 10*p*eps*lambda_max; autovectores: autoespacios con gap > 1e-8, modulo signo" = c("eigen_sym", "eigen_auto")),
  nota_plataforma = nota_plataforma)
man <- list(descripcion = "Fixtures de primitivas R para tests unitarios del port pymrcd",
            semilla = 20261100L, RNGkind = c("Mersenne-Twister", "Inversion", "Rejection"), entorno = vers,
            script = "tools/r/exportar_primitivas.R",
            lectura = "las entradas se releen con leer_csv_gz() (parse exacto) antes de calcular en R",
            convenciones = "CSV sin cabecera, %.17g, filas = filas de R; vectores = 1 columna; escalares 1x1; enteros sin decimales; logicos 1/0; indices 1-based",
            tolerancias = tol_prim,
            indices_sha256 = setNames(lapply(pi_idx, function(i) sha(file.path(RAIZ_FIXTURES, "primitivas", i))), pi_idx))
write_json(man, file.path(RAIZ_FIXTURES, "primitivas", "manifest.json"), auto_unbox = TRUE, digits = NA, pretty = TRUE)

## informe de tamano
cat("\n== Tamano (bytes reales de archivos) ==\n")
tam <- function(d) sum(file.size(list.files(d, recursive = TRUE, full.names = TRUE)))
tot <- 0
for (nm in c(names(casos), names(variantes))) {
  a <- tam(file.path(RAIZ_FIXTURES, nm)); ai <- tam(file.path(RAIZ_FIXTURES, nm, "intermedios")); tot <- tot + a
  cat(sprintf("%-6s total %7.2f MB  (intermedios %7.2f MB)\n", nm, a / 1e6, ai / 1e6))
}
tp <- tam(file.path(RAIZ_FIXTURES, "primitivas"))
cat(sprintf("casos: %.2f MB | primitivas: %.2f MB | TOTAL fixtures: %.2f MB\n", tot / 1e6, tp / 1e6, (tot + tp) / 1e6))
fs <- list.files(RAIZ_FIXTURES, pattern = "^[A-Za-z0-9_]+/intermedios/.*csv.gz$", recursive = TRUE, full.names = TRUE)
fs <- list.files(RAIZ_FIXTURES, recursive = TRUE, full.names = TRUE)
fs <- fs[grepl("/intermedios/", fs) & grepl("csv.gz$", fs)]
fam <- sub("_k[0-9]+.*$|\\.csv\\.gz$", "", basename(fs))
agg <- sort(tapply(file.size(fs), fam, sum), decreasing = TRUE)
cat("Intermedios por familia (MB, todos los casos), top 12:\n"); print(round(head(agg, 12) / 1e6, 2))
