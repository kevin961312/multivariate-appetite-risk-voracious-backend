"""``cov_mrcd`` de extremo a extremo contra ``rrcov::CovMrcd`` (protocolo de fidelidad ii y iii).

Nivel (ii) — prueba principal: se inyectan los seis subconjuntos iniciales de R (``initHsets``) y
todo lo demás se calcula en Python. Estricto:

- enteros (``best``, ``iBest``, ``n.csteps``, ``h``) exactos. Única excepción (D9, especificación
  §6 y §11): si un entero difiere **y** el margen de la decisión discreta que lo produce está por
  debajo de la cota propagada de clase B (``TOL_MARGEN`` relativo), se registra como divergencia D9
  documentada (aviso ``DivergenciaD9`` con los márgenes); si el margen es mayor, falla. Cada
  margen solo disculpa la decisión que mide (``_excuse_d9``): el de ``initV`` si cambian
  ``initV``/``setsV``; el de ``obj`` si, con los mismos subconjuntos procesados, C-steps y orden de
  los ``obj``, cambia el óptimo. Cualquier otra diferencia de enteros falla. Márgenes:
  ``initV`` (``min_k |rho_k - cutoff| / cutoff``) y selección del mejor (hueco relativo mínimo de
  ``obj`` entre el óptimo y cualquier otro subconjunto procesado; 0 si hay empate exacto, p. ej.
  C5: conjuntos 1 y 2 convergen al mismo subconjunto en distinto orden). Los márgenes se informan
  siempre (``record_property`` y aviso ``MargenesDecision``);
- en la plataforma de referencia, si ``rho`` coincide bit a bit con R, **todas** las salidas deben
  ser bit a bit (nada más depende de ``eigen`` con los ``hsets`` dados);
- si ``rho`` no coincide (solo puede deberse a ``eigen`` en la selección de ``rho``: D9), rigen las
  tolerancias de extremo a extremo de la especificación §11, declaradas aquí antes de comparar.

Nivel (iii) — desde cero (``r6pack`` en Python). Los subconjuntos iniciales **exigidos** iguales a
R se fijan por el régimen ``(n, p)`` (especificación §6 punto 3b), nunca por nombre de caso:

- ``p >= n`` → solo el 6 (los 1-5 son R1);
- ``ceil(n/2) <= p < n`` → 1, 2, 3, 4 y 6 (el 5 es R1);
- ``p < ceil(n/2)`` → los seis.

Un conjunto R1 distinto se registra (aviso ``DivergenciaR1``). Un conjunto **exigido** distinto
solo se acepta si es atribuible a D9 (§6, párrafo D9): la ``P`` del port y la de R coinciden con la
tolerancia B de autovectores (§11: módulo signo, autoespacios con gap relativo > 1e-8,
``10·p·eps·λmax/gap``) **y** ``initset(r6.x, P_R, h)`` con la ``P`` de R reproduce el subconjunto
de R; entonces se registra (aviso ``DivergenciaD9``) con la diferencia de ``P``
medida (``max|Δ|`` módulo signo). Si no, falla. Siempre se exige lo que no depende de ``eigen``
(``doScale`` y la ``U`` de OGK, bit a bit) y, si algún conjunto difiere, la coherencia interna
(mismo resultado al reinyectar los subconjuntos propios).
"""

from __future__ import annotations

import dataclasses
import math
import warnings
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pytest

from fixtures_r import (
    EPS,
    INTER_CASES,
    REFERENCE_PLATFORM,
    FloatArray,
    Inter,
    assert_r_equal,
)
from pymrcd import MrcdResult, cov_mrcd
from pymrcd.ogk import ogk_u
from pymrcd.r6pack import initset

# Tolerancias de extremo a extremo (especificación §11, columna «Extremo a extremo»).
TOL_RHO_ATOL = 1e-12
TOL_COV = (1e-9, 1e-11)  # cov, icov, target, center (target=1): rtol, atol
TOL_MAH_RTOL = 1e-9
TOL_CRIT_ATOL = 1e-9
TOL_MARGEN = 1e-12
"""Cota propagada de clase B (relativa) para los márgenes de las decisiones discretas."""

RecordProperty = Callable[[str, object], None]


class DivergenciaR1(UserWarning):
    """Divergencia documentada del nivel iii en un subconjunto R1 del régimen (§6)."""


class DivergenciaD9(UserWarning):
    """Divergencia documentada atribuible a ``eigen`` de Accelerate (D9), con su medida."""


