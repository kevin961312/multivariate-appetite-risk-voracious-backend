"""Stub tipado mínimo de ``threadpoolctl`` (3.7): solo lo que usa ``infrastructure/parallel.py``.

``threadpoolctl`` no publica ``py.typed`` ni anota ``threadpool_limits.__init__``. En lugar de
relajar mypy (``untyped_calls_exclude`` o ``follow_untyped_imports``), este stub declara la única
llamada que hace el proyecto. En tiempo de ejecución ``threadpool_limits`` es una clase; aquí se
declara como una función que devuelve el limitador, que es como se usa.
"""

class ThreadpoolLimiter:
    """Limitador activo de los hilos de BLAS/OpenMP (``threadpool_limits`` en ejecución)."""

    def restore_original_limits(self) -> None:
        """Restaura los límites de hilos anteriores."""

def threadpool_limits(limits: int | None = None, user_api: str | None = None) -> ThreadpoolLimiter:
    """Limita los hilos de las librerías nativas (BLAS, OpenMP).

    Args:
        limits: Hilos máximos por librería, o ``None`` para no cambiarlos.
        user_api: ``"blas"``, ``"openmp"`` o ``None`` (todas).

    Returns:
        El limitador activo.
    """
