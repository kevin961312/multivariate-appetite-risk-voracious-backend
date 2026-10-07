## Genera tools/r/detmrcd_instrumentado.R a partir del código OFICIAL de rrcov 1.7-7
## (referencias/rrcov-1.7-7/R/detmrcd.R y CovMrcd.R), insertando SOLO líneas de captura
## ".cap(...)  # captura: <archivo>:<línea>" detrás de la línea indicada (nº de línea del original).
## Invariante verificable: quitar del resultado las líneas con "# captura:" o "## [INSTR]" devuelve
## EXACTAMENTE detmrcd.R + CovMrcd.R (lo comprueba verificar_instrumentado.R).
## Uso: Rscript tools/r/construir_instrumentado.R   (desde la raíz del repo)
DIR_SRC <- "referencias/rrcov-1.7-7/R"
SALIDA  <- "tools/r/detmrcd_instrumentado.R"

ins <- list(detmrcd.R = list(), CovMrcd.R = list())
## cap(archivo, línea_origen, nombre, expr, desc, k=, it=, grande=): registra una captura
cap <- function(f, L, nombre, expr, desc, k = "NULL", it = "NULL", grande = FALSE,
                tag = NULL, despues = L) {
  src <- sprintf("%s:%s", f, if (is.null(tag)) L else tag)
  code <- sprintf('.cap("%s", %s, k=%s, it=%s, src="%s", d="%s", grande=%s)  # captura: %s',
                  nombre, expr, k, it, src, desc, if (grande) "TRUE" else "FALSE", src)
  ins[[f]][[as.character(despues)]] <<- c(ins[[f]][[as.character(despues)]], code)
}
raw <- function(f, L, code, tag = L) {
  ins[[f]][[as.character(L)]] <<- c(ins[[f]][[as.character(L)]],
                                    sprintf("%s  # captura: %s:%s", code, f, tag))
}
D <- "detmrcd.R"; C <- "CovMrcd.R"

## ---- CovMrcd.R
cap(C, 19, "in_ok", "ok", "filas finitas de x (n0); TRUE/FALSE como 1/0")
cap(C, 20, "in_x", "x", "x filtrada (n x p)")

## ---- .detmrcd: preámbulo y estandarización
cap(D, 404, "pre_n", "n", "numero de observaciones")
cap(D, 404, "pre_p", "p", "numero de variables")
cap(D, 404, "pre_h", "h", "tamano del subconjunto h")
cap(D, 404, "pre_alpha", "alpha", "alpha efectivo")
cap(D, 417, "std_vmx", "vmx", "medianas por variable (apply median sobre mX p x n)")
cap(D, 418, "std_vsd_raw", "vsd", "Qn por variable antes de minscale")
cap(D, 419, "std_vsd", "vsd", "Qn por variable tras vsd[vsd<minscale]<-minscale")
cap(D, 421, "std_mU", "mU", "datos estandarizados scale(t(mX), vmx, vsd) (n x p)")
## .TargetCorr (solo target=1)
cap(D, 217, "tgt_cortmp_rank", "cortmp", "cor(t(mX), method=spearman) (p x p); solo target=1")
cap(D, 218, "tgt_cortmp_sin", "cortmp", "sin(1/2*pi*cortmp) (p x p); solo target=1")
cap(D, 224, "tgt_constcor", "constcor", "constcor tras la cota inferior; solo target=1")
cap(D, 226, "tgt_R", "R", "matriz objetivo equicorrelacion R (p x p); solo target=1")
## eigenEQ y mW (solo target=1)
cap(D, 432, "eq_values", "mTeigen$values", "valores propios de eigenEQ (p); solo target=1")
cap(D, 432, "eq_mQ", "mQ", "matriz de Helmert mQ (p x p); solo target=1")
cap(D, 432, "eq_mW", "mW", "mU %*% mQ %*% misqL (n x p); solo target=1")

