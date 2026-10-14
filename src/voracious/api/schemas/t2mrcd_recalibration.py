"""Schemas HTTP de la recalibración paso a paso de T²MRCD (vuelta 3.4).

``POST …/recalibrations`` en modo ``stepwise`` (``201``), ``…/recalibrations/{id}/extension`` y
``…/versions``. Solo referencias por id: ningún dato ni parámetro estadístico viaja en estos
cuerpos. Sin comparación de bases (decisión del dueño, 2026-10-14).
"""

from typing import Literal

from pydantic import Field

from voracious.api.schemas.common import RequestModel, ResponseModel

__all__ = [
    "ExtensionOut",
    "ExtensionRequest",
    "StepwiseRecalibrationOut",
    "VersionProposalRequest",
]


class StepwiseRecalibrationOut(ResponseModel):
    """Respuesta ``201`` de una recalibración paso a paso: la sesión abierta.

    Attributes:
        recalibration_id: Recalibración (``running`` mientras admita pasos).
        candidates_dataset_id: Dataset ``recalibration_candidates`` (raíz de sus pasos).
        status: Siempre ``running``.
    """

    recalibration_id: str
    candidates_dataset_id: str
    status: Literal["running"] = "running"


class ExtensionRequest(RequestModel):
    """Extensión de la base de una recalibración que la amplía (EXTEND, por defecto).

    Attributes:
        dataset_id: Filas nuevas conservadas: el dataset de candidatas (si ninguna tiene causa
            asignable) o la salida de su exclusión humana.
    """

    dataset_id: str = Field(min_length=1)


class ExtensionOut(ResponseModel):
    """Respuesta ``201`` de la extensión: el dataset ``recalibration_extension``.

    Attributes:
        dataset_id: Dataset de extensión (base vigente + nuevas conservadas, en ese orden); se
            ajusta con ``/fits`` y se calibra con ``/limits`` (``recalibration_id``).
        n_base: Filas de la base vigente.
        n_kept_new: Filas nuevas conservadas.
    """

    dataset_id: str
    n_base: int
    n_kept_new: int


class VersionProposalRequest(RequestModel):
    """Propuesta de versión de una recalibración.

    Attributes:
        recalibration_id: Recalibración en curso.
        fit_id: Ajuste final: el del dataset de extensión (EXTEND, por defecto) o el de las filas
            nuevas conservadas (REPLACE: evento estructural o petición explícita).
        limits_id: Límites de ese ajuste.
    """

    recalibration_id: str = Field(min_length=1)
    fit_id: str = Field(min_length=1)
    limits_id: str = Field(min_length=1)
