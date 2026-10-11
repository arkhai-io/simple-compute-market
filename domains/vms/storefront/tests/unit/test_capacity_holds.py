from __future__ import annotations

import pytest

from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient


@pytest.fixture
def client(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "agent.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))


@pytest.mark.asyncio
async def test_capacity_hold_bookkeeping_round_trip(client):
    await client.save_capacity_hold(
        negotiation_id="neg-1",
        listing_id="lst-1",
        capacity_reservation_id="alloc-1",
        payload={"resource_id": "r1", "vm_host": "kvm1"},
        expires_at="2099-01-01T00:00:00+00:00",
    )
    hold = await client.load_capacity_hold(negotiation_id="neg-1")
    assert hold["capacity_reservation_id"] == "alloc-1"
    assert hold["payload"]["vm_host"] == "kvm1"

    await client.delete_capacity_hold(negotiation_id="neg-1")
    assert await client.load_capacity_hold(negotiation_id="neg-1") is None
