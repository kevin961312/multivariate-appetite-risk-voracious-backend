/*
 *  pymrcd: port de rutinas de ordenación de R 4.5.2 usadas por robustbase::Qn.
 *
 *  Copyright (C) 1998-2025   The R Core Team
 *  Copyright (C) 1995, 1996  Robert Gentleman and Ross Ihaka
 *  Copyright (C) 2004        The R Foundation
 *  Port a la extensión C de pymrcd (2026): ver la lista de cambios en rsort.c.
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
 *  pymrcd se distribuye bajo GPL-3.0-or-later (compatible con GPL-2+).
 */

#ifndef PYMRCD_RSORT_H
#define PYMRCD_RSORT_H

#include <stddef.h>

/* R_qsort (R-4.5.2/src/main/qsort.c:164-167 + qsort-body.c:27-169), sin índice. */
void pymrcd_R_qsort(double *v, size_t i, size_t j);

/* rPsort (R-4.5.2/src/main/sort.c:724-727 -> rPsort2 :692-698 -> psort_body :668-681). */
void pymrcd_rPsort(double *x, int n, int k);

#endif /* PYMRCD_RSORT_H */
