"""``Clock`` de producción: hora del sistema en UTC."""

from datetime import UTC, datetime

__all__ = ["SystemClock"]


class SystemClock:
    """Reloj del sistema."""

    def now(self) -> datetime:
        """Instante actual.

        Returns:
            La hora actual con zona UTC.
        """
        return datetime.now(UTC)