class MargenesDecision(UserWarning):
    """Aviso informativo con los márgenes de ``initV`` y de la selección del mejor."""


def required_sets(n: int, p: int) -> frozenset[int]:
    """Subconjuntos iniciales (base 1) exigidos iguales a R desde cero (§6 punto 3b).

    Args:
        n: Observaciones.
        p: Variables.

    Returns:
        Conjunto de índices exigidos.
    """
    if p >= n:
        return frozenset({6})
    if p >= math.ceil(n / 2):
        return frozenset({1, 2, 3, 4, 6})
    return frozenset({1, 2, 3, 4, 5, 6})


def _run(inter: Inter, with_hsets: bool) -> MrcdResult:
    hs = None
    if with_hsets:
        hs = np.asarray(inter.output("hsets_init"), dtype=np.int64) - 1
    return cov_mrcd(
        inter.input_x(),
        alpha=float(inter.manifest["parametros"]["alpha"]),
        target=inter.target,
        init_hsets=hs,
    )


def _rel(a: FloatArray, e: FloatArray) -> float:
    a = np.asarray(a, dtype=np.float64)
    e = np.asarray(e, dtype=np.float64)
    scale = float(np.max(np.abs(e))) or 1.0
    return float(np.max(np.abs(a - e))) / scale


@dataclass(frozen=True)
class Margenes:
    """Márgenes relativos de las decisiones discretas de ``.detmrcd``.

    Attributes:
        init_v: ``min_k |rho_k - cutoff| / cutoff`` (``detmrcd.R:518-535``).
        obj: Hueco relativo mínimo de ``obj`` respecto del óptimo (``detmrcd.R:561-575``).
    """

    init_v: float
    obj: float


def margins(res: MrcdResult) -> Margenes:
    """Márgenes de ``initV`` y de la selección del mejor subconjunto del resultado del port."""
    det = res.detail
    init_v = math.inf
    if det.selection is not None:
        cutoff = det.selection.cutoff
        init_v = min(abs(r.rho - cutoff) / cutoff for r in det.rho_k)
    objs = [obj for _k, _ret, obj in det.csteps]
    best = min(range(len(objs)), key=lambda i: objs[i])
    gaps = [abs(o - objs[best]) / abs(objs[best]) for i, o in enumerate(objs) if i != best]
    return Margenes(init_v=init_v, obj=min(gaps) if gaps else math.inf)


def _integer_mismatches(inter: Inter, res: MrcdResult) -> list[str]:
    """Enteros que difieren de R (``h``, ``n.obs`` y ``alpha`` se exigen siempre)."""
    assert res.quan == int(inter.output("h").item())
    assert res.n_obs == inter.input_x().shape[0]
    assert res.alpha == float(inter.output("alpha").item())
    out = []
    pairs = (
        ("best", res.best + 1, inter.output("best")),
        ("iBest", res.i_best + 1, inter.output("iBest")),
        ("n.csteps", res.n_csteps, inter.output("n_csteps")),
    )
    for name, got, ref in pairs:
        if not np.array_equal(got, ref.ravel().astype(np.int64)):
            out.append(f"{name}: {got.tolist()} vs R {ref.ravel().astype(np.int64).tolist()}")
    return out


def _check_integers(
    inter: Inter, res: MrcdResult, record_property: RecordProperty, nivel: str
) -> bool:
    """Enteros exactos o divergencia D9 documentada por margen; informa los márgenes.

    Returns:
        ``True`` si ``best`` coincide con R (las salidas continuas son comparables).
    """
    m = margins(res)
    record_property("margen_initV", m.init_v)
    record_property("margen_obj", m.obj)
    warnings.warn(
        f"{inter.case} ({nivel}): margen initV = {m.init_v:.3g}, margen obj = {m.obj:.3g} "
        f"(cota {TOL_MARGEN:g})",
        MargenesDecision,
        stacklevel=1,
    )
    bad = _integer_mismatches(inter, res)
    if not bad:
        return True
    reason = _excuse_d9(inter, res, m, bad, nivel)
    warnings.warn(
        f"{inter.case} ({nivel}): divergencia D9 en enteros ({'; '.join(bad)}): {reason}",
        DivergenciaD9,
        stacklevel=1,
    )
    return bool(np.array_equal(res.best + 1, inter.output("best").ravel().astype(np.int64)))


