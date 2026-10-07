"""Contrato común de una carta de control (ADR 0004, punto 8).

Cada carta (``domain/charts/<carta>/``) lo implementa con su propia lógica estadística; las capas
``application`` e ``infrastructure`` solo trabajan contra este ``Protocol``. Una carta no guarda
estado entre llamadas: el modelo de Fase I es un valor que se persiste fuera del dominio, y la base
de datos de cada versión también (``recalibrate`` la recibe de vuelta).
"""

from typing import Protocol, TypeVar

from voracious.domain.common.parallel import TaskMapper
from voracious.domain.common.recalibration import RecalibrationOutcome
from voracious.domain.common.types import BoolVector, FloatMatrix

__all__ = ["ControlChart"]

ParamsT_contra = TypeVar("ParamsT_contra", contravariant=True)
ModelT = TypeVar("ModelT")
ResultT_co = TypeVar("ResultT_co", covariant=True)
RecalParamsT_contra = TypeVar("RecalParamsT_contra", contravariant=True)
ReportT_co = TypeVar("ReportT_co", covariant=True)


class ControlChart(Protocol[ParamsT_contra, ModelT, ResultT_co, RecalParamsT_contra, ReportT_co]):
    """Carta de control con Fase I (ajuste y límites), Fase II (puntuación) y recalibración.

    Tipos:
        ``ParamsT_contra``: parámetros de la carta (contravariante).
        ``ModelT``: modelo de Fase I (invariante: entra y sale).
        ``ResultT_co``: resultado de Fase II (covariante).
        ``RecalParamsT_contra``: parámetros de la recalibración (contravariante).
        ``ReportT_co``: informe de la recalibración (covariante).
    """

    @property
    def chart_id(self) -> str:
        """Identificador estable de la carta, igual al de su ruta ``/v1/charts/<carta>``."""
        ...

    def fit_phase1(
        self,
        x: FloatMatrix,
        params: ParamsT_contra,
        *,
        mapper: TaskMapper,
        excluded: BoolVector | None = None,
    ) -> ModelT:
        """Ajusta la carta con datos históricos y calcula sus límites de control.

        Args:
            x: Datos históricos ``n x p``.
            params: Parámetros de la carta.
            mapper: Reparto de las tareas independientes (p. ej. réplicas bootstrap).
            excluded: Filas excluidas por una persona (causa asignable confirmada), máscara
                booleana de longitud ``n``; ``None`` si no se excluye ninguna.

        Returns:
            El modelo de Fase I (versión inicial).

        Raises:
            DomainError: Entrada inválida, decisión pendiente o fallo de estimación.
        """
        ...

    def validate_phase2_input(self, model: ModelT, x_new: FloatMatrix) -> None:
        """Valida de forma síncrona las observaciones de Fase II antes de encolarlas.

        Args:
            model: Modelo de Fase I.
            x_new: Observaciones nuevas.

        Raises:
            InvalidInputError: Si no son compatibles con el modelo.
        """
        ...

    def score_phase2(self, model: ModelT, x_new: FloatMatrix) -> ResultT_co:
        """Puntúa observaciones nuevas contra el modelo y marca señales.

        Args:
            model: Modelo de Fase I.
            x_new: Observaciones nuevas ``m x p``.

        Returns:
            El resultado de Fase II.

        Raises:
            InvalidInputError: Si no son compatibles con el modelo.
        """
        ...

    def pending_recalibration_decisions(self, params: RecalParamsT_contra) -> list[str]:
        """Elementos estadísticos de la recalibración aún sin decidir, en orden estable.

        Args:
            params: Parámetros de la recalibración.

        Returns:
            Nombres de los campos pendientes (vacío si no falta nada).
        """
        ...

    def recalibrate(
        self,
        active_model: ModelT,
        base: FloatMatrix,
        x_new: FloatMatrix,
        *,
        assignable_cause: BoolVector | None,
        force_replace: bool,
        params: RecalParamsT_contra,
        mapper: TaskMapper,
    ) -> RecalibrationOutcome[ModelT, ReportT_co]:
        """Crea una nueva versión del modelo con las observaciones acumuladas en Fase II.

        Args:
            active_model: Modelo vigente.
            base: Base de datos del modelo vigente (las filas con las que se ajustó).
            x_new: Observaciones nuevas ``m x p``.
            assignable_cause: Filas de ``x_new`` excluidas por una persona (causa asignable
                confirmada), o ``None``.
            force_replace: Reemplazar la base sin comparar (decisión humana).
            params: Parámetros de la recalibración.
            mapper: Reparto de las tareas independientes.

        Returns:
            La decisión, el modelo nuevo (o ``None``) y el informe.

        Raises:
            DomainError: Entrada inválida, decisión pendiente o fallo de estimación.
        """
        ...
