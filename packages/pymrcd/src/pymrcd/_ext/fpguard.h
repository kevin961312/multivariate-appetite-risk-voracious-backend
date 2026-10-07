/*
 *  pymrcd: barreras de compilación de coma flotante de la extensión C.
 *
 *  Copyright (C) 2026 pymrcd contributors
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  Especificación: docs/metodos/mrcd-especificacion.md §3.12.9 b) (puntos 1-2).
 *  - El binario de R del oráculo no tiene FMA en qn0/whimed_i/R_qsort/rPsort (sonda S18), pero
 *    clang contrae por defecto k_L (qn_sn.c:154) y (s*s - d*d)/4 (sonda S19): la contracción
 *    debe estar desactivada. setup.py pasa -ffp-contract=off y define PYMRCD_FP_CONTRACT_OFF;
 *    los pragmas son la segunda barrera (GCC ignora STDC FP_CONTRACT y depende de la opción).
 *  - FLT_EVAL_METHOD != 0 (x87 de 32 bits) rompería el redondeo de (float) de qn_sn.c:195.
 *  - -ffast-math / -ffinite-math-only cambian comparaciones y signos de cero.
 *  Incluir antes de cualquier código de coma flotante, en cada unidad de traducción.
 */

#ifndef PYMRCD_FPGUARD_H
#define PYMRCD_FPGUARD_H

#include <float.h>

#ifndef PYMRCD_FP_CONTRACT_OFF
#error "pymrcd: falta PYMRCD_FP_CONTRACT_OFF; compile con setup.py (-ffp-contract=off)"
#endif

#if !defined(FLT_EVAL_METHOD) || FLT_EVAL_METHOD != 0
#error "pymrcd: FLT_EVAL_METHOD debe ser 0 (el redondeo a float de qn0 depende de ello)"
#endif

#if defined(__FAST_MATH__)
#error "pymrcd: prohibido compilar con -ffast-math"
#endif

#if defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__
#error "pymrcd: prohibido compilar con -ffinite-math-only"
#endif

#if defined(__clang__)
#pragma STDC FP_CONTRACT OFF
#pragma clang fp contract(off)
#elif !defined(__GNUC__)
#pragma STDC FP_CONTRACT OFF
#endif

_Static_assert(sizeof(double) == 8, "pymrcd: double debe ser binary64");
_Static_assert(sizeof(float) == 4, "pymrcd: float debe ser binary32");

#endif /* PYMRCD_FPGUARD_H */
