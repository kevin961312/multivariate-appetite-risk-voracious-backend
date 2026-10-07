"""Contratos comunes de un estimador de ubicación y dispersión (ADR 0004, punto 4).

Solo describen la **forma** de un ajuste (``center``, ``cov`` y las distancias de Mahalanobis al
cuadrado), sin ninguna lógica estadística: cada estimador (``domain/estimators/<estimador>/``) los
cumple con su propio método y una carta los recibe ya construidos. Así la carta puede repartir las
réplicas bootstrap con un ``TaskMapper`` sin conocer al estimador concreto, y los tests pueden
inyectar estimadores «SOLO TEST» (``tests/support/``) para comprobar el procedimiento contra la
teoría clásica sin tocar ``src/``.
"""

from typing import Protocol

import numpy.typing as npt

from voracious.domain.common.types import FloatMatrix, FloatVector

__all__ = ["LocationScatterEstimator", "LocationScatterFit"]


class LocationScatterFit(Protocol):
    """Ajuste de ubicación y dispersión."""

    @property
    def center(self) -> FloatVector:
        """Ubicación estimada, longitud ``p``."""
        ...

    @property
    def cov(self) -> FloatMatrix:
        """Dispersión estimada, ``p x p``."""
        ...

    def distances(self, x: npt.ArrayLike) -> FloatVector:
        """Distancias de Mahalanobis al cuadrado de cada fila respecto al ajuste.

        Args:
            x: Observaciones ``m x p``.

        Returns:
            Vector de ``m`` distancias al cuadrado.
        """
        ...


class LocationScatterEstimator(Protocol):
    """Estimador de ubicación y dispersión.

    Contrato: *picklable* (viaja una vez en el contexto de un ``TaskMapper`` con procesos) y
    determinista (mismo ``x`` → mismo ajuste); si falla, lanza ``DomainError`` con su código.
    """

    @property
    def name(self) -> str:
        """Nombre estable del estimador (p. ej. ``"mrcd"``), para auditar el modelo."""
        ...

    def fit(self, x: FloatMatrix) -> LocationScatterFit:
        """Ajusta ubicación y dispersión.

        Args:
            x: Datos ``n x p``.

        Returns:
            El ajuste.

        Raises:
            DomainError: Si el método falla (sin *fallback*).
        """
        ...
