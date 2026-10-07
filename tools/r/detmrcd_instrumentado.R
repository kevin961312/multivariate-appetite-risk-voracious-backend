## [INSTR] Copia INSTRUMENTADA de rrcov 1.7-7 oficial (detmrcd.R + CovMrcd.R). Generado por
## [INSTR] tools/r/construir_instrumentado.R: NO editar a mano. Solo se anaden lineas '# captura:'.
## [INSTR] Se evalua con tools/r/instrumentacion.R (entorno hijo del namespace de rrcov oficial).
## [INSTR] ===== inicio detmrcd.R (lineas citadas = las del original) =====
## @title Compute the Minimum Regularized Covariance Determinant (MRCD) estimator
## @references Paper available at: http://dx.doi.org/10.2139/ssrn.2905259.
## @param x a numerical matrix. The columns represent variables, and rows represent observations.
## @param alpha the proportion of the contamination (between 0.5 and 1)
## @param h the size of the subset (between ceiling(n/2) and n)
## @param initHsets NULL or a K x h integer matrix of initial subsets of observations
##     of size h (specified by the indices in 1:n). If provided, then the initial
##     shape estimates are not calculated.
## @param save.hsets
## @param maxcsteps maximum number of generalized C-steps for each initial subset (default 200)
## @param maxcond maximum condition number allowed (see step 3.4 in algorithm 1) (default 50)
## @param minscale minimum scale allowed (default 0.001)
## @param target = c("identity", "equicorrelation"). Structure of the robust
##     positive definite target matrix: (default) "identity": target matrix is
##     diagonal matrix with robustly estimated univariate scales on the diagonal or
##     "equicorrelation": non-diagonal target matrix that incorporates an
##     equicorrelation structure (see (17) in paper)
## @param trace
## @return A list with the following elements:
## \describe{
## \item{icov}{inverse of the covariance matrix}
## \item{rho}{regularization parameter}
## \item{target}{the target matrix used}
## }
##
.detmrcd <- function(x, h=NULL, alpha=.75, rho=NULL,
            maxcond=50, minscale=0.001, target=0, maxcsteps = 200,
            hsets.init=NULL, save.hsets=missing(hsets.init), full.h = save.hsets,
            trace=FALSE)
{
## NOTES: VT
##
##  - use r6pack from robustbase
##  - X check subset #5 - something is wrong there
##  - X mX is not back transformed to compensate the SVD rescaling
##      ==> the distances returned by MWRCD are different from
##      the distances computed outside of MWRCD.
##
##  - X MRCD works with the transposed matrix X - it shoould be transposed inside the function
##  - Help of CovMcd - remove data.matrix from the example
##  - X What is doing the parameter 'bc'? Can be omitted - bc removed
##  - X parameter 'initrho' is never used: remove it
##  - X scfactor(alpha, p) is equivalent to robustbase:::.MCDcons(p, alpha) - replaced
##  - X condnumber () is never used - remove it - removed
##  - X robustbase:::r6pack() will not work for p > n, because there is a check svd$rank < p - comment out the check
##  - X using kendal's tau cor.fk from pcaPP - replace by spearman. Later we could move cor.fk() from pcaPP into robustbase
##  - X No SVD if the target matrix is the Identity; if equicorrelation, the eigenvectors are a helmert matrix
##----------------------------------------------------------------

## @title Robust Distance based observation orderings based on robust "Six pack"
## @param x  n x p data matrix
## @param h  integer
## @param full.h full (length n) ordering or only the first h?
## @param scaled is 'x' is already scaled?  otherwise, apply doScale(x, median, scalefn)
## @param scalefn function to compute a robust univariate scale.
## @return a h' x 6 matrix of indices from 1:n; if(full.h) h' = n else h' = h
r6pack <- function(x, h, full.h, adjust.eignevalues=TRUE, scaled=TRUE, scalefn=Qn)
{
    ## As the considered initial estimators Sk may have very
    ## inaccurate eigenvalues, we try to 'improve' them by applying
    ## a transformation similar to that used in the OGK algorithm.
    ##
    ## After that compute the corresponding distances, order them and
    ## return the indices
    initset <- function(data, scalefn, P, h)
    {
       stopifnot(length(d <- dim(data)) == 2, length(h) == 1, h >= 1)
       n <- d[1]
       stopifnot(h <= n)
.S$k <- .S$k + 1  # captura: detmrcd.R:65
       lambda <- doScale(data %*% P, center=median, scale=scalefn)$scale
.cap("is_proj", data %*% P, k=.S$k, it=NULL, src="detmrcd.R:70", d="proyeccion data %*% P (n x p) del conjunto k", grande=FALSE)  # captura: detmrcd.R:70
.cap("is_lambda", lambda, k=.S$k, it=NULL, src="detmrcd.R:70", d="escalas lambda de doScale(data %*% P) (p)", grande=FALSE)  # captura: detmrcd.R:70
       sqrtcov    <- P %*% (lambda * t(P)) ## == P %*% diag(lambda) %*% t(P)
.cap("is_sqrtcov", sqrtcov, k=.S$k, it=NULL, src="detmrcd.R:71", d="P %*% (lambda * t(P)) (p x p)", grande=FALSE)  # captura: detmrcd.R:71
       sqrtinvcov <- P %*% (t(P) / lambda) ## == P %*% diag(1/lambda) %*% t(P)
.cap("is_sqrtinvcov", sqrtinvcov, k=.S$k, it=NULL, src="detmrcd.R:72", d="P %*% (t(P)/lambda) (p x p)", grande=FALSE)  # captura: detmrcd.R:72
	   estloc <- colMedians(data %*% sqrtinvcov) %*% sqrtcov
.cap("is_colmed", colMedians(data %*% sqrtinvcov), k=.S$k, it=NULL, src="detmrcd.R:73", d="colMedians(data %*% sqrtinvcov) (p)", grande=FALSE)  # captura: detmrcd.R:73
.cap("is_estloc", estloc, k=.S$k, it=NULL, src="detmrcd.R:73", d="estloc = colMedians(.) %*% sqrtcov (p)", grande=FALSE)  # captura: detmrcd.R:73
       centeredx <- (data - rep(estloc, each=n)) %*% P
.cap("is_centeredx", centeredx, k=.S$k, it=NULL, src="detmrcd.R:74", d="(data - estloc) %*% P (n x p)", grande=FALSE)  # captura: detmrcd.R:74
.cap("is_dist", mahalanobisD(centeredx, FALSE, lambda), k=.S$k, it=NULL, src="detmrcd.R:75", d="distancias mahalanobisD (n)", grande=FALSE)  # captura: detmrcd.R:75
.cap("is_ord", sort.list(mahalanobisD(centeredx, FALSE, lambda))[1:h], k=.S$k, it=NULL, src="detmrcd.R:75", d="primeras h posiciones del orden de distancias, base 1 (h)", grande=FALSE)  # captura: detmrcd.R:75
	   sort.list(mahalanobisD(centeredx, FALSE, lambda))[1:h]# , partial = 1:h
    }

    ##
    ##  Compute the raw OGK estimator. For m(.) and s(.) (robust
    ##  univariate estimators of location and scale) use the median
    ##  and Qn for reasons of simplicity (no choice of tuning parameters)
    ##  and to be consistent with the other components of DetMCD.
    ##
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
            ## also set the upper triangle
            U[ii,i] <- U[i,ii]
        }
.cap("r6_U", U, k=NULL, it=NULL, src="detmrcd.R:97-101", d="matriz U de ogkscatter completa antes de eigen (p x p)", grande=FALSE)  # captura: detmrcd.R:97-101

        ## now done above: U <- lower.tri(U) * U + t(U)    #    U <- tril(U, -1) + t(U)
        P <- eigen(U, symmetric=TRUE)$vectors
.cap("r6_ev6", eigen(U, symmetric=TRUE)$values, k=NULL, it=NULL, src="detmrcd.R:101", d="autovalores de U (p)", grande=FALSE)  # captura: detmrcd.R:101
    	if(only.P)
    	    return(P)

        ## else :
        Z <- Y %*% t(P)
        sigz <- apply(Z, 2, scalefn)
        lambda <- diag(sigz^2)

        list(P=P, lambda=lambda)
    }

    stopifnot(length(dx <- dim(x)) == 2)
    n <- dx[1]
    p <- dx[2]

    ## If scalefn is missing or is NULL, use Qn for smaller data sets (n < 1000)
    ## and tau-scale of Yohai and Zamar (1988) otherwise.
    ## scalefn <- robustbase:::robScalefn(scalefn, n)

    ## If the data was not scaled already (scaled=FALSE), center and scale using
    ## the median and the provided function 'scalefn'.
    if(!scaled) { ## Center and scale the data to (0, 1) - robustly
.cap("r6_center", doScale(x, center=median, scale=scalefn)$center, k=NULL, it=NULL, src="detmrcd.R:124", d="centros de doScale (p)", grande=FALSE)  # captura: detmrcd.R:124
.cap("r6_scale", doScale(x, center=median, scale=scalefn)$scale, k=NULL, it=NULL, src="detmrcd.R:124", d="escalas Qn de doScale tras centrar (p)", grande=FALSE)  # captura: detmrcd.R:124
        x <- doScale(x, center=median, scale=scalefn)$x
.cap("r6_x", x, k=NULL, it=NULL, src="detmrcd.R:124", d="x tras doScale (n x p)", grande=FALSE)  # captura: detmrcd.R:124
    }

    nsets <- 6
    hsets <- matrix(integer(), h, nsets)

    ## Determine 6 initial estimates (ordering of obs)
    ## 1. Hyperbolic tangent of standardized data
    y1 <- tanh(x)
