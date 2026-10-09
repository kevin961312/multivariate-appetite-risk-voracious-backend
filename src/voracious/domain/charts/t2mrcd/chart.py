"""Carta T²MRCD: Fase I (MRCD + límites bootstrap), Fase II (T² y señales) y recalibración.

Estimador declarado: MRCD, siempre (ADR 0002, ADR 0004 punto 5). Sin *fallbacks*: si MRCD o una
réplica fallan, la operación termina en ``failed`` con su código. Las decisiones P2, P4, P6 y las
de Fase II y recalibración (Q1 a Q9, dueño 2026-10-07) están en ``params.py``, ``aggregation.py``,
``phase2_limit.py``, ``comparison.py`` y ``revalidation.py``. Se conserva el mecanismo de
decisiones pendientes: un campo decisivo en ``None`` lanza ``MethodDecisionPendingError``
(``T2MRCD_DECISION_PENDING``) **antes** de ajustar nada.

Límite operativo (Q2): la versión inicial vigila con ``phase1_limit`` de forma provisional
(``LimitRegime.PHASE1_PROVISIONAL``); las versiones recalibradas, con ``phase2_limit``
(``LimitRegime.PHASE2``).

Sin depuración automática iterativa (decisión del dueño, 2026-10-09): la Fase I es exclusión
humana opcional, un ajuste MRCD, una calibración y el modelo; la recalibración, exclusión humana
de las filas nuevas y una recalibración como Fase I, en una sola pasada.

Piezas públicas (vuelta 3.2 del Paso 3): ``fit_phase1`` y ``recalibrate`` **componen** los pasos
``validate_phase1_input``, ``fit_base``, ``calibrate`` (con la semilla de ``stage_spawn_key``),
``compare`` y ``assemble_model``; un orquestador puede ejecutarlos por separado y obtiene los
mismos bits. ``mrcd_threads`` solo cambia el rendimiento de ``pymrcd``.
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import numpy as np
import numpy.typing as npt

from voracious.domain.charts.t2mrcd.bootstrap import BootstrapLimits
from voracious.domain.charts.t2mrcd.codec import (
    decode_model,
    decode_report,
    encode_model,
    encode_report,
)
from voracious.domain.charts.t2mrcd.comparison import ComparisonResult, compare_bases
from voracious.domain.charts.t2mrcd.model import LimitRegime, T2MRCDModel, T2MRCDMonitoring
from voracious.domain.charts.t2mrcd.params import T2MRCDParams, _is_int
from voracious.domain.charts.t2mrcd.phase1 import (
    MAX_REPORTED_ROWS,
    T2MRCD_CLEAN_CRITERION_INVALID,
    T2MRCD_NO_CLEAN_OBSERVATIONS,
    Aggregations,
    Phase1Stage,
    calibrate_stage,
    fit_base,
    fit_base_mrcd,
)
from voracious.domain.charts.t2mrcd.registry import (
    DEFAULT_STRATEGIES,
    T2MRCDStrategies,
    decode_params,
    decode_recalibration_params,
    encode_params,
    encode_recalibration_params,
)
from voracious.domain.charts.t2mrcd.revalidation import (
    LimitsSnapshot,
    T2MRCDRecalibrationParams,
    T2MRCDRecalibrationReport,
    decide,
)
from voracious.domain.charts.t2mrcd.seeds import (
    SLOT_NEW_ROWS,
    SLOT_PHASE1,
    STAGE_INDEX,
    SpawnKey,
)
from voracious.domain.charts.t2mrcd.statistic import t2
from voracious.domain.common import (
    BoolVector,
    ControlChart,
    EstimationError,
    FloatMatrix,
    InvalidInputError,
    MethodDecisionPendingError,
    RecalibrationDecision,
    RecalibrationOutcome,
    RowDisposition,
    StageKind,
    TaskMapper,
    as_matrix,
)
from voracious.domain.estimators.mrcd import (
    PYMRCD_VERSION,
    IndexVector,
    MRCDEstimator,
    MRCDFit,
    MRCDParams,
)

__all__ = [
    "BASE_CONSISTENCY_RTOL",
    "CHART_ID",
    "STATISTIC_REFERENCE",
    "T2MRCD_CLEAN_CRITERION_INVALID",
    "T2MRCD_DECISION_PENDING",
    "T2MRCD_NO_CLEAN_OBSERVATIONS",
    "T2MRCDChart",
]

CHART_ID: Final = "t2mrcd"
"""Identificador de la carta (ruta ``/v1/charts/t2mrcd``)."""

STATISTIC_REFERENCE: Final = "Artículo T²MRCD del dueño (en proceso de publicación)"
"""Cita de la estadística T² (P6, decisión del dueño 2026-10-07); se sustituye al publicarse."""

T2MRCD_DECISION_PENDING: Final = "T2MRCD_DECISION_PENDING"
"""Código de error: hay decisiones estadísticas pendientes (``details["pending"]``)."""

BASE_CONSISTENCY_RTOL: Final = 1e-9
"""Tolerancia relativa al comprobar que la base reproduce los T² guardados (redondeo de BLAS)."""


def _validated(x: npt.ArrayLike, *, name: str, n_features: int | None = None) -> FloatMatrix:
    """Convierte y valida una entrada de la carta: matriz no vacía, finita y con ``p`` columnas.

    Args:
        x: Entrada.
        name: Nombre para los mensajes.
        n_features: ``p`` exigido, o ``None`` si no se exige.

    Returns:
        La matriz validada.

    Raises:
        InvalidInputError: Si no cumple el contrato.
    """
    arr = as_matrix(x, name=name)
    n, p = arr.shape
    if n == 0 or p == 0:
        raise InvalidInputError(
            f"'{name}' no puede estar vacía", details={"input": name, "shape": [n, p]}
        )
    if n_features is not None and p != n_features:
        raise InvalidInputError(
            f"'{name}' tiene {p} variables y el modelo {n_features}",
            details={"input": name, "expected_features": n_features, "got_features": p},
        )
    bad_rows = np.flatnonzero(~np.isfinite(arr).all(axis=1))
    if bad_rows.size:
        raise InvalidInputError(
            f"'{name}' contiene valores no finitos (NaN o infinito)",
            details={
                "input": name,
                "non_finite_rows": int(bad_rows.size),
                "rows": [int(i) for i in bad_rows[:MAX_REPORTED_ROWS]],
            },
        )
    return arr


def _validated_mask(mask: npt.ArrayLike | None, n: int, *, name: str) -> BoolVector:
    """Valida una máscara de exclusión humana (booleana, longitud ``n``).

    Args:
        mask: Máscara o ``None`` (ninguna fila excluida).
        n: Longitud exigida.
        name: Nombre para los mensajes.

    Returns:
        Copia booleana de la máscara.

    Raises:
        InvalidInputError: Si no es booleana de longitud ``n``.
    """
    if mask is None:
        return np.zeros(n, dtype=np.bool_)
    arr = np.asarray(mask)
    if arr.dtype != np.bool_ or arr.shape != (n,):
        raise InvalidInputError(
            f"'{name}' debe ser una máscara booleana de longitud {n}",
            details={"input": name, "dtype": str(arr.dtype), "shape": list(arr.shape)},
        )
    return arr.copy()


def _dispositions(excluded: BoolVector) -> tuple[RowDisposition, ...]:
    """Destino de cada fila a partir de la exclusión humana.

    Args:
        excluded: Excluidas por una persona.

    Returns:
        Los destinos.
    """
    return tuple(
        RowDisposition.EXCLUDED_ASSIGNABLE_CAUSE if human else RowDisposition.KEPT
        for human in excluded.tolist()
    )


def _kept_rows(excluded: BoolVector) -> IndexVector:
    """Índices de las filas no excluidas, en orden.

    Args:
        excluded: Excluidas por una persona.

    Returns:
        Los índices.
    """
    return np.flatnonzero(~excluded).astype(np.int64)


_STAGE_SLOTS: Final[Mapping[StageKind, int]] = {
    StageKind.PHASE1: SLOT_PHASE1,
    StageKind.NEW_ROWS: SLOT_NEW_ROWS,
    StageKind.EXTENSION: SLOT_PHASE1,
}
"""Hueco de semilla de cada operación (``seeds.py``); la extensión usa ``(SLOT_PHASE1, 0)``."""


@dataclass(frozen=True)
class T2MRCDChart:
    """Carta T²MRCD.

    ``ControlChart[T2MRCDParams, T2MRCDModel, T2MRCDMonitoring, T2MRCDRecalibrationParams,
    T2MRCDRecalibrationReport]``.

    Attributes:
        statistic_reference: Cita del artículo que define la estadística T² de la carta (P6).
            Por defecto ``STATISTIC_REFERENCE`` (artículo en proceso de publicación); se
            actualiza con la cita final cuando se publique.
        strategies: Registro ``nombre → estrategia`` con el que se codifican y decodifican los
            parámetros y los modelos (M1). Por defecto, solo las estrategias de producción
            decididas.
        mrcd_threads: Hilos de la extensión C de ``pymrcd`` en cada ajuste MRCD (base, réplicas
            y pruebas de cambio). Parámetro de **rendimiento**: no es estadístico, no se guarda
            con el modelo y no cambia ningún bit (``fit_mrcd``). ``None`` ⇒ decide ``pymrcd``.
    """

    statistic_reference: str = STATISTIC_REFERENCE
    strategies: T2MRCDStrategies = field(default=DEFAULT_STRATEGIES, compare=False)
    mrcd_threads: int | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        """Valida ``mrcd_threads``.

        Raises:
            InvalidInputError: Si no es ``None`` ni un entero ``>= 1``.
        """
        if self.mrcd_threads is not None and (
            not _is_int(self.mrcd_threads) or self.mrcd_threads < 1
        ):
            raise InvalidInputError(
                "'mrcd_threads' debe ser None o un entero >= 1",
                details={"field": "mrcd_threads"},
            )

    @property
    def chart_id(self) -> str:
        """Identificador de la carta: ``"t2mrcd"``."""
        return CHART_ID

    # --- codificación (M1) ----------------------------------------------------------------------

    def encode_params(self, params: T2MRCDParams) -> dict[str, object]:
        """Codifica los parámetros con las estrategias por nombre (M1).

        Args:
            params: Parámetros de la carta.

        Returns:
            Diccionario serializable.

        Raises:
            InvalidInputError: Si una estrategia no está en ``strategies``.
        """
        return encode_params(params, self.strategies)

    def decode_params(self, data: Mapping[str, object]) -> T2MRCDParams:
        """Decodifica los parámetros (inversa de ``encode_params``).

        Args:
            data: Parámetros codificados.

        Returns:
            Los parámetros.

        Raises:
            InvalidInputError: Datos inválidos o estrategia desconocida.
        """
        return decode_params(data, self.strategies)

    def encode_recalibration_params(self, params: T2MRCDRecalibrationParams) -> dict[str, object]:
        """Codifica los parámetros de la recalibración con las estrategias por nombre (M1).

        Args:
            params: Parámetros de la recalibración.

        Returns:
            Diccionario serializable.

        Raises:
            InvalidInputError: Si una estrategia no está en ``strategies``.
        """
        return encode_recalibration_params(params, self.strategies)

    def decode_recalibration_params(self, data: Mapping[str, object]) -> T2MRCDRecalibrationParams:
        """Decodifica los parámetros de la recalibración.

        Args:
            data: Parámetros codificados.

        Returns:
            Los parámetros de la recalibración.

        Raises:
            InvalidInputError: Datos inválidos o estrategia desconocida.
        """
        return decode_recalibration_params(data, self.strategies)

    def encode_model(self, model: T2MRCDModel) -> dict[str, object]:
        """Codifica un modelo como datos, exacto en bits (``codec.py``, M1).

        Args:
            model: Modelo de Fase I (inicial o recalibrado).

        Returns:
            Diccionario serializable.

        Raises:
            InvalidInputError: Si una estrategia de sus parámetros no está en ``strategies``.
        """
        return encode_model(model, self.strategies)

    def decode_model(self, data: Mapping[str, object]) -> T2MRCDModel:
        """Decodifica un modelo (inversa de ``encode_model``).

        Args:
            data: Modelo codificado.

        Returns:
            El modelo.

        Raises:
            InvalidInputError: Campo desconocido, ausente o inválido, o estrategia desconocida.
        """
        return decode_model(data, self.strategies)

    def encode_report(self, report: object) -> dict[str, object]:
        """Codifica un informe de recalibración como datos (M1).

        Recibe ``object`` porque el tipo del informe es covariante en ``ControlChart``.

        Args:
            report: Informe (``T2MRCDRecalibrationReport``).

        Returns:
            Diccionario serializable.

        Raises:
            TypeError: Si ``report`` no es un informe de T²MRCD.
        """
        if not isinstance(report, T2MRCDRecalibrationReport):
            msg = f"se esperaba T2MRCDRecalibrationReport, no {type(report).__name__}"
            raise TypeError(msg)
        return encode_report(report)

    def decode_report(self, data: Mapping[str, object]) -> T2MRCDRecalibrationReport:
        """Decodifica un informe de recalibración (inversa de ``encode_report``).

        Args:
            data: Informe codificado.

        Returns:
            El informe.

        Raises:
            InvalidInputError: Campo desconocido, ausente o inválido.
        """
        return decode_report(data)

    # --- decisiones pendientes ------------------------------------------------------------------

    def pending_decisions(self, params: T2MRCDParams) -> list[str]:
        """Elementos estadísticos de la Fase I sin decidir, en orden estable.

        Args:
            params: Parámetros de la carta.

        Returns:
            Nombres de los campos pendientes (vacío si no falta nada).
        """
        return params.bootstrap.pending_fields()

    def pending_recalibration_decisions(self, params: T2MRCDRecalibrationParams) -> list[str]:
        """Elementos estadísticos de la recalibración sin decidir, en orden estable.

        Con los defaults de producción quedan pendientes las pruebas formales de cambio
        (``covariance_test``, ``mean_test``) y su número de remuestreos.

        Args:
            params: Parámetros de la recalibración.

        Returns:
            Nombres de los campos pendientes (vacío si no falta nada).
        """
        return params.pending_fields()

    def _aggregations(self, params: T2MRCDParams) -> Aggregations:
        """Resuelve las agregaciones o lanza el error de decisiones pendientes.

        Args:
            params: Parámetros de la carta.

        Returns:
            Las agregaciones de Fase I y de Fase II.

        Raises:
            MethodDecisionPendingError: ``T2MRCD_DECISION_PENDING``.
        """
        boot = params.bootstrap
        if boot.aggregation is None or boot.phase2_aggregation is None:
            raise MethodDecisionPendingError(
                T2MRCD_DECISION_PENDING,
                "T²MRCD tiene decisiones estadísticas pendientes (docs/metodos/t2mrcd.md)",
                self.pending_decisions(params),
            )
        return Aggregations(phase1=boot.aggregation, phase2=boot.phase2_aggregation)

    # --- piezas públicas (vuelta 3.2) ------------------------------------------------------------

    def validate_phase1_input(self, x: FloatMatrix) -> None:
        """Valida de forma síncrona el histórico de Fase I (no vacío y finito).

        Args:
            x: Histórico ``n x p``.

        Raises:
            InvalidInputError: Si está vacío, no es una matriz o tiene valores no finitos.
        """
        _validated(x, name="x")

    def stage_spawn_key(self, kind: StageKind) -> SpawnKey:
        """Hueco de semilla de la calibración de una operación (``seeds.py``).

        ``PHASE1`` → ``(0, 0)``; ``NEW_ROWS`` → ``(1, 0)``; ``EXTENSION`` → ``(0, 0)``.

        Args:
            kind: Operación (se admite su valor como texto, p. ej. ``"phase1"``).

        Returns:
            La clave bajo la semilla raíz.

        Raises:
            InvalidInputError: Si ``kind`` no es una operación conocida.
        """
        try:
            stage = StageKind(kind)
        except ValueError as exc:
            raise InvalidInputError(
                f"'kind' no es una operación conocida: {kind!r}",
                details={"field": "stage_kind"},
            ) from exc
        return (_STAGE_SLOTS[stage], STAGE_INDEX)

    def fit_base(self, x_rows: FloatMatrix, rows: IndexVector, params: T2MRCDParams) -> MRCDFit:
        """Ajuste MRCD de unas filas (``phase1.fit_base``).

        Args:
            x_rows: Filas ``n_k x p`` (finitas).
            rows: Índices de esas filas en la entrada (para los mensajes).
            params: Parámetros de la carta.

        Returns:
            El ajuste.

        Raises:
            InvalidInputError: Filas cuya suma desborda.
            EstimationError: ``MRCD_FIT_FAILED``.
        """
        return fit_base(x_rows, rows, params, n_threads=self.mrcd_threads)

    def fit_estimator(self, x_rows: FloatMatrix, rows: IndexVector, mrcd: MRCDParams) -> MRCDFit:
        """``fit_base`` con solo los parámetros de MRCD (ajuste suelto, vuelta 3.3).

        Mismo ajuste, bit a bit, que ``fit_base`` con ``params.mrcd == mrcd``.

        Args:
            x_rows: Filas ``n_k x p`` (finitas).
            rows: Índices de esas filas en la entrada (para los mensajes).
            mrcd: Parámetros de MRCD.

        Returns:
            El ajuste.

        Raises:
            InvalidInputError: Filas cuya suma desborda.
            EstimationError: ``MRCD_FIT_FAILED``.
        """
        return fit_base_mrcd(x_rows, rows, mrcd, n_threads=self.mrcd_threads)

    def calibrate(
        self,
        x_rows: FloatMatrix,
        fit: MRCDFit,
        params: T2MRCDParams,
        *,
        kind: StageKind,
        mapper: TaskMapper,
    ) -> Phase1Stage:
        """Filas limpias y límites bootstrap de un ajuste (``calibrate_stage``).

        La semilla es la raíz ``params.bootstrap.seed`` con el hueco ``stage_spawn_key(kind)``.

        Args:
            x_rows: Filas, las mismas con las que se ajustó ``fit``.
            fit: Ajuste de esas filas (``fit_base``).
            params: Parámetros de la carta (en una recalibración, los heredados con la semilla
                de la recalibración).
            kind: Operación a la que pertenece la calibración.
            mapper: Reparto de las réplicas.

        Returns:
            El ajuste con sus filas limpias y sus límites.

        Raises:
            MethodDecisionPendingError: ``T2MRCD_DECISION_PENDING``.
            EstimationError: Criterio de fila limpia inválido, sin filas limpias o fallo del
                bootstrap.
        """
        return calibrate_stage(
            x_rows,
            fit,
            params,
            aggregations=self._aggregations(params),
            seed=params.bootstrap.seed,
            spawn_key=self.stage_spawn_key(kind),
            mapper=mapper,
            n_threads=self.mrcd_threads,
        )

    def _stage(
        self,
        x: FloatMatrix,
        rows: IndexVector,
        *,
        params: T2MRCDParams,
        kind: StageKind,
        mapper: TaskMapper,
    ) -> Phase1Stage:
        """``fit_base`` seguido de ``calibrate`` sobre las filas ``rows`` de ``x``.

        Args:
            x: Entrada.
            rows: Filas que se ajustan (índices en ``x``, para los mensajes).
            params: Parámetros de la carta.
            kind: Operación.
            mapper: Reparto de las réplicas.

        Returns:
            El ajuste con sus filas limpias y sus límites.
        """
        x_rows = x[rows]
        fit = self.fit_base(x_rows, rows, params)
        return self.calibrate(x_rows, fit, params, kind=kind, mapper=mapper)

    def assemble_model(
        self,
        arr: FloatMatrix,
        params: T2MRCDParams,
        fit: MRCDFit,
        clean: BoolVector,
        limits: BootstrapLimits,
        *,
        excluded: BoolVector,
        regime: LimitRegime,
    ) -> T2MRCDModel:
        """Construye el modelo a partir del ajuste de ``arr[~excluded]``.

        Args:
            arr: Entrada ``n x p``.
            params: Parámetros que se guardan en el modelo.
            fit: Ajuste de las filas no excluidas, en su orden.
            clean: Filas limpias del ajuste (máscara sobre las filas no excluidas).
            limits: Límites del ajuste.
            excluded: Filas excluidas por una persona (el resto forma la base).
            regime: Régimen del límite de la versión.

        Returns:
            El modelo.
        """
        kept = ~excluded
        rows = np.flatnonzero(kept)
        clean_mask = np.zeros(arr.shape[0], dtype=np.bool_)
        clean_mask[rows[clean]] = True
        historical_t2 = t2(fit, arr)
        return T2MRCDModel(
            params=params,
            mrcd=fit,
            n_features=int(arr.shape[1]),
            base_mask=kept,
            row_disposition=_dispositions(excluded),
            clean_mask=clean_mask,
            limits=limits,
            limit_regime=regime,
            historical_t2=historical_t2,
            historical_outlier=historical_t2 > limits.phase1_limit,
            pymrcd_version=PYMRCD_VERSION,
            seed=params.bootstrap.seed,
            statistic_reference=self.statistic_reference,
        )

    def compare(
        self,
        active_model: T2MRCDModel,
        base: FloatMatrix,
        new_kept: FloatMatrix,
        fit1: MRCDFit,
        params: T2MRCDRecalibrationParams,
        mapper: TaskMapper,
    ) -> ComparisonResult:
        """Compara la base vigente con las filas nuevas conservadas (``compare_bases``).

        Reajusta con MRCD y los parámetros del modelo vigente (Q8) y la semilla de la
        recalibración (huecos de las pruebas, ``seeds.py``).

        Args:
            active_model: Modelo vigente (``μ₀``, ``S₀``).
            base: Base del modelo vigente.
            new_kept: Filas nuevas conservadas tras la exclusión humana.
            fit1: Ajuste de esas filas (``μ₁``, ``S₁``).
            params: Parámetros de la recalibración.
            mapper: Reparto de los remuestreos.

        Returns:
            La comparación.

        Raises:
            InvalidInputError: Si ``base`` no es la del modelo vigente o ``new_kept`` no es
                compatible.
            MethodDecisionPendingError: ``T2MRCD_DECISION_PENDING`` si faltan las pruebas
                formales o sus remuestreos.
        """
        base_arr = self._validated_base(active_model, base)
        new = _validated(new_kept, name="x_new", n_features=active_model.n_features)
        covariance_test, mean_test = params.covariance_test, params.mean_test
        n_test_resamples = params.n_test_resamples
        if covariance_test is None or mean_test is None or n_test_resamples is None:
            raise MethodDecisionPendingError(
                T2MRCD_DECISION_PENDING,
                "la comparación de T²MRCD tiene decisiones pendientes (docs/metodos/t2mrcd.md)",
                self.pending_recalibration_decisions(params),
            )
        return compare_bases(
            base_arr,
            new,
            fit0=active_model.mrcd,
            fit1=fit1,
            metric=params.relative_change_metric,
            threshold=params.relative_change_threshold,
            threshold_decides=params.threshold_decides,
            covariance_test=covariance_test,
            mean_test=mean_test,
            decision_rule=params.decision_rule,
            estimator=MRCDEstimator(active_model.params.mrcd, self.mrcd_threads),
            seed=params.seed,
            n_test_resamples=n_test_resamples,
            mapper=mapper,
        )

    # --- Fase I y Fase II -----------------------------------------------------------------------

    def fit_phase1(
        self,
        x: FloatMatrix,
        params: T2MRCDParams,
        *,
        mapper: TaskMapper,
        excluded: BoolVector | None = None,
    ) -> T2MRCDModel:
        """Fase I: valida, comprueba pendientes, excluye, ajusta y calibra los dos límites.

        Orden: validar la entrada y la máscara; comprobar pendientes (antes de ajustar); excluir
        las filas con causa asignable; **un** ``fit_base`` y **un** ``calibrate`` (operación
        ``PHASE1``) sobre las demás; ``assemble_model``, que puntúa todo el histórico. Sin
        depuración automática iterativa (decisión del dueño, 2026-10-09): las filas fuera de
        ``best`` siguen en la base. Régimen: ``PHASE1_PROVISIONAL``.

        Args:
            x: Histórico ``n x p``, finito.
            params: Parámetros de la carta.
            mapper: Reparto de las réplicas bootstrap.
            excluded: Filas con causa asignable confirmada (máscara booleana de longitud ``n``).

        Returns:
            El modelo de Fase I (versión inicial).

        Raises:
            InvalidInputError: Entrada vacía, no finita, cuya suma por fila desborda o máscara
                inválida.
            MethodDecisionPendingError: ``T2MRCD_DECISION_PENDING`` (antes de ajustar).
            EstimationError: ``T2MRCD_NO_CLEAN_OBSERVATIONS`` (la exclusión quitó todas las
                filas), ``MRCD_FIT_FAILED``, ``BOOTSTRAP_REPLICATE_FAILED``,
                ``BOOTSTRAP_OOB_EMPTY`` u otro fallo.
        """
        self.validate_phase1_input(x)
        arr = as_matrix(x, name="x")
        mask = _validated_mask(excluded, arr.shape[0], name="excluded")
        self._aggregations(params)
        if bool(mask.all()):
            raise EstimationError(T2MRCD_NO_CLEAN_OBSERVATIONS, "la exclusión humana no dejó filas")
        stage = self._stage(
            arr, _kept_rows(mask), params=params, kind=StageKind.PHASE1, mapper=mapper
        )
        return self.assemble_model(
            arr,
            params,
            stage.fit,
            stage.clean,
            stage.limits,
            excluded=mask,
            regime=LimitRegime.PHASE1_PROVISIONAL,
        )

    def validate_phase2_input(self, model: T2MRCDModel, x_new: FloatMatrix) -> None:
        """Valida las observaciones de Fase II (no vacías, finitas y con ``p`` del modelo).

        Args:
            model: Modelo de Fase I.
            x_new: Observaciones nuevas.

        Raises:
            InvalidInputError: Si no son compatibles con el modelo.
        """
        _validated(x_new, name="x_new", n_features=model.n_features)

    def score_phase2(self, model: T2MRCDModel, x_new: FloatMatrix) -> T2MRCDMonitoring:
        """Fase II: T² de cada observación y señal si supera el límite operativo (estricto).

        Args:
            model: Modelo de Fase I.
            x_new: Observaciones nuevas ``m x p``.

        Returns:
            T², señales, el límite usado y su régimen.

        Raises:
            InvalidInputError: Si no son compatibles con el modelo.
        """
        arr = _validated(x_new, name="x_new", n_features=model.n_features)
        values = t2(model.mrcd, arr)
        limit = model.operative_limit
        return T2MRCDMonitoring(
            t2=values, signal=values > limit, limit=limit, limit_kind=model.limit_regime
        )

    # --- recalibración --------------------------------------------------------------------------

    def _validated_base(self, active_model: T2MRCDModel, base: FloatMatrix) -> FloatMatrix:
        """Valida que ``base`` sea la base del modelo vigente.

        Args:
            active_model: Modelo vigente.
            base: Base recibida.

        Returns:
            La base validada.

        Raises:
            InvalidInputError: Si el número de filas o sus T² no coinciden con los guardados en
                el modelo (``details["reason"] == "base_mismatch"``).
        """
        arr = _validated(base, name="base", n_features=active_model.n_features)
        expected = active_model.historical_t2[active_model.base_mask]
        if arr.shape[0] != expected.shape[0] or not np.allclose(
            t2(active_model.mrcd, arr), expected, rtol=BASE_CONSISTENCY_RTOL, atol=0.0
        ):
            raise InvalidInputError(
                "'base' no es la base del modelo vigente",
                details={
                    "input": "base",
                    "reason": "base_mismatch",
                    "expected_rows": int(expected.shape[0]),
                    "got_rows": int(arr.shape[0]),
                },
            )
        return arr

    def recalibrate(
        self,
        active_model: T2MRCDModel,
        base: FloatMatrix,
        x_new: FloatMatrix,
        *,
        assignable_cause: BoolVector | None,
        force_replace: bool,
        params: T2MRCDRecalibrationParams,
        mapper: TaskMapper,
    ) -> RecalibrationOutcome[T2MRCDModel, T2MRCDRecalibrationReport]:
        """Crea una nueva versión del modelo con las observaciones de Fase II.

        Pasos: (1) validar; (2) pendientes antes de ajustar, salvo ``force_replace``;
        (3) exclusión humana; (4) ``INSUFFICIENT`` si quedan menos de ``min_observations``;
        (5) **un** ajuste y **una** calibración de las filas nuevas conservadas (heredando B,
        niveles, agregaciones y MRCD del modelo vigente, Q8; operación ``NEW_ROWS``): ``μ₁``,
        ``S₁``; (6) ``compare`` con la base vigente, salvo ``force_replace`` (deciden las pruebas
        formales; el cambio relativo es informativo salvo ``threshold_decides``); (7) ``EXTEND``
        = ``vstack(base, nuevas)`` o ``REPLACE`` = solo las nuevas; (8) Fase I final sobre la
        nueva base con régimen ``PHASE2`` (``assemble_model``), e informe. Sin depuración
        automática iterativa (decisión del dueño, 2026-10-09). El modelo guarda los parámetros
        heredados tal cual con la semilla de la recalibración.

        En ``REPLACE`` la nueva base es exactamente la de las filas nuevas conservadas (mismas
        filas, mismo orden, mismos parámetros y semilla raíz), así que se reutiliza su ajuste y su
        calibración (hueco ``(SLOT_NEW_ROWS, 0)``) en lugar de repetir las B réplicas. En
        ``EXTEND`` se calibra con la operación ``EXTENSION`` (hueco ``(SLOT_PHASE1, 0)``).

        Args:
            active_model: Modelo vigente.
            base: Base del modelo vigente (``x[active_model.base_mask]`` de su entrada).
            x_new: Observaciones nuevas ``m x p``.
            assignable_cause: Filas de ``x_new`` con causa asignable confirmada, o ``None``.
            force_replace: Reemplazar sin comparar (decisión humana).
            params: Parámetros de la recalibración.
            mapper: Reparto de las réplicas.

        Returns:
            La decisión, el modelo nuevo (``None`` si ``INSUFFICIENT``) y el informe.

        Raises:
            InvalidInputError: Entradas inválidas o base que no es la del modelo vigente.
            MethodDecisionPendingError: ``T2MRCD_DECISION_PENDING`` (antes de ajustar).
            EstimationError: Fallo de MRCD o del bootstrap.
        """
        base_arr = self._validated_base(active_model, base)
        new = _validated(x_new, name="x_new", n_features=active_model.n_features)
        human = _validated_mask(assignable_cause, new.shape[0], name="assignable_cause")
        pending = self.pending_recalibration_decisions(params)
        if pending and not force_replace:
            raise MethodDecisionPendingError(
                T2MRCD_DECISION_PENDING,
                "la recalibración de T²MRCD tiene decisiones pendientes (docs/metodos/t2mrcd.md)",
                pending,
            )
        inherited = dataclasses.replace(
            active_model.params,
            bootstrap=dataclasses.replace(active_model.params.bootstrap, seed=params.seed),
        )
        self._aggregations(inherited)
        rows = _kept_rows(human)
        kept_new = new[rows]
        n_kept = int(rows.shape[0])
        stage = None
        if n_kept >= params.min_observations:
            stage = self._stage(new, rows, params=inherited, kind=StageKind.NEW_ROWS, mapper=mapper)
        comparison = None
        if stage is not None and not force_replace:
            comparison = self.compare(active_model, base_arr, kept_new, stage.fit, params, mapper)
        decision = decide(
            comparison,
            n_kept=n_kept,
            min_observations=params.min_observations,
            force_replace=force_replace,
        )
        model = None
        if stage is not None and decision is not RecalibrationDecision.INSUFFICIENT:
            if decision is RecalibrationDecision.EXTEND:
                x_final = np.vstack([base_arr, kept_new])
                final_stage = self._stage(
                    x_final,
                    np.arange(x_final.shape[0], dtype=np.int64),
                    params=inherited,
                    kind=StageKind.EXTENSION,
                    mapper=mapper,
                )
            else:
                # REPLACE: las filas nuevas conservadas ya se ajustaron y calibraron.
                x_final, final_stage = kept_new, stage
            model = self.assemble_model(
                x_final,
                inherited,
                final_stage.fit,
                final_stage.clean,
                final_stage.limits,
                excluded=np.zeros(x_final.shape[0], dtype=np.bool_),
                regime=LimitRegime.PHASE2,
            )
        report = T2MRCDRecalibrationReport(
            decision=decision,
            forced=force_replace,
            row_disposition=(RowDisposition.ALREADY_IN_BASE,) * base_arr.shape[0]
            + _dispositions(human),
            n_base=int(base_arr.shape[0]),
            n_new=int(new.shape[0]),
            n_excluded_assignable_cause=int(human.sum()),
            n_kept_new=n_kept,
            min_observations=params.min_observations,
            comparison=comparison,
            before=LimitsSnapshot.of(active_model),
            after=None if model is None else LimitsSnapshot.of(model),
            phase2_exceeds_phase1=None if model is None else model.limits.phase2_exceeds_phase1,
        )
        return RecalibrationOutcome(decision=decision, model=model, report=report)


if TYPE_CHECKING:
    # mypy verifica que la carta cumple el contrato común (ADR 0004, punto 8).
    _conforms: ControlChart[
        T2MRCDParams,
        T2MRCDModel,
        T2MRCDMonitoring,
        T2MRCDRecalibrationParams,
        T2MRCDRecalibrationReport,
    ] = T2MRCDChart()
