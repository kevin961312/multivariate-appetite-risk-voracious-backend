## Fixtures de PRIMITIVAS para tests unitarios del port (sin necesidad del MRCD completo).
## Salida: packages/pymrcd/tests/golden/fixtures/primitivas/<funcion>/{entrada_<nombre>_<id>,salida_<nombre>_<id>}.csv.gz
##         + indice.json por función (casos, formas, tipos, parámetros, descripción).
## Formato: sin cabecera, %.17g, matrices con filas = filas de R, vectores = 1 columna, escalares = 1x1,
## enteros sin decimales, lógicos 1/0, índices 1-based.
## Las ENTRADAS se generan en R (semilla fija), se guardan con %.17g y se RELEEN con leer_csv_gz()
## antes de calcular, para que R opere sobre los mismos doubles que leerá Python.
## Uso: Rscript tools/r/exportar_primitivas.R   (desde la raíz del repo)
source("tools/r/casos.R")
suppressMessages({ library(rrcov, lib.loc = LIB_RRCOV); library(robustbase); library(jsonlite); library(digest) })
stopifnot(normalizePath(find.package("rrcov")) == normalizePath(file.path(LIB_RRCOV, "rrcov")))
SEMILLA_PRIM <- 20261100L
set.seed(SEMILLA_PRIM, kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
RAIZ_PRIM <- file.path(RAIZ_FIXTURES, "primitivas")
unlink(RAIZ_PRIM, recursive = TRUE); dir.create(RAIZ_PRIM, recursive = TRUE)
sha <- function(f) digest(f, algo = "sha256", file = TRUE)

escribir_entero_gz <- function(m, ruta) {
  if (is.null(dim(m))) m <- matrix(m, ncol = 1)
  con <- gzfile(ruta, "wb", compression = 9); on.exit(close(con))
  writeLines(apply(matrix(as.character(as.integer(m)), nrow(m), ncol(m)), 1, paste, collapse = ","), con)
}
tipo_de <- function(v) if (is.logical(v)) "logical" else if (is.integer(v)) "int" else "double"
clase_de <- function(v) if (!is.null(dim(v))) "matriz" else if (length(v) == 1) "escalar" else "vector"
## escribe un objeto y devuelve su descriptor
escribir_obj <- function(v, ruta) {
  tipo <- tipo_de(v); cl <- clase_de(v)
  v2 <- if (is.logical(v)) as.integer(v) else v
  if (is.null(dim(v2))) m <- matrix(v2, ncol = 1) else m <- unname(v2)
  if (tipo == "double") escribir_csv_gz(m, ruta) else escribir_entero_gz(m, ruta)
  list(archivo = basename(ruta), forma = dim(m), clase = cl, tipo = tipo, sha256 = sha(ruta))
}
## lee de vuelta una entrada con la clase/tipo originales
releer <- function(ruta, desc) {
  m <- leer_csv_gz(ruta)
  v <- if (desc$clase == "matriz") m else as.numeric(m)
  if (desc$tipo != "double") storage.mode(v) <- "integer"
  if (desc$tipo == "logical") v <- v != 0L
  v
}

indices <- list()
## caso(): entradas = lista nombrada de objetos R; calc(e) recibe las entradas RELEÍDAS y devuelve lista nombrada
caso <- function(fun, id, entradas, calc, descripcion, parametros = NULL, extra = NULL) {
  dir <- file.path(RAIZ_PRIM, fun); dir.create(dir, showWarnings = FALSE, recursive = TRUE)
  id <- sprintf("%s", id)
  ent_d <- list(); rel <- list()
  for (n in names(entradas)) {
    ruta <- file.path(dir, sprintf("entrada_%s_%s.csv.gz", n, id))
    ent_d[[n]] <- escribir_obj(entradas[[n]], ruta)
    rel[[n]] <- releer(ruta, ent_d[[n]])
    stopifnot(identical(unname(rel[[n]]), unname(entradas[[n]])) || is.integer(entradas[[n]]) || is.logical(entradas[[n]]) ||
              all(unname(rel[[n]]) == unname(entradas[[n]]) | (is.na(rel[[n]]) & is.na(entradas[[n]]))))
  }
  sal <- suppressWarnings(calc(rel))
  sal_d <- list()
  for (n in names(sal)) { if (is.null(sal[[n]])) stop(sprintf('salida NULL: %s/%s/%s', fun, id, n)) }
  for (n in names(sal)) sal_d[[n]] <- escribir_obj(sal[[n]], file.path(dir, sprintf("salida_%s_%s.csv.gz", n, id)))
  c1 <- c(list(id = id, descripcion = descripcion, entradas = ent_d, salidas = sal_d),
          if (!is.null(parametros)) list(parametros = parametros), if (!is.null(extra)) list(extra = extra))
  indices[[fun]] <<- c(indices[[fun]], list(c1))
  invisible(sal)
}
meta_fun <- list()
def <- function(fun, descripcion, referencia) meta_fun[[fun]] <<- list(descripcion = descripcion, referencia = referencia)
rn <- function(n, p = NULL) if (is.null(p)) rnorm(n) else matrix(rnorm(n * p), n, p)
cc <- function(i) sprintf("%02d", i)

## ---------------------------------------------------------------- median
def("median", "stats::median (media de dos pasadas para n par; summary.c:479-518). Cada caso: matriz M (filas = vectores de igual longitud); salida = apply(M,1,median).", "median.R:21-33")
i <- 0
for (L in c(1:12, 15, 20, 21, 50, 51, 100, 101, 200, 201)) {
  i <- i + 1
  M <- matrix(0, 30, L)
  for (r in 1:10) M[r, ] <- sample(1:9, L, replace = TRUE) / 10             # decimales tipo 0.1/0.7 (con empates)
  for (r in 11:20) M[r, ] <- rnorm(L)
  for (r in 21:25) M[r, ] <- sample(-3:3, L, replace = TRUE)               # enteros con empates
  for (r in 26:30) M[r, ] <- round(rnorm(L, 0, 1e-2), 4)                   # escala financiera
  caso("median", cc(i), list(M = M), function(e) list(mediana = apply(e$M, 1, median)),
       sprintf("30 vectores de longitud %d (10 decimales .1-.9, 10 normales, 5 enteros, 5 escala 1e-2)", L))
}
pares <- expand.grid(a = (1:9) / 10, b = (1:9) / 10)
caso("median", "pares_decimales", list(M = as.matrix(pares)), function(e) list(mediana = apply(e$M, 1, median)),
     "mediana de todos los pares (i/10, j/10), i,j en 1..9: caso medida S1b 0.1,0.7")
caso("median", "s1b", list(M = matrix(c(0.1, 0.7, 5, -3), 1)), function(e) list(mediana = apply(e$M, 1, median)),
     "median(c(0.1,0.7,5,-3)) = 0.40000000000000002 distinto de (0.1+0.7)/2 (spec S1b)")

## ---------------------------------------------------------------- colMedians (robustbase)
def("colMedians", "robustbase::colMedians (par: (a+b)/2 sin correccion; rowMedians_TYPE-template.h:138). Salida = colMedians(X).", "comedian.R:21-22")
i <- 0
for (d in list(c(10, 4), c(11, 4), c(2, 3), c(3, 3), c(50, 20), c(51, 20), c(100, 7), c(25, 200), c(26, 200))) {
  i <- i + 1
  X <- matrix(rnorm(d[1] * d[2]), d[1], d[2])
  if (i %% 2 == 0) X[] <- sample(1:9, length(X), replace = TRUE) / 10
  caso("colMedians", cc(i), list(X = X), function(e) list(colmed = colMedians(e$X)),
       sprintf("matriz %dx%d%s", d[1], d[2], if (i %% 2 == 0) " con decimales tipo 0.1-0.9" else " normal"))
}

## ---------------------------------------------------------------- Qn
def("Qn", "robustbase::Qn (qn_sn.c); salida Qn(x) y rama de qn0: 'double' = d exacto, 'float32' = d redondeado a float32 (T1). Incluye Qn(-x) como caso propio (T2).", "qnsn.R:20-68, qn_sn.c:118-296")
f32 <- function(z) readBin(writeBin(z, raw(), size = 4), "numeric", size = 4)
qn_raw_exacto <- function(x) {
  n <- length(x); k <- choose(n %/% 2 + 1, 2)
  m <- abs(outer(x, x, "-")); sort(m[lower.tri(m)])[k]
}
qn_desde_raw <- function(d, n) {
  r <- 2.21914 * d
  if (n <= 12) r * c(.399356, .99365, .51321, .84401, .61220, .85877, .66993, .87344, .72014, .88906, .75743)[n - 1]
  else r / (if (n %% 2) (1.60188 + (-2.1284 - 5.172 / n) / n) / n + 1
            else (3.67561 + (1.9654 + (6.987 - 77 / n) / n) / n) / n + 1)
}
rama_qn <- function(x) {
  n <- length(x); if (n < 2) return("trivial")
  d <- qn_raw_exacto(x); q <- Qn(x)
  if (identical(q, qn_desde_raw(d, n))) "double"
  else if (identical(q, qn_desde_raw(f32(d), n))) "float32" else "otra"
}
qn_caso <- function(id, x, desc) {
  for (neg in c(FALSE, TRUE)) {
    xx <- if (neg) -x else x
    idc <- paste0(id, if (neg) "_neg" else "")
    caso("Qn", idc, list(x = xx), function(e) list(qn = Qn(e$x)),
         paste0(desc, if (neg) " (Qn de -x)" else ""), extra = list(n = length(xx), rama = rama_qn(xx)))
  }
}
j <- 0
for (n in c(1:12, 13:30, 40, 50, 60, 75, 100, 101, 150, 200)) {
  for (rep in 1:(if (n <= 30) 2 else 3)) {
    j <- j + 1
    x <- if (rep == 3) round(rnorm(n), 1) else rnorm(n)      # rep 3: valores con empates
    qn_caso(sprintf("n%03d_%d", n, rep), x, sprintf("n=%d %s", n, if (rep == 3) "con empates (redondeado a 1 decimal)" else "normal"))
  }
}
## garantizar casos que salgan por la rama float32 (>= 30) y casos con Qn(x) != Qn(-x) (>= 20)
nf <- 0; nt <- 0; intentos <- 0
while ((nf < 30 || nt < 20) && intentos < 20000) {
  intentos <- intentos + 1
  n <- sample(c(5:30, 50, 100, 101), 1); x <- rnorm(n)
  rm <- rama_qn(x); rneg <- rama_qn(-x)
  difsig <- !identical(Qn(x), Qn(-x))
  if ((rm == "float32" && nf < 30) || (difsig && nt < 20)) {
    nf <- nf + (rm == "float32"); nt <- nt + difsig
    qn_caso(sprintf("sel%03d_n%d", nf + nt, n), x,
            sprintf("n=%d seleccionado: rama(x)=%s rama(-x)=%s Qn(x)%s Qn(-x)", n, rm, rneg, if (difsig) "!=" else "=="))
  }
}
x <- c(rep(0, 12), rnorm(8)); qn_caso("ceros60", x, "n=20 con 60% de ceros (camino non0Q en doScale)")

## ---------------------------------------------------------------- doScale
def("doScale", "robustbase:::doScale(x, center=median, scale=Qn): salidas x, center, scale (centra con mediana, Qn sobre la columna centrada; non0Q si escala 0).", "detmcd.R:229-289")
i <- 0
for (d in list(c(20, 5), c(21, 5), c(50, 10), c(100, 20), c(12, 4), c(40, 60))) {
  i <- i + 1; X <- matrix(rnorm(d[1] * d[2]), d[1], d[2])
  caso("doScale", cc(i), list(X = X), function(e) { r <- robustbase:::doScale(e$X, median, Qn)
        list(x = r$x, center = r$center, scale = r$scale) }, sprintf("matriz %dx%d normal", d[1], d[2]))
}
X <- matrix(rnorm(30 * 4), 30, 4); X[sample(30, 18), 2] <- 0
caso("doScale", "ceros60", list(X = X), function(e) { r <- robustbase:::doScale(e$X, median, Qn)
      list(x = r$x, center = r$center, scale = r$scale) }, "30x4 con 60% de ceros en la columna 2 (escala 0 -> non0Q)")
X <- matrix(rnorm(20 * 3), 20, 3); X[, 3] <- 2.5
caso("doScale", "constante", list(X = X), function(e) { r <- robustbase:::doScale(e$X, median, Qn)
      list(x = r$x, center = r$center, scale = r$scale) }, "20x3 con columna constante (non0Q sin cuantil distinto de 0 -> escala 1)")
X <- matrix(sample(1:9, 25 * 6, TRUE) / 10, 25, 6)
caso("doScale", "decimales", list(X = X), function(e) { r <- robustbase:::doScale(e$X, median, Qn)
      list(x = r$x, center = r$center, scale = r$scale) }, "25x6 con decimales 0.1-0.9 y muchos empates")

## ---------------------------------------------------------------- rank
def("rank", "base::rank(ties.method='average') por vector; salida = rangos (semienteros exactos).", "rank.R:19-50")
i <- 0
for (n in c(1, 2, 3, 5, 10, 11, 25, 50, 100, 200)) {
  i <- i + 1
  x <- if (i %% 3 == 0) sample(1:6, n, TRUE) else if (i %% 3 == 1) rnorm(n) else sample(1:9, n, TRUE) / 10
  caso("rank", cc(i), list(x = x), function(e) list(rango = rank(e$x)), sprintf("n=%d %s", n, c("con empates enteros", "normal", "decimales con empates")[i %% 3 + 1]))
}
caso("rank", "cero_negativo", list(x = c(0, -0, 1, -1, 0, 2)), function(e) list(rango = rank(e$x)), "-0 y 0 empatan")
caso("rank", "columnas", list(X = matrix(rnorm(40 * 6), 40, 6)), function(e) list(rangos = apply(e$X, 2L, rank)), "apply(X, 2, rank) sobre 40x6")

## ---------------------------------------------------------------- cor / cov
def("cor_pearson", "stats::cor(X) (pearson; two-pass mean, suma secuencial, clamp). Salida = matriz de correlacion.", "cor.R, cov.c:304-370")
def("cor_spearman", "stats::cor(X, method='spearman') = pearson de rangos promedio.", "cor.R:66-70")
def("cor_complete_obs", "stats::cor(X, use='complete.obs') (cov_complete1).", "cov.c:244-301")
def("cov", "stats::cov(X) (n-1).", "cov.c:201-240, :333")
i <- 0
for (d in list(c(10, 3), c(20, 5), c(25, 12), c(50, 8), c(60, 40), c(20, 30), c(100, 6))) {
  i <- i + 1
  X <- matrix(rnorm(d[1] * d[2]), d[1], d[2]) %*% chol(0.5^abs(outer(1:d[2], 1:d[2], "-")))
  if (i == 7) X[, 1] <- round(X[, 1], 1)
  ds <- sprintf("matriz %dx%d AR(1) 0.5%s", d[1], d[2], if (i == 7) ", columna 1 con empates" else "")
  caso("cor_pearson", cc(i), list(X = X), function(e) list(R = cor(e$X)), ds)
  caso("cor_spearman", cc(i), list(X = X), function(e) list(R = cor(e$X, method = "spearman")), ds)
  caso("cor_complete_obs", cc(i), list(X = X), function(e) list(R = cor(e$X, use = "complete.obs")), ds)
  caso("cov", cc(i), list(X = X), function(e) list(C = cov(e$X)), ds)
}

## ---------------------------------------------------------------- qnorm
def("qnorm", "stats::qnorm(p) (AS241 de Wichura, qnorm.c:47+). Entrada p (vector), salida q.", "qnorm.c")
rej <- unique(c(seq(0.0005, 0.9995, by = 0.0005), 0.5, 0.425 + 0.5 - 1e-12, 0.075, 0.925,
                10^-(seq(1, 300, by = 0.5)), 1 - 10^-(1:16), 10^-(seq(300, 323, by = 1)),
                exp(-25), exp(-25) * (1 + 1e-15), exp(-25) * (1 - 1e-15), exp(-5^2) , 0, 1,
                5e-324, 1e-320, 1 - .Machine$double.eps / 2))
caso("qnorm", "rejilla_amplia", list(p = rej), function(e) list(q = qnorm(e$p)),
     "rejilla uniforme 0.0005..0.9995, potencias de 10 hasta colas denormales, fronteras de ramas (r=5 y |q|=0.425), 0, 1")
for (n in c(20, 50, 100, 200, 250)) {
  rk <- (1:n - 1 / 3) / (n + 1 / 3)
  caso("qnorm", sprintf("tukey_n%d", n), list(p = rk), function(e) list(q = qnorm(e$p)), sprintf("puntos (i-1/3)/(n+1/3), n=%d", n))
}
caso("qnorm", "aleatorio", list(p = runif(2000)), function(e) list(q = qnorm(e$p)), "2000 uniformes")

## ---------------------------------------------------------------- quantile tipo 7
def("quantile7", "stats::quantile(x, probs, type=7, names=FALSE); entradas x y probs.", "quantile.R:57-67")
alph <- c(10:19, 19.75) / 20
i <- 0
for (n in c(5, 10, 11, 20, 21, 51, 100)) {
  i <- i + 1; x <- abs(rnorm(n)); if (i %% 2 == 0) x[sample(n, n %/% 2)] <- 0
  caso("quantile7", cc(i), list(x = x, probs = alph), function(e) list(q = quantile(e$x, e$probs, type = 7, names = FALSE)),
       sprintf("n=%d probs c(10:19,19.75)/20 (non0Q)%s", n, if (i %% 2 == 0) ", 50% ceros" else ""))
}
caso("quantile7", "general", list(x = rnorm(37), probs = c(0, 0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1, 1 / 3, 2 / 3)),
     function(e) list(q = quantile(e$x, e$probs, type = 7, names = FALSE)), "n=37, probs variadas")

## ---------------------------------------------------------------- .MCDcons, qchisq, pgamma
def("MCDcons", "robustbase:::.MCDcons(p, alpha) = 1/(pgamma(qchisq(alpha,p)/2, p/2+1)/alpha); pares (p, alpha) alineados.", "covMcd.R:602-607")
def("qchisq", "stats::qchisq(alpha, df=p); pares alineados.", "nmath/qchisq.c")
def("pgamma", "stats::pgamma(q, shape); pares alineados.", "nmath/pgamma.c")
ps <- c(1:10, 15, 20, 40, 50, 100, 200, 250, 300, 500, 1000)
al <- c(0.5, 0.51, 0.6, 0.75, 0.9, 0.975, 25 / 50, 50 / 100, 125 / 250, 0.5 + 1e-12)
g <- expand.grid(p = ps, a = al)
caso("MCDcons", "rejilla", list(p = g$p, alpha = g$a), function(e) list(scfac = mapply(robustbase:::.MCDcons, e$p, e$alpha)),
     "rejilla p en 1..1000 x alpha en {0.5,...,0.975}")
caso("qchisq", "rejilla", list(p = g$p, alpha = g$a), function(e) list(q = qchisq(e$alpha, e$p)), "misma rejilla")
caso("pgamma", "rejilla", list(shape = g$p / 2 + 1, q = qchisq(g$a, g$p) / 2), function(e) list(pg = pgamma(e$q, e$shape)), "q = qchisq(alpha,p)/2, shape = p/2+1")

## ---------------------------------------------------------------- uniroot
def("uniroot", "stats::uniroot(f, lower, upper) con tol y maxiter por defecto (tol=.Machine$double.eps^0.25, maxiter=1000), envuelto en try() como detmrcd.R:495. Salidas: path (1 = ok, 2 = error), root, f.root, iter, estim.prec (solo si path=1). f segun 'parametros$f'.", "nlm.R:55-170, zeroin.c:89-194")
## (a) funcion de rho real: f(rho) = (rho+(1-rho)*ep)/(rho+(1-rho)*e1) - maxcond con (e1, ep) de casos reales
rho_caso <- function(id, e1, ep, maxcond = 50, desc) {
  caso("uniroot", id, list(e1 = e1, ep = ep, maxcond = maxcond, lower = 0.00001, upper = 0.99), function(e) {
    f <- function(rho) (rho + (1 - rho) * e$ep) / (rho + (1 - rho) * e$e1) - e$maxcond
    o <- try(uniroot(f, lower = e$lower, upper = e$upper), silent = TRUE)
    if (inherits(o, "try-error")) list(path = 2L, f_lower = f(e$lower), f_upper = f(e$upper))
    else list(path = 1L, root = o$root, f_root = o$f.root, iter = as.integer(o$iter), estim_prec = o$estim.prec,
              f_lower = f(e$lower), f_upper = f(e$upper))
  }, desc, parametros = list(f = "(rho+(1-rho)*ep)/(rho+(1-rho)*e1)-maxcond", lower = 1e-5, upper = 0.99))
}
for (cs in c("C1", "C5", "C7", "C8", "C9", "C10", "C8_eq")) {
  for (k in 1:6) {
    e1 <- as.numeric(leer_csv_gz(file.path(RAIZ_FIXTURES, cs, "intermedios", sprintf("rs_e1_k%d.csv.gz", k))))
    ep <- as.numeric(leer_csv_gz(file.path(RAIZ_FIXTURES, cs, "intermedios", sprintf("rs_ep_k%d.csv.gz", k))))
    rho_caso(sprintf("%s_k%d", cs, k), e1, ep, 50, sprintf("(e1,ep) reales del caso %s, subconjunto %d", cs, k))
  }
}
sint <- list(c(0.001, 2), c(0.01, 5), c(0.0001, 10), c(1e-5, 1), c(0.05, 3), c(0.3, 1.2), c(-8.9e-16, 120), c(2, 3), c(0.5, 0.5), c(1e-10, 1e-3))
for (j in seq_along(sint)) rho_caso(sprintf("sint%02d", j), sint[[j]][1], sint[[j]][2], 50, sprintf("(e1,ep)=(%g,%g) sintetico", sint[[j]][1], sint[[j]][2]))
rho_caso("maxcond10", 0.01, 0.5, 10, "maxcond=10 sintetico")
## (b) funciones de prueba
fpr <- list(
  list(id = "poly3", f = function(x) x^3 - 2, txt = "x^3 - 2", lo = 0, up = 2),
  list(id = "cosx", f = function(x) cos(x) - x, txt = "cos(x) - x", lo = 0, up = 1),
  list(id = "expx", f = function(x) exp(x) - 5, txt = "exp(x) - 5", lo = 0, up = 3),
  list(id = "sqrt2", f = function(x) x * x - 2, txt = "x*x - 2", lo = 0, up = 2),
  list(id = "lineal", f = function(x) 3 * x - 1, txt = "3*x - 1", lo = -1, up = 1),
  list(id = "rac_extremo", f = function(x) x - 1e-5, txt = "x - 1e-5", lo = 1e-5, up = 0.99),
  list(id = "sin_cambio", f = function(x) x * x + 1, txt = "x*x + 1", lo = 0, up = 1),
  list(id = "pendiente", f = function(x) (x - 0.3)^3, txt = "(x-0.3)^3 (raiz triple)", lo = 0, up = 1),
  list(id = "tanh", f = function(x) tanh(x) - 0.5, txt = "tanh(x) - 0.5", lo = 0, up = 3),
  list(id = "recip", f = function(x) 1 / x - 7, txt = "1/x - 7", lo = 0.01, up = 0.99))
for (fp in fpr) {
  fn <- fp$f
  caso("uniroot", paste0("f_", fp$id), list(lower = fp$lo, upper = fp$up), function(e) {
    o <- try(uniroot(fn, lower = e$lower, upper = e$upper), silent = TRUE)
    if (inherits(o, "try-error")) list(path = 2L)
    else list(path = 1L, root = o$root, f_root = o$f.root, iter = as.integer(o$iter), estim_prec = o$estim.prec)
  }, paste("funcion de prueba", fp$txt), parametros = list(f = fp$txt, lower = fp$lo, upper = fp$up))
}
def("rho_rejilla", "irho = min(grid[abs(fncond(grid)) == min(abs(fncond(grid)))]) con grid = c(1e-6, seq(0.001,0.99,by=0.001), 0.999999) (detmrcd.R:503-506); tambien exporta la rejilla.", "detmrcd.R:503-511, seq.R:88-96")
for (j in seq_along(sint)) caso("rho_rejilla", sprintf("sint%02d", j), list(e1 = sint[[j]][1], ep = sint[[j]][2], maxcond = 50),
  function(e) { grid <- c(0.000001, seq(0.001, 0.99, by = 0.001), 0.999999)
    og <- abs((grid + (1 - grid) * e$ep) / (grid + (1 - grid) * e$e1) - e$maxcond)
    list(irho = min(grid[og == min(og)]), grid = grid) }, sprintf("(e1,ep)=(%g,%g)", sint[[j]][1], sint[[j]][2]))
for (cs in c("C7", "C9")) for (k in 1:6) {
  e1 <- as.numeric(leer_csv_gz(file.path(RAIZ_FIXTURES, cs, "intermedios", sprintf("rs_e1_k%d.csv.gz", k))))
  ep <- as.numeric(leer_csv_gz(file.path(RAIZ_FIXTURES, cs, "intermedios", sprintf("rs_ep_k%d.csv.gz", k))))
  caso("rho_rejilla", sprintf("%s_k%d", cs, k), list(e1 = e1, ep = ep, maxcond = 50),
    function(e) { grid <- c(0.000001, seq(0.001, 0.99, by = 0.001), 0.999999)
      og <- abs((grid + (1 - grid) * e$ep) / (grid + (1 - grid) * e$e1) - e$maxcond)
      list(irho = min(grid[og == min(og)]), grid = grid) }, sprintf("(e1,ep) reales de %s subconjunto %d", cs, k))
}

## ---------------------------------------------------------------- algebra lineal
spd <- function(p, h = 3 * p) { A <- matrix(rnorm(p * h), p, h); A %*% t(A) / h + diag(0.1, p) }
def("mahalanobis", "stats::mahalanobis(x, center, icov, inverted=TRUE) = rowSums((xc %*% icov) * xc).", "mahalanobis.R:30-43")
i <- 0
for (d in list(c(10, 3), c(30, 8), c(50, 20), c(100, 40), c(40, 100))) {
  i <- i + 1; p <- d[2]; S <- spd(p, max(p, 20)); IS <- solve(S)
  caso("mahalanobis", cc(i), list(x = rn(d[1], p), center = rnorm(p), icov = IS),
       function(e) list(d2 = mahalanobis(e$x, e$center, e$icov, inverted = TRUE)), sprintf("x %dx%d, icov SPD %dx%d", d[1], p, p, p))
}
def("chol", "base::chol(A) (dpotrf 'U'): factor triangular superior.", "chol.R:21-29, Lapack.c:1090-1104")
def("chol2inv_chol", "base::chol2inv(chol(A)) (dpotrf+dpotri 'U' + espejo).", "Lapack.c:1139-1182")
i <- 0
for (p in c(2, 3, 5, 10, 25, 50, 100, 200)) {
  i <- i + 1; A <- spd(p, max(p, 20))
  caso("chol", cc(i), list(A = A), function(e) list(R = chol(e$A)), sprintf("SPD %dx%d", p, p))
  caso("chol2inv_chol", cc(i), list(A = A), function(e) list(inv = chol2inv(chol(e$A))), sprintf("SPD %dx%d", p, p))
}
## regularizada tipo rcov: rho*I + (1-rho)*scfac*S (S de rango deficiente)
for (p in c(30, 60)) {
  E1 <- matrix(rnorm(p * 10), p, 10); S <- E1 %*% t(E1) / 10; rho <- 0.05
  A <- rho * diag(p) + (1 - rho) * 1.3 * S
  caso("chol2inv_chol", sprintf("rcov%d", p), list(A = A), function(e) list(inv = chol2inv(chol(e$A))), sprintf("rho*I + (1-rho)*scfac*S, S rango 10, p=%d", p))
  caso("chol", sprintf("rcov%d", p), list(A = A), function(e) list(R = chol(e$A)), sprintf("rho*I + (1-rho)*scfac*S, S rango 10, p=%d", p))
}
def("determinant", "base::determinant(A)$modulus (log|det|, dgetrf) y sign; ademas det(A) y obj = det(A)^(1/p) como detmrcd.R:410-413.", "det.R:25-29, Lapack.c:1403-1458")
i <- 0
for (p in c(2, 3, 5, 10, 20, 40, 100)) {
  i <- i + 1; A <- spd(p, max(p, 20))
  caso("determinant", cc(i), list(A = A), function(e) { d <- determinant(e$A)
        list(modulus = as.numeric(d$modulus), sign = as.integer(d$sign), det = det(e$A), obj = det(e$A)^(1 / nrow(e$A))) },
       sprintf("SPD %dx%d", p, p))
}
caso("determinant", "general", list(A = rn(7, 7)), function(e) { d <- determinant(e$A)
     list(modulus = as.numeric(d$modulus), sign = as.integer(d$sign), det = det(e$A), obj = abs(det(e$A))^(1 / 7)) }, "general 7x7 (signo variable)")
caso("determinant", "subdesborde", list(A = diag(rep(1e-10, 40)) + 0), function(e) { d <- determinant(e$A)
     list(modulus = as.numeric(d$modulus), sign = as.integer(d$sign), det = det(e$A), obj = det(e$A)^(1 / 40)) }, "diag(1e-10) 40x40: det subdesborda a 0 (T19) pero modulus finito")
def("matprod", "A %*% B (dgemm 'N','N'); B se entrega MATERIALIZADA (p.ej. t(A)).", "array.c:788-843")
def("matvec", "A %*% v (dgemv 'N').", "array.c:831-833")
def("vecmat", "v %*% B (dgemv 'T').", "array.c:834-838")
def("crossprod", "crossprod(X) (dsyrk 'U','T' + espejo).", "array.c:983-1020")
i <- 0
for (d in list(c(5, 3, 4), c(20, 12, 9), c(40, 12, 12), c(100, 50, 50), c(50, 200, 200), c(15, 5, 15), c(200, 40, 40), c(100, 250, 250))) {
  i <- i + 1
  caso("matprod", cc(i), list(A = rn(d[1], d[2]), B = rn(d[2], d[3])), function(e) list(C = e$A %*% e$B),
       sprintf("(%dx%d)(%dx%d)", d[1], d[2], d[2], d[3]))
}
for (d in list(c(5, 15), c(10, 25), c(40, 25), c(200, 50), c(250, 50))) {         # mE %*% t(mE)
  i <- i + 1; E1 <- rn(d[1], d[2])
  caso("matprod", cc(i), list(A = E1, B = t(E1)), function(e) list(C = e$A %*% e$B),
       sprintf("mE %%*%% t(mE) con mE %dx%d (S7: no exactamente simetrica)", d[1], d[2]))
}
i <- 0
for (d in list(c(10, 4), c(50, 20), c(200, 40), c(100, 250))) {
  i <- i + 1
  caso("matvec", cc(i), list(A = rn(d[1], d[2]), v = rn(d[2])), function(e) list(y = e$A %*% e$v), sprintf("(%dx%d) %%*%% v", d[1], d[2]))
  caso("vecmat", cc(i), list(v = rn(d[1]), B = rn(d[1], d[2])), function(e) list(y = e$v %*% e$B), sprintf("v %%*%% (%dx%d)", d[1], d[2]))
  caso("crossprod", cc(i), list(X = rn(d[1], d[2])), function(e) list(C = crossprod(e$X)), sprintf("crossprod de %dx%d", d[1], d[2]))
}
caso("crossprod", "n_menor_p", list(X = rn(30, 80)), function(e) list(C = crossprod(e$X)), "crossprod 30x80 (rango deficiente)")
def("eigen_sym", "eigen(A, symmetric=TRUE) (dsyevr jobz='V', uplo='L'): valores decrecientes y vectores (columnas). Los signos de los vectores son los de LAPACK.", "eigen.R:45-74, Lapack.c:166-237")
def("eigen_auto", "eigen(A) sin symmetric= (isSymmetric tol 100*eps => La_rs jobz='V'); A = mE %*% t(mE)/(h-1) no exactamente simetrica. Salida valores y vectores.", "eigen.R:22-74")
i <- 0
for (d in list(c(3, 3), c(5, 20), c(12, 40), c(20, 100), c(40, 60), c(60, 30), c(100, 50), c(200, 50))) {
  i <- i + 1; p <- d[1]
  X <- rn(d[2], p)
  A <- cor(X)
  caso("eigen_sym", cc(i), list(A = A), function(e) { r <- eigen(e$A, symmetric = TRUE); list(valores = r$values, vectores = r$vectors) },
       sprintf("cor de datos %dx%d%s", d[2], p, if (d[2] <= p) " (rango deficiente, autoespacio nulo)" else ""))
  E1 <- rn(p, d[2]); S <- E1 %*% t(E1) / (d[2] - 1)
  caso("eigen_auto", cc(i), list(A = S), function(e) { r <- eigen(1.3 * e$A); list(valores = r$values, vectores = r$vectors) },
       sprintf("1.3 * mE %%*%% t(mE)/(h-1), mE %dx%d", p, d[2]))
}
caso("eigen_sym", "identidad", list(A = diag(6)), function(e) { r <- eigen(e$A, symmetric = TRUE); list(valores = r$values, vectores = r$vectors) }, "identidad 6x6")
caso("eigen_sym", "diag_distinta", list(A = diag(c(5, 3, 1, 4, 2))), function(e) { r <- eigen(e$A, symmetric = TRUE); list(valores = r$values, vectores = r$vectors) }, "diagonal 5x5")
U <- diag(8); for (i2 in 2:8) for (j2 in 1:(i2 - 1)) { U[i2, j2] <- rnorm(1) / 3; U[j2, i2] <- U[i2, j2] }
caso("eigen_sym", "ogk_U", list(A = U), function(e) { r <- eigen(e$A, symmetric = TRUE); list(valores = r$values, vectores = r$vectors) }, "forma de la U de OGK (diag 1, simetrica, 8x8)")

## ---------------------------------------------------------------- libm y otras funciones elementales
xs_t <- c(seq(-10, 10, by = 0.01), rnorm(5000, 0, 2), 10^-(1:20), -10^-(1:20), 20, -20, 40, -40, 700, 0)
def("tanh", "base::tanh(x) (libm).", "detmrcd.R:132")
caso("tanh", "rejilla", list(x = xs_t), function(e) list(y = tanh(e$x)), "rejilla -10..10 paso 0.01, normales, magnitudes pequenas y extremos")
caso("tanh", "datos_std", list(x = rn(100, 20)), function(e) list(y = tanh(e$x)), "matriz 100x20 normal estandar")
def("sin", "base::sin(x) (libm). Entrada: correlaciones en [-1,1]; salida sin(0.5*pi*x) (detmrcd.R:218, 1/2*pi == 0.5*pi exacto).", "detmrcd.R:218")
rr <- c(seq(-1, 1, by = 0.001), runif(3000, -1, 1))
caso("sin", "rejilla", list(r = rr), function(e) list(y = sin(1 / 2 * pi * e$r)), "sin(1/2*pi*r) en [-1,1]")
def("log", "base::log(x) (libm).", "Lapack.c:1434")
caso("log", "rejilla", list(x = c(10^seq(-15, 15, by = 0.25), runif(2000, 0.001, 50), 1, 2, 0.5)), function(e) list(y = log(e$x)), "log")
def("exp", "base::exp(x) (libm); det = sign*exp(modulus).", "det.R:25-29")
caso("exp", "rejilla", list(x = c(seq(-800, 700, by = 1.5), runif(2000, -50, 50), 0)), function(e) list(y = exp(e$x)), "exp (incluye subdesborde/desborde)")
def("r_pow", "x^y con R_POW: y==2 -> x*x; x^(-1); det^(1/p). Entradas x, y alineadas.", "arithmetic.c:204-247")
g <- expand.grid(x = c(0.5, 1e-3, 3, 100, 2.718281828459045, 1e-300, 1e300, 0, 1, 1e-10, 0.1234567, 987.654), y = c(2, -1, 0, 1 / 3, 1 / 20, 1 / 200, 1 / 250, 0.5, 1))
caso("r_pow", "rejilla", list(x = g$x, y = g$y), function(e) list(z = e$x^e$y), "rejilla x en valores variados, y en {2,-1,0,1/3,1/20,...}")
def("sqrt", "base::sqrt(x) (IEEE).", "")
caso("sqrt", "rejilla", list(x = c(runif(2000, 0, 100), 0, 1, 2, 1e-300, 1e300)), function(e) list(y = sqrt(e$x)), "sqrt")

## ---------------------------------------------------------------- medias y sumas (T5)
def("rowMeans", "rowMeans(X) (suma secuencial por columnas, luego /m).", "array.c:2001-2098")
def("rowSums", "rowSums(X) (suma secuencial).", "array.c:2001-2098")
def("mean", "mean(x) de dos pasadas (summary.c:479-518).", "summary.c:479-518")
i <- 0
for (d in list(c(5, 7), c(20, 25), c(200, 50), c(250, 100), c(40, 1000))) {
  i <- i + 1; X <- rn(d[1], d[2]) * 10^sample(-3:3, d[1] * d[2], TRUE)
  caso("rowMeans", cc(i), list(X = X), function(e) list(m = rowMeans(e$X)), sprintf("%dx%d con magnitudes mezcladas", d[1], d[2]))
  caso("rowSums", cc(i), list(X = X), function(e) list(s = rowSums(e$X)), sprintf("%dx%d con magnitudes mezcladas", d[1], d[2]))
  caso("mean", cc(i), list(x = as.numeric(X[1, ])), function(e) list(m = mean(e$x)), sprintf("vector de %d con magnitudes mezcladas", d[2]))
}
caso("mean", "upper_tri", list(x = as.numeric(sin(0.5 * pi * cor(rn(20, 12), method = "spearman"))[upper.tri(diag(12))])),
     function(e) list(m = mean(e$x)), "vals de upper.tri de sin(pi/2*cor spearman) como en .TargetCorr")

## ---------------------------------------------------------------- order, scale, mahalanobisD
def("order", "order(x) (radix, estable, -0 == 0), base 1.", "sort.R:211-269")
i <- 0
for (n in c(5, 20, 50, 100, 200)) {
  i <- i + 1; x <- if (i %% 2) rnorm(n) else sample(1:5, n, TRUE) / 10
  caso("order", cc(i), list(x = x), function(e) list(ord = order(e$x)), sprintf("n=%d %s", n, if (i %% 2) "normal" else "decimales con empates"))
}
caso("order", "cero_negativo", list(x = c(0, -0, 1, -1, 0, 2, -0)), function(e) list(ord = order(e$x)), "-0 y 0 empatan")
def("scale", "scale(X, center=, scale=) = dos sweeps (resta y luego division).", "scale.R:21-58")
i <- 0
for (d in list(c(10, 3), c(50, 12), c(100, 250))) {
  i <- i + 1; X <- rn(d[1], d[2]) * 7 + 2
  caso("scale", cc(i), list(X = X, center = apply(X, 2, median), scale = apply(X, 2, Qn)),
       function(e) list(Z = scale(e$X, center = e$center, scale = e$scale)[, , drop = FALSE]), sprintf("%dx%d, center=mediana, scale=Qn", d[1], d[2]))
}
def("mahalanobisD", "robustbase:::mahalanobisD(x, FALSE, lambda) = rowSums((x/lambda)^2) con x/lambda por columnas.", "OGK.R:48-53")
i <- 0
for (d in list(c(10, 3), c(50, 20), c(100, 250))) {
  i <- i + 1
  caso("mahalanobisD", cc(i), list(X = rn(d[1], d[2]), lambda = abs(rnorm(d[2])) + 0.1),
       function(e) list(d = as.numeric(robustbase:::mahalanobisD(e$X, FALSE, e$lambda))), sprintf("%dx%d", d[1], d[2]))
}

## ---------------------------------------------------------------- indices
for (fun in names(indices)) {
  meta <- meta_fun[[fun]]
  write_json(list(funcion = fun, descripcion = if (is.null(meta)) "" else meta$descripcion,
                  referencia = if (is.null(meta)) "" else meta$referencia,
                  semilla = SEMILLA_PRIM, RNGkind = RNGkind(), casos = indices[[fun]]),
             file.path(RAIZ_PRIM, fun, "indice.json"), auto_unbox = TRUE, pretty = TRUE, digits = NA, null = "null")
}
tam <- sum(file.size(list.files(RAIZ_PRIM, recursive = TRUE, full.names = TRUE)))
cat(sprintf("primitivas: %d funciones, %d casos, %.2f MB\n", length(indices), sum(lengths(indices)), tam / 1e6))
