## Carga y ejecución de la copia instrumentada de rrcov (detmrcd_instrumentado.R).
## Se evalúa en un entorno hijo del namespace de rrcov OFICIAL (referencias/R-lib), de modo que
## Qn, doScale, mahalanobisD, colMedians, CovControlMrcd... resuelven igual que en el oráculo.
## Uso: source("tools/r/casos.R"); source("tools/r/instrumentacion.R")
##      r <- correr_instrumentado(x, target="identity", initHsets=NULL)   # r$res (S4), r$cap, r$meta
suppressMessages(library(rrcov, lib.loc = "referencias/R-lib"))
stopifnot(normalizePath(find.package("rrcov")) == normalizePath("referencias/R-lib/rrcov"))

cargar_instrumentado <- function(ruta = "tools/r/detmrcd_instrumentado.R") {
  E <- new.env(parent = asNamespace("rrcov"))
  E$.S <- new.env()
  E$.S$cap <- list(); E$.S$meta <- list(); E$.S$k <- 0; E$.S$full <- TRUE
  E$.cap <- function(nombre, valor, k = NULL, it = NULL, src, d, grande = FALSE) {
    if (grande && !isTRUE(.S$full)) return(invisible(valor))
    if (startsWith(nombre, "smw_")) {
      nombre <- paste0(.S$ctx, "_", sub("smw_", "smw", nombre))
      if (.S$ctx == "cs") { k <- .S$kcur; it <- .S$it }
    }
    full <- nombre
    if (!is.null(k)) full <- paste0(full, "_k", k)
    if (!is.null(it)) full <- paste0(full, "_it", it)
    .S$cap[[full]] <- valor
    .S$meta[[full]] <- list(src = src, d = d)
    invisible(valor)
  }
  E$.cap_uniroot <- function(out, fncond, k) {
    ok <- !inherits(out, "try-error")
    s <- "detmrcd.R:495-511"
    .cap("rs_path", if (ok) 1L else 2L, k = k, src = s, d = "camino de rho_k: 1 = uniroot, 2 = rejilla (uniroot fallo)")
    .cap("rs_flower", fncond(0.00001), k = k, src = "detmrcd.R:495", d = "fncond(lower=1e-5)")
    .cap("rs_fupper", fncond(0.99), k = k, src = "detmrcd.R:495", d = "fncond(upper=0.99)")
    if (ok) {
      .cap("rs_root", out$root, k = k, src = "detmrcd.R:500", d = "raiz de uniroot")
      .cap("rs_iter", as.integer(out$iter), k = k, src = "detmrcd.R:500", d = "iteraciones de uniroot")
      .cap("rs_estimprec", out$estim.prec, k = k, src = "detmrcd.R:500", d = "estim.prec de uniroot")
    }
  }
  environment(E$.cap) <- E; environment(E$.cap_uniroot) <- E
  sys.source(ruta, envir = E, keep.source = FALSE)
  E
}

reiniciar_captura <- function(E, full) {
  E$.S$cap <- list(); E$.S$meta <- list(); E$.S$k <- 0; E$.S$full <- full
  E$.S$kcur <- 0; E$.S$ctx <- "cs"; E$.S$it <- 0
}

## full: capturar matrices p x p de los C-steps (por defecto solo si p <= 40; ver informe de tamano)
correr_instrumentado <- function(x, target = "identity", initHsets = NULL, save.hsets = FALSE,
                                 full = ncol(x) <= 40, E = cargar_instrumentado()) {
  reiniciar_captura(E, full)
  res <- E$CovMrcd(x, target = target, initHsets = initHsets, save.hsets = save.hsets)
  list(res = res, cap = E$.S$cap, meta = E$.S$meta, E = E)
}
## compara dos objetos CovMrcd slot a slot (excepto 'call'); devuelve vector lógico
comparar_s4 <- function(a, b) {
  sl <- setdiff(slotNames(a), "call")
  vapply(sl, function(s) identical(slot(a, s), slot(b, s)), logical(1))
}
