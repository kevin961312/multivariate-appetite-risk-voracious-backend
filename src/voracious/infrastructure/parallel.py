"""``ProcessPoolTaskMapper``: reparte tareas independientes (réplicas bootstrap) en procesos.

Contrato de ``TaskMapper`` (``domain/common/parallel.py``): ``fn`` y ``context`` viajan **una
vez** por proceso en el ``initializer`` y cada tarea solo lleva su índice y su semilla; el
resultado conserva el orden y no depende del número de procesos. Se usa el contexto ``spawn``
(procesos limpios, sin heredar hilos ni cerrojos del padre). En cada proceso se limitan a 1 los
hilos de BLAS/OpenMP (``threadpoolctl``) y se fija ``PYMRCD_NUM_THREADS`` para que procesos por
hilos no sobresuscriban la máquina; los hilos solo afectan al rendimiento, no a ningún bit.
"""

import multiprocessing
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import cast

from threadpoolctl import threadpool_limits

__all__ = ["ProcessPoolTaskMapper"]

PYMRCD_THREADS_ENV = "PYMRCD_NUM_THREADS"
"""Variable que lee la extensión C de ``pymrcd`` en cada llamada."""

_WORKER: dict[str, object] = {}
"""Estado del proceso de trabajo: función, contexto y límite de hilos activo."""


def _init_worker(fn: Callable[..., object], context: object, mrcd_threads: int | None) -> None:
    """Fija la función, el contexto y los límites de hilos del proceso (una vez).

    Args:
        fn: Función de las tareas.
        context: Contexto compartido.
        mrcd_threads: Hilos de ``pymrcd`` por ajuste, o ``None`` para no fijarlos.
    """
    if mrcd_threads is not None:
        os.environ[PYMRCD_THREADS_ENV] = str(mrcd_threads)
    _WORKER["limits"] = threadpool_limits(limits=1)
    _WORKER["fn"] = fn
    _WORKER["context"] = context


def _call(task: object) -> object:
    """Ejecuta una tarea con la función y el contexto del proceso.

    Args:
        task: Tarea.

    Returns:
        El resultado de ``fn(context, task)``.

    Raises:
        RuntimeError: Si el proceso no se inicializó.
    """
    fn = _WORKER.get("fn")
    if not callable(fn):
        msg = "el proceso de trabajo no está inicializado"
        raise RuntimeError(msg)
    return fn(_WORKER["context"], task)


class ProcessPoolTaskMapper:
    """``TaskMapper`` con un ``ProcessPoolExecutor`` (``spawn``) por llamada.

    Attributes:
        max_workers: Procesos.
        mrcd_threads: Hilos de ``pymrcd`` en cada proceso (``None`` = no se fijan).
    """

    def __init__(self, max_workers: int, mrcd_threads: int | None = None) -> None:
        """Construye el mapper.

        Args:
            max_workers: Procesos (``>= 1``).
            mrcd_threads: Hilos de ``pymrcd`` por proceso (``>= 1``) o ``None``.

        Raises:
            ValueError: Si algún valor es menor que 1.
        """
        if max_workers < 1:
            msg = "max_workers debe ser >= 1"
            raise ValueError(msg)
        if mrcd_threads is not None and mrcd_threads < 1:
            msg = "mrcd_threads debe ser >= 1 o None"
            raise ValueError(msg)
        self.max_workers = max_workers
        self.mrcd_threads = mrcd_threads

    def map[C, T, R](self, fn: Callable[[C, T], R], context: C, tasks: Sequence[T]) -> list[R]:
        """Aplica ``fn(context, task)`` a cada tarea en procesos.

        Args:
            fn: Función pura a nivel de módulo (picklable).
            context: Contexto compartido (se envía una vez por proceso).
            tasks: Tareas.

        Returns:
            Resultados en el orden de ``tasks``. Una excepción de ``fn`` se propaga.
        """
        if not tasks:
            return []
        with ProcessPoolExecutor(
            max_workers=min(self.max_workers, len(tasks)),
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_init_worker,
            initargs=(fn, context, self.mrcd_threads),
        ) as pool:
            # Los resultados son los de ``fn`` (por pickle): el tipo ``R`` lo garantiza el
            # contrato de ``map``, no se puede comprobar en tiempo de ejecución.
            return cast("list[R]", list(pool.map(_call, tasks)))
