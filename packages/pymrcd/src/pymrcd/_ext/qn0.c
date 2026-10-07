/*
 *  Copyright (C) 2005--2023	Martin Maechler, ETH Zurich (qn_sn.c)
 *  Copyright (C) 2006--2007	the R Development Core Team (wgt_himed.c, wgt_himed_templ.h)
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
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
 *
 * This is a merge of the C version of original files  qn.f and sn.f,
 * translated by f2c (version 20010821).
 * and then by f2c-clean,v 1.9 2000/01/13 13:46:53
 * and further clean-edited manually by Martin Maechler.
 *
 * Note that Peter Rousseeuw has explicitely given permission to
 * use his code under the GPL for the R project.
 *
 *  Rousseeuw, P.J. and Croux, C. (1993)
 *  Alternatives to the Median Absolute Deviation",
 *  Journal of the American Statistical Association, Vol. 88, 1273-1283.
 *
 *  pymrcd (GPL-3.0-or-later) incluye este port literal; GPL-2+ permite redistribuirlo bajo GPL-3.
 *
 *  Origen (robustbase 0.99-6, referencias/robustbase-0.99-6/src/):
 *    - qn0:      qn_sn.c:118-296 (llamado por Qn0, qn_sn.c:98-104, desde qnsn.R:48-49).
 *    - whimed_i: wgt_himed_templ.h:27-122 instanciado en wgt_himed.c:37-38 con
 *                _WGT_TYPE_ = int y _WGT_SUM_TYPE_ = int64_t (wgt_himed_templ.h:15-20).
 *  Especificación: docs/metodos/mrcd-especificacion.md §3.12.9 (tabla a).
 *
 *  Cambios respecto al original (ninguno cambia un bit del resultado; spec §3.12.9 a, g):
 *    1. qn0 no reserva memoria: recibe el espacio de trabajo del hilo (los 9 R_alloc de
 *       qn_sn.c:133-142, ahorro A1) y no copia x -> y: el llamador escribe y (la copia de
 *       :156-157 se fusiona con la comprobación NaN/Inf, A3, o con la construcción del par de
 *       OGK, A2). R_qsort(y, 1, n) de :158 sí se hace aquí.
 *    2. nn2, n2, k_L, h (:144-155) se calculan una vez por llamada en pymrcd_qn_consts_init
 *       (A5), con la misma expresión y tipos; k_L sin contracción (fpguard.h).
 *    3. sump/sumq (:228-234) se acumulan dentro de los bucles de p (:213-218) y q (:222-227)
 *       (A6, sumas enteras int64_t exactas).
 *    4. Las copias right[] = p[] (:239-240) y left[] = q[] (:246-247) se hacen por
 *       intercambio de punteros (A7): p y q se reescriben enteros antes de leerse.
 *    5. Rboolean/TRUE/FALSE -> bool/true/false; R_NaReal y NA_REAL -> NAN (inalcanzables:
 *       trial solo sale con found, :260-261; whimed_i nunca recibe n == 0, spec §3.12.9 d.5).
 *    6. Se omiten los bloques #ifdef DEBUG_qn/DEBUG_whimed (REprintf).
 *    7. Comprobación defensiva en :266-272: si j == n antes de escribir work[j] se devuelve
 *       PYMRCD_QN_ERR_WORK (R escribiría fuera del búfer; spec §3.12.9 d: nunca ocurre con el
 *       k por defecto).
 *    8. Nombres con prefijo pymrcd_; rPsort/R_qsort son los de rsort.c.
 *    9. whimed_i: (void) wright tras :67-74 (el original la acumula sin usarla; evita el aviso
 *       -Wunused-but-set-variable sin quitar la suma).
 */

#include "fpguard.h"

#include <math.h>
#include <stdbool.h>
#include <stdint.h>

#include "qn0.h"
#include "rsort.h"

/*
 * k_L de qn_sn.c:154: (int64_t)(5 - 1.75*(n % 2) + (0.3939 - 0.0067*(n % 2)) * ((int64_t) n)*(n-1)).
 * Aritmética double (int64_t n se convierte a double en el producto) truncada hacia 0 al
 * convertir a int64_t. Sin contracción FMA (fpguard.h; sonda S19).
 */
