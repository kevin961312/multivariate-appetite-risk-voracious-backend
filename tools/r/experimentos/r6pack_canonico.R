## EXPERIMENTO (rama experimento/mrcd-canonico) — NO es rrcov ni un cambio a rrcov.
## Variante «canónica» de los subconjuntos iniciales de MRCD para p >= n (hipótesis del dueño):
##   en initset, para los conjuntos 1-5, se conservan solo las direcciones con autovalor significativo
##   lambda_i > lambda_1 * max(n, p) * .Machine$double.eps * kappa   (kappa = 1 por defecto)
##   y la proyección, las escalas Qn y las distancias se calculan solo en ese subespacio de rango r;
##   además se fija el signo de cada autovector conservado (componente de mayor |valor| positiva).
##   El conjunto 6 (OGK) queda exactamente como rrcov. Selección de rho, C-steps y estimación final:
##   rrcov oficial sin tocar (se inyectan los initHsets con correr_instrumentado(..., initHsets=)).
##
## Copia de rrcov 1.7-7 oficial (referencias/rrcov-1.7-7/R/detmrcd.R, MD5 d56485337b83f927bba70002357be341):
##   r6pack (:57-197) e initset (:65-76); ogkscatter (:84-111) sin cambios. Los únicos cambios llevan
##   la marca  ## [CANONICO] detmrcd.R:<línea de origen>.
## canonical2 (piloto 2): además del subespacio significativo V_r, se añade W, la base de las direcciones
##   del complemento en las que los datos sí varían: Z = data (I - V_r V_r^T), SVD de Z, se conservan los
##   vectores singulares derechos con sigma_j > sigma_1(data) * sqrt(eps) * kappa2 (signo fijado).
##   El umbral max(n, p) * eps propuesto inicialmente queda DENTRO del ruido de redondeo del residuo Z
##   (Z = data - (data V) V^T acumula errores de productos de longitud p: en SCM se observó
##   sigma(ruido) = 7.5e-12 ~ 1670 eps sigma_1, por encima de 200 eps sigma_1), y conserva direcciones de
##   ruido que rompen el determinismo. sqrt(eps) queda en el centro (logarítmico) del hueco observado
##   entre ruido (<= ~4e-13 relativo) y variación real (>= ~4e-4 relativo); ver el informe del piloto 2.
##   P = [V_r, W] y el resto de initset es el de rrcov. El umbral se refiere a sigma_1(data) y NO a
##   sigma_1(Z): si Z es puro ruido (SCM, o n > p), sigma_1(Z) ~ 1e-15 y un umbral relativo a él
##   conservaría ese ruido (ver docs/experimentos/2026-10-06-mrcd-canonico-piloto2.md, §3).
## Con variantes = list(list(kappa = NA, signo = FALSE)) se reproduce rrcov oficial bit a bit
## (verificación en tools/r/experimentos/verificar_canonico.R).
##
## Uso:
##   source("tools/r/casos.R"); source("tools/r/instrumentacion.R")
##   source("tools/r/experimentos/r6pack_canonico.R")
##   H <- initHsets_canonico(x)                         # h x 6, kappa = 1, signo = TRUE
##   r <- correr_instrumentado(x, initHsets = H, E = E)  # resto de MRCD: rrcov oficial
## Todas las funciones se evalúan en un entorno hijo del namespace de rrcov OFICIAL (referencias/R-lib),
## de modo que Qn, doScale, colMedians y mahalanobisD resuelven igual que en el oráculo.

.ENV_CANON <- new.env(parent = asNamespace("rrcov"))

## Variante oficial (sin truncar ni fijar signo) y canónica por defecto
VAR_OFICIAL <- list(kappa = NA_real_, signo = FALSE)
VAR_CANON   <- function(kappa = 1) list(kappa = kappa, signo = TRUE)
## canonical2: V_r (como VAR_CANON) + W = direcciones del complemento con variación real de los datos
## base2 = "sqrt": umbral del complemento sigma_1(data) * sqrt(eps) * kappa2 (por defecto);
## base2 = "eps":  sigma_1(data) * max(n, p) * eps * kappa2 (el propuesto; cae dentro del ruido de redondeo de Z)
VAR_CANON2  <- function(kappa = 1, kappa2 = 1, base2 = "sqrt")
    list(kappa = kappa, signo = TRUE, comp = TRUE, kappa2 = kappa2, base2 = base2)

