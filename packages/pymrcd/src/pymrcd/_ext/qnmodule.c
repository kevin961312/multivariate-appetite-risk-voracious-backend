/*
 *  pymrcd._qn_ext: extensión CPython de qn0 (robustbase) y de la matriz U de OGK (rrcov).
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
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 *  Especificación: docs/metodos/mrcd-especificacion.md §3.12.9 (M5). Créditos del método y del
 *  código portado: robustbase 0.99-6 (M. Maechler y colaboradores; qn0 y whimed_i de
 *  P. Rousseeuw y C. Croux), rrcov 1.7-7 (V. Todorov; ogkscatter en R/detmrcd.R:84-111) y
 *  R 4.5.2 (R Core Team; R_qsort, rPsort).
 *
 *  Interfaz: CPython C-API pura con el protocolo de búfer (sin cabeceras de numpy). Hilos
 *  POSIX con paralelismo entre columnas (o pares de OGK); determinista por construcción
 *  (spec §3.12.9 e): cada columna es una función pura de sus datos y de n, el espacio de
 *  trabajo es privado por hilo y se reserva entero antes de crear hilos, cada salida la escribe
 *  un solo hilo, el GIL se libera durante el cálculo y todos los hilos se unen antes de volver.
 *  Errores: MemoryError (reserva), OSError (pthread_create), ValueError (±Inf, argumentos),
 *  RuntimeError (entorno de coma flotante, comprobación defensiva j == n). Nunca hay resultado
 *  parcial: ante cualquier error se lanza la excepción tras unir los hilos.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "fpguard.h"

#include <errno.h>
#include <fenv.h>
#include <limits.h>
#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#if defined(__linux__)
#include <sched.h>
#endif

#include "qn0.h"
#include "rsort.h"

/* ------------------------------------------------------------------ entorno de coma flotante */

/*
 * Redondeo al más cercano y sin flush-to-zero (spec §3.12.9 b.3): los pares de OGK y las
 * diferencias y[i] - y[m] pueden ser subnormales. Se comprueba en cada hilo al empezar.
 */
static bool fp_rounding_ok(void)
{
    return fegetround() == FE_TONEAREST;
}

static bool fp_subnormals_ok(void)
{
    volatile double tiny = DBL_MIN;
    volatile double half = tiny / 2.0;
    double h = half;
    uint64_t bits;
    memcpy(&bits, &h, sizeof bits);
    return bits != 0; /* con FTZ el cociente subnormal se vuelve +0 */
}

static bool fp_env_ok(void)
{
    return fp_rounding_ok() && fp_subnormals_ok();
}

/* ------------------------------------------------------------------ número de hilos */

/*
 * Hilos por defecto: PYMRCD_NUM_THREADS si está definida; si no, los CPU visibles por afinidad
 * (sched_getaffinity en Linux, como os.sched_getaffinity) o los CPU en línea
 * (sysconf(_SC_NPROCESSORS_ONLN), como os.cpu_count). Se resuelve en C para no añadir
 * importaciones de os a pymrcd. Devuelve -1 con ValueError si la variable no es válida.
 */
static long default_threads(void)
{
    const char *env = getenv("PYMRCD_NUM_THREADS");
    if (env != NULL && env[0] != '\0') {
        char *end = NULL;
        errno = 0;
        long v = strtol(env, &end, 10);
        if (errno != 0 || end == env || *end != '\0' || v < 1 || v > 4096) {
            PyErr_Format(PyExc_ValueError,
                         "PYMRCD_NUM_THREADS debe ser un entero entre 1 y 4096 (vale '%s')",
                         env);
            return -1;
        }
        return v;
    }
#if defined(__linux__) && defined(CPU_COUNT)
    {
        cpu_set_t set;
        CPU_ZERO(&set);
        if (sched_getaffinity(0, sizeof set, &set) == 0) {
            int c = CPU_COUNT(&set);
            if (c >= 1) return c;
        }
    }
#endif
    long c = sysconf(_SC_NPROCESSORS_ONLN);
    return c >= 1 ? c : 1;
}

/* ------------------------------------------------------------------ trabajo y hilos */

