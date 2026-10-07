"""Reparto de tareas independientes (p. ej. réplicas bootstrap) sin acoplar el dominio a procesos.

El dominio solo describe *qué* se calcula: una función pura ``fn(context, task)`` aplicada a cada
tarea. *Cómo* se reparte (en serie, en un ``ProcessPoolExecutor``, en Celery) lo decide un
adaptador de infraestructura que implemente ``TaskMapper``.

El ``context`` se entrega **una sola vez** por llamada y no viaja dentro de cada tarea: un
adaptador con procesos puede enviarlo a cada proceso en su ``initializer`` y despachar solo las
tareas (pequeñas: índice y semilla). Contrato para cualquier implementación:

- ``fn``, ``context`` y cada tarea son *picklables* (``fn`` definida a nivel de módulo);
- el resultado conserva el orden de ``tasks``;
- el resultado no depende del orden de ejecución ni del número de procesos (cada tarea lleva su
  propia semilla);
- si ``fn`` lanza, la excepción se propaga al llamador.
"""

from collections.abc import Callable, Sequence
from typing import Protocol

__all__ = ["SerialTaskMapper", "TaskMapper"]


class TaskMapper(Protocol):
    """Puerto de ejecución de tareas independientes con un contexto compartido."""

    def map[C, T, R](self, fn: Callable[[C, T], R], context: C, tasks: Sequence[T]) -> list[R]:
        """Aplica ``fn(context, task)`` a cada tarea.

        Args:
            fn: Función pura a nivel de módulo.
            context: Datos compartidos por todas las tareas (se envían una vez).
            tasks: Tareas independientes.

        Returns:
            Resultados en el mismo orden que ``tasks``.
        """
        ...


class SerialTaskMapper:
    """``TaskMapper`` en serie, en el proceso actual (por defecto y para tests)."""

    def map[C, T, R](self, fn: Callable[[C, T], R], context: C, tasks: Sequence[T]) -> list[R]:
        """Aplica ``fn(context, task)`` a cada tarea, en orden.

        Args:
            fn: Función a aplicar.
            context: Datos compartidos.
            tasks: Tareas.

        Returns:
            Resultados en el mismo orden que ``tasks``.
        """
        return [fn(context, task) for task in tasks]