## ---- r6pack local
cap(D, 123, "r6_center", "doScale(x, center=median, scale=scalefn)$center", "centros de doScale (p)", tag = 124)
cap(D, 123, "r6_scale", "doScale(x, center=median, scale=scalefn)$scale", "escalas Qn de doScale tras centrar (p)", tag = 124)
cap(D, 124, "r6_x", "x", "x tras doScale (n x p)")
cap(D, 132, "r6_y1", "y1", "tanh(x) (n x p)")
cap(D, 133, "r6_R1", "R1", "cor(y1) (p x p)")
cap(D, 134, "r6_P1", "P", "autovectores de R1 (p x p, orden decreciente de valores)")
cap(D, 134, "r6_ev1", "eigen(R1, symmetric=TRUE)$values", "autovalores de R1 (p)")
cap(D, 138, "r6_rank", "apply(x, 2L, rank)", "rangos promedio por columna de x (n x p)")
cap(D, 138, "r6_R2", "R2", "cor spearman de x (p x p)")
cap(D, 139, "r6_P2", "P", "autovectores de R2 (p x p)")
cap(D, 139, "r6_ev2", "eigen(R2, symmetric=TRUE)$values", "autovalores de R2 (p)")
cap(D, 143, "r6_y3", "y3", "qnorm((rank-1/3)/(n+1/3)) (n x p)")
cap(D, 144, "r6_R3", "R3", "cor(y3, use=complete.obs) (p x p)")
cap(D, 145, "r6_P3", "P", "autovectores de R3 (p x p)")
cap(D, 145, "r6_ev3", "eigen(R3, symmetric=TRUE)$values", "autovalores de R3 (p)")
cap(D, 149, "r6_znorm", "znorm", "norma euclidea por fila de x (n)")
cap(D, 152, "r6_xnrmd", "x.nrmd", "x con filas normalizadas (n x p)")
cap(D, 153, "r6_SCM", "SCM", "crossprod(x.nrmd) (p x p)")
cap(D, 154, "r6_P4", "P", "autovectores de SCM (p x p)")
cap(D, 154, "r6_ev4", "eigen(SCM, symmetric=TRUE)$values", "autovalores de SCM (p)")
cap(D, 158, "r6_ind5", "ind5", "order(znorm), base 1 (n)")
cap(D, 160, "r6_Hinit", "Hinit", "primeras ceil(n/2) filas de ind5, base 1")
cap(D, 161, "r6_covx", "covx", "cov(x[Hinit,]) (p x p)")
cap(D, 162, "r6_P5", "P", "autovectores de covx (p x p)")
cap(D, 162, "r6_ev5", "eigen(covx, symmetric=TRUE)$values", "autovalores de covx (p)")
cap(D, 98, "r6_U", "U", "matriz U de ogkscatter completa antes de eigen (p x p)", tag = "97-101")
cap(D, 101, "r6_ev6", "eigen(U, symmetric=TRUE)$values", "autovalores de U (p)")
cap(D, 166, "r6_P6", "P", "autovectores de U (p x p)")

## ---- initset (se invoca 6 veces: contador .S$k)
raw(D, 69, ".S$k <- .S$k + 1", tag = 65)
cap(D, 70, "is_proj", "data %*% P", "proyeccion data %*% P (n x p) del conjunto k", k = ".S$k", tag = 70)
cap(D, 70, "is_lambda", "lambda", "escalas lambda de doScale(data %*% P) (p)", k = ".S$k")
cap(D, 71, "is_sqrtcov", "sqrtcov", "P %*% (lambda * t(P)) (p x p)", k = ".S$k")
cap(D, 72, "is_sqrtinvcov", "sqrtinvcov", "P %*% (t(P)/lambda) (p x p)", k = ".S$k")
cap(D, 73, "is_colmed", "colMedians(data %*% sqrtinvcov)", "colMedians(data %*% sqrtinvcov) (p)", k = ".S$k")
cap(D, 73, "is_estloc", "estloc", "estloc = colMedians(.) %*% sqrtcov (p)", k = ".S$k")
cap(D, 74, "is_centeredx", "centeredx", "(data - estloc) %*% P (n x p)", k = ".S$k")
cap(D, 74, "is_dist", "mahalanobisD(centeredx, FALSE, lambda)", "distancias mahalanobisD (n)", k = ".S$k", tag = 75)
cap(D, 74, "is_ord", "sort.list(mahalanobisD(centeredx, FALSE, lambda))[1:h]", "primeras h posiciones del orden de distancias, base 1 (h)", k = ".S$k", tag = 75)