.cap("r6_y1", y1, k=NULL, it=NULL, src="detmrcd.R:132", d="tanh(x) (n x p)", grande=FALSE)  # captura: detmrcd.R:132
    R1 <- cor(y1)
.cap("r6_R1", R1, k=NULL, it=NULL, src="detmrcd.R:133", d="cor(y1) (p x p)", grande=FALSE)  # captura: detmrcd.R:133
    P <- eigen(R1, symmetric=TRUE)$vectors
.cap("r6_P1", P, k=NULL, it=NULL, src="detmrcd.R:134", d="autovectores de R1 (p x p, orden decreciente de valores)", grande=FALSE)  # captura: detmrcd.R:134
.cap("r6_ev1", eigen(R1, symmetric=TRUE)$values, k=NULL, it=NULL, src="detmrcd.R:134", d="autovalores de R1 (p)", grande=FALSE)  # captura: detmrcd.R:134
    hsets[,1] <- initset(x, scalefn=scalefn, P=P, h=h)

    ## 2. Spearmann correlation matrix
    R2 <- cor(x, method="spearman")
.cap("r6_rank", apply(x, 2L, rank), k=NULL, it=NULL, src="detmrcd.R:138", d="rangos promedio por columna de x (n x p)", grande=FALSE)  # captura: detmrcd.R:138
.cap("r6_R2", R2, k=NULL, it=NULL, src="detmrcd.R:138", d="cor spearman de x (p x p)", grande=FALSE)  # captura: detmrcd.R:138
    P <- eigen(R2, symmetric=TRUE)$vectors
.cap("r6_P2", P, k=NULL, it=NULL, src="detmrcd.R:139", d="autovectores de R2 (p x p)", grande=FALSE)  # captura: detmrcd.R:139
.cap("r6_ev2", eigen(R2, symmetric=TRUE)$values, k=NULL, it=NULL, src="detmrcd.R:139", d="autovalores de R2 (p)", grande=FALSE)  # captura: detmrcd.R:139
    hsets[,2] <- initset(x, scalefn=scalefn, P=P, h=h)

    ## 3. Tukey normal scores
    y3 <- qnorm((apply(x, 2L, rank) - 1/3)/(n + 1/3))
.cap("r6_y3", y3, k=NULL, it=NULL, src="detmrcd.R:143", d="qnorm((rank-1/3)/(n+1/3)) (n x p)", grande=FALSE)  # captura: detmrcd.R:143
    R3 <- cor(y3, use = "complete.obs")
.cap("r6_R3", R3, k=NULL, it=NULL, src="detmrcd.R:144", d="cor(y3, use=complete.obs) (p x p)", grande=FALSE)  # captura: detmrcd.R:144
    P <- eigen(R3, symmetric=TRUE)$vectors
.cap("r6_P3", P, k=NULL, it=NULL, src="detmrcd.R:145", d="autovectores de R3 (p x p)", grande=FALSE)  # captura: detmrcd.R:145
.cap("r6_ev3", eigen(R3, symmetric=TRUE)$values, k=NULL, it=NULL, src="detmrcd.R:145", d="autovalores de R3 (p)", grande=FALSE)  # captura: detmrcd.R:145
    hsets[,3] <- initset(x, scalefn=scalefn, P=P, h=h)

    ## 4. Spatial sign covariance matrix
    znorm <- sqrt(rowSums(x^2))
.cap("r6_znorm", znorm, k=NULL, it=NULL, src="detmrcd.R:149", d="norma euclidea por fila de x (n)", grande=FALSE)  # captura: detmrcd.R:149
    ii <- znorm > .Machine$double.eps
    x.nrmd <- x
    x.nrmd[ii,] <- x[ii, ] / znorm[ii]
.cap("r6_xnrmd", x.nrmd, k=NULL, it=NULL, src="detmrcd.R:152", d="x con filas normalizadas (n x p)", grande=FALSE)  # captura: detmrcd.R:152
    SCM <- crossprod(x.nrmd)# / (n-1) not needed for e.vectors