enum { JOB_COLUMNS = 0, JOB_OGK = 1 };

enum {
    ERR_NONE = 0,
    ERR_INF = 1,  /* ±Inf en una columna sin NaN (ValueError, qn.py) */
    ERR_WORK = 2, /* j == n en la rama «no encontrado» (RuntimeError, spec §3.12.9 d) */
    ERR_FPENV = 3 /* entorno de coma flotante inválido (RuntimeError, spec §3.12.9 b.3) */
};

typedef struct {
    int kind;
    const char *xbuf;  /* datos n x m (columnas) o n x p (OGK), cualquier stride */
    Py_ssize_t s0, s1; /* strides en bytes (filas, columnas) */
    int n;
    Py_ssize_t ncols;  /* m (columnas) o p (OGK) */
    double *out;       /* m (columnas) o p x p C-contigua (OGK) */
    int64_t k;         /* k de qn0 (len_k = 1) */
    pymrcd_qn_consts consts;
    double constant;   /* OGK: 2.21914 (qnsn.R:44), calculada en Python */
    double factor;     /* OGK: TAB[n-2] (qnsn.R:58-63) o Qn.finite.c(n) (qnsn.R:13-16) */
    int small_n;       /* OGK: 1 si n <= 12 (multiplica), 0 si divide (qnsn.R:56-65) */
    size_t n_items;
    atomic_size_t next;
    atomic_int abort_flag;
    int poison;        /* depuración A1: llena el espacio de trabajo antes de cada ítem */
} job_t;

typedef struct {
    job_t *job;
    pymrcd_qn_ws ws;
    void *block;
    int err_code;
    size_t err_index;
} worker_t;

static inline double load_xy(const job_t *job, Py_ssize_t r, Py_ssize_t c)
{
    double v;
    memcpy(&v, job->xbuf + r * job->s0 + c * job->s1, sizeof v);
    return v;
}

static void record_error(worker_t *w, int code, size_t index)
{
    if (w->err_code == ERR_NONE || index < w->err_index ||
        (index == w->err_index && code < w->err_code)) {
        w->err_code = code;
        w->err_index = index;
    }
}

/* Ahorro A1, modo de depuración: NaN con carga distinta por ítem y enteros basura. */
static void poison_ws(pymrcd_qn_ws *ws, int n, size_t item)
{
    uint64_t bits = 0x7ff8000000000000ULL | ((uint64_t) (item * 2654435761u + 12345u) & 0xfffffULL);
    double nanv;
    memcpy(&nanv, &bits, sizeof nanv);
    int junk = INT_MIN + (int) (item % 1000u);
    for (int r = 0; r < n; ++r) {
        ws->y[r] = nanv; ws->work[r] = nanv; ws->a_srt[r] = nanv; ws->a_cand[r] = nanv;
        ws->left[r] = junk; ws->right[r] = junk; ws->p[r] = junk; ws->q[r] = junk;
        ws->weight[r] = junk;
    }
}

/* Clasifica ws->y tras la copia fusionada (ahorro A3): 0 finito, 1 NaN, 2 ±Inf sin NaN. */
static int scan_y(const double *y, int n)
{
    bool has_inf = false;
    for (int r = 0; r < n; ++r) {
        if (isnan(y[r])) return 1;
        if (isinf(y[r])) has_inf = true;
    }
    return has_inf ? 2 : 0;
}

/* qn0 de ws->y con la semántica de qn.py: NaN => NaN; ±Inf => error; si no, qn0. */
static double qn_of_y(worker_t *w, int *code)
{
    job_t *job = w->job;
    int st = scan_y(w->ws.y, job->n);
    *code = ERR_NONE;
    if (st == 1) return NAN;
    if (st == 2) { *code = ERR_INF; return NAN; }
    double res = NAN;
    int64_t k = job->k;
    if (pymrcd_qn0(&job->consts, &k, 1, &res, &w->ws) != PYMRCD_QN_OK) {
        *code = ERR_WORK;
        return NAN;
    }
    return res;
}

