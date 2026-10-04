"""Lifecycle-event sinks deliver an event once."""

from datetime import datetime, timezone
import pytest
from compute_provisioning import (
    IdempotentLifecycleEventSink,
)
from compute_provisioning_contracts import (
    LifecycleEvent,
)


@pytest.mark.asyncio
async def test_event_sink_deduplicates_only_after_successful_delivery():
    delivered = []
    sink = IdempotentLifecycleEventSink(lambda event: _record(delivered, event.event_id))
    event = LifecycleEvent(
        event_id="event-1",
        capacity_reservation_id="alloc-1",
        deal_ref={"escrow_uid": "escrow-1"},
        offering_mode="vm",
        event_kind="usage_ready",
        payload={},
        occurred_at=datetime.now(timezone.utc),
    )
    assert await sink.deliver(event) is True
    assert await sink.deliver(event) is False
    assert delivered == ["event-1"]


async def _record(values, value):
    values.append(value)