.cap("r6_SCM", SCM, k=NULL, it=NULL, src="detmrcd.R:153", d="crossprod(x.nrmd) (p x p)", grande=FALSE)  # captura: detmrcd.R:153
    P <- eigen(SCM, symmetric=TRUE)$vectors
.cap("r6_P4", P, k=NULL, it=NULL, src="detmrcd.R:154", d="autovectores de SCM (p x p)", grande=FALSE)  # captura: detmrcd.R:154
.cap("r6_ev4", eigen(SCM, symmetric=TRUE)$values, k=NULL, it=NULL, src="detmrcd.R:154", d="autovalores de SCM (p)", grande=FALSE)  # captura: detmrcd.R:154
    hsets[,4] <- initset(x, scalefn=scalefn, P=P, h=h)

    ## 5. BACON
    ind5 <- order(znorm)
.cap("r6_ind5", ind5, k=NULL, it=NULL, src="detmrcd.R:158", d="order(znorm), base 1 (n)", grande=FALSE)  # captura: detmrcd.R:158
    half <- ceiling(n/2)
    Hinit <- ind5[1:half]
.cap("r6_Hinit", Hinit, k=NULL, it=NULL, src="detmrcd.R:160", d="primeras ceil(n/2) filas de ind5, base 1", grande=FALSE)  # captura: detmrcd.R:160
    covx <- cov(x[Hinit, , drop=FALSE])
.cap("r6_covx", covx, k=NULL, it=NULL, src="detmrcd.R:161", d="cov(x[Hinit,]) (p x p)", grande=FALSE)  # captura: detmrcd.R:161
    P <- eigen(covx, symmetric=TRUE)$vectors
.cap("r6_P5", P, k=NULL, it=NULL, src="detmrcd.R:162", d="autovectores de covx (p x p)", grande=FALSE)  # captura: detmrcd.R:162
.cap("r6_ev5", eigen(covx, symmetric=TRUE)$values, k=NULL, it=NULL, src="detmrcd.R:162", d="autovalores de covx (p)", grande=FALSE)  # captura: detmrcd.R:162
    hsets[,5] <- initset(x, scalefn=scalefn, P=P, h=h)

    ## 6. Raw OGK estimate for scatter
    P <- ogkscatter(x, scalefn, only.P=TRUE)
.cap("r6_P6", P, k=NULL, it=NULL, src="detmrcd.R:166", d="autovectores de U (p x p)", grande=FALSE)  # captura: detmrcd.R:166
    hsets[,6] <- initset(x, scalefn=scalefn, P=P, h=h)

    ## VT::15.11.2019
    ##  No need of the code below in MRCD.
    ##  Instead of computing md and sorting, just return hsets.
    ##
    if(!adjust.eignevalues)
        return (hsets)

    ## Now combine the six pack :
    if(full.h) hsetsN <- matrix(integer(), n, nsets)
    for(k in 1:nsets) ## sort each of the h-subsets in *increasing* Mah.distances
    {
        xk <- x[hsets[,k], , drop=FALSE]
	    svd <- classPC(xk, signflip=FALSE) # [P,T,L,r,centerX,meanvct] = classSVD(xk)

        ## VT::15.10.2018 - we do not need this check, because we are using r6pack
        ##  also for MRCD. Comment it out , maybe should move it to detmcd: FIXME
        ##  if(svd$rank < p) ## FIXME: " return("exactfit")  "
        ##      stop('More than half of the observations lie on a hyperplane.')

        score <- (x - rep(svd$center, each=n)) %*% svd$loadings
        ord <- order(mahalanobisD(score, FALSE, sqrt(abs(svd$eigenvalues))))
        if(full.h)
            hsetsN[,k] <- ord
        else hsets[,k] <- ord[1:h]
    }

    ## return
    if(full.h) hsetsN else hsets
}

# Return target correlation matrix with given structure
# input:
#   mX: the p by n matrix of the data
#   target: structure of the robust positive definite target matrix (default=1)
#           0: identity matrix
#           1: non-diagonal matrix with an equicorrelation structure (see (17) in paper)
# output:
#   the target correlation matrix
.TargetCorr <- function(mX, target=1, mindet=0)
{
    p <- dim(mX)[1]
    I <- diag(1, p)

    if(target == 0){
        R <- I
    } else if(target == 1) {
##        cortmp <- cor.fk(t(mX))                   # from pcaPP
##        cortmp <- cor(t(mX), method="kendal")     # very slow
        cortmp <- cor(t(mX), method="spearman")
.cap("tgt_cortmp_rank", cortmp, k=NULL, it=NULL, src="detmrcd.R:217", d="cor(t(mX), method=spearman) (p x p); solo target=1", grande=FALSE)  # captura: detmrcd.R:217
        cortmp <- sin(1/2 * pi * cortmp)
.cap("tgt_cortmp_sin", cortmp, k=NULL, it=NULL, src="detmrcd.R:218", d="sin(1/2*pi*cortmp) (p x p); solo target=1", grande=FALSE)  # captura: detmrcd.R:218
        constcor <- mean(cortmp[upper.tri(cortmp, diag=FALSE)])

        # KB: add bound to ensure positive definiteness; see paper page 7, below (17)
        if(constcor <= min(c(0, (-1/(p-1) + 0.01)))){
            constcor <-  min(c(0,(-1/(p-1) + 0.01)))
        }
.cap("tgt_constcor", constcor, k=NULL, it=NULL, src="detmrcd.R:224", d="constcor tras la cota inferior; solo target=1", grande=FALSE)  # captura: detmrcd.R:224
        J <- matrix(1, p, p)
        R <- constcor * J + (1-constcor) * I
.cap("tgt_R", R, k=NULL, it=NULL, src="detmrcd.R:226", d="matriz objetivo equicorrelacion R (p x p); solo target=1", grande=FALSE)  # captura: detmrcd.R:226
    }
    return(R)
}

eigenEQ <- function(T)
{
    rho <- T[1,2]
    d <- ncol(T)

    helmert <- matrix(0, nrow=d, ncol=d)
    helmert[, 1] <- rep(1/sqrt(d), d)
    for(j in 2:ncol(helmert))
    {
        helmert[1:(j-1), j] <- 1/sqrt(j*(j-1))
        helmert[j, j] <- -(j-1)/sqrt(j*(j-1))
    }

    out <- NULL
    out$values <- c(1 + (d-1)*rho, rep(1-rho, d-1))
    out$vectors <- helmert
    out
}