static void do_column(worker_t *w, size_t c)
{
    job_t *job = w->job;
    const int n = job->n;
    if (job->poison) poison_ws(&w->ws, n, c);
    double *y = w->ws.y;
    for (int r = 0; r < n; ++r) /* qn_sn.c:156-157 (copia), con strides (A4) */
        y[r] = load_xy(job, r, (Py_ssize_t) c);
    int code;
    double v = qn_of_y(w, &code);
    if (code != ERR_NONE) record_error(w, code, c);
    job->out[c] = v;
}

/* Par t (orden de np.tril_indices(p, -1)) -> (i, j) con i > j. */
static void pair_of(size_t t, size_t *pi, size_t *pj)
{
    size_t i = (size_t) ((1.0 + sqrt(1.0 + 8.0 * (double) t)) / 2.0);
    while (i > 1 && i * (i - 1) / 2 > t) --i;
    while ((i + 1) * i / 2 <= t) ++i;
    *pi = i;
    *pj = t - i * (i - 1) / 2;
}

/* Escala Qn de qnsn.R:44-65 a partir de qn0: (2.21914 * r) * TAB[n-2] o / Qn.finite.c(n). */
static inline double qn_scale(const job_t *job, double raw)
{
    double r = job->constant * raw;
    return job->small_n ? r * job->factor : r / job->factor;
}

/*
 * U[i,j] de ogkscatter (rrcov-1.7-7/R/detmrcd.R:89-97, M1 del dueño): y = Y_i + Y_j (la copia
 * de qn_sn.c:156-157 es la construcción del par, A2), qn0; y = Y_i - Y_j, qn0; s y d con la
 * constante y el factor de Qn (pasados desde Python); U = (s*s - d*d)/4 sin contracción
 * (fpguard.h; spec §3.12.9 a, última fila); espejo U[j,i] (:97).
 */
static void do_pair(worker_t *w, size_t t)
{
    job_t *job = w->job;
    const int n = job->n;
    size_t i, j;
    pair_of(t, &i, &j);
    double *y = w->ws.y;
    int code;

    if (job->poison) poison_ws(&w->ws, n, 2 * t);
    for (int r = 0; r < n; ++r)
        y[r] = load_xy(job, r, (Py_ssize_t) i) + load_xy(job, r, (Py_ssize_t) j);
    double qplus = qn_of_y(w, &code);
    if (code != ERR_NONE) record_error(w, code, t);

    if (job->poison) poison_ws(&w->ws, n, 2 * t + 1);
    for (int r = 0; r < n; ++r)
        y[r] = load_xy(job, r, (Py_ssize_t) i) - load_xy(job, r, (Py_ssize_t) j);
    double qminus = qn_of_y(w, &code);
    if (code != ERR_NONE) record_error(w, code, t);

    double s = qn_scale(job, qplus);
    double d = qn_scale(job, qminus);
    double u = (s * s - d * d) / 4;
    size_t p = (size_t) job->ncols;
    job->out[i * p + j] = u;
    job->out[j * p + i] = u;
}

static void *worker_main(void *arg)
{
    worker_t *w = (worker_t *) arg;
    job_t *job = w->job;
    if (!fp_env_ok()) {
        record_error(w, ERR_FPENV, 0);
        return NULL;
    }
    for (;;) {
        if (atomic_load(&job->abort_flag)) break;
        size_t t = atomic_fetch_add(&job->next, 1);
        if (t >= job->n_items) break;
        if (job->kind == JOB_COLUMNS)
            do_column(w, t);
        else
            do_pair(w, t);
    }
    return NULL;
}

/* Reserva el espacio de trabajo de un hilo (los 9 búferes de qn_sn.c:133-142, tamaño n). */
static int ws_alloc(worker_t *w, int n)
{
    size_t nn = (size_t) n;
    size_t bytes = nn * (4 * sizeof(double) + 5 * sizeof(int));
    char *b = (char *) malloc(bytes > 0 ? bytes : 1);
    if (b == NULL) return -1;
    w->block = b;
    w->ws.y = (double *) b;
    w->ws.work = w->ws.y + nn;
    w->ws.a_srt = w->ws.work + nn;
    w->ws.a_cand = w->ws.a_srt + nn;
    w->ws.left = (int *) (w->ws.a_cand + nn);
    w->ws.right = w->ws.left + nn;
    w->ws.p = w->ws.right + nn;
    w->ws.q = w->ws.p + nn;
    w->ws.weight = w->ws.q + nn;
    return 0;
}