def _excuse_d9(inter: Inter, res: MrcdResult, m: Margenes, bad: list[str], nivel: str) -> str:
    """Atribuye una diferencia de enteros a la decisión discreta que realmente cambió, o falla.

    - Si ``initV``/``setsV`` del port difieren de ``rs_initV``/``rs_setsV`` de R, solo disculpa el
      margen de ``initV`` (``< TOL_MARGEN``); el resto de enteros es consecuencia de ese cambio.
    - Si coinciden, los C-steps deben coincidir (``n.csteps`` igual) y solo pueden cambiar
      ``best``/``iBest``; lo disculpa el margen de ``obj`` siempre que los subconjuntos procesados
      y el orden de los ``obj`` (fuera del grupo casi empatado con el óptimo) coincidan con los
      ``cs_obj_k*`` de R.
    - Cualquier otra diferencia (p. ej. en los C-steps) falla.

    Returns:
        Motivo documentado de la divergencia D9.
    """
    det = res.detail
    head = f"{inter.case} ({nivel}): enteros distintos de R ({'; '.join(bad)})"
    init_r = int(inter.scalar("rs_initV")) - 1
    sets_r = (inter.ints("rs_setsV") - 1) if inter.has("rs_setsV") else np.array([], np.int64)
    if det.init_v != init_r or not np.array_equal(det.sets_v, sets_r):
        assert m.init_v < TOL_MARGEN, (
            f"{head}: cambia initV/setsV ({det.init_v + 1}/{(det.sets_v + 1).tolist()} vs R "
            f"{init_r + 1}/{(sets_r + 1).tolist()}) con margen initV {m.init_v:.3g} >= cota"
        )
        return f"cambia initV/setsV con margen initV {m.init_v:.3g} < {TOL_MARGEN:g}"
    n_cs_r = inter.output("n_csteps").ravel().astype(np.int64)
    assert np.array_equal(res.n_csteps, n_cs_r), f"{head}: difieren los C-steps (no disculpable)"
    assert m.obj < TOL_MARGEN, f"{head}: cambia el óptimo con margen obj {m.obj:.3g} >= cota"
    obj_py = {k: obj for k, _ret, obj in det.csteps}
    assert all(inter.has(f"cs_obj_k{k + 1}") for k in obj_py), (
        f"{head}: faltan cs_obj_k* de R; no se puede atribuir el cambio de óptimo a D9"
    )
    obj_r = {k: inter.scalar(f"cs_obj_k{k + 1}") for k in obj_py}

    def near(objs: dict[int, float]) -> set[int]:
        best = min(objs.values())
        return {k for k, o in objs.items() if abs(o - best) / abs(best) < TOL_MARGEN}

    tie_py, tie_r = near(obj_py), near(obj_r)
    rest_py = sorted((k for k in obj_py if k not in tie_py), key=lambda k: obj_py[k])
    rest_r = sorted((k for k in obj_r if k not in tie_r), key=lambda k: obj_r[k])
    assert (tie_py, rest_py) == (tie_r, rest_r), (
        f"{head}: el orden de los obj no coincide con R (casi empatados {sorted(tie_py)} vs "
        f"{sorted(tie_r)}; resto {rest_py} vs {rest_r})"
    )
    return (
        f"mismos subconjuntos procesados y orden de obj; cambia el óptimo entre casi empatados "
        f"{sorted(k + 1 for k in tie_py)} con margen obj {m.obj:.3g} < {TOL_MARGEN:g}"
    )


def _check_continuous(inter: Inter, res: MrcdResult) -> None:
    p = res.cov.shape[0]
    rho_r = float(inter.output("rho").item())
    assert_r_equal(res.cnp2, inter.output("calpha").item(), "scfac", "cnp2")
    target_r = inter.get("out_target") if inter.has("out_target") else None
    exact = REFERENCE_PLATFORM and res.rho == rho_r
    if exact:
        # Nada depende ya de eigen: bit a bit.
        assert_r_equal(res.center, inter.output("center").ravel(), "E", "center")
        assert_r_equal(res.cov, inter.output("cov").reshape(p, p), "B", "cov")
        assert_r_equal(res.icov, inter.output("icov").reshape(p, p), "B", "icov")
        assert_r_equal(res.mah, inter.output("mah").ravel(), "B", "mah")
        assert_r_equal(res.crit, inter.output("crit").item(), "B", "crit")
        if target_r is not None:
            assert_r_equal(res.target, target_r, "B", "target")
        return
    assert abs(res.rho - rho_r) <= TOL_RHO_ATOL, f"rho: |Δ|={abs(res.rho - rho_r):.3g}"
    rtol, atol = TOL_COV
    if inter.equicorrelation:
        np.testing.assert_allclose(res.center, inter.output("center").ravel(), rtol=rtol, atol=atol)
    else:  # center (target=0) solo depende de hindex: exacto (§11)
        assert_r_equal(res.center, inter.output("center").ravel(), "E", "center")
    np.testing.assert_allclose(res.cov, inter.output("cov").reshape(p, p), rtol=rtol, atol=atol)
    np.testing.assert_allclose(res.icov, inter.output("icov").reshape(p, p), rtol=rtol, atol=atol)
    np.testing.assert_allclose(res.mah, inter.output("mah").ravel(), rtol=TOL_MAH_RTOL, atol=0)
    assert abs(res.crit - float(inter.output("crit").item())) <= TOL_CRIT_ATOL
    if target_r is not None:
        np.testing.assert_allclose(res.target, target_r, rtol=rtol, atol=atol)