# compute the regularized covariance
# input:
#   XX, the p by n (or h) matrix of the data (not necessarily demeaned)
#   vMu: the initial mean (p-vector)
#   rho: the regularization parameter
#   mT: the target matrix
#   scfac: the scaling factor
#   bcd: diagonal matrix used for rescaling (ratio of scales of target and mcd component)
#   target: structure of the robust positive definite target matrix (default=1)
#           0: identity matrix
#           1: non-diagonal matrix with an equicorrelation structure (see (17) in paper)
#   invert: if true, gives also inverted regularized covariance
#
# output (a list):
#   rho: the regularization parameter
#   mT: the target matrix
#   cov: the covariance matrix based on subset (without regularization step)
#   rcov: the regularized covariance matrix
#   inv_rcov: the inverse of the regularized covariance matrix (if invert=True)
.RCOV <- function(XX, vMu, rho=NULL, mT, scfac, target=1, invert=FALSE)
{
    mE <- XX-vMu
    n <- dim(mE)[2]
    p <- dim(mE)[1]
    mS <- mE %*% t(mE)/n
    rcov <- rho * mT + (1-rho) * scfac * mS

    if(invert) {
        if(p > n) {
          nu <- (1-rho) * scfac
          mU <- mE/sqrt(n)
          inv_rcov <- .InvSMW(rho=rho, mT=mT, nu=nu, mU=mU)
        }else {
          inv_rcov = chol2inv(chol(rcov))
        }
        return(list(rho=rho, mT=mT, cov=mS, rcov=rcov, inv_rcov=inv_rcov))
    }
    else
        return(list(rho=rho, mT=mT, cov=mS, rcov=rcov))

}

##  Compute inverse of covariance matrix using Sherman-Morrison-Woodbury
##  identity when dimension is larger than sample size
#
# input:
#   rho: the regularization parameter
#   mT: the target matrix
#	nu: the scaling factor multiplied with (1-rho)
#   mU: the scaled data
# output:
#	  the inverse of the covariance matrix
.InvSMW <- function(rho, mT, nu, mU)
{
    p = dim(mT)[1]
    pp = dim(mU)
    vD = sqrt(diag(mT))
    imD = diag(vD^(-1))
    R = imD %*% mT %*% imD
    constcor = R[2, 1]
    I = diag(1, p)
    J = matrix(1, p, p)
    imR = 1/(1-constcor) * (I - constcor/(1 + (p-1) * constcor) * J)
    imB = (rho)^(-1) * imD %*% imR %*% imD
    Temp <- base::chol2inv(base::chol(diag(pp[2]) + nu * (t(mU) %*% (imB %*% mU))))
.cap("smw_G", t(mU) %*% (imB %*% mU), k=NULL, it=NULL, src="detmrcd.R:314", d="G = t(mU) %*% (imB %*% mU) (h x h) dentro de .InvSMW", grande=FALSE)  # captura: detmrcd.R:314
.cap("smw_Temp", Temp, k=NULL, it=NULL, src="detmrcd.R:314", d="chol2inv(chol(I + nu*G)) (h x h) dentro de .InvSMW", grande=FALSE)  # captura: detmrcd.R:314

    return(imB - (imB%*%mU) %*% (nu * Temp) %*% (t(mU)%*%imB))
}

# Apply generalized C-steps to obtain optimal subset
# input:
#   mX: the p by T matrix of the residuals or data, not necessarily demeaned
#   rho: the regularization parameter
#   mT: the target matrix
#   target: structure of the robust positive definite target matrix (default=1)
#           0: identity matrix
#           1: non-diagonal matrix with an equicorrelation structure (see (17) in paper)
#   vMu: the initial mean (as vector)
#   mIS: the p by p matrix of the initial inverted covariance
#   h: the size of the subset OR alpha: the proportion of the contamination
#   maxcsteps: the maximal number of iteration of the C-step algorithm
#   index: the initial subset H_0
# output (a list)
#   index: the optimal h-subset
#   numit: the number of iterations
#   mu: the vector with means
#   cov: the regularized covariance estimate
#   icov: the inverse of the regularized covariance matrix
#   rho: the regularization parameter
#   mT: the target matrix
#   dist: the Mahalanobis distances using the MRCD estimates
#   scfac: the scaling factor
.cstep_mrcd <- function(mX, rho=NULL, mT=NULL, target=1, vMu=NULL, mIS=NULL, h, scfac, index=NULL, maxcsteps=50)
{
    n <- dim(mX)[2]
    p <- dim(mX)[1]

    # random choice
    if(is.null(index))
        index <- sample(1:n, h) # if no index is given we sample one...
    XX <- mX[, index] # p x h
.cap("cs_index", index, k=.S$kcur, it=0, src="detmrcd.R:350", d="indice h usado en la iteracion (base 1, h)", grande=FALSE)  # captura: detmrcd.R:350
.S$it <- 0  # captura: detmrcd.R:350

    if(is.null(vMu))
        vMu = rowMeans(XX)

    if(is.null(mIS)){
        ret = .RCOV(XX=XX, vMu=vMu, rho=rho, mT=mT, scfac=scfac, target=target, invert=T)
        mIS = ret$inv_rcov
    }

    vdst = diag(t(mX-vMu) %*% (mIS %*% (mX-vMu))) #vdst = apply(mX-vMu,2,ftmp)
    index = sort(sort.int(vdst, index.return=T)$ix[1:h])
.cap("cs_vMu", vMu, k=.S$kcur, it=0, src="detmrcd.R:361", d="media del subconjunto en el paso t (p)", grande=FALSE)  # captura: detmrcd.R:361
.cap("cs_mS", ret$cov, k=.S$kcur, it=0, src="detmrcd.R:361", d="mS de .RCOV, divisor h (p x p)", grande=TRUE)  # captura: detmrcd.R:361
.cap("cs_rcov", ret$rcov, k=.S$kcur, it=0, src="detmrcd.R:361", d="covarianza regularizada rcov (p x p)", grande=TRUE)  # captura: detmrcd.R:361
.cap("cs_inv", ret$inv_rcov, k=.S$kcur, it=0, src="detmrcd.R:361", d="inversa de rcov (p x p)", grande=TRUE)  # captura: detmrcd.R:361
.cap("cs_vdst", vdst, k=.S$kcur, it=0, src="detmrcd.R:361", d="distancias diag(t(D) %*% (mIS %*% D)) (n)", grande=FALSE)  # captura: detmrcd.R:361
.cap("cs_nndex", index, k=.S$kcur, it=0, src="detmrcd.R:361", d="nuevo indice sort(order(vdst)[1:h]) (base 1, h)", grande=FALSE)  # captura: detmrcd.R:361

    iter = 1

    while(iter < maxcsteps){
        XX <- mX[,index]
.S$it <- iter  # captura: detmrcd.R:366
.cap("cs_index", index, k=.S$kcur, it=iter, src="detmrcd.R:366", d="indice h usado en la iteracion (base 1, h)", grande=FALSE)  # captura: detmrcd.R:366
        vMu <- rowMeans(XX)
        ret <- .RCOV(XX=XX, vMu=vMu, rho=rho, mT=mT, target=target, scfac=scfac, invert=T)
        mIS <- ret$inv_rcov

        vdst <- diag(t(mX-vMu) %*% (mIS %*% (mX-vMu)))
        nndex <- sort(sort.int(vdst,index.return=T)$ix[1:h])
.cap("cs_vMu", vMu, k=.S$kcur, it=iter, src="detmrcd.R:372", d="media del subconjunto en el paso t (p)", grande=FALSE)  # captura: detmrcd.R:372
.cap("cs_mS", ret$cov, k=.S$kcur, it=iter, src="detmrcd.R:372", d="mS de .RCOV, divisor h (p x p)", grande=TRUE)  # captura: detmrcd.R:372
.cap("cs_rcov", ret$rcov, k=.S$kcur, it=iter, src="detmrcd.R:372", d="covarianza regularizada rcov (p x p)", grande=TRUE)  # captura: detmrcd.R:372
.cap("cs_inv", ret$inv_rcov, k=.S$kcur, it=iter, src="detmrcd.R:372", d="inversa de rcov (p x p)", grande=TRUE)  # captura: detmrcd.R:372
.cap("cs_vdst", vdst, k=.S$kcur, it=iter, src="detmrcd.R:372", d="distancias (n)", grande=FALSE)  # captura: detmrcd.R:372
.cap("cs_nndex", nndex, k=.S$kcur, it=iter, src="detmrcd.R:372", d="nuevo indice (base 1, h)", grande=FALSE)  # captura: detmrcd.R:372

        if(all(nndex == index))
            break

        index <- nndex
        iter <- iter+1
    }

    return(list(index=index, numit=iter, mu=vMu, cov=ret$rcov,
              icov=ret$inv_rcov, rho=ret$rho, mT=ret$mT, dist=vdst, scfac=scfac))
}

    mX <- t(x)          # we want the transposed data matrix

    ## several parametrs which we do not want toexpose to the user.
    mindet <- 0         # minimum determinant allowed for target matrix
    objective <- "geom" # objective function to determine optimal subset, see (3) in paper
                        # 'det': typically one minimizes the determinant of the sample covariance based on the subset
                        # 'geom': p-th root of determinant or standardized generalized variance (for numerical reasons)

    n <- dim(mX)[2]
    p <- dim(mX)[1]

    if(!is.null(h))          alpha <- h/n
    else if(!is.null(alpha)) h <- ceiling(alpha*n)
    else
        stop("Either 'h' (number of observations in a subset) or 'alpha' (proportion of observations) has to be supplied!")
    if(alpha < 1/2 | alpha > 1)
        stop("'alpha' must be between 0.5 and 1.0!")

    ## VT::21.04.2021 - h has to be an integer (a non-integer h will break the sprintf at the end).
    h <- as.integer(h)