/*
 * Ejecuta el trabajo con nthreads hilos (el llamador es el hilo 0). Devuelve 0 o -1 con una
 * excepción de Python fijada. El GIL se libera solo durante el cálculo.
 */
static int run_job(job_t *job, long nthreads)
{
    if (job->n_items == 0) return 0;
    if ((size_t) nthreads > job->n_items) nthreads = (long) job->n_items;
    if (nthreads < 1) nthreads = 1;

    worker_t *workers = (worker_t *) calloc((size_t) nthreads, sizeof(worker_t));
    pthread_t *tids = (pthread_t *) calloc((size_t) nthreads, sizeof(pthread_t));
    if (workers == NULL || tids == NULL) {
        free(workers);
        free(tids);
        PyErr_NoMemory();
        return -1;
    }
    for (long t = 0; t < nthreads; ++t) {
        workers[t].job = job;
        if (ws_alloc(&workers[t], job->n) != 0) {
            for (long u = 0; u < t; ++u) free(workers[u].block);
            free(workers);
            free(tids);
            PyErr_NoMemory();
            return -1;
        }
    }
    atomic_store(&job->next, 0);
    atomic_store(&job->abort_flag, 0);

    long created = 0;
    int create_rc = 0;
    Py_BEGIN_ALLOW_THREADS
    for (long t = 1; t < nthreads; ++t) {
        create_rc = pthread_create(&tids[t], NULL, worker_main, &workers[t]);
        if (create_rc != 0) {
            atomic_store(&job->abort_flag, 1);
            break;
        }
        ++created;
    }
    if (create_rc == 0) worker_main(&workers[0]);
    for (long t = 1; t <= created; ++t) pthread_join(tids[t], NULL);
    Py_END_ALLOW_THREADS

    int code = ERR_NONE;
    size_t index = 0;
    for (long t = 0; t < nthreads; ++t) {
        worker_t *w = &workers[t];
        if (w->err_code == ERR_NONE) continue;
        if (w->err_code == ERR_FPENV) {
            code = ERR_FPENV;
            index = 0;
            break;
        }
        if (code == ERR_NONE || w->err_index < index ||
            (w->err_index == index && w->err_code < code)) {
            code = w->err_code;
            index = w->err_index;
        }
    }
    for (long t = 0; t < nthreads; ++t) free(workers[t].block);
    free(workers);
    free(tids);

    if (create_rc != 0) {
        errno = create_rc;
        PyErr_SetFromErrno(PyExc_OSError);
        return -1;
    }
    switch (code) {
    case ERR_NONE:
        return 0;
    case ERR_INF:
        PyErr_SetString(PyExc_ValueError,
                        "Qn con valores infinitos no está soportado por el port");
        return -1;
    case ERR_WORK:
        PyErr_Format(PyExc_RuntimeError,
                     "qn0: la rama «no encontrado» excede el búfer de tamaño n (n=%d, "
                     "índice %zu); ver especificación §3.12.9 d",
                     job->n, index);
        return -1;
    default:
        PyErr_SetString(PyExc_RuntimeError,
                        "entorno de coma flotante no soportado: se exige redondeo al más "
                        "cercano y sin flush-to-zero (especificación §3.12.9 b.3)");
        return -1;
    }
}

/* ------------------------------------------------------------------ búferes */

static bool is_double_format(const char *fmt)
{
    if (fmt == NULL) return false;
    if (fmt[0] == '@' || fmt[0] == '=') ++fmt;
#if PY_LITTLE_ENDIAN
    else if (fmt[0] == '<') ++fmt;
#else
    else if (fmt[0] == '>' || fmt[0] == '!') ++fmt;
#endif
    return fmt[0] == 'd' && fmt[1] == '\0';
}