int64_t pymrcd_qn_k_L(int n)
{
    return (int64_t) (5 - 1.75*(n % 2) + (0.3939 - 0.0067*(n % 2)) * ((int64_t) n)*(n-1));
}

/* Constantes de qn_sn.c:144-155 (ahorro A5). */
void pymrcd_qn_consts_init(pymrcd_qn_consts *c, int n)
{
    c->n = n;
    c->nn2 = (int64_t) n * (n + 1) / 2; /* = choose(n+1, 2)  (:145) */
    c->n2 = (int64_t) n * n;            /* :146 */
    c->k_L = pymrcd_qn_k_L(n);          /* :154 */
    c->h = n / 2 + 1;                   /* :155 */
}

/*
 * whimed_i(a, w, n, a_cand, a_srt, w_cand): weighted high median, el menor a[j] tal que la suma
 * de los pesos de los a[i] <= a[j] supera estrictamente la mitad del total. Port literal de
 * robustbase-0.99-6/src/wgt_himed_templ.h:27-122 (instancia int / int64_t). Modifica a[] y w[]
 * en sitio (:116-119), como el original; usa rPsort sobre la copia a_srt (:61-63) y selecciona
 * candidatos en el orden original de a (:86-99): ambos deciden el signo de un cero devuelto.
 */
double pymrcd_whimed_i(double *a, int *w, int n, double *a_cand, double *a_srt, int *w_cand)
{
    int i;
    /* sum of weights: `int' do overflow when  n ~>= 1e5 */
    int64_t wleft, wmid, wright, w_tot, wrest; /* :46 */
    double trial;

    w_tot = wrest = 0;          /* :49 */
    for (i = 0; i < n; ++i)     /* :50-51 */
        w_tot += w[i];

    if (n == 0) return NAN;     /* :56 (NA_REAL; inalcanzable desde qn0) */

/* REPEAT : */
    do {                        /* :59 */
        int n2 = n/2;/* =^= n/2 +1 with 0-indexing */ /* :60 */
        for (i = 0; i < n; ++i) /* :61-62 */
            a_srt[i] = a[i];
        pymrcd_rPsort(a_srt, n, n2); /* :63 */
        trial = a_srt[n2];      /* :64 */

        wleft = 0;    wmid  = 0;    wright= 0; /* :66 */
        for (i = 0; i < n; ++i) { /* :67-74 */
            if (a[i] < trial)
                wleft += w[i];
            else if (a[i] > trial)
                wright += w[i];
            else
                wmid += w[i];
        }
        (void) wright; /* cambio 9: el original la calcula y no la usa (-Wunused) */

        int kcand = 0;          /* :84 */
        if (2 * (wrest + wleft) > w_tot) { /* :85 */
            for (i = 0; i < n; ++i) {
                if (a[i] < trial) {
                    a_cand[kcand] = a[i];
                    w_cand[kcand] = w[i];	++kcand;
                }
            }
        }
        else if (2 * (wrest + wleft + wmid) <= w_tot) { /* :93 */
            for (i = 0; i < n; ++i) {
                if (a[i] > trial) {
                    a_cand[kcand] = a[i];
                    w_cand[kcand] = w[i];	++kcand;
                }
            }
            wrest += wleft + wmid; /* :100 */
        }
        else {                  /* :105-111 */
            return trial;
            /*==========*/
        }
        n = kcand;              /* :112 */
        for (i = 0; i < n; ++i) { /* :116-119 */
            a[i] = a_cand[i];
            w[i] = w_cand[i];
        }
    } while(1);

} /* whimed_i */

/*
 * qn0: Q*_n = { |x_i - x_j|; i<j }_(k), el k-ésimo estadístico de orden de las diferencias
 * (Qn sin constante ni corrección). Port literal de robustbase-0.99-6/src/qn_sn.c:118-296 con
 * los cambios 1-8 de la cabecera. Entrada: ws->y con los n datos SIN ordenar (los escribe el
 * llamador; :156-157). Devuelve PYMRCD_QN_OK o PYMRCD_QN_ERR_WORK (comprobación defensiva).
 */
