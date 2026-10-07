## Resume tools/r/experimentos/resultados/piloto_canonico.csv en tablas Markdown (para el informe).
## Uso: Rscript tools/r/experimentos/resumen_piloto.R [csv]
args <- commandArgs(TRUE)
ruta <- if (length(args)) args[1] else "tools/r/experimentos/resultados/piloto_canonico.csv"
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
por <- function(fun) lapply(seq_len(nrow(cfgs)), function(i) { d <- D[D$cfg_id == cfgs$cfg_id[i], ]; c(cfgs$config[i], fun(d)) })

cat(sprintf("Filas: %d; réplicas por configuración: %s; copia oficial == rrcov en todas: %s\n\n",
            nrow(D), paste(unique(table(D$cfg_id)), collapse = ","), all(D$ver_hsets_oficial)))

cat("### Rango conservado por conjunto (kappa = 1) y sensibilidad al umbral\n\n")
tabla(c("config", "r set1..5 (valores observados)", "r igual con kappa 0.1", "r igual con kappa 10",
        "initHsets distintos kappa 0.1 vs 1", "initHsets distintos kappa 10 vs 1", "conjuntos can != oficial (media)"),
  por(function(d) c(paste(vapply(paste0("r_set", 1:5), function(s) paste(unique(d[[s]]), collapse = "/"), ""), collapse = ", "),
                    pct(d$r_k01_igual), pct(d$r_k10_igual), sum(d$sens01_nsets), sum(d$sens10_nsets),
                    f(mean(d$nsets_can_vs_off)))))

cat("### 1. Determinismo ante perturbación 1e-14 relativa (3 por réplica): réplicas con algún cambio\n\n")
tabla(c("config", "initHsets ofi", "initHsets can", "best ofi", "best can", "rho ofi", "rho can",
        "cov ofi (relF>1e-8)", "cov can (relF>1e-8)", "conjuntos cambiados ofi (media/réplica)"),
  por(function(d) c(pct(d$off_pert_hsets > 0), pct(d$can_pert_hsets > 0), pct(d$off_pert_best > 0), pct(d$can_pert_best > 0),
                    pct(d$off_pert_rho > 0), pct(d$can_pert_rho > 0), pct(d$off_pert_cov > 0), pct(d$can_pert_cov > 0),
                    f(mean(d$off_pert_nsets / 3)))))
cat("Magnitud (máximo sobre las 3 perturbaciones de cada réplica; mediana [p5, p95] entre réplicas):\n\n")
tabla(c("config", "max|Δrho| ofi", "max|Δrho| can", "max relF(Δcov) ofi", "max relF(Δcov) can",
        "max|Δcov| ofi", "max|Δcov| can", "max|Δcrit| ofi", "max|Δcrit| can"),
  por(function(d) c(q(d$off_pert_maxdrho, 2), q(d$can_pert_maxdrho, 2), q(d$off_pert_maxrelF, 2), q(d$can_pert_maxrelF, 2),
                    q(d$off_pert_maxabs, 2), q(d$can_pert_maxabs, 2), q(d$off_pert_maxdcrit, 2), q(d$can_pert_maxdcrit, 2))))

cat("### 2. Objetivo: canónico − oficial (media / mediana [p5, p95])\n\n")
tabla(c("config", "Δrho", "Δcrit (log det cov final)", "Δ log obj (rho propio)", "Δ log obj (mismo rho = rho ofi)",
        "can mejor con mismo rho (Δ<0)", "can peor con mismo rho (Δ>0)"),
  por(function(d) { dd <- d$logobj_can_rhooff - d$logobj_off
    c(mq(d$rho_can - d$rho_off), mq(d$crit_can - d$crit_off), mq(d$logobj_can - d$logobj_off), mq(dd),
      pct(dd < -1e-12), pct(dd > 1e-12)) }))
cat("Control: |logobj_off − log(cs_obj capturado)| máximo =", f(max(abs(D$chk_logobj), na.rm = TRUE)),
    "(NA en", sum(is.na(D$chk_logobj)), "filas)\n\n")
cat("Conjunto ganador (iBest) — frecuencias:\n\n")
tabla(c("config", "iBest oficial", "iBest canónico"),
  por(function(d) c(paste(names(table(d$iBest_off)), table(d$iBest_off), sep = ":", collapse = " "),
                    paste(names(table(d$iBest_can)), table(d$iBest_can), sep = ":", collapse = " "))))

cat("### 3. Distancia entre soluciones vs variabilidad propia de rrcov\n\n")
tabla(c("config", "relF(cov_can, cov_ofi)", "max|Δcov|", "solape best (media, mín)", "best idéntico",
        "relF propio rrcov (pert)", "réplicas con relF can-ofi > relF propio"),
  por(function(d) c(q(d$relF_can_off), q(d$maxabs_can_off), sprintf("%s, %s", f(mean(d$solape_best)), f(min(d$solape_best))),
                    pct(d$best_igual), q(d$off_pert_maxrelF, 2), pct(d$relF_can_off > d$off_pert_maxrelF))))

dc <- D[D$n_atip > 0, ]
if (nrow(dc)) {
  cat("### 4. Contaminados: fracción de atípicos dentro de best y AUC de mah (atípico vs limpio)\n\n")
  tabla(c("config", "atípicos", "frac en best ofi (media, máx)", "frac en best can (media, máx)", "AUC ofi (media, mín)", "AUC can (media, mín)"),
    lapply(split(dc, dc$config), function(d) c(d$config[1], d$n_atip[1],
      sprintf("%s, %s", f(mean(d$atip_en_best_off)), f(max(d$atip_en_best_off))),
      sprintf("%s, %s", f(mean(d$atip_en_best_can)), f(max(d$atip_en_best_can))),
      sprintf("%s, %s", f(mean(d$auc_off)), f(min(d$auc_off))), sprintf("%s, %s", f(mean(d$auc_can)), f(min(d$auc_can))))))
}

dn <- D[D$n > D$p, ]
if (nrow(dn)) {
  cat("### 5. n > p: ¿canónico idéntico a rrcov?\n\n")
  tabla(c("config", "initHsets iguales", "best idéntico", "rho idéntico", "cov idéntica (bit a bit)", "max|Δcov|"),
    lapply(split(dn, dn$config), function(d) c(d$config[1], pct(d$nsets_can_vs_off == 0), pct(d$best_igual),
      pct(d$rho_identico), pct(d$cov_identica), f(max(d$maxabs_can_off)))))
}

cat("### 6. Tiempo por ajuste (s, media / mediana [p5, p95]; 8 procesos en paralelo)\n\n")
tabla(c("config", "oficial", "canónico (r6pack canónico + CovMrcd)", "solo r6pack canónico", "ratio can/ofi (mediana)"),
  por(function(d) c(mq(d$t_off), mq(d$t_can), mq(d$t_can_r6), f(median(d$t_can / d$t_off)))))
