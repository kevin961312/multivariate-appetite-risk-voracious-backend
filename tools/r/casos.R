## Definición común de casos del port MRCD (plan F1a). Se carga con source().
## Semilla de cada caso = 20261000 + nº de caso.
RAIZ_FIXTURES <- "packages/pymrcd/tests/golden/fixtures"
LIB_RRCOV <- "referencias/R-lib"

casos <- list(
  C1  = list(n=50,  p=200, sigma="I",    contam=0),
  C2  = list(n=100, p=200, sigma="I",    contam=0),
  C3  = list(n=50,  p=250, sigma="I",    contam=0),
  C4  = list(n=100, p=250, sigma="I",    contam=0),
  C5  = list(n=50,  p=200, sigma="AR1",  contam=0),
  C6  = list(n=100, p=250, sigma="AR1",  contam=0),
  C7  = list(n=100, p=20,  sigma="I",    contam=0),
  C8  = list(n=200, p=40,  sigma="AR1",  contam=0),
  C9  = list(n=100, p=20,  sigma="I",    contam=0.20),
  C10 = list(n=50,  p=200, sigma="I",    contam=0.10),
  ## C11: regimen ceil(n/2) <= p < n (h = 31 <= p = 40 < n = 60); semilla 20261011
  C11 = list(n=60,  p=40,  sigma="I",    contam=0)
)
PHI <- 0.7
SHIFT <- 5
## variantes: nombre -> caso cuya entrada reutiliza
variantes <- list(C1_eq="C1", C5_eq="C5", C8_eq="C8")

num_caso <- function(nm) as.integer(sub("^C", "", nm))
semilla  <- function(nm) 20261000L + num_caso(nm)

sigma_de <- function(tipo, p) {
  if (tipo == "I") diag(p) else PHI^abs(outer(seq_len(p), seq_len(p), "-"))
}

fmt17 <- function(m) {
  s <- sprintf("%.17g", m)
  if (!is.null(dim(m))) dim(s) <- dim(m)
  s
}
## escribe CSV sin cabecera ni nombres, 17 dígitos, gzip determinista (mtime fijo no es
## configurable en gzfile; el hash se calcula sobre el .csv.gz generado)
escribir_csv_gz <- function(m, ruta) {
  if (is.null(dim(m))) m <- matrix(m, ncol = 1)
  s <- fmt17(m)
  con <- gzfile(ruta, "wb", compression = 9)
  on.exit(close(con))
  writeLines(apply(s, 1, paste, collapse = ","), con)
  invisible(ruta)
}
escribir_int_gz <- function(v, ruta) {
  con <- gzfile(ruta, "wb", compression = 9); on.exit(close(con))
  writeLines(as.character(as.integer(v)), con)
}
## as.numeric() de R usa R_strtod, que NO redondea correctamente (en arm64, ~18 % de los
## valores de 17 dígitos salen 1 ulp desplazados; readr/data.table tampoco son exactos).
## Python (float()/numpy) sí es correcto, y es el que lee las fixtures. Para que el oráculo R
## opere sobre los mismos doubles, se corrige cada valor: con 17 cifras significativas la
## correspondencia double <-> cadena es biunívoca, así que se elige el vecino (+-1 ulp) cuya
## representación "%.17g" coincide con la cadena del archivo. Se aborta si alguno no cuadra.
## descompone una cadena %.17g en (signo, dígitos sin ceros laterales, exponente decimal de la coma)
.dec <- function(s) {
  m <- regmatches(s, regexec("^(-?)([0-9]*)\\.?([0-9]*)(?:e([+-][0-9]+))?$", s))[[1]]
  sg <- if (m[2] == "-") -1L else 1L
  ex <- if (nzchar(m[5])) as.integer(m[5]) else 0L
  dg <- paste0(m[3], m[4]); pt <- nchar(m[3]) + ex
  lead <- nchar(dg) - nchar(sub("^0+", "", dg)); dg <- sub("^0+", "", dg); pt <- pt - lead
  dg <- sub("0+$", "", dg)
  list(sg = if (dg == "") 0L else sg, dg = dg, pt = pt)
}
## compara dos cadenas %.17g numéricamente: -1, 0, 1
.cmp_dec <- function(a, b) {
  A <- .dec(a); B <- .dec(b)
  if (A$sg != B$sg) return(sign(A$sg - B$sg))
  if (A$sg == 0L) return(0L)
  mag <- if (A$pt != B$pt) sign(A$pt - B$pt) else {
    w <- max(nchar(A$dg), nchar(B$dg)); pa <- formatC(A$dg, width = -w, flag = " "); pb <- formatC(B$dg, width = -w, flag = " ")
    pa <- gsub(" ", "0", pa); pb <- gsub(" ", "0", pb)
    if (pa == pb) 0L else if (pa < pb) -1L else 1L }
  as.integer(A$sg * mag)
}
parse_exacto <- function(s) {
  y <- as.numeric(s)
  for (k in which(sprintf("%.17g", y) != s)) {
    v <- y[k]
    e <- if (v == 0) -1074 else floor(log2(abs(v))) - 52
    hallado <- FALSE
    ## 1) vecinos cercanos (+-1 ulp ... +-200): caso habitual de R_strtod (errores de 1 ulp)
    for (u in c(2^e, 2^(e - 1))) {
      d <- 1L
      while (!hallado && d <= 200L) {
        for (sg in c(1, -1)) if (!hallado && sprintf("%.17g", v + sg * d * u) == s[k]) { y[k] <- v + sg * d * u; hallado <- TRUE }
        d <- d + 1L
      }
      if (hallado) break
    }
    ## 2) R_strtod puede errar >1e5 ulp con exponentes grandes (p. ej. 1e-295): bisección en valor
    ##    comparando cadenas %.17g (la correspondencia double -> %.17g es monótona y biunívoca)
    if (!hallado) {
      lo <- v * (1 - 1e-6); hi <- v * (1 + 1e-6); if (lo > hi) { t <- lo; lo <- hi; hi <- t }
      if (.cmp_dec(sprintf("%.17g", lo), s[k]) <= 0 && .cmp_dec(sprintf("%.17g", hi), s[k]) >= 0) {
        for (it in 1:200) {
          mid <- lo + (hi - lo) / 2; sm <- sprintf("%.17g", mid); c0 <- .cmp_dec(sm, s[k])
          if (c0 == 0L) { y[k] <- mid; hallado <- TRUE; break }
          if (c0 < 0L) lo <- mid else hi <- mid
          if (mid == lo && mid == hi) break
          if (!(lo < hi) || identical(mid, lo) && identical(mid, hi)) break
        }
      }
    }
    if (!hallado) stop("parse_exacto: no se pudo reconstruir ", s[k])
  }
  y
}
leer_csv_gz <- function(ruta) {
  con <- gzfile(ruta, "rb"); on.exit(close(con))
  l <- readLines(con)
  partes <- strsplit(l, ",", fixed = TRUE)
  p <- length(partes[[1]])
  v <- parse_exacto(unlist(partes, use.names = FALSE))
  matrix(v, nrow = length(l), ncol = p, byrow = TRUE)
}
