"""Registros append-only en memoria: observaciones, anotaciones y eventos estructurales."""

from collections.abc import Sequence
from datetime import datetime

from voracious.application.ports import DuplicateKeyError
from voracious.application.records import ObservationRecord, SignalAnnotation, StructuralEvent
from voracious.infrastructure.memory.codec import PassthroughCodec, RecordCodec
from voracious.infrastructure.memory.store import KeyedStore

__all__ = [
    "InMemoryObservationRepository",
    "InMemorySignalAnnotationRepository",
    "InMemoryStructuralEventRepository",
]

ChildKey = tuple[str, str, str, str]


class InMemoryObservationRepository:
    """``ObservationRepository`` en memoria con clave (tenant, carta, modelo, observación)."""

    def __init__(self, codec: RecordCodec[ObservationRecord] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec de las observaciones; ``None`` las guarda tal cual.
        """
        self._store: KeyedStore[ChildKey, ObservationRecord] = KeyedStore(
            codec if codec is not None else PassthroughCodec(ObservationRecord)
        )

    def _of(self, tenant_id: str, chart_id: str, model_id: str) -> list[ObservationRecord]:
        prefix = (tenant_id, chart_id, model_id)
        return self._store.select(lambda k: k[:3] == prefix)

    def add_many(self, records: Sequence[ObservationRecord]) -> None:
        """Añade observaciones (todas o ninguna).

        Args:
            records: Observaciones.

        Raises:
            DuplicateKeyError: Si alguna clave se repite o ya existe.
        """
        keys = [(r.tenant_id, r.chart_id, r.model_id, r.observation_id) for r in records]
        with self._store.lock:
            if len(set(keys)) != len(keys) or any(self._store.contains(k) for k in keys):
                raise DuplicateKeyError("observación repetida")
            for key, record in zip(keys, records, strict=True):
                self._store.put(key, record)

    def get(
        self, tenant_id: str, chart_id: str, model_id: str, observation_id: str
    ) -> ObservationRecord | None:
        """Busca una observación.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observation_id: Observación.

        Returns:
            La observación o ``None``.
        """
        return self._store.get((tenant_id, chart_id, model_id, observation_id))

    def list(
        self,
        tenant_id: str,
        chart_id: str,
        model_id: str,
        *,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
        signals_only: bool = False,
    ) -> list[ObservationRecord]:
        """Observaciones del rango (inclusivo), por fecha y orden de registro.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observed_from: Inicio o ``None``.
            observed_to: Fin o ``None``.
            signals_only: Solo señales.

        Returns:
            Las observaciones.
        """
        rows = [
            r
            for r in self._of(tenant_id, chart_id, model_id)
            if (observed_from is None or r.observed_at >= observed_from)
            and (observed_to is None or r.observed_at <= observed_to)
            and (not signals_only or r.signal)
        ]
        return sorted(rows, key=lambda r: r.observed_at)

    def max_observed_at(self, tenant_id: str, chart_id: str, model_id: str) -> datetime | None:
        """Fecha de la última observación del modelo.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            La mayor fecha o ``None``.
        """
        rows = self._of(tenant_id, chart_id, model_id)
        return max((r.observed_at for r in rows), default=None)

    def count_scored_with(
        self, tenant_id: str, chart_id: str, model_id: str, version_number: int
    ) -> int:
        """Observaciones puntuadas con una versión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            version_number: Versión.

        Returns:
            El recuento.
        """
        rows = self._of(tenant_id, chart_id, model_id)
        return sum(r.version_number == version_number for r in rows)


class InMemorySignalAnnotationRepository:
    """``SignalAnnotationRepository`` append-only con clave (tenant, carta, modelo, anotación)."""

    def __init__(self, codec: RecordCodec[SignalAnnotation] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec de las anotaciones; ``None`` las guarda tal cual.
        """
        self._store: KeyedStore[ChildKey, SignalAnnotation] = KeyedStore(
            codec if codec is not None else PassthroughCodec(SignalAnnotation)
        )

    def add(self, annotation: SignalAnnotation) -> None:
        """Añade una anotación.

        Args:
            annotation: Anotación.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        a = annotation
        key = (a.tenant_id, a.chart_id, a.model_id, a.annotation_id)
        with self._store.lock:
            if self._store.contains(key):
                raise DuplicateKeyError(str(key))
            self._store.put(key, annotation)

    def history(
        self, tenant_id: str, chart_id: str, model_id: str, observation_id: str
    ) -> list[SignalAnnotation]:
        """Anotaciones de una observación, de la más antigua a la más reciente.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observation_id: Observación.

        Returns:
            Las anotaciones.
        """
        prefix = (tenant_id, chart_id, model_id)
        rows = self._store.select(lambda k: k[:3] == prefix)
        return [a for a in rows if a.observation_id == observation_id]

    def latest_for(
        self, tenant_id: str, chart_id: str, model_id: str, observation_ids: Sequence[str]
    ) -> dict[str, SignalAnnotation]:
        """Anotación más reciente de cada observación pedida que tenga alguna.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            observation_ids: Observaciones.

        Returns:
            ``observation_id → anotación``.
        """
        wanted = set(observation_ids)
        prefix = (tenant_id, chart_id, model_id)
        out: dict[str, SignalAnnotation] = {}
        for annotation in self._store.select(lambda k: k[:3] == prefix):
            if annotation.observation_id in wanted:
                out[annotation.observation_id] = annotation
        return out


class InMemoryStructuralEventRepository:
    """``StructuralEventRepository`` append-only con clave (tenant, carta, modelo, evento)."""

    def __init__(self, codec: RecordCodec[StructuralEvent] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec de los eventos; ``None`` los guarda tal cual.
        """
        self._store: KeyedStore[ChildKey, StructuralEvent] = KeyedStore(
            codec if codec is not None else PassthroughCodec(StructuralEvent)
        )

    def add(self, event: StructuralEvent) -> None:
        """Añade un evento.

        Args:
            event: Evento.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        key = (event.tenant_id, event.chart_id, event.model_id, event.event_id)
        with self._store.lock:
            if self._store.contains(key):
                raise DuplicateKeyError(str(key))
            self._store.put(key, event)

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[StructuralEvent]:
        """Eventos del modelo por ``occurred_at`` y, a igualdad, por registro.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            Los eventos.
        """
        prefix = (tenant_id, chart_id, model_id)
        rows = self._store.select(lambda k: k[:3] == prefix)
        return sorted(rows, key=lambda e: (e.occurred_at, e.registered_at))