## ---- conjuntos iniciales, scfac
cap(D, 459, "hs_init", "hsets.init", "subconjuntos iniciales hsets.init[1:h,] (h x 6), base 1, orden de distancia")
cap(D, 460, "scfac", "scfac", ".MCDcons(p, h/n)")
cap(D, 460, "scfac_q", "qchisq(h/n, p)", "qchisq(h/n, p) (covMcd.R:604)", tag = "460 (covMcd.R:604)")
cap(D, 460, "scfac_pg", "pgamma(qchisq(h/n, p)/2, p/2 + 1)", "pgamma(q/2, p/2+1) (covMcd.R:605)", tag = "460 (covMcd.R:605)")

## ---- seleccion de rho (por k = variable de bucle)
cap(D, 468, "rs_mu", "vMusubset", "medias del subconjunto k (p)", k = "k")
cap(D, 470, "rs_mS", "mS", "mE %*% t(mE)/(h-1) (p x p)", k = "k")
cap(D, 475, "rs_veigen", "veigen", "autovalores eigen(scfac*mS) (p)", k = "k")
cap(D, 475, "rs_e1", "e1", "minimo autovalor", k = "k")
cap(D, 475, "rs_ep", "ep", "maximo autovalor", k = "k")
raw(D, 495, ".cap_uniroot(out, fncond, k)", tag = "495-511")
cap(D, 506, "rs_irho", "irho", "rho de la rejilla (solo si uniroot fallo)", k = "k")
cap(D, 514, "rs_rhok","rho6pack[k]", "rho_k elegido para el subconjunto k", k = "k", tag = "500/511")
cap(D, 518, "rs_rho6", "rho6pack", "rho_k de los 6 subconjuntos (6)")
cap(D, 518, "rs_cutoff", "cutoffrho", "max(0.1, median(rho6))")
cap(D, 519, "rs_rho", "rho", "rho global = max(rho6[rho6<=cutoff])")
cap(D, 528, "rs_Vsel", "Vselection", "Vselection (6), NA como -1", tag = 528)
cap(D, 533, "rs_initV", "initV", "subconjunto inicial initV (base 1)")
cap(D, 535, "rs_setsV", "setsV", "subconjuntos restantes setsV (base 1, longitud variable)")

## ---- C-steps (k actual en .S$kcur, iteracion en .S$it)
raw(D, 546, ".S$kcur <- initV; .S$ctx <- \"cs\"", tag = 547)
raw(D, 551, ".S$kcur <- k", tag = 559)
cap(D, 350, "cs_index", "index", "indice h usado en la iteracion (base 1, h)", k = ".S$kcur", it = "0")
raw(D, 350, ".S$it <- 0", tag = 350)
cap(D, 361, "cs_vMu", "vMu", "media del subconjunto en el paso t (p)", k = ".S$kcur", it = "0")
cap(D, 361, "cs_mS", "ret$cov", "mS de .RCOV, divisor h (p x p)", k = ".S$kcur", it = "0", grande = TRUE)
cap(D, 361, "cs_rcov", "ret$rcov", "covarianza regularizada rcov (p x p)", k = ".S$kcur", it = "0", grande = TRUE)
cap(D, 361, "cs_inv", "ret$inv_rcov", "inversa de rcov (p x p)", k = ".S$kcur", it = "0", grande = TRUE)
cap(D, 361, "cs_vdst", "vdst", "distancias diag(t(D) %*% (mIS %*% D)) (n)", k = ".S$kcur", it = "0")
cap(D, 361, "cs_nndex", "index", "nuevo indice sort(order(vdst)[1:h]) (base 1, h)", k = ".S$kcur", it = "0")
raw(D, 366, ".S$it <- iter", tag = 366)
cap(D, 366, "cs_index", "index", "indice h usado en la iteracion (base 1, h)", k = ".S$kcur", it = "iter")
cap(D, 372, "cs_vMu", "vMu", "media del subconjunto en el paso t (p)", k = ".S$kcur", it = "iter")
cap(D, 372, "cs_mS", "ret$cov", "mS de .RCOV, divisor h (p x p)", k = ".S$kcur", it = "iter", grande = TRUE)
cap(D, 372, "cs_rcov", "ret$rcov", "covarianza regularizada rcov (p x p)", k = ".S$kcur", it = "iter", grande = TRUE)
cap(D, 372, "cs_inv", "ret$inv_rcov", "inversa de rcov (p x p)", k = ".S$kcur", it = "iter", grande = TRUE)
cap(D, 372, "cs_vdst", "vdst", "distancias (n)", k = ".S$kcur", it = "iter")
cap(D, 372, "cs_nndex", "nndex", "nuevo indice (base 1, h)", k = ".S$kcur", it = "iter")
## InvSMW (contexto cs o fin)
cap(D, 314, "smw_G", "t(mU) %*% (imB %*% mU)", "G = t(mU) %*% (imB %*% mU) (h x h) dentro de .InvSMW")
cap(D, 314, "smw_Temp", "Temp", "chol2inv(chol(I + nu*G)) (h x h) dentro de .InvSMW")
cap(D, 548, "cs_numit", "ret$numit", "iteraciones del C-step del subconjunto inicial", k = "initV")
cap(D, 548, "cs_obj", "objret", "obj = det(cov)^(1/p)", k = "initV")
cap(D, 548, "cs_det", "det(ret$cov)", "det(cov)", k = "initV")
cap(D, 561, "cs_numit", "tmp$numit", "iteraciones del C-step", k = "k")
cap(D, 561, "cs_obj", "objtmp", "obj = det(cov)^(1/p)", k = "k")
cap(D, 561, "cs_det", "det(tmp$cov)", "det(cov)", k = "k")
raw(D, 576, ".S$ctx <- \"fin\"", tag = 577)
cap(D, 575, "sel_best6pack", "best6pack", "subconjuntos empatados en el optimo (base 1, longitud variable)")
cap(D, 575, "sel_hindex", "hindex", "indice h final (base 1)")
cap(D, 575, "sel_n_csteps", "hset.csteps", "numit por subconjunto (6; 0 en initV)")

