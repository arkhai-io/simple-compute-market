"""A VM delivery record's read times come from the process time source.

Library integration: the VM store over a database its migration chain built. The
resume pass lists unfinished deliveries by their last change and claims each
until a lease instant it compares with the store's own time; under an injected
source each of those times is the source's instant, never a read of the wall
clock.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.migrations import migrate_storefront_database
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fulfillment_fixtures import seed_delivery_admission, vm_delivery_evidence

pytestmark = pytest.mark.asyncio


def _times(path: str) -> tuple[str, str, str | None]:
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT created_at, updated_at, processing_lease_until FROM vm_delivery_records"
            " WHERE negotiation_id = 'payment-1'"
        ).fetchone()


async def test_a_delivery_record_holds_the_injected_instant(tmp_path, injected_source):
    path = str(tmp_path / "delivery.db")
    migrate_storefront_database(path)
    db = SQLiteClient(path, registry=build_vm_storefront_registry(build_vm_storefront_domain()))
    await db.save_vm_settlement_evidence(
        vm_delivery_evidence(negotiation_id="payment-1", settlement_ref="transaction-1")
    )
    seed_delivery_admission(db, negotiation_id="payment-1", commitment_ref="transaction-1")
    start = datetime.fromtimestamp(injected_source.now(), timezone.utc)

    assert await db.insert_vm_delivery(negotiation_id="payment-1")
    assert _times(path) == (start.isoformat(), start.isoformat(), None)

    later = start + timedelta(minutes=10)
    injected_source.set(int(later.timestamp()))
    lease = later + timedelta(minutes=1)
    assert await db.claim_vm_delivery(
        negotiation_id="payment-1", owner="worker-a", lease_until=lease.isoformat()
    )
    assert _times(path) == (start.isoformat(), later.isoformat(), lease.isoformat())

    # Another worker's claim is refused until the source reaches the lease.
    assert not await db.claim_vm_delivery(
        negotiation_id="payment-1", owner="worker-b", lease_until=lease.isoformat()
    )
    injected_source.set(int(lease.timestamp()) + 1)
    assert await db.claim_vm_delivery(
        negotiation_id="payment-1", owner="worker-b", lease_until=lease.isoformat()
    )
