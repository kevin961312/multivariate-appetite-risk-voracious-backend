"""Contrato común de una carta de control (ADR 0004, punto 8).

Cada carta (``domain/charts/<carta>/``) lo implementa con su propia lógica estadística; las capas
``application`` e ``infrastructure`` solo trabajan contra este ``Protocol``. Una carta no guarda
estado entre llamadas: el modelo de Fase I es un valor que se persiste fuera del dominio.
"""

from typing import Protocol, TypeVar

from voracious.domain.common.parallel import TaskMapper
from voracious.domain.common.types import FloatMatrix

__all__ = ["ControlChart"]

ParamsT_contra = TypeVar("ParamsT_contra", contravariant=True)
ModelT = TypeVar("ModelT")
ResultT_co = TypeVar("ResultT_co", covariant=True)


class ControlChart(Protocol[ParamsT_contra, ModelT, ResultT_co]):
    """Carta de control con Fase I (ajuste y límites) y Fase II (puntuación y señales).

    Tipos:
        ``ParamsT_contra``: parámetros de la carta (contravariante).
        ``ModelT``: modelo de Fase I (invariante: entra y sale).
        ``ResultT_co``: resultado de Fase II (covariante).
    """

    @property
    def chart_id(self) -> str:
        """Identificador estable de la carta, igual al de su ruta ``/v1/charts/<carta>``."""
        ...

    def fit_phase1(self, x: FloatMatrix, params: ParamsT_contra, *, mapper: TaskMapper) -> ModelT:
        """Ajusta la carta con datos históricos y calcula sus límites de control.

        Args:
            x: Datos históricos ``n x p``.
            params: Parámetros de la carta.
            mapper: Reparto de las tareas independientes (p. ej. réplicas bootstrap).

        Returns:
            El modelo de Fase I.

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