.cap("pre_n", n, k=NULL, it=NULL, src="detmrcd.R:404", d="numero de observaciones", grande=FALSE)  # captura: detmrcd.R:404
.cap("pre_p", p, k=NULL, it=NULL, src="detmrcd.R:404", d="numero de variables", grande=FALSE)  # captura: detmrcd.R:404
.cap("pre_h", h, k=NULL, it=NULL, src="detmrcd.R:404", d="tamano del subconjunto h", grande=FALSE)  # captura: detmrcd.R:404
.cap("pre_alpha", alpha, k=NULL, it=NULL, src="detmrcd.R:404", d="alpha efectivo", grande=FALSE)  # captura: detmrcd.R:404

    # choose objective function to determine optimal subset
    if (objective == 'det'){
        obj <- function(x) det(x)
    }else if (objective == 'geom'){
        obj <- function(x)
        {
            det(x)^(1/p)
        } #geometric mean of eigenvalues
    }

    ## 1. Standardize the p variables: compute standardized observations u_i, see (6) in paper, using median and Qn estimator
    vmx <- apply(mX, 1, median)
.cap("std_vmx", vmx, k=NULL, it=NULL, src="detmrcd.R:417", d="medianas por variable (apply median sobre mX p x n)", grande=FALSE)  # captura: detmrcd.R:417
    vsd <- apply(mX, 1, Qn)
.cap("std_vsd_raw", vsd, k=NULL, it=NULL, src="detmrcd.R:418", d="Qn por variable antes de minscale", grande=FALSE)  # captura: detmrcd.R:418
    vsd[vsd < minscale] <- minscale
.cap("std_vsd", vsd, k=NULL, it=NULL, src="detmrcd.R:419", d="Qn por variable tras vsd[vsd<minscale]<-minscale", grande=FALSE)  # captura: detmrcd.R:419
    Dx <- diag(vsd)
    mU <- scale(t(mX), center=vmx, scale=vsd)
.cap("std_mU", mU, k=NULL, it=NULL, src="detmrcd.R:421", d="datos estandarizados scale(t(mX), vmx, vsd) (n x p)", grande=FALSE)  # captura: detmrcd.R:421
    mX <- t(mU)
    mT <- .TargetCorr(mX, target=target, mindet=mindet)

    ## 2. Perform singular value decomposition of target matrix and compute observations w_i
    if(target == 1){
        mTeigen <- eigenEQ(mT)
        mQ <- mTeigen$vectors
        mL <- diag(mTeigen$values)
        msqL <- diag(sqrt(mTeigen$values))
        misqL <- diag(sqrt(mTeigen$values)^(-1))
        mW <- mU %*% mQ %*% misqL
.cap("eq_values", mTeigen$values, k=NULL, it=NULL, src="detmrcd.R:432", d="valores propios de eigenEQ (p); solo target=1", grande=FALSE)  # captura: detmrcd.R:432
.cap("eq_mQ", mQ, k=NULL, it=NULL, src="detmrcd.R:432", d="matriz de Helmert mQ (p x p); solo target=1", grande=FALSE)  # captura: detmrcd.R:432
.cap("eq_mW", mW, k=NULL, it=NULL, src="detmrcd.R:432", d="mU %*% mQ %*% misqL (n x p); solo target=1", grande=FALSE)  # captura: detmrcd.R:432
        mX <- t(mW)
    }

    mT = diag(p)

    ## 3.1-3.2 Follow Hubert et al. (2012) to obtain 6 initial
    ##      scatter matrices (if scatter matrix is not invertible,
    ##      use its regularized version)
    ## 3.3 Determine subsets with lowest Mahalanobis distance

    ## Assume that 'hsets.init' already contains h-subsets: the first h observations each
    ## VT::15.11.2019 - added adjust.eignevalues=FALSE, this will set automatically full.h=FALSE
    if(is.null(hsets.init)) {
	   hsets.init <- r6pack(x=t(mX), h=h, full.h=FALSE, adjust.eignevalues=FALSE, scaled=FALSE, scalefn=Qn)
	   dh <- dim(hsets.init)
    } else { ## user specified, (even just *one* vector):
	   if(is.vector(hsets.init)) hsets.init <- as.matrix(hsets.init)
	   dh <- dim(hsets.init)
	   if(dh[1] < h || dh[2] < 1)
	       stop("'hsets.init' must be a  h' x L  matrix (h' >= h) of observation indices")
	   if(full.h && dh[1] != n)
	       warning("'full.h' is true, but 'hsets.init' has less than n rows")
	   if(min(hsets.init) < 1 || max(hsets.init) > n)
	       stop("'hsets.init' must be in {1,2,...,n}; n = ", n)
    }

    hsets.init <- hsets.init[1:h, ]
