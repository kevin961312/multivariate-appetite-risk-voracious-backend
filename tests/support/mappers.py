"""``TaskMapper`` de prueba: orden inverso y procesos reales (``ProcessPoolExecutor``).

``ProcessPoolTaskMapper`` es el boceto del adaptador del Paso 3: el contexto viaja **una vez** por
proceso en el ``initializer`` y cada tarea solo lleva su índice y su semilla (M4).
"""

from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import cast

_WORKER_STATE: dict[str, object] = {}
"""Función y contexto del proceso de trabajo, fijados por el ``initializer``."""


class ReversedTaskMapper:
    """Ejecuta las tareas en orden inverso y devuelve los resultados en el orden original."""

    def __init__(self) -> None:
        self.executed: list[int] = []

    def map[C, T, R](self, fn: Callable[[C, T], R], context: C, tasks: Sequence[T]) -> list[R]:
        results: dict[int, R] = {}
        for i in reversed(range(len(tasks))):
            self.executed.append(i)
            results[i] = fn(context, tasks[i])
        return [results[i] for i in range(len(tasks))]


def _init_worker(fn: Callable[[object, object], object], context: object) -> None:
    _WORKER_STATE["fn"] = fn
    _WORKER_STATE["context"] = context


def _call(task: object) -> object:
    fn = cast("Callable[[object, object], object]", _WORKER_STATE["fn"])
    return fn(_WORKER_STATE["context"], task)


class ProcessPoolTaskMapper:
    """Reparte las tareas en procesos; el contexto se envía una vez por proceso."""

    def __init__(self, max_workers: int = 2) -> None:
        self.max_workers = max_workers

    def map[C, T, R](self, fn: Callable[[C, T], R], context: C, tasks: Sequence[T]) -> list[R]:
        with ProcessPoolExecutor(
            max_workers=self.max_workers, initializer=_init_worker, initargs=(fn, context)
        ) as pool:
            return cast("list[R]", list(pool.map(_call, tasks)))
