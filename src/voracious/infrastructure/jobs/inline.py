"""``InlineJobQueue``: ejecuta los trabajos en el mismo proceso, en hilos por carril.

Cada carril (``JobLane``) tiene su propio ``ThreadPoolExecutor``: una calibración larga no
bloquea la puntuación de un lote. ``enqueue`` vuelve enseguida (la API responde ``202`` antes de
que el trabajo termine). Una excepción del manejador se registra en el log y no tumba el
proceso; el registro del trabajo ya queda ``failed`` por el caso de uso.
"""

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor

import structlog

from voracious.application.ports import JobKind, JobLane, JobRequest, lane_of

__all__ = ["InlineJobQueue", "JobHandler"]

JobHandler = Callable[[JobRequest], None]
"""Función que ejecuta un trabajo (``Run…Job.execute``)."""

_log = structlog.get_logger(__name__)


class InlineJobQueue:
    """Cola en el mismo proceso con un grupo de hilos por carril."""

    def __init__(
        self, handlers: Mapping[JobKind, JobHandler], workers_per_lane: Mapping[JobLane, int]
    ) -> None:
        """Crea un ejecutor por carril.

        Args:
            handlers: Manejador de cada tipo de trabajo admitido. Se guarda **por referencia**:
                el contenedor lo completa después de crear la cola, porque los manejadores
                (``Run…Job``) reciben la cola para avisar a las tuberías.
            workers_per_lane: Hilos de cada carril (todos los carriles, cada uno ``>= 1``).

        Raises:
            ValueError: Si falta un carril o alguno tiene menos de un hilo.
        """
        missing = [lane for lane in JobLane if lane not in workers_per_lane]
        if missing:
            msg = f"faltan los hilos de los carriles {[str(lane) for lane in missing]}"
            raise ValueError(msg)
        bad = {str(k): v for k, v in workers_per_lane.items() if v < 1}
        if bad:
            msg = f"cada carril necesita al menos un hilo: {bad}"
            raise ValueError(msg)
        self._handlers = handlers
        self._executors = {
            lane: ThreadPoolExecutor(
                max_workers=workers_per_lane[lane], thread_name_prefix=f"voracious-{lane}"
            )
            for lane in JobLane
        }

    def enqueue(self, job: JobRequest) -> None:
        """Programa el trabajo en su carril y vuelve sin esperar.

        Args:
            job: Petición.

        Raises:
            ValueError: Si no hay manejador para ``job.kind``.
            RuntimeError: Si la cola ya se apagó.
        """
        handler = self._handlers.get(job.kind)
        if handler is None:
            msg = f"no hay manejador para los trabajos '{job.kind}'"
            raise ValueError(msg)
        self._executors[lane_of(job.kind)].submit(_run, handler, job)

    def shutdown(self, *, wait: bool = True) -> None:
        """Apaga los carriles.

        Args:
            wait: Si ``True`` espera a los trabajos en curso y en cola; si ``False`` cancela los
                que aún no empezaron.
        """
        for executor in self._executors.values():
            executor.shutdown(wait=wait, cancel_futures=not wait)


def _run(handler: JobHandler, job: JobRequest) -> None:
    """Ejecuta un trabajo y registra cualquier excepción sin propagarla al hilo.

    Args:
        handler: Manejador.
        job: Petición.
    """
    try:
        handler(job)
    except Exception:
        _log.exception(
            "job_failed",
            kind=str(job.kind),
            tenant_id=job.tenant_id,
            scope=job.scope,
            resource_id=job.resource_id,
            model_id=job.model_id,
        )
