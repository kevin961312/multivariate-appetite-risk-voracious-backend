"""Calibración por bootstrap de los límites de Fase I y Fase II de T²MRCD (``t2mrcd.md``).

Decidido (dueño, 2026-10-07): cada réplica toma su muestra de ajuste y sus observaciones nuevas
del ``ReplicateSampler`` (en producción, ``BootstrapOOBSampler``: con reemplazo, ``n_clean`` filas
limpias, y las *out-of-bag*), reajusta el estimador **sobre la muestra** y calcula con ese ajuste
los T² de la muestra (``t2_in``) y los de las observaciones nuevas (``t2_oob``). Fase I y Fase II
comparten réplicas: un único ajuste por réplica.

Cada límite es la agregación de producción ``pooled_quantile``: el cuantil ``1 - alpha`` del *pool*
de los T² de todas las réplicas (``alpha_limit`` en Fase I, ``phase2_alpha_limit`` en Fase II).
Junto con cada límite se informa su error Monte Carlo (M6, ver ``aggregation.py``).

Reparto (M4): las réplicas se ejecutan con un ``TaskMapper``; ``x_clean``, el estimador y el
muestreador van una sola vez en ``ReplicateContext`` y cada ``ReplicateTask`` lleva solo su índice
y su semilla (huecos fijos de ``seeds.py``), así que el resultado no depende del orden ni del
número de procesos. ``run_replicate`` está a nivel de módulo y todo es *picklable*.

Sin *fallbacks*: una réplica que falla (estimador o *out-of-bag* vacío) hace fallar la calibración;
nunca se descarta.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

import numpy as np

from voracious.domain.charts.t2mrcd.params import LimitAggregation
from voracious.domain.charts.t2mrcd.phase2_limit import BOOTSTRAP_OOB_EMPTY, ReplicateSampler
from voracious.domain.charts.t2mrcd.seeds import SpawnKey, child
from voracious.domain.charts.t2mrcd.statistic import t2
from voracious.domain.common import (
    DomainError,
    EstimationError,
    FloatMatrix,
    FloatVector,
    LocationScatterEstimator,
    TaskMapper,
)

__all__ = [
    "BOOTSTRAP_LIMIT_NOT_FINITE",
    "BOOTSTRAP_REPLICATE_FAILED",
    "BootstrapLimits",
    "ReplicateContext",
    "ReplicateFailure",
    "ReplicateOutcome",
    "ReplicateTask",
    "calibrate_limits",
    "replicate_tasks",
    "run_replicate",
]

BOOTSTRAP_REPLICATE_FAILED: Final = "BOOTSTRAP_REPLICATE_FAILED"
"""Código de error: una réplica falló y con ella toda la calibración (sin descartar réplicas)."""

BOOTSTRAP_LIMIT_NOT_FINITE: Final = "BOOTSTRAP_LIMIT_NOT_FINITE"
"""Código de error: la agregación devolvió un límite no finito."""

_EMPTY = np.empty(0, dtype=np.float64)

_REPLICATES_SLOT: Final = 0
"""Hueco de las réplicas dentro de la clave de una calibración (``k + (0, i)``)."""

_MC_ERROR_SLOT: Final = 1
"""Hueco del diagnóstico del error Monte Carlo (``k + (1,)``)."""


@dataclass(frozen=True, eq=False)
class ReplicateContext:
    """Datos compartidos por todas las réplicas (se envían una sola vez).

    Attributes:
        x_clean: Observaciones limpias ``n_clean x p``.
        estimator: Estimador que se reajusta en cada réplica (en producción, MRCD).
        sampler: Genera la muestra de ajuste y las observaciones nuevas de cada réplica.
    """

    x_clean: FloatMatrix
    estimator: LocationScatterEstimator
    sampler: ReplicateSampler


@dataclass(frozen=True)
class ReplicateTask:
    """Una réplica: su índice y su semilla.

    Attributes:
        index: Índice de la réplica, base 0.
        seed: Semilla propia de la réplica.
    """

    index: int
    seed: np.random.SeedSequence


@dataclass(frozen=True)
class ReplicateFailure:
    """Error de una réplica, en forma serializable.

    Attributes:
        code: Código del ``DomainError`` original (o ``BOOTSTRAP_OOB_EMPTY``).
        message: Mensaje original.
        details: Detalles originales.
    """

    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class ReplicateOutcome:
    """Resultado de una réplica.

    Attributes:
        index: Índice de la réplica.
        t2_in: T² de las filas de la muestra de ajuste (vacío si falló).
        t2_oob: T² de las observaciones nuevas con el ajuste de la muestra (vacío si falló).
        failure: Error de la réplica, o ``None`` si terminó bien.
    """

    index: int
    t2_in: FloatVector
    t2_oob: FloatVector
    failure: ReplicateFailure | None = None


@dataclass(frozen=True)
class BootstrapLimits:
    """Límites calibrados y la configuración que los produjo.

    Attributes:
        phase1_limit: Límite de Fase I (cuantil ``1 - alpha_limit`` de los T² de las muestras).
        phase2_limit: Límite de Fase II (cuantil ``1 - phase2_alpha_limit`` de los T²
            *out-of-bag*).
        n_replicates: Número de réplicas B.
        seed: Semilla raíz.
        spawn_key: Clave del hijo de ``SeedSequence(seed)`` usado en esta calibración.
        n_clean: Número de observaciones limpias remuestreadas.
        alpha_limit: Nivel del límite de Fase I.
        phase2_alpha_limit: Nivel del límite de Fase II.
        oob_size_min: Mínimo de observaciones nuevas (*out-of-bag*) entre réplicas.
        oob_size_mean: Media de observaciones nuevas por réplica.
        phase1_mc_error: Error Monte Carlo de ``phase1_limit`` (M6; ver ``aggregation.py``), o
            ``None`` si no está disponible (``B = 1``).
        phase2_mc_error: Error Monte Carlo de ``phase2_limit``, o ``None`` si no está disponible.
        estimator_name: Estimador de las réplicas (``"mrcd"`` en producción).
        sampler_name: Muestreador de las réplicas (``"bootstrap_oob"`` en producción).
    """

    phase1_limit: float
    phase2_limit: float
    n_replicates: int
    seed: int
    spawn_key: SpawnKey
    n_clean: int
    alpha_limit: float
    phase2_alpha_limit: float
    oob_size_min: int
    oob_size_mean: float
    phase1_mc_error: float | None
    phase2_mc_error: float | None
    estimator_name: str
    sampler_name: str

    @property
    def phase2_exceeds_phase1(self) -> bool:
        """Diagnóstico (Q9): ``phase2_limit > phase1_limit``; lo esperado, pero no se exige."""
        return self.phase2_limit > self.phase1_limit


def replicate_tasks(seed: int, n_replicates: int, spawn_key: SpawnKey = ()) -> list[ReplicateTask]:
    """Crea las tareas: la réplica ``i`` usa el hijo ``spawn_key + (0, i)`` de ``seed``.

    Args:
        seed: Semilla raíz.
        n_replicates: Número de réplicas B.
        spawn_key: Clave de la calibración (hueco fijo, ``seeds.py``).

    Returns:
        Las tareas en orden de índice.
    """
    children = child(seed, (*spawn_key, _REPLICATES_SLOT)).spawn(n_replicates)
    return [ReplicateTask(index=i, seed=c) for i, c in enumerate(children)]


def run_replicate(context: ReplicateContext, task: ReplicateTask) -> ReplicateOutcome:
    """Ejecuta una réplica bootstrap (función pura a nivel de módulo).

    Los ``DomainError`` del estimador se devuelven como ``ReplicateFailure`` para que crucen
    procesos sin depender de cómo se serializan las excepciones; cualquier otra excepción se
    propaga. Si la réplica no deja observaciones nuevas, falla con ``BOOTSTRAP_OOB_EMPTY`` antes de
    ajustar.

    Args:
        context: Observaciones limpias, estimador y muestreador.
        task: Índice y semilla de la réplica.

    Returns:
        Los T² de la muestra y de las observaciones nuevas, o el error de la réplica.
    """
    rng = np.random.default_rng(task.seed)
    sample, new = context.sampler.sample(context.x_clean, rng)
    if new.shape[0] == 0:
        failure = ReplicateFailure(
            code=BOOTSTRAP_OOB_EMPTY,
            message="la réplica no dejó observaciones out-of-bag",
            details={"n_clean": int(context.x_clean.shape[0])},
        )
        return ReplicateOutcome(task.index, _EMPTY, _EMPTY, failure)
    try:
        fit = context.estimator.fit(sample)
        t2_in = t2(fit, sample)
        t2_oob = t2(fit, new)
    except DomainError as exc:
        failure = ReplicateFailure(code=exc.code, message=exc.message, details=exc.details)
        return ReplicateOutcome(task.index, _EMPTY, _EMPTY, failure)
    return ReplicateOutcome(task.index, t2_in, t2_oob)


def _raise_first_failure(outcomes: list[ReplicateOutcome]) -> None:
    """Lanza el error de la réplica fallida de menor índice, si la hay.

    Args:
        outcomes: Resultados en orden de índice.

    Raises:
        EstimationError: ``BOOTSTRAP_OOB_EMPTY`` o ``BOOTSTRAP_REPLICATE_FAILED``.
    """
    for outcome in outcomes:
        failure = outcome.failure
        if failure is None:
            continue
        code = (
            BOOTSTRAP_OOB_EMPTY
            if failure.code == BOOTSTRAP_OOB_EMPTY
            else (BOOTSTRAP_REPLICATE_FAILED)
        )
        raise EstimationError(
            code,
            f"la réplica bootstrap {outcome.index} falló: {failure.message}",
            details={
                "replicate_index": outcome.index,
                "error_code": failure.code,
                "error_message": failure.message,
                "error_details": dict(failure.details),
            },
        )


def _finite(value: float, which: str) -> float:
    """Comprueba que un límite sea finito.

    Args:
        value: Límite.
        which: ``"phase1"`` o ``"phase2"``.

    Returns:
        El mismo valor.

    Raises:
        EstimationError: ``BOOTSTRAP_LIMIT_NOT_FINITE``.
    """
    if not np.isfinite(value):
        raise EstimationError(
            BOOTSTRAP_LIMIT_NOT_FINITE,
            "la agregación bootstrap devolvió un límite no finito",
            details={"limit": str(value), "phase": which},
        )
    return value


def _optional_float(value: float | None) -> float | None:
    """Convierte a ``float`` de Python salvo ``None`` (error Monte Carlo no disponible).

    Args:
        value: Valor o ``None``.

    Returns:
        El valor como ``float``, o ``None``.
    """
    return None if value is None else float(value)


def calibrate_limits(
    x_clean: FloatMatrix,
    *,
    estimator: LocationScatterEstimator,
    sampler: ReplicateSampler,
    n_replicates: int,
    seed: int,
    spawn_key: SpawnKey = (),
    alpha: float,
    phase2_alpha: float,
    aggregation: LimitAggregation,
    phase2_aggregation: LimitAggregation,
    mapper: TaskMapper,
) -> BootstrapLimits:
    """Calibra los límites de Fase I y Fase II con B réplicas compartidas.

    Args:
        x_clean: Observaciones limpias ``n_clean x p``.
        estimator: Estimador de cada réplica (en producción, ``MRCDEstimator``).
        sampler: Muestreador (en producción, ``BootstrapOOBSampler``).
        n_replicates: Número de réplicas B.
        seed: Semilla raíz.
        spawn_key: Clave de esta calibración bajo ``seed`` (hueco fijo, ``seeds.py``).
        alpha: Nivel del límite de Fase I (``alpha_limit``); no es el ``alpha`` de MRCD.
        phase2_alpha: Nivel del límite de Fase II (``phase2_alpha_limit``).
        aggregation: Agregación de Fase I.
        phase2_aggregation: Agregación de Fase II.
        mapper: Reparto de las réplicas.

    Returns:
        Los límites calibrados.

    Raises:
        EstimationError: ``BOOTSTRAP_REPLICATE_FAILED`` o ``BOOTSTRAP_OOB_EMPTY`` si alguna réplica
            falla (se informa la de menor índice), o ``BOOTSTRAP_LIMIT_NOT_FINITE``.
    """
    context = ReplicateContext(x_clean=x_clean, estimator=estimator, sampler=sampler)
    outcomes = sorted(
        mapper.map(run_replicate, context, replicate_tasks(seed, n_replicates, spawn_key)),
        key=lambda o: o.index,
    )
    if [o.index for o in outcomes] != list(range(n_replicates)):
        msg = "el TaskMapper no devolvió exactamente una salida por réplica"
        raise RuntimeError(msg)
    _raise_first_failure(outcomes)
    t2_in = [o.t2_in for o in outcomes]
    t2_oob = [o.t2_oob for o in outcomes]
    phase1_limit = _finite(float(aggregation(t2_in, alpha)), "phase1")
    phase2_limit = _finite(float(phase2_aggregation(t2_oob, phase2_alpha)), "phase2")
    mc_seed = (*spawn_key, _MC_ERROR_SLOT)
    oob_sizes = np.array([v.size for v in t2_oob], dtype=np.int64)
    return BootstrapLimits(
        phase1_limit=phase1_limit,
        phase2_limit=phase2_limit,
        n_replicates=n_replicates,
        seed=seed,
        spawn_key=tuple(spawn_key),
        n_clean=int(x_clean.shape[0]),
        alpha_limit=alpha,
        phase2_alpha_limit=phase2_alpha,
        oob_size_min=int(oob_sizes.min()),
        oob_size_mean=float(oob_sizes.mean()),
        phase1_mc_error=_optional_float(
            aggregation.mc_error(t2_in, alpha, child(seed, (*mc_seed, 0)))
        ),
        phase2_mc_error=_optional_float(
            phase2_aggregation.mc_error(t2_oob, phase2_alpha, child(seed, (*mc_seed, 1)))
        ),
        estimator_name=estimator.name,
        sampler_name=sampler.name,
    )
