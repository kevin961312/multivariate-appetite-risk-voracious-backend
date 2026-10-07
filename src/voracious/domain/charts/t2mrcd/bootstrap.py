"""Calibración por bootstrap del límite de control de T²MRCD (``docs/metodos/t2mrcd.md``).

Decidido (dueño, 2026-10-07): cada réplica remuestrea **con reemplazo** ``n_clean`` filas de las
observaciones limpias, reajusta MRCD sobre la muestra (mismos parámetros) y calcula el T² de las
filas de la muestra. Con la ``LimitAggregation`` de producción se toma el cuantil
``1 - alpha_limit`` de cada réplica y el límite es el **promedio** de esos B cuantiles (no el
cuantil del conjunto de todos los T²; defaults en ``params.py``, P4). Con el criterio de
producción ``n_clean == h``; si se inyecta otro ``clean_criterion``, el tamaño de cada muestra es
su ``n_clean``.
Ese mismo límite se usa en Fase I (atípicos del histórico) y en Fase II (señales): no hay un
límite aparte de Fase II.

Reparto (M4): las réplicas se ejecutan con un ``TaskMapper``; ``x_clean`` y los parámetros van una
sola vez en ``ReplicateContext`` y cada ``ReplicateTask`` lleva solo su índice y su semilla. Las
semillas salen de ``SeedSequence(seed).spawn(B)``, así que el resultado no depende del orden ni del
número de procesos. ``run_replicate`` está a nivel de módulo y todo es *picklable*.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from voracious.domain.charts.t2mrcd.params import LimitAggregation
from voracious.domain.charts.t2mrcd.statistic import t2
from voracious.domain.common import (
    DomainError,
    EstimationError,
    FloatMatrix,
    FloatVector,
    TaskMapper,
)
from voracious.domain.estimators.mrcd import MRCDParams, fit_mrcd

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

BOOTSTRAP_REPLICATE_FAILED = "BOOTSTRAP_REPLICATE_FAILED"
"""Código de error: una réplica falló y con ella toda la Fase I (sin descartar réplicas)."""

BOOTSTRAP_LIMIT_NOT_FINITE = "BOOTSTRAP_LIMIT_NOT_FINITE"
"""Código de error: la agregación devolvió un límite no finito."""

_EMPTY = np.empty(0, dtype=np.float64)


@dataclass(frozen=True, eq=False)
class ReplicateContext:
    """Datos compartidos por todas las réplicas (se envían una sola vez).

    Attributes:
        x_clean: Observaciones limpias ``n_clean x p``.
        mrcd: Parámetros de MRCD de cada réplica.
    """

    x_clean: FloatMatrix
    mrcd: MRCDParams


@dataclass(frozen=True)
class ReplicateTask:
    """Una réplica: su índice y su semilla (hija de ``SeedSequence(seed)``).

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
        code: Código del ``DomainError`` original.
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
        t2: T² de las filas de la muestra remuestreada (vacío si falló).
        failure: Error de la réplica, o ``None`` si terminó bien.
    """

    index: int
    t2: FloatVector
    failure: ReplicateFailure | None = None


@dataclass(frozen=True)
class BootstrapLimits:
    """Límite calibrado y la configuración que lo produjo.

    Attributes:
        limit: Límite de control, común a Fase I y Fase II.
        n_replicates: Número de réplicas B.
        seed: Semilla raíz.
        n_clean: Número de observaciones limpias remuestreadas (tamaño de cada muestra).
        alpha_limit: Nivel del límite (cuantil de probabilidad ``1 - alpha_limit``).
    """

    limit: float
    n_replicates: int
    seed: int
    n_clean: int
    alpha_limit: float


def replicate_tasks(seed: int, n_replicates: int) -> list[ReplicateTask]:
    """Crea las tareas con semillas ``SeedSequence(seed).spawn(n_replicates)``.

    Args:
        seed: Semilla raíz.
        n_replicates: Número de réplicas B.

    Returns:
        Las tareas en orden de índice.
    """
    children = np.random.SeedSequence(seed).spawn(n_replicates)
    return [ReplicateTask(index=i, seed=child) for i, child in enumerate(children)]


def run_replicate(context: ReplicateContext, task: ReplicateTask) -> ReplicateOutcome:
    """Ejecuta una réplica bootstrap (función pura a nivel de módulo).

    Los ``DomainError`` (p. ej. ``MRCD_FIT_FAILED``) se devuelven como ``ReplicateFailure`` para
    que crucen procesos sin depender de cómo se serializan las excepciones; cualquier otra
    excepción se propaga.

    Args:
        context: Observaciones limpias y parámetros de MRCD.
        task: Índice y semilla de la réplica.

    Returns:
        Los T² de la muestra remuestreada, o el error de la réplica.
    """
    x_clean = context.x_clean
    n_clean = x_clean.shape[0]
    rng = np.random.default_rng(task.seed)
    in_sample = rng.integers(0, n_clean, size=n_clean)
    sample = x_clean[in_sample]
    try:
        fit = fit_mrcd(sample, context.mrcd)
        values = t2(fit, sample)
    except DomainError as exc:
        failure = ReplicateFailure(code=exc.code, message=exc.message, details=exc.details)
        return ReplicateOutcome(task.index, _EMPTY, failure)
    return ReplicateOutcome(task.index, values)


def calibrate_limits(
    x_clean: FloatMatrix,
    *,
    mrcd: MRCDParams,
    n_replicates: int,
    seed: int,
    alpha: float,
    aggregation: LimitAggregation,
    mapper: TaskMapper,
) -> BootstrapLimits:
    """Calibra el límite de control (común a Fase I y Fase II) con B réplicas bootstrap.

    Args:
        x_clean: Observaciones limpias ``n_clean x p``.
        mrcd: Parámetros de MRCD de cada réplica.
        n_replicates: Número de réplicas B.
        seed: Semilla raíz.
        alpha: Nivel del límite (``alpha_limit``, proporción); el cuantil usa ``1 - alpha``.
            No es el ``alpha`` de MRCD (que va en ``mrcd``).
        aggregation: Agregación de los T² de las réplicas en un límite.
        mapper: Reparto de las réplicas.

    Returns:
        El límite calibrado.

    Raises:
        EstimationError: ``BOOTSTRAP_REPLICATE_FAILED`` si alguna réplica falla (se informa la
            de menor índice) o ``BOOTSTRAP_LIMIT_NOT_FINITE`` si el límite no es finito.
    """
    context = ReplicateContext(x_clean=x_clean, mrcd=mrcd)
    outcomes = sorted(
        mapper.map(run_replicate, context, replicate_tasks(seed, n_replicates)),
        key=lambda o: o.index,
    )
    if [o.index for o in outcomes] != list(range(n_replicates)):
        msg = "el TaskMapper no devolvió exactamente una salida por réplica"
        raise RuntimeError(msg)
    for outcome in outcomes:
        if outcome.failure is not None:
            raise EstimationError(
                BOOTSTRAP_REPLICATE_FAILED,
                f"la réplica bootstrap {outcome.index} falló: {outcome.failure.message}",
                details={
                    "replicate_index": outcome.index,
                    "error_code": outcome.failure.code,
                    "error_message": outcome.failure.message,
                    "error_details": dict(outcome.failure.details),
                },
            )
    limit = float(aggregation([o.t2 for o in outcomes], alpha))
    if not np.isfinite(limit):
        raise EstimationError(
            BOOTSTRAP_LIMIT_NOT_FINITE,
            "la agregación bootstrap devolvió un límite no finito",
            details={"limit": str(limit)},
        )
    return BootstrapLimits(
        limit=limit,
        n_replicates=n_replicates,
        seed=seed,
        n_clean=int(x_clean.shape[0]),
        alpha_limit=alpha,
    )