static bool is_int32_format(const char *fmt)
{
    if (fmt == NULL) return false;
    if (fmt[0] == '@' || fmt[0] == '=') ++fmt;
#if PY_LITTLE_ENDIAN
    else if (fmt[0] == '<') ++fmt;
#else
    else if (fmt[0] == '>' || fmt[0] == '!') ++fmt;
#endif
    return (fmt[0] == 'i' || (fmt[0] == 'l' && sizeof(long) == 4)) && fmt[1] == '\0';
}

/* Búfer float64 de 2 dimensiones, solo lectura, cualquier stride. */
static int get_matrix(PyObject *obj, Py_buffer *view, const char *name)
{
    if (PyObject_GetBuffer(obj, view, PyBUF_STRIDES | PyBUF_FORMAT) != 0) return -1;
    if (view->ndim != 2 || view->itemsize != 8 || !is_double_format(view->format)) {
        PyErr_Format(PyExc_ValueError, "%s debe ser una matriz float64 de 2 dimensiones", name);
        PyBuffer_Release(view);
        return -1;
    }
    return 0;
}

/* Búfer float64 escribible y C-contiguo de longitud total len (elementos). */
static int get_out(PyObject *obj, Py_buffer *view, Py_ssize_t len, const char *name)
{
    if (PyObject_GetBuffer(obj, view, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_C_CONTIGUOUS) != 0)
        return -1;
    if (view->itemsize != 8 || !is_double_format(view->format) || view->len != len * 8) {
        PyErr_Format(PyExc_ValueError, "%s debe ser float64 C-contiguo con %zd elementos", name,
                     len);
        PyBuffer_Release(view);
        return -1;
    }
    return 0;
}

/* Extensión [lo, hi) en bytes de un búfer con strides. */
static void extent(const Py_buffer *v, const char **lo, const char **hi)
{
    const char *base = (const char *) v->buf;
    const char *a = base, *b = base;
    bool empty = false;
    for (int d = 0; d < v->ndim; ++d) {
        if (v->shape[d] == 0) empty = true;
    }
    if (!empty) {
        for (int d = 0; d < v->ndim; ++d) {
            Py_ssize_t span = (v->shape[d] - 1) * v->strides[d];
            if (span < 0) a += span; else b += span;
        }
        b += v->itemsize;
    }
    *lo = a;
    *hi = empty ? a : b;
}

static int check_no_overlap(const Py_buffer *in, const Py_buffer *out)
{
    const char *ilo, *ihi;
    extent(in, &ilo, &ihi);
    const char *olo = (const char *) out->buf;
    const char *ohi = olo + out->len;
    if (ilo < ohi && olo < ihi && ilo != ihi && olo != ohi) {
        PyErr_SetString(PyExc_ValueError, "la salida no puede compartir memoria con la entrada");
        return -1;
    }
    return 0;
}

static long resolve_threads(long n_threads)
{
    if (n_threads < 0) {
        PyErr_SetString(PyExc_ValueError, "n_threads debe ser >= 1 (o 0 para el valor por defecto)");
        return -1;
    }
    if (n_threads == 0) return default_threads();
    return n_threads;
}

/* ------------------------------------------------------------------ funciones Python */

PyDoc_STRVAR(qn0_columns_doc,
"qn0_columns(x, out, k, n_threads, poison=0)\n--\n\n"
"qn0 (robustbase-0.99-6/src/qn_sn.c:118-296) por columna de x (n x m, float64, cualquier\n"
"stride) con len_k = 1; escribe en out (m, float64, C-contiguo). NaN en la columna => NaN;\n"
"±Inf sin NaN => ValueError. Requiere 2 <= n <= INT_MAX y 1 <= k.");