.cap("hs_init", hsets.init, k=NULL, it=NULL, src="detmrcd.R:459", d="subconjuntos iniciales hsets.init[1:h,] (h x 6), base 1, orden de distancia", grande=FALSE)  # captura: detmrcd.R:459
    scfac <- robustbase::.MCDcons(p, h/n)           # for consistency with MCD
.cap("scfac", scfac, k=NULL, it=NULL, src="detmrcd.R:460", d=".MCDcons(p, h/n)", grande=FALSE)  # captura: detmrcd.R:460
.cap("scfac_q", qchisq(h/n, p), k=NULL, it=NULL, src="detmrcd.R:460 (covMcd.R:604)", d="qchisq(h/n, p) (covMcd.R:604)", grande=FALSE)  # captura: detmrcd.R:460 (covMcd.R:604)
.cap("scfac_pg", pgamma(qchisq(h/n, p)/2, p/2 + 1), k=NULL, it=NULL, src="detmrcd.R:460 (covMcd.R:605)", d="pgamma(q/2, p/2+1) (covMcd.R:605)", grande=FALSE)  # captura: detmrcd.R:460 (covMcd.R:605)

    ## 3.4 Determine smallest value of rho_i for each subset
    rho6pack <- condnr <- c()
    nsets <- ncol(hsets.init)
    if(is.null(rho)) {
        for(k in 1:nsets){
            mXsubset <- mX[ , hsets.init[, k]]
            vMusubset <- rowMeans(mXsubset)
.cap("rs_mu", vMusubset, k=k, it=NULL, src="detmrcd.R:468", d="medias del subconjunto k (p)", grande=FALSE)  # captura: detmrcd.R:468
            mE <- mXsubset-vMusubset
            mS <- mE%*%t(mE)/(h-1)
.cap("rs_mS", mS, k=k, it=NULL, src="detmrcd.R:470", d="mE %*% t(mE)/(h-1) (p x p)", grande=FALSE)  # captura: detmrcd.R:470

            if(all(mT == diag(p))) {
                veigen <- eigen(scfac * mS)$values
                e1 <- min(veigen)
                ep <- max(veigen)
.cap("rs_veigen", veigen, k=k, it=NULL, src="detmrcd.R:475", d="autovalores eigen(scfac*mS) (p)", grande=FALSE)  # captura: detmrcd.R:475
.cap("rs_e1", e1, k=k, it=NULL, src="detmrcd.R:475", d="minimo autovalor", grande=FALSE)  # captura: detmrcd.R:475
.cap("rs_ep", ep, k=k, it=NULL, src="detmrcd.R:475", d="maximo autovalor", grande=FALSE)  # captura: detmrcd.R:475

                ##  cat("\ncase T=I: ", k, e1, ep)

                fncond <- function(rho)
                {
                    condnr <-  (rho + (1-rho) * ep) / (rho + (1-rho) * e1)
                    ##  cat("\n ...... condnr: ", condnr, condnr-maxcond, "\n")
                    return(condnr - maxcond)
                }
            } else {
                fncond <- function(rho)
                {
                    rcov <- rho*mT + (1-rho) * scfac * mS
                    temp <- eigen(rcov)$values
                    condnr <- max(temp) / min(temp)
                    return(condnr - maxcond)
                }
            }

            out <- try(uniroot(f=fncond, lower=0.00001, upper=0.99), silent=TRUE)
.cap_uniroot(out, fncond, k)  # captura: detmrcd.R:495-511

            ## VT::11.08.2022: fix error "Found if() conditions comparing class() to string"
            ##  if(class(out) != "try-error") {
            if(!is(out, "try-error")) {
                rho6pack[k] <- out$root
                ##  cat("\nOK: ", k, out$root, "\n")
            }else {
                grid <- c(0.000001, seq(0.001, 0.99, by=0.001), 0.999999)
                if(all(mT == diag(p))) {
                    objgrid <- abs(fncond(grid))
                    irho <- min(grid[objgrid == min(objgrid)])
.cap("rs_irho", irho, k=k, it=NULL, src="detmrcd.R:506", d="rho de la rejilla (solo si uniroot fallo)", grande=FALSE)  # captura: detmrcd.R:506
                }else {
                    objgrid <- abs(apply(as.matrix(grid), 1, "fncond"))
                    irho <- min(grid[objgrid == min(objgrid)])
                }
                rho6pack[k] <- irho
                ##  cat("\nNOT OK: ", k, irho, "\n")

            }
.cap("rs_rhok", rho6pack[k], k=k, it=NULL, src="detmrcd.R:500/511", d="rho_k elegido para el subconjunto k", grande=FALSE)  # captura: detmrcd.R:500/511
        }

        ## 3.5 Set rho as max of the rho_i's obtained for each subset in previous step
        cutoffrho <- max(c(0.1, median(rho6pack)))
.cap("rs_rho6", rho6pack, k=NULL, it=NULL, src="detmrcd.R:518", d="rho_k de los 6 subconjuntos (6)", grande=FALSE)  # captura: detmrcd.R:518
.cap("rs_cutoff", cutoffrho, k=NULL, it=NULL, src="detmrcd.R:518", d="max(0.1, median(rho6))", grande=FALSE)  # captura: detmrcd.R:518
        rho <- max(rho6pack[rho6pack <= cutoffrho])
.cap("rs_rho", rho, k=NULL, it=NULL, src="detmrcd.R:519", d="rho global = max(rho6[rho6<=cutoff])", grande=FALSE)  # captura: detmrcd.R:519

        if(trace) {
            cat("\nSet rho as max of the rho_i obtained for each subset in previous step.")
            cat("\nrho, cutoffrho=", rho, cutoffrho, "\n")
            print(rho6pack)
        }

        Vselection <- seq(1, nsets)
        Vselection[rho6pack > cutoffrho] = NA
.cap("rs_Vsel", Vselection, k=NULL, it=NULL, src="detmrcd.R:528", d="Vselection (6), NA como -1", grande=FALSE)  # captura: detmrcd.R:528
        if(sum(!is.na(Vselection)) == 0){
            stop("None of the initial subsets is well-conditioned")
        }

        initV <- min(Vselection, na.rm=TRUE)
.cap("rs_initV", initV, k=NULL, it=NULL, src="detmrcd.R:533", d="subconjunto inicial initV (base 1)", grande=FALSE)  # captura: detmrcd.R:533
        setsV <- Vselection[!is.na(Vselection)]
        setsV <- setsV[-1]
.cap("rs_setsV", setsV, k=NULL, it=NULL, src="detmrcd.R:535", d="subconjuntos restantes setsV (base 1, longitud variable)", grande=FALSE)  # captura: detmrcd.R:535
    }else{
        setsV <- 1:ncol(hsets.init)
        initV <- 1
    }

    ## 3.6 For each of the six initial subsets, repeat the generalized
    ##  C-steps (from Theorem 1) until convergence
    ##
    ## 3.7 Choose final subset that has lowest determinant among the
    ##  ones obtained from the six initial subsets
    hset.csteps <- integer(nsets)