@dataclass(frozen=True)
class DiferenciaP:
    """Diferencia entre la ``P_k`` del port y la de R.

    Attributes:
        max_abs: ``max|Δ|`` módulo signo sobre todas las columnas.
        within_b: ``True`` si las columnas con gap relativo > 1e-8 cumplen la tolerancia B (§11).
        flips: Columnas con signo opuesto.
    """

    max_abs: float
    within_b: bool
    flips: int


def p_difference(got: FloatArray, ref: FloatArray, vals: FloatArray) -> DiferenciaP:
    """Mide ``P`` del port frente a la de R con la regla de autovectores de clase B (§11).

    Args:
        got: ``P`` del port.
        ref: ``P`` de R.
        vals: Autovalores de R (orden de las columnas).

    Returns:
        ``DiferenciaP``.
    """
    p = vals.shape[0]
    lam_max = float(np.max(np.abs(vals)))
    max_abs = 0.0
    within = True
    flips = 0
    for i in range(p):
        s = 1.0 if float(got[:, i] @ ref[:, i]) >= 0 else -1.0
        flips += int(s < 0)
        err = float(np.max(np.abs(s * got[:, i] - ref[:, i])))
        max_abs = max(max_abs, err)
        gaps = [abs(vals[i] - vals[j]) for j in (i - 1, i + 1) if 0 <= j < p]
        gap = min(gaps) if gaps else math.inf
        if lam_max == 0 or gap / lam_max <= 1e-8:
            continue
        within &= err <= 10 * p * EPS * lam_max / gap
    return DiferenciaP(max_abs=max_abs, within_b=within, flips=flips)


@pytest.mark.parametrize("case", INTER_CASES)
def test_nivel_ii_hsets_de_r(case: str, record_property: RecordProperty) -> None:
    """Extremo a extremo con los ``initHsets`` de R (prueba principal de fidelidad)."""
    inter = Inter(case)
    res = _run(inter, with_hsets=True)
    if _check_integers(inter, res, record_property, "ii"):
        _check_continuous(inter, res)


def _coherence(inter: Inter, res: MrcdResult) -> None:
    """El resultado es el que da el algoritmo con esos mismos subconjuntos (coherencia interna)."""
    again = cov_mrcd(
        inter.input_x(),
        alpha=float(inter.manifest["parametros"]["alpha"]),
        target=inter.target,
        init_hsets=res.init_hsets,
    )
    assert np.array_equal(again.cov, res.cov)
    assert np.array_equal(again.best, res.best)