## ---- final
cap(D, 578, "fin_mE", "mE", "mX[,hindex] - ret$mu (p x h)")
cap(D, 579, "fin_W", "weightedScov", "mE %*% t(mE)/(h-1) (p x p)")
cap(D, 583, "fin_mu_std", "MRCDmu", "rowMeans(mX[,hindex]) (p)")
cap(D, 584, "fin_cov_std", "MRCDcov", "rho*I + (1-rho)*c_alpha*W (p x p), espacio estandarizado")
cap(D, 593, "fin_icov_std", "iMRCDcov", "inversa (SMW o chol2inv) en espacio estandarizado (p x p)", tag = "588-593")
cap(D, 615, "fin_center", "as.numeric(MRCDmu)", "centro final tras retro-transformacion (p)")
cap(D, 615, "fin_cov", "MRCDcov", "covarianza final (p x p)")
cap(D, 615, "fin_icov", "iMRCDcov", "inversa final (p x p)")
cap(D, 615, "fin_target", "mT", "target final retro-transformado (p x p)")
cap(D, 618, "fin_dist_detmrcd", "dist", "distancias mahalanobis internas de .detmrcd (NO usadas por CovMrcd) (n)")
cap(D, 619, "fin_crit", "objret", "determinant(MRCDcov)$modulus (log-det)")
cap(D, 634, "out_iBest", "best6pack", "iBest devuelto por .detmrcd (base 1, longitud variable)")
cap(D, 634, "out_n_csteps", "hset.csteps", "n.csteps devuelto por .detmrcd (6)")

## ---- ensamblado
leer <- function(f) readLines(file.path(DIR_SRC, f))
partes <- list()
partes[[1]] <- c(
  "## [INSTR] Copia INSTRUMENTADA de rrcov 1.7-7 oficial (detmrcd.R + CovMrcd.R). Generado por",
  "## [INSTR] tools/r/construir_instrumentado.R: NO editar a mano. Solo se anaden lineas '# captura:'.",
  "## [INSTR] Se evalua con tools/r/instrumentacion.R (entorno hijo del namespace de rrcov oficial).")
for (f in c("detmrcd.R", "CovMrcd.R")) {
  lin <- leer(f)
  salida <- character()
  for (i in seq_along(lin)) {
    salida <- c(salida, lin[i], ins[[f]][[as.character(i)]])
  }
  partes[[length(partes) + 1]] <- c(sprintf("## [INSTR] ===== inicio %s (lineas citadas = las del original) =====", f), salida)
}
writeLines(unlist(partes), SALIDA)
cat("escrito", SALIDA, "con", length(unlist(partes)), "lineas\n")