int pymrcd_qn0(const pymrcd_qn_consts *c, const int64_t k[], int len_k, double *res,
               pymrcd_qn_ws *ws)
{
    const int n = c->n;
    double *y = ws->y;          /* :133 */
    double *work = ws->work;    /* :134 */
    double *a_srt = ws->a_srt;  /* :135 */
    double *a_cand = ws->a_cand; /* :136 */

    int *left = ws->left;       /* :138 */
    int *right = ws->right;     /* :139 */
    int *p = ws->p;             /* :140 */
    int *q = ws->q;             /* :141 */
    int *weight = ws->weight;   /* :142 */

    const int64_t nn2 = c->nn2, n2 = c->n2, k_L = c->k_L; /* :144-154 (A5) */
    int h = c->h;               /* :155 */

    pymrcd_R_qsort(y, 1, (size_t) n); /* y := sort(x)  (:158) */

  for(int i_k=0; i_k < len_k; i_k++) { /* :165 */
    /* Following should be `long long int' : they can be of order n^2 */
    int64_t nl = nn2, nr = n2, knew = k[i_k] + nl;/* = k + (n+1 \over 2) */ /* :167 */
/* L200: */
    bool found = false;         /* :172 */
    double trial = NAN;/* -Wall */ /* :173 (R_NaReal; nunca sale sin asignar) */
    int i, j;                   /* :174 */

    for (int i = 0; i < n; ++i) /* :176-177 */
        left [i] = n - i + 1;
    if(k[i_k] >= k_L) { /* :178 */
        for (int i = 0; i < n; ++i)
            right[i] = n;
    } else {
        for (int i = 0; i < n; ++i)
            right[i] = (i <= h) ? n : n - (i - h); /* :183 */
    }

    while(!found && nr - nl > n) { /* :187 */
        j = 0;
        /* Truncation to float :
           try to make sure that the same values are got later (guard bits !) */
        for (i = 1; i < n; ++i) { /* :191-198 */
            if (left[i] <= right[i]) {
                weight[j] = right[i] - left[i] + 1;
                int jh = left[i] + weight[j] / 2;
                work[j] = (float)(y[i] - y[n - jh]); /* :195 */
                ++j;
            }
        }
        trial = pymrcd_whimed_i(work, weight, j, a_cand, a_srt, /*iw_cand*/ p); /* :199 */

        int64_t
            sump = 0,           /* :228-230 */
            sumq = 0;
        j = 0;                  /* :213 */
        for (i = n - 1; i >= 0; --i) { /* :214-218 */
            while (j < n && ((float)(y[i] - y[n - j - 1])) < trial)
                ++j;
            p[i] = j;
            sump += p[i];       /* :232 (A6) */
        }
        j = n + 1;              /* :222 */
        for (i = 0; i < n; ++i) { /* :223-227 */
            while ((float)(y[i] - y[n - j + 1]) > trial)
                --j;
            q[i] = j;
            sumq += q[i] - 1;   /* :233 (A6) */
        }
        if (knew <= sump) {     /* :238 */
            int *tmp = right; right = p; p = tmp; /* :239-240 (A7) */
            nr = sump;          /* :241 */
        } else if (knew > sumq) { /* :245 */
            int *tmp = left; left = q; q = tmp; /* :246-247 (A7) */
            nl = sumq;          /* :248 */
        } else { /* sump < knew <= sumq */
            found = true;       /* :253 */
        }
    } /* while */

    if (found)                  /* :260 */
        res[i_k] = trial;       /* :261 */
    else {
        j = 0;                  /* :266 */
        for (i = 1; i < n; ++i) {
            for (int jj = left[i]; jj <= right[i]; ++jj) {
                if (j >= n) /* cambio 7: defensiva (spec §3.12.9 d) */
                    return PYMRCD_QN_ERR_WORK;
                work[j] = y[i] - y[n - jj]; /* :269 */
                j++;
            }/* j will be = sum_{i=2}^n (right[i] - left[i] + 1)_{+}  */
        }

        /* return pull(work, j - 1, knew - nl)	: */
        knew -= (nl + 1); /* -1: 0-indexing */ /* :278 */

        if(knew  > j-1) { // see this happening when the quantile number k[i_k] is close to the right end!
            knew = j-1;         /* :281 */
        } else if(knew < 0) {
            knew = 0;           /* :286 */
        }
        pymrcd_rPsort(work, j, (int)knew); /* :291 */
        res[i_k] = work[knew];  /* :292 */
    }
  } // for(int i_k=0, i_k < len_k ...) { k_ = k[i_k] ; ....
  return PYMRCD_QN_OK;
} /* qn0 */