@pytest.mark.parametrize("case", INTER_CASES)
def test_nivel_iii_desde_cero(case: str, record_property: RecordProperty) -> None:
    """Desde cero (``r6pack`` en Python), con los conjuntos exigidos según ``(n, p)``."""
    inter = Inter(case)
    res = _run(inter, with_hsets=False)
    r6 = res.detail.r6
    assert r6 is not None
    # Lo que no depende de eigen es exacto siempre (si el intermedio está versionado; en los casos
    # grandes solo vive en local y el resto del nivel iii usa únicamente ficheros versionados).
    if inter.has("r6_x"):
        assert_r_equal(r6.x, inter.get("r6_x"), "E", "r6_x")
    if inter.has("r6_U"):
        assert_r_equal(ogk_u(r6.x), inter.get("r6_U"), "E", "r6_U")
    n, p = res.n_obs, res.cov.shape[0]
    required = required_sets(n, p)
    record_property("exigidos", sorted(required))
    hs_r = np.asarray(inter.output("hsets_init"), dtype=np.int64) - 1
    differ = [
        k for k in range(1, 7) if not np.array_equal(res.init_hsets[:, k - 1], hs_r[:, k - 1])
    ]
    record_property("distintos", differ)

    d9: list[str] = []
    for k in sorted(set(differ) & required):
        if not inter.has(f"r6_P{k}"):
            pytest.skip(
                f"{case}: conjunto exigido {k} distinto de R y r6_P{k} no versionado: no se puede "
                "comprobar la atribución a D9; regenerar con tools/r/"
            )
        p_r = inter.get(f"r6_P{k}")
        diff = p_difference(r6.p_mats[k - 1], p_r, inter.get(f"r6_ev{k}").ravel())
        record_property(f"dP{k}", diff.max_abs)
        assert diff.within_b, (
            f"{case} (n={n}, p={p}): conjunto exigido {k} distinto de R y P{k} fuera de la "
            f"tolerancia B (max|Δ| módulo signo = {diff.max_abs:.3g}): no atribuible a D9"
        )
        # Con la P de R, initset del port debe reproducir el subconjunto de R: la diferencia
        # viene solo de P (eigen, D9), no del resto de la cadena.
        assert np.array_equal(initset(r6.x, p_r, res.quan).ord, hs_r[:, k - 1]), (
            f"{case}: initset(r6.x, P{k} de R, h) no reproduce el hsets de R: no atribuible a D9"
        )
        d9.append(f"{k} (max|Δ P{k}| módulo signo = {diff.max_abs:.3g}, signos {diff.flips})")
    if d9:
        warnings.warn(
            f"{case} (n={n}, p={p}): conjuntos exigidos distintos de R atribuibles a D9 (P dentro "
            f"de la tolerancia B): {', '.join(d9)}",
            DivergenciaD9,
            stacklevel=1,
        )
    r1 = sorted(set(differ) - required)
    if r1:
        warnings.warn(
            f"{case} (n={n}, p={p}): subconjuntos R1 distintos de R = {r1} (exigidos "
            f"{sorted(required)} iguales salvo D9 {[s.split()[0] for s in d9]}); rho {res.rho!r} "
            f"vs {float(inter.output('rho').item())!r}; best igual = "
            f"{bool(np.array_equal(res.best + 1, inter.output('best').ravel()))}; "
            f"max rel cov = {_rel(res.cov, inter.output('cov').reshape(res.cov.shape)):.3g}",
            DivergenciaR1,
            stacklevel=1,
        )
    if differ:
        # rho, best y salidas continuas no son comparables (§6): coherencia interna.
        _coherence(inter, res)
        return
    if _check_integers(inter, res, record_property, "iii"):
        _check_continuous(inter, res)


@pytest.mark.parametrize(
    ("n", "p", "expected"),
    [
        (50, 200, {6}),
        (50, 50, {6}),
        (60, 40, {1, 2, 3, 4, 6}),
        (60, 30, {1, 2, 3, 4, 6}),
        (61, 30, {1, 2, 3, 4, 5, 6}),
        (100, 20, {1, 2, 3, 4, 5, 6}),
    ],
)
def test_required_sets_by_regime(n: int, p: int, expected: set[int]) -> None:
    """Régimen de §6 punto 3b, incluidas las fronteras ``p = n`` y ``p = ceil(n/2)``."""
    assert required_sets(n, p) == expected


def test_excusa_d9_atada_a_la_decision(record_property: RecordProperty) -> None:
    """Una diferencia de enteros que no corresponde a la decisión casi empatada falla (C7)."""
    inter = Inter("C7")
    res = _run(inter, with_hsets=True)
    m = margins(res)
    other = dataclasses.replace(res, n_csteps=res.n_csteps + 1)
    with pytest.raises(AssertionError, match="C-steps"):
        _excuse_d9(inter, other, Margenes(init_v=m.init_v, obj=0.0), ["n.csteps"], "test")
    with pytest.raises(AssertionError, match="margen obj"):
        _excuse_d9(inter, res, m, ["iBest"], "test")
    tied = _excuse_d9(inter, res, Margenes(init_v=m.init_v, obj=0.0), ["iBest"], "test")
    assert "cambia el óptimo" in tied
    det = dataclasses.replace(res.detail, init_v=res.detail.init_v + 1)
    moved = dataclasses.replace(res, detail=det)
    with pytest.raises(AssertionError, match="initV/setsV"):
        _excuse_d9(inter, moved, m, ["best"], "test")
    assert "initV" in _excuse_d9(inter, moved, Margenes(init_v=0.0, obj=m.obj), ["best"], "test")
    record_property("margenes_C7", (m.init_v, m.obj))
