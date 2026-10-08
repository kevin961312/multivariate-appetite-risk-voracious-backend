"""``ModelVersionRepository`` en memoria: append-only con comparar-y-cambiar de estado."""

from collections.abc import Sequence
from dataclasses import replace

from voracious.application.ports import DuplicateKeyError, VersionStatusChange
from voracious.application.records import ModelVersion, VersionStatus
from voracious.infrastructure.memory.codec import PassthroughCodec, RecordCodec
from voracious.infrastructure.memory.store import KeyedStore

__all__ = ["InMemoryModelVersionRepository"]

VersionKey = tuple[str, str, str, int]


def _decided(version: ModelVersion, change: VersionStatusChange) -> ModelVersion:
    """Versión con el estado nuevo y los datos de la decisión del cambio.

    Args:
        version: Versión actual.
        change: Cambio a aplicar.

    Returns:
        La versión cambiada.
    """
    out = replace(version, status=change.new)
    decision = change.decision
    if decision is None:
        return out
    approved = change.new is VersionStatus.ACTIVE
    rejected = change.new is VersionStatus.REJECTED
    return replace(
        out,
        effective_from=decision.effective_from if approved else out.effective_from,
        approved_at=decision.decided_at if approved else out.approved_at,
        rejected_at=decision.decided_at if rejected else out.rejected_at,
        decided_by=decision.decided_by,
        decision_note=decision.note,
    )


class InMemoryModelVersionRepository:
    """Versiones con clave (tenant, carta, modelo, número)."""

    def __init__(self, codec: RecordCodec[ModelVersion] | None = None) -> None:
        """Construye el repositorio vacío.

        Args:
            codec: Codec de las versiones; ``None`` guarda la versión tal cual (tests).
        """
        self._store: KeyedStore[VersionKey, ModelVersion] = KeyedStore(
            codec if codec is not None else PassthroughCodec(ModelVersion)
        )

    @staticmethod
    def _key(version: ModelVersion) -> VersionKey:
        return (version.tenant_id, version.chart_id, version.model_id, version.number)

    def add(self, version: ModelVersion) -> None:
        """Añade una versión.

        Args:
            version: Versión.

        Raises:
            DuplicateKeyError: Si ya existe la clave.
        """
        key = self._key(version)
        with self._store.lock:
            if self._store.contains(key):
                raise DuplicateKeyError(str(key))
            self._store.put(key, version)

    def add_proposal_if_none(self, version: ModelVersion) -> bool:
        """Añade una propuesta si el modelo no tiene otra sin resolver (atómico).

        Args:
            version: Versión ``proposed``.

        Returns:
            ``True`` si se añadió.

        Raises:
            ValueError: Si la versión no está ``proposed``.
            DuplicateKeyError: Si ya existe la clave.
        """
        if version.status is not VersionStatus.PROPOSED:
            msg = "add_proposal_if_none solo admite versiones 'proposed'"
            raise ValueError(msg)
        with self._store.lock:
            current = self.list(version.tenant_id, version.chart_id, version.model_id)
            if any(v.status is VersionStatus.PROPOSED for v in current):
                return False
            self.add(version)
            return True

    def get(self, tenant_id: str, chart_id: str, model_id: str, number: int) -> ModelVersion | None:
        """Busca una versión.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.
            number: Número.

        Returns:
            La versión o ``None``.
        """
        return self._store.get((tenant_id, chart_id, model_id, number))

    def list(self, tenant_id: str, chart_id: str, model_id: str) -> list[ModelVersion]:
        """Versiones del modelo ordenadas por número.

        Args:
            tenant_id: Tenant.
            chart_id: Carta.
            model_id: Modelo.

        Returns:
            Las versiones.
        """
        prefix = (tenant_id, chart_id, model_id)
        rows = self._store.select(lambda k: k[:3] == prefix)
        return sorted(rows, key=lambda v: v.number)

    def apply_status_changes(self, changes: Sequence[VersionStatusChange]) -> bool:
        """Aplica todos los cambios o ninguno (comparar-y-cambiar bajo el cerrojo).

        Args:
            changes: Cambios.

        Returns:
            ``True`` si se aplicaron todos.
        """
        keys = [(c.tenant_id, c.chart_id, c.model_id, c.number) for c in changes]
        with self._store.lock:
            current = [self._store.get(k) for k in keys]
            for version, change in zip(current, changes, strict=True):
                if version is None or version.status is not change.expected:
                    return False
            for key, version, change in zip(keys, current, changes, strict=True):
                if version is not None:
                    self._store.put(key, _decided(version, change))
            return True
