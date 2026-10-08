"""Despacho de los trabajos ``pipeline``: Fase I o recalibración según el tipo de tubería."""

from dataclasses import dataclass

from voracious.application.ports import JobKind, JobRequest, PipelineRepository
from voracious.application.records import PipelineKind
from voracious.application.use_cases.pipelines import RunPhase1Pipeline, get_pipeline
from voracious.application.use_cases.recalibration import RunRecalibrationJob

__all__ = ["RunPipelineJob"]


@dataclass(frozen=True)
class RunPipelineJob:
    """Manejador único de ``JobKind.PIPELINE``: delega en la tubería de su tipo.

    Attributes:
        pipelines: Repositorio de tuberías.
        phase1: Tubería de Fase I.
        recalibration: Tubería de recalibración.
    """

    pipelines: PipelineRepository
    phase1: RunPhase1Pipeline
    recalibration: RunRecalibrationJob

    def execute(self, job: JobRequest) -> None:
        """Ejecuta el trabajo con la tubería que corresponde.

        Args:
            job: Petición ``pipeline``.

        Raises:
            ValueError: Si ``job`` no es de tipo ``pipeline``.
            PipelineNotFoundError: Si la tubería no existe.
        """
        if job.kind is not JobKind.PIPELINE:
            msg = f"RunPipelineJob solo ejecuta trabajos 'pipeline', no '{job.kind}'"
            raise ValueError(msg)
        record = get_pipeline(self.pipelines, job.tenant_id, job.scope, job.resource_id)
        if record.kind is PipelineKind.RECALIBRATION:
            self.recalibration.execute(job)
        else:
            self.phase1.execute(job)
