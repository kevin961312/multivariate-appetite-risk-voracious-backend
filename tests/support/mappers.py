"""``TaskMapper`` de prueba: orden inverso; los procesos reales son el adaptador de producción.

``ProcessPoolTaskMapper`` se reexporta desde ``voracious.infrastructure.parallel`` (el boceto del
Paso 2 pasó a producción en el Paso 3). ``boom_task`` es una tarea a nivel de módulo que falla,
para comprobar que la excepción de un proceso llega al llamador.
"""

from collections.abc import Callable, Sequence

from voracious.infrastructure.parallel import ProcessPoolTaskMapper

__all__ = ["ProcessPoolTaskMapper", "ReversedTaskMapper", "boom_task"]


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


def boom_task(context: object, task: int) -> int:
    """Devuelve ``task`` salvo en la tarea 3, que lanza ``ValueError``."""
    if task == 3:
        raise ValueError(f"tarea {task} falló")
    return task
