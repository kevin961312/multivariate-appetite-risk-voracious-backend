/*
 *  R : A Computer Language for Statistical Data Analysis
 *  Copyright (C) 1998-2025   The R Core Team
 *  Copyright (C) 1995, 1996  Robert Gentleman and Ross Ihaka
 *  Copyright (C) 2004        The R Foundation
 *  Copyright (C) 2002-2017   The R Core Team (qsort.c)
 *  Copyright (C) 2002-2012   The R Core Team (qsort-body.c)
 *
 *  qsort-body.c: Based on CACM algorithm #347 by R. C. Singleton (1969)
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
 *  along with this program; if not, a copy is available at
 *  https://www.R-project.org/Licenses/
 *
 *  pymrcd (GPL-3.0-or-later) incluye este port literal; GPL-2+ permite redistribuirlo bajo GPL-3.
 *
 *  Origen (R 4.5.2, extraído de referencias/R-4.5.2.tar.gz):
 *    - R_qsort:  src/main/qsort.c:161-167 (sin qsort_Index, NUMERIC = double)
 *                + src/main/qsort-body.c:27-169 (INTt = size_t por :37-39).
 *                MD5 qsort.c aed8963a407b216482687faf796a5693,
 *                    qsort-body.c e9ad0818f8128f7b4bbe5fabb0d05e45.
 *    - rPsort:   src/main/sort.c:724-727 -> rPsort2 :692-698 -> psort_body :668-681,
 *                rcmp :45-54. MD5 sort.c fb06d6d29e508700a0c48e56fe8b4931.
 *  Especificación: docs/metodos/mrcd-especificacion.md §3.12.9 a) y c).
 *
 *  Cambios respecto al original (ninguno altera el orden de las comparaciones ni de los
 *  intercambios, que deciden la posición de los ±0):
 *    1. Nombres con prefijo pymrcd_ (evita choques de símbolos con otras extensiones).
 *    2. qsort-body.c se pega como cuerpo de la función en vez de #include; se eliminan las
 *       ramas #ifdef qsort_Index (indefinido para R_qsort, qsort.c:162).
 *    3. psort_body (macro) se expande dentro de rPsort2 con TYPE_CMP = rcmp.
 *    4. rcmp: ISNAN -> isnan (la macro de R es isnan sobre double, Arith.h). Ningún NaN llega:
 *       las columnas con NaN se excluyen antes.
 *    5. R_xlen_t -> ptrdiff_t (R_xlen_t es ptrdiff_t en 64 bits); Rboolean/bool -> bool.
 *    6. Comentarios en español con las líneas de origen.
 */

#include "fpguard.h"

#include <math.h>
#include <stdbool.h>
#include <stddef.h>

#include "rsort.h"

/*
 * R_qsort(v, i, j): ordena v[i..j] (base 1) de forma creciente, Singleton (CACM #347) con la
 * modificación de Peto. Port literal de R-4.5.2/src/main/qsort-body.c:27-169 instanciado en
 * qsort.c:164-167 (NUMERIC = double, sin índice). Se conservan los goto (L10, L20, L80, L100),
 * los índices size_t, R = 0.375 (:47), el desplazamiento --v (:55) y las pilas il/iu de 40
 * (:41). El centinela de la inserción (:156-162) no tiene cota inferior: es correcto porque
 * :139 evita el tramo izquierdo (no se "arregla").
 */