.S$kcur <- initV; .S$ctx <- "cs"  # captura: detmrcd.R:547
    ret <- .cstep_mrcd(mX=mX, rho=rho, mT=mT, target=target, h=h, scfac=scfac, index=hsets.init[, initV], maxcsteps=maxcsteps)
    objret <- obj(ret$cov)
.cap("cs_numit", ret$numit, k=initV, it=NULL, src="detmrcd.R:548", d="iteraciones del C-step del subconjunto inicial", grande=FALSE)  # captura: detmrcd.R:548
.cap("cs_obj", objret, k=initV, it=NULL, src="detmrcd.R:548", d="obj = det(cov)^(1/p)", grande=FALSE)  # captura: detmrcd.R:548
.cap("cs_det", det(ret$cov), k=initV, it=NULL, src="detmrcd.R:548", d="det(cov)", grande=FALSE)  # captura: detmrcd.R:548
    hindex <- ret$index
    best6pack <- initV
    for(k in setsV){
.S$kcur <- k  # captura: detmrcd.R:559
        if(trace) {
            if(trace >= 2)
                cat(sprintf("H-subset %d = observations c(%s):\n-----------\n",
                    k, paste(hsets.init[1:h, k], collapse=", ")))
             else
                cat(sprintf("H-subset %d: ", k))
       }
       tmp <- .cstep_mrcd(mX=mX, rho=rho, mT=mT, target=target, h=h, scfac=scfac, index=hsets.init[,k], maxcsteps=maxcsteps)
        objtmp <- obj(tmp$cov)
        hset.csteps[k] <- tmp$numit
.cap("cs_numit", tmp$numit, k=k, it=NULL, src="detmrcd.R:561", d="iteraciones del C-step", grande=FALSE)  # captura: detmrcd.R:561
.cap("cs_obj", objtmp, k=k, it=NULL, src="detmrcd.R:561", d="obj = det(cov)^(1/p)", grande=FALSE)  # captura: detmrcd.R:561
.cap("cs_det", det(tmp$cov), k=k, it=NULL, src="detmrcd.R:561", d="det(cov)", grande=FALSE)  # captura: detmrcd.R:561
        if(trace)
            cat(sprintf("%3d csteps, obj=log(det|.|)=%g", k, objtmp))
        if(objtmp < objret){
            if(trace)
                cat(" = new optim.\n")
            ret <- tmp
            objret <- objtmp
            hindex <- tmp$index
            best6pack <- k
        } else if(objtmp == objret)     # store as well
            best6pack <- c(best6pack, k)
        else
            if(trace) cat("\n")
    }
.cap("sel_best6pack", best6pack, k=NULL, it=NULL, src="detmrcd.R:575", d="subconjuntos empatados en el optimo (base 1, longitud variable)", grande=FALSE)  # captura: detmrcd.R:575
.cap("sel_hindex", hindex, k=NULL, it=NULL, src="detmrcd.R:575", d="indice h final (base 1)", grande=FALSE)  # captura: detmrcd.R:575
.cap("sel_n_csteps", hset.csteps, k=NULL, it=NULL, src="detmrcd.R:575", d="numit por subconjunto (6; 0 en initV)", grande=FALSE)  # captura: detmrcd.R:575

.S$ctx <- "fin"  # captura: detmrcd.R:577
    c_alpha <- ret$scfac #scaling factor
    mE <- mX[, hindex] - ret$mu
.cap("fin_mE", mE, k=NULL, it=NULL, src="detmrcd.R:578", d="mX[,hindex] - ret$mu (p x h)", grande=FALSE)  # captura: detmrcd.R:578
    weightedScov <-  mE %*% t(mE)/(h-1)
.cap("fin_W", weightedScov, k=NULL, it=NULL, src="detmrcd.R:579", d="mE %*% t(mE)/(h-1) (p x p)", grande=FALSE)  # captura: detmrcd.R:579
    D  <- c_alpha * diag(1, p)

    ## MRCD estimates of the standardized data W (inner part of (12) in paper)
    MRCDmu = rowMeans(mX[,hindex])
.cap("fin_mu_std", MRCDmu, k=NULL, it=NULL, src="detmrcd.R:583", d="rowMeans(mX[,hindex]) (p)", grande=FALSE)  # captura: detmrcd.R:583
    MRCDcov = rho*mT + (1-rho) * c_alpha * weightedScov
.cap("fin_cov_std", MRCDcov, k=NULL, it=NULL, src="detmrcd.R:584", d="rho*I + (1-rho)*c_alpha*W (p x p), espacio estandarizado", grande=FALSE)  # captura: detmrcd.R:584

    ## Computing inverse of scaled covariance matrix, using SMW identity
    ##      if data is fat (inner part of (14) and (15) in paper).
    if(p > n & target <= 1){    # !!!! formula InvSMW  is used when T is equicorrelation
        nu <- (1-rho) * c_alpha
        mU <- mE/sqrt(h-1)
        iMRCDcov <- .InvSMW(rho=rho, mT=mT, nu=nu, mU=mU)
    }else
        iMRCDcov <- chol2inv(chol(MRCDcov))
