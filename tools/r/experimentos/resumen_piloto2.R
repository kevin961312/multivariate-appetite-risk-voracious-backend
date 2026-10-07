## Resume tools/r/experimentos/resultados/piloto_canonico2.csv en tablas Markdown (informe del piloto 2).
## Uso: Rscript tools/r/experimentos/resumen_piloto2.R [csv]
args <- commandArgs(TRUE)
ruta <- if (length(args)) args[1] else "tools/r/experimentos/resultados/piloto_canonico2.csv"
D <- read.csv(ruta, stringsAsFactors = FALSE)
cfgs <- unique(D[order(D$cfg_id), c("cfg_id", "config")])
f <- function(v, d = 3) formatC(v, digits = d, format = "g")
pct <- function(b) sprintf("%d/%d", sum(b), length(b))
q <- function(v, d = 3) sprintf("%s [%s, %s]", f(median(v), d), f(quantile(v, .05), d), f(quantile(v, .95), d))
mq <- function(v, d = 3) sprintf("%s / %s [%s, %s]", f(mean(v), d), f(median(v), d), f(quantile(v, .05), d), f(quantile(v, .95), d))
tabla <- function(cab, filas) {
  cat("| ", paste(cab, collapse = " | "), " |\n|", paste(rep("---", length(cab)), collapse = "|"), "|\n", sep = "")
  for (r in filas) cat("| ", paste(r, collapse = " | "), " |\n", sep = "")
  cat("\n")
}
por <- function(fun, ids = cfgs$cfg_id) lapply(ids, function(i) { d <- D[D$cfg_id == i, ]; c(d$config[1], fun(d)) })
pn <- cfgs$cfg_id[cfgs$cfg_id %in% unique(D$cfg_id[D$p > D$n])]
signo <- function(dd) { nz <- dd[abs(dd) > 1e-12]; if (!length(nz)) return("—")
  sprintf("%d/%d peor (p=%s)", sum(nz > 0), length(nz), f(binom.test(sum(nz > 0), length(nz))$p.value, 2)) }

cat(sprintf("Filas: %d; réplicas por configuración: %s; verificación en todas: %s\n\n",
            nrow(D), paste(unique(table(D$cfg_id)), collapse = ","), all(D$ver_hsets)))

## reutilización del piloto 1
p1 <- "tools/r/experimentos/resultados/piloto_canonico.csv"
if (file.exists(p1)) {
  A <- read.csv(p1); M <- merge(A, D, by = c("cfg_id", "rep"), suffixes = c(".p1", ".p2"))
  cat(sprintf("Reutilización piloto 1 (%d réplicas comunes): rho_off igual %s, crit_off igual %s, rho_can igual %s, crit_can igual %s\n\n",
    nrow(M), all(M$rho_off.p1 == M$rho_off.p2), all(M$crit_off.p1 == M$crit_off.p2),
    all(M$rho_can.p1 == M$rho_can.p2), all(M$crit_can.p1 == M$crit_can.p2)))
}

cat("### Dimensiones conservadas (r = autovalores significativos, s = complemento con variación) y sensibilidad\n\n")
tabla(c("config", "r set1..5", "s set1..5 (canonical2)", "canonical: κ 0.1/10 conjuntos distintos", "canonical2: (κ,κ2) ∈ {0.1,1,10}² conjuntos distintos", "canonical2: combinaciones que cambian best"),
  por(function(d) c(paste(vapply(paste0("r_set", 1:5), function(s) paste(unique(d[[s]]), collapse = "/"), ""), collapse = ", "),
                    paste(vapply(paste0("s_set", 1:5), function(s) paste(unique(d[[s]]), collapse = "/"), ""), collapse = ", "),
                    sum(d$sens_can_nsets), sum(d$sens_can2_nsets), sum(d$sens_can2_best))))
tabla(c("config", "conjuntos can ≠ ofi (media)", "conjuntos can2 ≠ ofi (media)", "conjuntos can2 ≠ can (media)"),
  por(function(d) c(f(mean(d$nsets_can_vs_off)), f(mean(d$nsets_can2_vs_off)), f(mean(d$nsets_can2_vs_can)))))

V <- c(off = "rrcov", can = "canonical", can2 = "canonical2", can2eps = "canonical2 (umbral eps, control)")
cat("### 1. Determinismo ante perturbación 1e-14 (5 por réplica): réplicas con algún cambio (initHsets / best / rho / cov)\n\n")
tabla(c("config", V),
  por(function(d) vapply(names(V), function(s) sprintf("%s · %s · %s · %s",
     sum(d[[paste0("pert_hsets_", s)]] > 0), sum(d[[paste0("pert_best_", s)]] > 0),
     sum(d[[paste0("pert_rho_", s)]] > 0), sum(d[[paste0("pert_cov_", s)]] > 0)), "")))
cat("Magnitud: max relF(Δcov) y max|Δcrit| sobre las 5 perturbaciones; mediana [p5, p95] entre réplicas\n\n")
tabla(c("config", paste("relF", V[1:3]), paste("|Δcrit|", V[1:3])),
  por(function(d) c(vapply(c("off", "can", "can2"), function(s) q(d[[paste0("pert_maxrelF_", s)]], 2), ""),
                    vapply(c("off", "can", "can2"), function(s) q(d[[paste0("pert_maxdcrit_", s)]], 2), ""))))