local(envir = .ENV_CANON, {

VAR_OFICIAL <- list(kappa = NA_real_, signo = FALSE)

## [CANONICO] fija el signo de cada columna: su componente de mayor |valor| (primera en caso de empate) > 0
fijar_signo <- function(P) {
    for (j in seq_len(ncol(P))) {
        i <- which.max(abs(P[, j]))
        if (P[i, j] < 0) P[, j] <- -P[, j]
    }
    P
}

## Copia de r6pack (detmrcd.R:57-197) con la rama adjust.eignevalues=FALSE (la única que usa .detmrcd,
## llamada en detmrcd.R:446). Devuelve una lista de matrices h x 6, una por variante.
## diag = TRUE devuelve además, por conjunto, autovalores, P y data (para el diagnóstico de la causa).
r6pack_var <- function(x, h, scaled = TRUE, scalefn = Qn, variantes = list(VAR_OFICIAL), diag = FALSE)
{
    ## detmrcd.R:65-76 (initset) con dos argumentos nuevos:
    ##   ev: autovalores de la matriz de la que sale P; kappa: NA => sin truncar (oficial)
    initset <- function(data, scalefn, P, h, ev = NULL, kappa = NA_real_, signo = FALSE,
                        comp = FALSE, kappa2 = 1, sref = NULL, base2 = "sqrt")
    {
       stopifnot(length(d <- dim(data)) == 2, length(h) == 1, h >= 1)
       n <- d[1]
       stopifnot(h <= n)
       ## [CANONICO] detmrcd.R:70 — antes de proyectar, conservar solo las direcciones significativas.
       ## eigen(symmetric=TRUE) devuelve autovalores en orden decreciente, así que son las r primeras.
       if (!is.na(kappa)) {
           tol <- ev[1] * max(d[1], d[2]) * .Machine$double.eps * kappa
           r <- sum(ev > tol)
           P <- P[, seq_len(r), drop = FALSE]
       }
       ## [CANONICO] detmrcd.R:70 — signo canónico de cada autovector conservado
       if (signo) P <- fijar_signo(P)
       ## [CANONICO2] detmrcd.R:70 — complemento con variación real. 'data' es lo que initset proyecta en
       ## :70 (data %*% P) sin más centrado: la x de r6pack centrada por medianas y escalada por Qn en
       ## doScale (detmrcd.R:124; rb/detmcd.R:249,285). Z = data (I - P P^T) sin formar la base nula de LAPACK.
       if (comp) {
           Z <- data - (data %*% P) %*% t(P)
           sv <- svd(Z, nu = 0)
           b2 <- if (base2 == "eps") max(d[1], d[2]) * .Machine$double.eps else sqrt(.Machine$double.eps)
           s <- sum(sv$d > sref * b2 * kappa2)
           if (s > 0) P <- cbind(P, fijar_signo(sv$v[, seq_len(s), drop = FALSE]))
       }
       ## detmrcd.R:70-75 sin cambios (con P de p x r, todo queda en el subespacio de rango r)
       lambda <- doScale(data %*% P, center=median, scale=scalefn)$scale
       sqrtcov    <- P %*% (lambda * t(P)) ## == P %*% diag(lambda) %*% t(P)
       sqrtinvcov <- P %*% (t(P) / lambda) ## == P %*% diag(1/lambda) %*% t(P)
       estloc <- colMedians(data %*% sqrtinvcov) %*% sqrtcov
       centeredx <- (data - rep(estloc, each=n)) %*% P
       sort.list(mahalanobisD(centeredx, FALSE, lambda))[1:h]# , partial = 1:h
    }

    ## detmrcd.R:84-111 sin cambios
    ogkscatter <- function(Y, scalefn, only.P = TRUE)
    {
        stopifnot(length(p <- ncol(Y)) == 1, p >= 1)
        U <- diag(p)
        for(i in seq_len(p)[-1L]) {# i = 2:p
            sYi <- Y[,i]
            ii <- seq_len(i - 1L)
            for(j in ii) {
                sYj <- Y[,j]
                U[i,j] <- (scalefn(sYi + sYj)^2 - scalefn(sYi - sYj)^2) / 4
            }
            U[ii,i] <- U[i,ii]
        }
        P <- eigen(U, symmetric=TRUE)$vectors
        P
    }

    stopifnot(length(dx <- dim(x)) == 2)
    n <- dx[1]
    p <- dx[2]
    if(!scaled) { ## detmrcd.R:123-125
        x <- doScale(x, center=median, scale=scalefn)$x
    }
    ## [CANONICO2] escala de referencia del umbral del complemento: sigma_1 de los datos que ve initset
    sref <- if (any(vapply(variantes, function(v) isTRUE(v$comp), NA))) svd(x, nu = 0, nv = 0)$d[1] else NULL
    nsets <- 6
    nv <- length(variantes)
    hsets <- replicate(nv, matrix(integer(), h, nsets), simplify = FALSE)
    dg <- list()

    ## [CANONICO] detmrcd.R:134,139,145,154,162 — eigen() completo (vectors Y values) en vez de $vectors:
    ## es la misma llamada a LAPACK (dsyevr con jobz='V'), los vectores salen idénticos.
    aplicar <- function(k, M, P = NULL) {
        if (is.null(P)) { e <- eigen(M, symmetric=TRUE); P <- e$vectors; ev <- e$values }
        else ev <- NULL
        for (v in seq_len(nv)) {
            va <- variantes[[v]]
            if (k == 6) va <- VAR_OFICIAL      ## [CANONICO] detmrcd.R:166-167 — el conjunto 6 (OGK) queda como rrcov
            hsets[[v]][, k] <<- initset(x, scalefn=scalefn, P=P, h=h, ev=ev, kappa=va$kappa, signo=va$signo,
                                        comp=isTRUE(va$comp), kappa2=if (is.null(va$kappa2)) 1 else va$kappa2,
                                        sref=sref, base2=if (is.null(va$base2)) "sqrt" else va$base2)
        }
        if (diag) dg[[k]] <<- list(P = P, ev = ev)
    }

    ## 1. Hyperbolic tangent of standardized data (detmrcd.R:132-135)
    y1 <- tanh(x)
    R1 <- cor(y1)
    aplicar(1, R1)
    ## 2. Spearmann correlation matrix (detmrcd.R:138-140)
    R2 <- cor(x, method="spearman")
    aplicar(2, R2)
    ## 3. Tukey normal scores (detmrcd.R:143-146)
    y3 <- qnorm((apply(x, 2L, rank) - 1/3)/(n + 1/3))
    R3 <- cor(y3, use = "complete.obs")
    aplicar(3, R3)
    ## 4. Spatial sign covariance matrix (detmrcd.R:149-155)
    znorm <- sqrt(rowSums(x^2))
    ii <- znorm > .Machine$double.eps
    x.nrmd <- x
    x.nrmd[ii,] <- x[ii, ] / znorm[ii]
    SCM <- crossprod(x.nrmd)# / (n-1) not needed for e.vectors
    aplicar(4, SCM)
    ## 5. BACON (detmrcd.R:158-163)
    ind5 <- order(znorm)
    half <- ceiling(n/2)
    Hinit <- ind5[1:half]
    covx <- cov(x[Hinit, , drop=FALSE])
    aplicar(5, covx)
    ## 6. Raw OGK estimate for scatter (detmrcd.R:166-167)
    P <- ogkscatter(x, scalefn, only.P=TRUE)
    aplicar(6, NULL, P = P)

    ## detmrcd.R:173-174: return(hsets)
    if (diag) list(hsets = hsets, diag = dg, x = x, sref = sref) else hsets
}

## Paso 1 de .detmrcd (detmrcd.R:416-422, target = "identity") + llamada de :446.
## Devuelve la lista de matrices h x 6 (una por variante) que .detmrcd usaría como hsets.init.
initHsets_variantes <- function(x, alpha = 0.5, minscale = 0.001, variantes = list(VAR_OFICIAL), diag = FALSE)
{
    mX <- t(x)
    n <- dim(mX)[2]
    h <- as.integer(ceiling(alpha * n))                 ## detmrcd.R:400-404, :411
    vmx <- apply(mX, 1, median)                         ## detmrcd.R:417
    vsd <- apply(mX, 1, Qn)                             ## :418
    vsd[vsd < minscale] <- minscale                     ## :419
    mU <- scale(t(mX), center=vmx, scale=vsd)           ## :421
    mX <- t(mU)                                         ## :422
    r6pack_var(x=t(mX), h=h, scaled=FALSE, scalefn=Qn, variantes=variantes, diag=diag)   ## :446
}
})

initHsets_variantes <- .ENV_CANON$initHsets_variantes
## Atajo: initHsets canónicos (kappa = 1, signo fijado; conjunto 6 como rrcov)
initHsets_canonico <- function(x, kappa = 1) initHsets_variantes(x, variantes = list(VAR_CANON(kappa)))[[1]]
## Atajo: initHsets canonical2
initHsets_canonico2 <- function(x, kappa = 1, kappa2 = 1) initHsets_variantes(x, variantes = list(VAR_CANON2(kappa, kappa2)))[[1]]
