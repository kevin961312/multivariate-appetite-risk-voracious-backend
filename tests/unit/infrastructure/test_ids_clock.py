import uuid
from datetime import UTC

from voracious.infrastructure.clock import SystemClock
from voracious.infrastructure.ids import UuidIdGenerator


def test_uuid_ids_are_unique_uuid4() -> None:
    ids = UuidIdGenerator()
    a, b = ids.new_id(), ids.new_id()
    assert a != b
    assert uuid.UUID(a).version == 4


def test_system_clock_is_utc() -> None:
    assert SystemClock().now().tzinfo is UTC