static PyObject *py_qn0_columns(PyObject *self, PyObject *args)
{
    (void) self;
    PyObject *xo, *oo;
    long long k;
    long n_threads;
    int poison = 0;
    if (!PyArg_ParseTuple(args, "OOLl|p:qn0_columns", &xo, &oo, &k, &n_threads, &poison))
        return NULL;
    Py_buffer xv, ov;
    if (get_matrix(xo, &xv, "x") != 0) return NULL;
    Py_ssize_t n = xv.shape[0], m = xv.shape[1];
    if (n < 2 || n > INT_MAX) {
        PyBuffer_Release(&xv);
        PyErr_SetString(PyExc_ValueError, "qn0 requiere 2 <= n <= INT_MAX (qnsn.R:29-31)");
        return NULL;
    }
    if (k < 1) {
        PyBuffer_Release(&xv);
        PyErr_SetString(PyExc_ValueError, "k debe ser >= 1 (qnsn.R:35)");
        return NULL;
    }
    if (get_out(oo, &ov, m, "out") != 0) {
        PyBuffer_Release(&xv);
        return NULL;
    }
    int rc = check_no_overlap(&xv, &ov);
    long nt = rc == 0 ? resolve_threads(n_threads) : -1;
    if (rc == 0 && nt > 0) {
        job_t job;
        memset(&job, 0, sizeof job);
        job.kind = JOB_COLUMNS;
        job.xbuf = (const char *) xv.buf;
        job.s0 = xv.strides[0];
        job.s1 = xv.strides[1];
        job.n = (int) n;
        job.ncols = m;
        job.out = (double *) ov.buf;
        job.k = (int64_t) k;
        pymrcd_qn_consts_init(&job.consts, (int) n);
        job.n_items = (size_t) m;
        job.poison = poison;
        rc = run_job(&job, nt);
    } else {
        rc = -1;
    }
    PyBuffer_Release(&ov);
    PyBuffer_Release(&xv);
    if (rc != 0) return NULL;
    Py_RETURN_NONE;
}

PyDoc_STRVAR(ogk_u_doc,
"ogk_u(y, out, constant, factor, small_n, n_threads, poison=0)\n--\n\n"
"Triángulos de U de ogkscatter (rrcov-1.7-7/R/detmrcd.R:87-97) para y (n x p, float64): por\n"
"par i > j, s = Qn(Y_i + Y_j), d = Qn(Y_i - Y_j) y U[i,j] = U[j,i] = (s*s - d*d)/4. La\n"
"diagonal de out (p x p, C-contigua) no se toca. Qn = (constant * qn0) * factor si small_n,\n"
"si no / factor (qnsn.R:44-65). Requiere 2 <= n <= INT_MAX.");

static PyObject *py_ogk_u(PyObject *self, PyObject *args)
{
    (void) self;
    PyObject *yo, *oo;
    double constant, factor;
    int small_n;
    long n_threads;
    int poison = 0;
    if (!PyArg_ParseTuple(args, "OOddpl|p:ogk_u", &yo, &oo, &constant, &factor, &small_n,
                          &n_threads, &poison))
        return NULL;
    Py_buffer yv, ov;
    if (get_matrix(yo, &yv, "y") != 0) return NULL;
    Py_ssize_t n = yv.shape[0], p = yv.shape[1];
    if (n < 2 || n > INT_MAX) {
        PyBuffer_Release(&yv);
        PyErr_SetString(PyExc_ValueError, "ogk_u requiere 2 <= n <= INT_MAX");
        return NULL;
    }
    if (p > 0 && (size_t) p > SIZE_MAX / (size_t) p) {
        PyBuffer_Release(&yv);
        PyErr_SetString(PyExc_ValueError, "p demasiado grande");
        return NULL;
    }
    if (get_out(oo, &ov, p * p, "out") != 0) {
        PyBuffer_Release(&yv);
        return NULL;
    }
    int rc = check_no_overlap(&yv, &ov);
    long nt = rc == 0 ? resolve_threads(n_threads) : -1;
    if (rc == 0 && nt > 0) {
        job_t job;
        memset(&job, 0, sizeof job);
        job.kind = JOB_OGK;
        job.xbuf = (const char *) yv.buf;
        job.s0 = yv.strides[0];
        job.s1 = yv.strides[1];
        job.n = (int) n;
        job.ncols = p;
        job.out = (double *) ov.buf;
        pymrcd_qn_consts_init(&job.consts, (int) n);
        job.k = (int64_t) (n / 2 + 1) * (n / 2) / 2; /* choose(n %/% 2 + 1, 2), qnsn.R:21 */
        job.constant = constant;
        job.factor = factor;
        job.small_n = small_n;
        job.n_items = (size_t) p * (size_t) (p > 0 ? p - 1 : 0) / 2;
        job.poison = poison;
        rc = run_job(&job, nt);
    } else {
        rc = -1;
    }
    PyBuffer_Release(&ov);
    PyBuffer_Release(&yv);
    if (rc != 0) return NULL;
    Py_RETURN_NONE;
}

