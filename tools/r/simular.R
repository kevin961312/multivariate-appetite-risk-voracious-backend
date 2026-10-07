## Simula las entradas de los casos C1-C10 y las guarda en
## packages/pymrcd/tests/golden/fixtures/<caso>/x.csv.gz (17 dígitos, sin cabecera, filas = observaciones).
## Las variantes *_eq reutilizan la entrada de su caso base (no se duplica).
## Contaminación: las primeras ceil(frac*n) filas se desplazan +5 en todas las coordenadas.
## Uso: Rscript tools/r/simular.R [CASO ...]   (desde la raíz del repo; sin args = todos)
source("tools/r/casos.R")
RNGkind("Mersenne-Twister", "Inversion", "Rejection")

simular_caso <- function(nm) {
  cs <- casos[[nm]]
  set.seed(semilla(nm), kind = "Mersenne-Twister", normal.kind = "Inversion", sample.kind = "Rejection")
  x <- matrix(rnorm(cs$n * cs$p), cs$n, cs$p) %*% chol(sigma_de(cs$sigma, cs$p))
  if (cs$contam > 0) {
    m <- ceiling(cs$contam * cs$n)
    x[seq_len(m), ] <- x[seq_len(m), ] + SHIFT
  }
  x
}

args <- commandArgs(TRUE); todos <- names(casos); if (length(args)) todos <- args
for (nm in todos) {
  x <- simular_caso(nm)
  dir.create(file.path(RAIZ_FIXTURES, nm), recursive = TRUE, showWarnings = FALSE)
  ruta <- file.path(RAIZ_FIXTURES, nm, "x.csv.gz")
  escribir_csv_gz(x, ruta)
  y <- leer_csv_gz(ruta)
  ok <- identical(y, x)
  cat(sprintf("%-4s n=%3d p=%3d semilla=%d identical(releer)=%s\n", nm, nrow(x), ncol(x), semilla(nm), ok))
  if (!ok) cat(sprintf("     max|dif|=%g, n_dif=%d\n", max(abs(y - x)), sum(y != x)))
}
