## Casos ADICIONALES de robustbase::Qn (M5 / T2). Complementa a exportar_primitivas.R SIN regenerar nada:
## NO borra la carpeta de fixtures; solo AÑADE archivos nuevos a primitivas/Qn/ y los casos nuevos a
## primitivas/Qn/indice.json (los casos existentes se copian tal cual) + el sha256 del indice en primitivas/manifest.json.
## Uso: Rscript tools/r/exportar_qn_extra.R   (desde la raíz del repo). Aborta si un id nuevo ya existe.
##
## Formato EN BITS (nuevo, porque el CSV decimal %.17g pierde información útil como el signo del cero en
## los consumidores que parsean mal; aquí se deja explícito y exacto):
##   <archivo>.bits.csv.gz : una fila por elemento, SIN cabecera, "HEX,SIGNO"
##     HEX   = sprintf("%a", v)  (hexadecimal exacto del double; "-0x0p+0" para -0)
##     SIGNO = 1 si el bit de signo está activo (para ceros: 1/v < 0), 0 si no
##   En los descriptores del indice: archivo_bits / sha256_bits (entradas y salidas).
## Los CSV decimales (%.17g) se siguen escribiendo y releyendo con leer_csv_gz() antes de calcular
## (leer_csv_gz conserva -0; se verifica con identical + signo del cero).
##
## Semillas: cada caso fija set.seed(SEMILLA_QN_EXTRA + nº de caso) con
## RNGkind("Mersenne-Twister","Inversion","Rejection"); SEMILLA_QN_EXTRA = 20261200.
source("tools/r/casos.R")
suppressMessages({ library(robustbase); library(jsonlite); library(digest) })
SEMILLA_QN_EXTRA <- 20261200L
DIR_QN <- file.path(RAIZ_FIXTURES, "primitivas", "Qn")
sha <- function(f) digest(f, algo = "sha256", file = TRUE)
RNGkind("Mersenne-Twister", "Inversion", "Rejection")

## bit de signo de cada double (para ceros usa 1/v < 0; para el resto v < 0)
signo_bit <- function(v) ifelse(v == 0, as.integer(1 / v < 0), as.integer(v < 0))
## escribe v en bits ("%a,signo" por línea) y devuelve el sha256
escribir_bits_gz <- function(v, ruta) {
  con <- gzfile(ruta, "wb", compression = 9)
  writeLines(paste(sprintf("%a", v), signo_bit(v), sep = ","), con)
  close(con)   # cerrar (vaciar el buffer gzip) ANTES de calcular el hash; con on.exit el sha era el de un archivo vacío
  sha(ruta)
}
## verifica que la relectura decimal coincide EN BITS con el original (valor y signo del cero)
stopifnot_bits <- function(a, b) stopifnot(identical(sprintf("%a", as.numeric(a)), sprintf("%a", as.numeric(b))))

## k_L exacto de qn_sn.c:154 (mismo orden de evaluación en double; int64 trunca hacia 0)
k_L_de <- function(n) floor(5 - 1.75 * (n %% 2) + (0.3939 - 0.0067 * (n %% 2)) * as.numeric(n) * (n - 1))