PyDoc_STRVAR(default_threads_doc,
"default_threads()\n--\n\n"
"Hilos por defecto: PYMRCD_NUM_THREADS o los CPU visibles por afinidad.");

static PyObject *py_default_threads(PyObject *self, PyObject *noargs)
{
    (void) self;
    (void) noargs;
    long v = default_threads();
    if (v < 0) return NULL;
    return PyLong_FromLong(v);
}

PyDoc_STRVAR(build_info_doc,
"build_info()\n--\n\n"
"Salvaguardas de compilación y del entorno de coma flotante (spec §3.12.9 b).");

static PyObject *py_build_info(PyObject *self, PyObject *noargs)
{
    (void) self;
    (void) noargs;
#if defined(__clang__)
    const char *family = "clang";
#elif defined(__GNUC__)
    const char *family = "gcc";
#else
    const char *family = "other";
#endif
#if defined(__VERSION__)
    const char *version = __VERSION__;
#else
    const char *version = "unknown";
#endif
#if defined(__OPTIMIZE__)
    int optimize = 1;
#else
    int optimize = 0;
#endif
#if defined(__FAST_MATH__)
    int fast_math = 1;
#else
    int fast_math = 0;
#endif
#if defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__
    int finite_math_only = 1;
#else
    int finite_math_only = 0;
#endif
#if defined(PYMRCD_FP_CONTRACT_OFF)
    int contract_off = 1;
#else
    int contract_off = 0;
#endif
    return Py_BuildValue(
        "{s:s,s:s,s:O,s:O,s:i,s:O,s:O,s:O,s:O,s:i,s:i}",
        "compiler", family,
        "compiler_version", version,
        "fp_contract_off_macro", contract_off ? Py_True : Py_False,
        "optimize", optimize ? Py_True : Py_False,
        "flt_eval_method", (int) FLT_EVAL_METHOD,
        "fast_math", fast_math ? Py_True : Py_False,
        "finite_math_only", finite_math_only ? Py_True : Py_False,
        "rounding_to_nearest", fp_rounding_ok() ? Py_True : Py_False,
        "subnormals_preserved", fp_subnormals_ok() ? Py_True : Py_False,
        "sizeof_double", (int) sizeof(double),
        "sizeof_float", (int) sizeof(float));
}

/* ---- ganchos de prueba privados (spec §3.12.9 f: R_qsort, rPsort, whimed_i literales) ---- */

static int get_vec(PyObject *obj, Py_buffer *view, bool int32, const char *name)
{
    if (PyObject_GetBuffer(obj, view, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_C_CONTIGUOUS) != 0)
        return -1;
    bool ok = view->ndim == 1 && (int32 ? (view->itemsize == 4 && is_int32_format(view->format))
                                         : (view->itemsize == 8 && is_double_format(view->format)));
    if (!ok) {
        PyErr_Format(PyExc_ValueError, "%s debe ser un vector %s C-contiguo y escribible", name,
                     int32 ? "int32" : "float64");
        PyBuffer_Release(view);
        return -1;
    }
    if (view->shape[0] > INT_MAX) {
        PyErr_Format(PyExc_ValueError, "%s es demasiado largo", name);
        PyBuffer_Release(view);
        return -1;
    }
    return 0;
}

static PyObject *py_r_qsort(PyObject *self, PyObject *arg)
{
    (void) self;
    Py_buffer v;
    if (get_vec(arg, &v, false, "v") != 0) return NULL;
    pymrcd_R_qsort((double *) v.buf, 1, (size_t) v.shape[0]);
    PyBuffer_Release(&v);
    Py_RETURN_NONE;
}