void pymrcd_R_qsort(double *v, size_t i, size_t j)
{
    size_t il[40], iu[40]; /* qsort-body.c:41 */
    double vt, vtt;        /* :46 */
    double R = 0.375;      /* :47 */
    size_t ii, ij, k, l, m; /* :48 */

    /* 1-indexing for I[], v[]  (and `i' and `j') : (:54-55) */
    --v;

    ii = i; /* save (:60) */
    m = 1;  /* :61 */

L10: /* :63 */
    if (i < j) {
        if (R < 0.5898437) R += 0.0390625; else R -= 0.21875; /* :65 */
    L20: /* :66 */
        k = i;
        /* ij = (j + i) >> 1; midpoint */
        ij = (size_t)(i + (size_t)((j - i) * R)); /* :69 */
        vt = v[ij];                               /* :73 */
        if (v[i] > vt) {                          /* :74 */
            v[ij] = v[i]; v[i] = vt; vt = v[ij];  /* :78 */
        }
        /* L30: */
        l = j;                                    /* :81 */
        if (v[j] < vt) {                          /* :82 */
            v[ij] = v[j]; v[j] = vt; vt = v[ij];  /* :86 */
            if (v[i] > vt) {                      /* :87 */
                v[ij] = v[i]; v[i] = vt; vt = v[ij]; /* :91 */
            }
        }

        for (;;) { /*L50:*/ /* :95 */
            do l--; while (v[l] > vt); /* :96 */

            vtt = v[l]; /* :101 */
            /*L60:*/ do k++; while (v[k] < vt); /* :102 */

            if (k > l) break; /* :104 */

            /* else (k <= l) : */
            v[l] = v[k]; v[k] = vtt; /* :110 */
        }

        m++; /* :113 */
        if (l - i <= j - k) { /* :114 */
            /*L70: */
            il[m] = k;
            iu[m] = j;
            j = l;
        }
        else {
            il[m] = i;
            iu[m] = l;
            i = k;
        }
    }
    else { /* i >= j : (:126) */

    L80: /* :128 */
        if (m == 1) return; /* :129 */

        /* else */
        i = il[m]; /* :132 */
        j = iu[m];
        m--;
    }

    if (j - i > 10) goto L20; /* :137 */

    if (i == ii) goto L10; /* :139 */

    --i; /* :141 */
L100: /* :142 */
    do {
        ++i;
        if (i == j) {
            goto L80; /* :146 */
        }
        vt = v[i + 1]; /* :151 */
    } while (v[i] <= vt); /* :152 */

    k = i; /* :154 */

    do { /*L110:*/ /* :156 */
        v[k + 1] = v[k]; /* :160 */
        --k;
    } while (vt < v[k]); /* :162 */

    v[k + 1] = vt; /* :167 */
    goto L100;     /* :168 */
} /* R_qsort */

/* rcmp(x, y, nalast): R-4.5.2/src/main/sort.c:45-54 (ISNAN -> isnan). */
static int rcmp(double x, double y, bool nalast)
{
    int nax = isnan(x), nay = isnan(y);
    if (nax && nay)	return 0;
    if (nax)		return nalast ? 1 : -1;
    if (nay)		return nalast ? -1 : 1;
    if (x < y)		return -1;
    if (x > y)		return 1;
    return 0;
}

/*
 * rPsort2(x, lo, hi, k): selección parcial; x[k] queda en su sitio, menores a la izquierda y
 * mayores a la derecha. R-4.5.2/src/main/sort.c:692-698 con psort_body (:668-681) expandido y
 * TYPE_CMP = rcmp. Requiere k < n (lo garantiza el llamador, como en R).
 */
static void rPsort2(double *x, ptrdiff_t lo, ptrdiff_t hi, ptrdiff_t k)
{
    double v, w;                       /* :694 */
    bool nalast = true;                /* :669 */
    ptrdiff_t L, R, i, j;              /* :670 */

    for (L = lo, R = hi; L < R; ) {    /* :672 */
        v = x[k];                      /* :673 */
        for (i = L, j = R; i <= j;) {  /* :674 */
            while (rcmp(x[i], v, nalast) < 0) i++; /* :675 */
            while (rcmp(v, x[j], nalast) < 0) j--; /* :676 */
            if (i <= j) { w = x[i]; x[i++] = x[j]; x[j--] = w; } /* :677 */
        }
        if (j < k) L = i;              /* :679 */
        if (k < i) R = j;              /* :680 */
    }
}

/* rPsort(x, n, k): R-4.5.2/src/main/sort.c:724-727. */
void pymrcd_rPsort(double *x, int n, int k)
{
    rPsort2(x, 0, n - 1, k);
}