nuevos <- list(); nc <- 0L
## caso Qn: escribe x (y -x) y la salida en decimal y en bits; k = NULL usa el k por defecto de Qn()
caso_qn <- function(id, x, desc, tipo, k = NULL, entero = FALSE) {
  nc <<- nc + 1L
  for (neg in c(FALSE, TRUE)) {
    xx <- if (neg) -x else x
    idc <- paste0(id, if (neg) "_neg" else "")
    stopifnot(!file.exists(file.path(DIR_QN, sprintf("entrada_x_%s.csv.gz", idc))))
    re <- file.path(DIR_QN, sprintf("entrada_x_%s.csv.gz", idc))
    escribir_csv_gz(matrix(xx, ncol = 1), re)
    rel <- as.numeric(leer_csv_gz(re)); stopifnot_bits(rel, xx)       # relectura idéntica en bits
    rb <- file.path(DIR_QN, sprintf("entrada_x_%s.bits.csv.gz", idc))
    shb <- escribir_bits_gz(rel, rb)
    q <- if (is.null(k)) Qn(rel) else suppressWarnings(Qn(rel, k = k))
    rs <- file.path(DIR_QN, sprintf("salida_qn_%s.csv.gz", idc))
    escribir_csv_gz(matrix(q, ncol = 1), rs)
    rsb <- file.path(DIR_QN, sprintf("salida_qn_%s.bits.csv.gz", idc))
    shsb <- escribir_bits_gz(q, rsb)
    n <- length(rel)
    ex <- list(n = n, tipo = tipo, semilla = SEMILLA_QN_EXTRA + nc, salida_hex = sprintf("%a", q), salida_signo_bit = signo_bit(q),
               n_ceros = sum(rel == 0), n_cero_negativo = sum(rel == 0 & 1 / rel < 0),
               formato_bits = "archivo_bits: filas HEX,SIGNO; HEX=sprintf(%a), SIGNO=bit de signo (ceros: 1/v<0)")
    if (!is.null(k)) ex <- c(ex, list(k = k, k_L = k_L_de(n), k_ge_kL = k >= k_L_de(n), constante = 1 / (sqrt(2) * qnorm(((k - 1 / 2) / choose(n, 2) + 1) / 2))))
    d <- list(id = idc, descripcion = paste0(desc, if (neg) " (Qn de -x)" else ""),
              entradas = list(x = list(archivo = basename(re), forma = c(n, 1L), clase = if (n == 1) "escalar" else "vector", tipo = "double",
                                       sha256 = sha(re), archivo_bits = basename(rb), sha256_bits = shb)),
              salidas = list(qn = list(archivo = basename(rs), forma = c(1L, 1L), clase = "escalar", tipo = "double",
                                       sha256 = sha(rs), archivo_bits = basename(rsb), sha256_bits = shsb)),
              extra = ex)
    if (!is.null(k)) d$parametros <- list(k = k, finite.corr = FALSE)
    nuevos[[length(nuevos) + 1L]] <<- d
  }
}
sem <- function() set.seed(SEMILLA_QN_EXTRA + nc + 1L, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")

## (1) empates y valores enteros
for (n in c(10, 11, 50, 51, 200)) { sem(); caso_qn(sprintf("x1_ent_n%d", n), sample(-5:5, n, TRUE) * 1.0, sprintf("n=%d enteros en -5..5 (muchos empates)", n), "empates_enteros") }
for (n in c(20, 101)) { sem(); caso_qn(sprintf("x1_ent3_n%d", n), sample(1:3, n, TRUE) * 1.0, sprintf("n=%d enteros en 1..3 (empates masivos)", n), "empates_enteros") }
sem(); caso_qn("x1_const_n20", rep(2.5, 20), "n=20 constante (Qn=0)", "empates_enteros")
sem(); caso_qn("x1_dosvalores_n40", rep(c(1, 2), each = 20), "n=40 dos valores 1/2 (mitades)", "empates_enteros")
sem(); caso_qn("x1_dec_n60", sample(1:9, 60, TRUE) / 10, "n=60 decimales 0.1..0.9 con empates", "empates_enteros")
## (2) mezcla de +0 y -0
sem(); caso_qn("x2_mixcero_n5", c(0, -0, 0, -0, 0), "n=5 solo ceros mezcla +0/-0", "mezcla_cero_signado")
sem(); caso_qn("x2_mixcero_n12", rep(c(0, -0), 6), "n=12 solo ceros alternando +0/-0", "mezcla_cero_signado")
for (n in c(13, 30, 100)) {
  sem(); x <- rnorm(n); idx <- sample(n, round(n * 0.7)); x[idx] <- ifelse(runif(length(idx)) < 0.5, 0, -0)
  caso_qn(sprintf("x2_mixcero_n%d", n), x, sprintf("n=%d: 70%% ceros con signo aleatorio (+0/-0) y resto normal", n), "mezcla_cero_signado")
}
sem(); caso_qn("x2_mixcero_pm1_n24", sample(c(0, -0, 1, -1), 24, TRUE), "n=24 valores en {+0,-0,1,-1}", "mezcla_cero_signado")
## (3) 60-90 % de ceros
for (pz in c(0.6, 0.75, 0.9)) for (n in c(20, 100, 500)) {
  sem(); x <- rnorm(n); z <- sample(n, round(n * pz)); x[z] <- 0
  caso_qn(sprintf("x3_ceros%d_n%d", round(pz * 100), n), x, sprintf("n=%d con %d%% de ceros (+0), resto normal", n, round(pz * 100)), "muchos_ceros")
}
## (4) n grandes
for (n in c(250, 500, 1000, 2001)) {
  sem(); caso_qn(sprintf("x4_n%d", n), rnorm(n), sprintf("n=%d normal", n), "n_grande")
  sem(); caso_qn(sprintf("x4_ent_n%d", n), sample(-20:20, n, TRUE) * 1.0, sprintf("n=%d enteros -20..20 (empates)", n), "n_grande")
}
## (5) frontera k >= k_L (k no por defecto; finite.corr = FALSE como hace Qn(x, k=)). k_L = k_L_de(n) (qn_sn.c:154)
for (n in c(5, 6, 7, 8, 10, 11, 20, 21, 50, 51, 100, 101, 200)) {
  kL <- k_L_de(n); nn2 <- choose(n, 2)
  for (dk in c(-1, 0, 1)) {
    k <- kL + dk
    if (k < 1 || k > nn2) next
    sem(); caso_qn(sprintf("x5_n%d_k%d", n, k), rnorm(n), sprintf("n=%d k=%d (k_L=%d, k%s k_L; k_max=%d)", n, k, kL, if (k >= kL) ">=" else "<", nn2),
                   "frontera_kL", k = k)
  }
  sem(); caso_qn(sprintf("x5_n%d_kmax", n), round(rnorm(n), 1), sprintf("n=%d k=choose(n,2)=%d (maximo; con empates)", n, nn2), "frontera_kL", k = nn2)
}
## (6) pares Yi+Yj, Yi-Yj de un caso tipo OGK (n=100, p=20, 20 % contaminado +5; columnas escaladas con mediana/Qn como en doScale)
sem(); n <- 100; p <- 20
X <- matrix(rnorm(n * p), n, p); X[1:20, ] <- X[1:20, ] + 5
Z <- scale(X, apply(X, 2, median), apply(X, 2, Qn)); Z <- unname(Z[, ])
for (pr in list(c(1, 2), c(3, 7), c(5, 19), c(10, 11), c(1, 20), c(8, 15))) {
  u <- Z[, pr[1]]; v <- Z[, pr[2]]
  caso_qn(sprintf("x6_ogk_suma_%d_%d", pr[1], pr[2]), u + v, sprintf("OGK n=100 p=20 contaminado: Y%d+Y%d", pr[1], pr[2]), "par_ogk")
  caso_qn(sprintf("x6_ogk_resta_%d_%d", pr[1], pr[2]), u - v, sprintf("OGK n=100 p=20 contaminado: Y%d-Y%d", pr[1], pr[2]), "par_ogk")
}

## ---- indice.json: edición TEXTUAL aditiva (los casos existentes quedan byte a byte; no se re-serializa el JSON existente)
compacta <- function(j) {   # arrays de escalares en una línea, como en el indice existente
  repeat { j2 <- gsub("\\[\\s+([^\\[\\]{}]*?)\\s+\\]", "[\\1]", j, perl = TRUE); if (identical(j2, j)) break; j <- j2 }
  gsub(",\\s*\n\\s*(?=[^\\[\\]{}]*\\])", ", ", j, perl = TRUE)
}
ruta_ind <- file.path(DIR_QN, "indice.json")
txt <- readLines(ruta_ind, warn = FALSE)
ids_old <- vapply(fromJSON(ruta_ind, simplifyVector = FALSE)$casos, function(c) c$id, "")
stopifnot(!any(vapply(nuevos, function(c) c$id, "") %in% ids_old))
fin <- length(txt)
stopifnot(txt[fin] == "}", txt[fin - 1] == "  ]", txt[fin - 2] == "    }")
bloques <- vapply(nuevos, function(c) {
  j <- compacta(toJSON(c, auto_unbox = TRUE, pretty = TRUE, digits = NA, null = "null"))
  paste0("    ", gsub("\n", "\n    ", j))      # sangría de 4 espacios como los casos existentes
}, "")
txt[fin - 2] <- "    },"
nuevo_txt <- c(txt[1:(fin - 2)], paste(bloques, collapse = ",\n"), txt[(fin - 1):fin])
writeLines(nuevo_txt, ruta_ind)
stopifnot(length(fromJSON(ruta_ind, simplifyVector = FALSE)$casos) == length(ids_old) + length(nuevos))
## sha256 del indice en el manifest de primitivas (reemplazo textual de esa sola línea)
rm_ <- file.path(RAIZ_FIXTURES, "primitivas", "manifest.json")
mt <- readLines(rm_, warn = FALSE); il <- grep('"Qn/indice.json":', mt, fixed = TRUE); stopifnot(length(il) == 1)
mt[il] <- sub('"[0-9a-f]{64}"', paste0('"', sha(ruta_ind), '"'), mt[il]); writeLines(mt, rm_)
cat(sprintf("Qn extra: %d casos nuevos (incl. _neg)\n", length(nuevos)))
