"""Cupo por tenant de trabajos de cómputo activos (mejora M1 del paso E).

Un tenant tiene a la vez, como mucho, ``max_active`` trabajos de cómputo ``queued`` o ``running``:
ajustes y calibraciones de límites sueltos (los que no pidió una tubería) y tuberías (de Fase I o
de recalibración). Al pedir uno más, ``TooManyJobsError`` (``429 TOO_MANY_JOBS``). Es lo que acota
los cálculos de minutos de un cliente con un bucle defectuoso: la cola no tiene tope.

- Los pasos que crea una tubería (``pipeline_id``) no se comprueban ni se cuentan: la tubería ya
  ocupa su hueco, así que un trabajo nunca cuenta dos veces y una tubería admitida termina.
- Las exclusiones humanas, los ensamblados, las puntuaciones, las propuestas de versión, las
  extensiones y las subidas no cuentan ni se limitan: son ligeros o síncronos.
- Una recalibración paso a paso no es un trabajo (es una sesión): cuentan sus ajustes y límites
  sueltos; en modo ``pipeline`` cuenta su tubería.

**El cupo es blando.** Contar y después insertar no es atómico: con el pool de hilos de la API,
``k`` peticiones simultáneas del mismo tenant pueden pasar todas la comprobación y dejarlo con
hasta ``max_active - 1 + k`` trabajos activos. Está aceptado al aprobar M1: el objetivo es acotar
un bucle, no garantizar un máximo exacto. Un trabajo colgado en ``running`` ocupa su hueco hasta
que la recuperación del arranque (``RecoverInterruptedJobs``) lo cierra
``failed / JOB_INTERRUPTED``.
"""

from dataclasses import dataclass

from voracious.application.errors import TooManyJobsError
from voracious.application.ports import FitRepository, LimitsRepository, PipelineRepository

__all__ = ["JobAdmission"]


@dataclass(frozen=True)
class JobAdmission:
    """Comprueba el cupo de trabajos de cómputo activos de un tenant antes de encolar uno.

    Attributes:
        fits: Repositorio de ajustes (cuentan los sueltos).
        limits: Repositorio de límites (cuentan los sueltos).
        pipelines: Repositorio de tuberías (cuentan todas).
        max_active: Cupo por tenant (``VORACIOUS_MAX_ACTIVE_JOBS_PER_TENANT``), ``>= 1``.
    """

    fits: FitRepository
    limits: LimitsRepository
    pipelines: PipelineRepository
    max_active: int

    def __post_init__(self) -> None:
        """Valida el cupo.

        Raises:
            ValueError: Si ``max_active`` no es un entero ``>= 1`` (error de cableado: la
                configuración ya lo valida).
        """
        if isinstance(self.max_active, bool) or self.max_active < 1:
            msg = f"max_active debe ser un entero >= 1, no {self.max_active!r}"
            raise ValueError(msg)

    def active_jobs(self, tenant_id: str) -> int:
        """Trabajos de cómputo ``queued`` o ``running`` del tenant.

        Args:
            tenant_id: Tenant.

        Returns:
            Ajustes y límites sueltos más tuberías, de todas las cartas del tenant.
        """
        return (
            self.fits.count_unfinished_standalone(tenant_id)
            + self.limits.count_unfinished_standalone(tenant_id)
            + self.pipelines.count_unfinished(tenant_id)
        )

    def check(self, tenant_id: str) -> None:
        """Admite un trabajo nuevo del tenant o lo rechaza si ya tiene el cupo lleno.

        Va después de las validaciones síncronas de la petición (un error de la entrada se
        informa antes que el cupo) y antes de guardar el registro.

        Args:
            tenant_id: Tenant.

        Raises:
            TooManyJobsError: Si los trabajos activos del tenant son ``>= max_active``.
        """
        active = self.active_jobs(tenant_id)
        if active >= self.max_active:
            raise TooManyJobsError(
                TooManyJobsError.MESSAGE,
                details={"max_active_jobs": self.max_active, "active_jobs": active},
            )