.cap("fin_icov_std", iMRCDcov, k=NULL, it=NULL, src="detmrcd.R:588-593", d="inversa (SMW o chol2inv) en espacio estandarizado (p x p)", grande=FALSE)  # captura: detmrcd.R:588-593

    ## Backtransforming the rescaling steps that we applied in
    ##  the beginning (outer part of (11) and (12) in paper)

    # transformations due to SVD on target matrix
    if(target == 1) {
        ##VT::12.12 - corrected the restoration of X after SVD transformation
        mX <- t(t(mX) %*% msqL %*% t(mQ))
##        mX <- t(t(mX) %*% mQ %*% msqL)
        MRCDmu <- mQ %*% msqL %*% MRCDmu
        MRCDcov <- mQ %*% msqL %*% MRCDcov %*% msqL %*% t(mQ)
        iMRCDcov <- mQ %*% misqL %*% iMRCDcov %*% misqL %*% t(mQ)
        mT <- mQ %*% msqL %*% mT %*% msqL %*% t(mQ)
    }

    # transformations due to rescaling median and Qn
    mX <- t(t(mX) %*% Dx) + vmx
    MRCDmu <- Dx %*% MRCDmu + vmx
    MRCDcov <- Dx %*% MRCDcov %*% Dx
    mT <- Dx %*% mT %*% Dx
    iDx <- diag(1/diag(Dx))
    iMRCDcov <- iDx %*% iMRCDcov %*% iDx
.cap("fin_center", as.numeric(MRCDmu), k=NULL, it=NULL, src="detmrcd.R:615", d="centro final tras retro-transformacion (p)", grande=FALSE)  # captura: detmrcd.R:615
.cap("fin_cov", MRCDcov, k=NULL, it=NULL, src="detmrcd.R:615", d="covarianza final (p x p)", grande=FALSE)  # captura: detmrcd.R:615
.cap("fin_icov", iMRCDcov, k=NULL, it=NULL, src="detmrcd.R:615", d="inversa final (p x p)", grande=FALSE)  # captura: detmrcd.R:615
.cap("fin_target", mT, k=NULL, it=NULL, src="detmrcd.R:615", d="target final retro-transformado (p x p)", grande=FALSE)  # captura: detmrcd.R:615

    ## Compute the Mahalanobis distances based on MRCD estimates
    dist <- mahalanobis(t(mX), center=MRCDmu, cov=iMRCDcov, inverted=TRUE)
.cap("fin_dist_detmrcd", dist, k=NULL, it=NULL, src="detmrcd.R:618", d="distancias mahalanobis internas de .detmrcd (NO usadas por CovMrcd) (n)", grande=FALSE)  # captura: detmrcd.R:618
    objret <- determinant(MRCDcov)$modulus[1]
.cap("fin_crit", objret, k=NULL, it=NULL, src="detmrcd.R:619", d="determinant(MRCDcov)$modulus (log-det)", grande=FALSE)  # captura: detmrcd.R:619

    ret <- list(alpha=alpha, h=h,
              initmean=as.numeric(MRCDmu),
              initcovariance=MRCDcov,
              icov=iMRCDcov,
              rho=rho,
              best=hindex,
              mcdestimate=objret,
              mah=dist,
              target=mT,
              iBest = best6pack,
              n.csteps=hset.csteps,
              initHsets=if(save.hsets) hsets.init,
              calpha=c_alpha
            )
.cap("out_iBest", best6pack, k=NULL, it=NULL, src="detmrcd.R:634", d="iBest devuelto por .detmrcd (base 1, longitud variable)", grande=FALSE)  # captura: detmrcd.R:634
.cap("out_n_csteps", hset.csteps, k=NULL, it=NULL, src="detmrcd.R:634", d="n.csteps devuelto por .detmrcd (6)", grande=FALSE)  # captura: detmrcd.R:634

    return (ret)
}
## [INSTR] ===== inicio CovMrcd.R (lineas citadas = las del original) =====
CovMrcd <- function(x,
                   alpha=control@alpha,
                   h=control@h,
                   maxcsteps=control@maxcsteps,
                   initHsets=NULL, save.hsets=FALSE,
                   rho=control@rho,
                   target=control@target,
                   maxcond=control@maxcond,
                   trace=control@trace,
                   control=CovControlMrcd())
{
    if(is.data.frame(x))
        x <- data.matrix(x, rownames.force=FALSE)
    else if (!is.matrix(x))
        x <- matrix(x, length(x), 1,
            dimnames = list(names(x), deparse(substitute(x))))

    ## drop all rows with missing values (!!) :
    ok <- is.finite(x %*% rep.int(1, ncol(x)))
.cap("in_ok", ok, k=NULL, it=NULL, src="CovMrcd.R:19", d="filas finitas de x (n0); TRUE/FALSE como 1/0", grande=FALSE)  # captura: CovMrcd.R:19
    x <- x[ok, , drop = FALSE]
.cap("in_x", x, k=NULL, it=NULL, src="CovMrcd.R:20", d="x filtrada (n x p)", grande=FALSE)  # captura: CovMrcd.R:20
    if(!length(dx <- dim(x)))
        stop("All observations have missing values!")
    n <- dx[1]; p <- dx[2]
    dimn <- dimnames(x)

    ## VT::18.07.2022 - maxcond passed to the lowlevel function
    mcd <- .detmrcd (x, alpha=alpha, h=h, hsets.init = initHsets,
		      save.hsets=save.hsets, # full.h=full.h,
		      rho=rho, maxcond=maxcond, target=if(target=="identity") 0 else 1,
              maxcsteps=maxcsteps,
              trace=as.integer(trace))

    alpha <- mcd$alpha
    h <- mcd$h
    ans <- list(call = match.call(), method = sprintf("MRCD(alpha=%g ==> h=%d)", alpha, h))
	ans$method <- paste("Minimum Regularized Covariance Determinant", ans$method)

    ans$cov <- mcd$initcovariance
    ans$center <- as.vector(mcd$initmean)

    ans$n.obs <- n
    ans$best <- sort(as.vector(mcd$best))
    ans$alpha <- alpha
    ans$quan <- h
    ans$crit <- mcd$mcdestimate
    ans$mah <- mahalanobis(x, mcd$initmean, mcd$icov, inverted=TRUE)

	if(length(dimn[[1]]))
	    dimnames(x)[[1]] <- dimn[[1]][ok]
	else
	    dimnames(x) <- list(seq(along = ok)[ok], NULL)

    ans$X <- x
    if(trace)
        cat(ans$method, "\n")

    ans <- c(ans, mcd[c("calpha", "iBest","n.csteps", if(save.hsets) "initHsets", "icov","rho", "target")])
    class(ans) <- "mcd"

    if(!is.null(nms <- dimn[[2]])) {
        dimnames(ans$cov) <- list(nms, nms)
        dimnames(ans$icov) <- list(nms, nms)
        names(ans$center) <- nms
    }

    new("CovMrcd",
        call= ans$call,
        crit=ans$crit,
        cov=ans$cov,
        icov=ans$icov,
        rho=ans$rho,
        target=ans$target,
        center=ans$center,
        n.obs=ans$n.obs,
        mah = ans$mah,
        X = ans$X,
        method=ans$method,
        best=ans$best,
        alpha=ans$alpha,
        quan=ans$quan,
        cnp2 = ans$calpha)
}