cat("### 2. Objetivo frente a rrcov (media / mediana [p5, p95])\n\n")
tabla(c("config", "Δrho can", "Δrho can2", "Δcrit can", "Δcrit can2"),
  por(function(d) c(mq(d$rho_can - d$rho_off), mq(d$rho_can2 - d$rho_off), mq(d$crit_can - d$crit_off), mq(d$crit_can2 - d$crit_off)), pn))
tabla(c("config", "Δ log obj mismo rho: can", "Δ log obj mismo rho: can2", "signo can", "signo can2", "best can2 = best rrcov"),
  por(function(d) c(mq(d$logobj_can_rhooff - d$logobj_off), mq(d$logobj_can2_rhooff - d$logobj_off),
                    signo(d$logobj_can_rhooff - d$logobj_off), signo(d$logobj_can2_rhooff - d$logobj_off), pct(d$best_igual_can2)), pn))
Dp <- D[D$p > D$n, ]
cat(sprintf("Global p>n (mismo rho): canonical %s; canonical2 %s\n\n",
            signo(Dp$logobj_can_rhooff - Dp$logobj_off), signo(Dp$logobj_can2_rhooff - Dp$logobj_off)))

cat("### 3. Percentil del objetivo dentro de los 5 objetivos de rrcov bajo perturbación\n\n")
cat("pctl = (#rrcov < v + 0.5·#empates)/5; 0 = mejor que las 5, 1 = peor que las 5.\n\n")
cl <- function(v) sprintf("%s · %s · %s (media %s)", sum(v == 0), sum(v > 0 & v < 1), sum(v == 1), f(mean(v), 2))
tabla(c("config", "can, mismo rho (mejor · dentro · peor)", "can2, mismo rho", "can, rho propio", "can2, rho propio",
        "rrcov: las 5 perturbaciones con el mismo objetivo (mismo rho)"),
  por(function(d) c(cl(d$pctl_rho_can), cl(d$pctl_rho_can2), cl(d$pctl_own_can), cl(d$pctl_own_can2),
                    pct(abs(d$rrcov_pert_obj_rho_max - d$rrcov_pert_obj_rho_min) <= 1e-12)), pn))

cat("### 4. Distancia entre soluciones\n\n")
tabla(c("config", "relF(can, rrcov)", "relF(can2, rrcov)", "solape best can / can2 (media)", "best idéntico can / can2", "relF propio rrcov (5 pert)"),
  por(function(d) c(q(d$relF_can_off), q(d$relF_can2_off), sprintf("%s / %s", f(mean(d$solape_can)), f(mean(d$solape_can2))),
                    sprintf("%s / %s", pct(d$best_igual_can), pct(d$best_igual_can2)), q(d$pert_maxrelF_off, 2)), pn))

dc <- D[D$n_atip > 0, ]
if (nrow(dc)) {
  cat("### 5. Contaminados: fracción de atípicos en best (media, máx) y AUC de mah (media, mín)\n\n")
  tabla(c("config", "en best rrcov", "en best can", "en best can2", "AUC rrcov", "AUC can", "AUC can2"),
    por(function(d) c(vapply(c("off", "can", "can2"), function(s) { v <- d[[paste0("atip_en_best_", s)]]; sprintf("%s, %s", f(mean(v)), f(max(v))) }, ""),
                      vapply(c("off", "can", "can2"), function(s) { v <- d[[paste0("auc_", s)]]; sprintf("%s, %s", f(mean(v)), f(min(v))) }, "")),
        unique(dc$cfg_id)))
  tabla(c("config", "Δ AUC can2 − rrcov (media [p5, p95])", "Δ AUC can − rrcov", "réplicas con algún atípico en best: rrcov / can / can2"),
    por(function(d) c(sprintf("%s [%s, %s]", f(mean(d$auc_can2 - d$auc_off)), f(quantile(d$auc_can2 - d$auc_off, .05)), f(quantile(d$auc_can2 - d$auc_off, .95))),
                      sprintf("%s [%s, %s]", f(mean(d$auc_can - d$auc_off)), f(quantile(d$auc_can - d$auc_off, .05)), f(quantile(d$auc_can - d$auc_off, .95))),
                      sprintf("%d / %d / %d", sum(d$atip_en_best_off > 0), sum(d$atip_en_best_can > 0), sum(d$atip_en_best_can2 > 0))), unique(dc$cfg_id)))
}

dn <- D[D$n > D$p, ]
if (nrow(dn)) {
  cat("### 6. n > p: identidad bit a bit con rrcov (best · rho · cov)\n\n")
  tabla(c("config", "canonical", "canonical2"),
    por(function(d) c(sprintf("%s · %s · %s", pct(d$best_igual_can), pct(d$rho_identico_can), pct(d$cov_identica_can)),
                      sprintf("%s · %s · %s", pct(d$best_igual_can2), pct(d$rho_identico_can2), pct(d$cov_identica_can2))), unique(dn$cfg_id)))
}

cat("### 7. Tiempo por ajuste (s, mediana [p5, p95]; 8 procesos en paralelo)\n\n")
tabla(c("config", "rrcov", "canonical", "canonical2", "ratio can2/rrcov (mediana)"),
  por(function(d) c(q(d$t_off), q(d$t_can), q(d$t_can2), f(median(d$t_can2 / d$t_off)))))

cat("### 8. Conjunto ganador (iBest)\n\n")
fr <- function(v) paste(names(table(v)), table(v), sep = ":", collapse = " ")
tabla(c("config", "rrcov", "canonical", "canonical2"), por(function(d) c(fr(d$iBest_off), fr(d$iBest_can), fr(d$iBest_can2))))
