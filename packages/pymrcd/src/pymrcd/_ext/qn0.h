/*
 *  pymrcd: port de qn0 y whimed_i de robustbase 0.99-6.
 *
 *  Copyright (C) 2005--2023	Martin Maechler, ETH Zurich (qn_sn.c)
 *  Copyright (C) 2006--2007	the R Development Core Team (wgt_himed.c)
 *  Port a la extensión C de pymrcd (2026): ver la lista de cambios en qn0.c.
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  Note by MM: We have explicit permission from P.Rousseeuw to
 *  licence it under the GNU Public Licence.
 *
 *  pymrcd se distribuye bajo GPL-3.0-or-later (compatible con GPL-2+).
 */

#ifndef PYMRCD_QN0_H
#define PYMRCD_QN0_H

#include <stdint.h>

/* Espacio de trabajo de qn0 (los 9 R_alloc de qn_sn.c:133-142), uno por hilo (ahorro A1). */
typedef struct {
    double *y, *work, *a_srt, *a_cand;
    int *left, *right, *p, *q, *weight;
} pymrcd_qn_ws;

/* Constantes de qn0 que dependen solo de n (qn_sn.c:144-155; ahorro A5). */
typedef struct {
    int n;
    int64_t nn2, n2, k_L;
    int h;
} pymrcd_qn_consts;

/* Códigos de retorno de pymrcd_qn0. */
#define PYMRCD_QN_OK 0
#define PYMRCD_QN_ERR_WORK 1 /* j == n en la rama «no encontrado» (spec §3.12.9 d) */

int64_t pymrcd_qn_k_L(int n);
void pymrcd_qn_consts_init(pymrcd_qn_consts *c, int n);
double pymrcd_whimed_i(double *a, int *w, int n, double *a_cand, double *a_srt, int *w_cand);
int pymrcd_qn0(const pymrcd_qn_consts *c, const int64_t k[], int len_k, double *res,
               pymrcd_qn_ws *ws);

#endif /* PYMRCD_QN0_H */