static PyObject *py_rpsort(PyObject *self, PyObject *args)
{
    (void) self;
    PyObject *o;
    int k;
    if (!PyArg_ParseTuple(args, "Oi:_rpsort", &o, &k)) return NULL;
    Py_buffer v;
    if (get_vec(o, &v, false, "x") != 0) return NULL;
    if (k < 0 || (Py_ssize_t) k >= v.shape[0]) {
        PyBuffer_Release(&v);
        PyErr_SetString(PyExc_ValueError, "rPsort requiere 0 <= k < n (sort.c:665)");
        return NULL;
    }
    pymrcd_rPsort((double *) v.buf, (int) v.shape[0], k);
    PyBuffer_Release(&v);
    Py_RETURN_NONE;
}

static PyObject *py_whimed_i(PyObject *self, PyObject *args)
{
    (void) self;
    PyObject *ao, *wo;
    if (!PyArg_ParseTuple(args, "OO:_whimed_i", &ao, &wo)) return NULL;
    Py_buffer av, wv;
    if (get_vec(ao, &av, false, "a") != 0) return NULL;
    if (get_vec(wo, &wv, true, "w") != 0) {
        PyBuffer_Release(&av);
        return NULL;
    }
    if (av.shape[0] != wv.shape[0]) {
        PyBuffer_Release(&av);
        PyBuffer_Release(&wv);
        PyErr_SetString(PyExc_ValueError, "a y w deben tener la misma longitud");
        return NULL;
    }
    int n = (int) av.shape[0];
    size_t nn = n > 0 ? (size_t) n : 1;
    double *a_cand = (double *) malloc(nn * sizeof(double));
    double *a_srt = (double *) malloc(nn * sizeof(double));
    int *w_cand = (int *) malloc(nn * sizeof(int));
    if (a_cand == NULL || a_srt == NULL || w_cand == NULL) {
        free(a_cand);
        free(a_srt);
        free(w_cand);
        PyBuffer_Release(&av);
        PyBuffer_Release(&wv);
        return PyErr_NoMemory();
    }
    double r = pymrcd_whimed_i((double *) av.buf, (int *) wv.buf, n, a_cand, a_srt, w_cand);
    free(a_cand);
    free(a_srt);
    free(w_cand);
    PyBuffer_Release(&av);
    PyBuffer_Release(&wv);
    return PyFloat_FromDouble(r);
}

static PyObject *py_k_l(PyObject *self, PyObject *arg)
{
    (void) self;
    long n = PyLong_AsLong(arg);
    if (n == -1 && PyErr_Occurred()) return NULL;
    if (n < 0 || n > INT_MAX) {
        PyErr_SetString(PyExc_ValueError, "n fuera de rango");
        return NULL;
    }
    return PyLong_FromLongLong((long long) pymrcd_qn_k_L((int) n));
}

static PyMethodDef methods[] = {
    {"qn0_columns", py_qn0_columns, METH_VARARGS, qn0_columns_doc},
    {"ogk_u", py_ogk_u, METH_VARARGS, ogk_u_doc},
    {"default_threads", py_default_threads, METH_NOARGS, default_threads_doc},
    {"build_info", py_build_info, METH_NOARGS, build_info_doc},
    {"_r_qsort", py_r_qsort, METH_O, "R_qsort(v, 1, n) en sitio (qsort.c:164-167)."},
    {"_rpsort", py_rpsort, METH_VARARGS, "rPsort(x, n, k) en sitio (sort.c:724-727)."},
    {"_whimed_i", py_whimed_i, METH_VARARGS,
     "whimed_i(a, w, n) (wgt_himed_templ.h:27-122); modifica a y w en sitio."},
    {"_k_l", py_k_l, METH_O, "k_L de qn_sn.c:154."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "pymrcd._qn_ext",
    "Extensión C de pymrcd: qn0 de robustbase y U de OGK de rrcov (GPL-3.0-or-later).",
    -1,
    methods,
    NULL,
    NULL,
    NULL,
    NULL,
};

PyMODINIT_FUNC PyInit__qn_ext(void)
{
    return PyModule_Create(&moduledef);
}
