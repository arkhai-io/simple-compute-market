from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import provisioning_client
from market_storefront.services import publication_service
from market_storefront.services import fulfillment_service
from domains.vms.listings.reconciler import record_derived_listing
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import FakeSite, pump_events, site_capacity


@pytest.fixture
def client(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "agent.db"))


async def _seed_compute_pool(client: SQLiteClient) -> None:
    await client.upsert_resource(
        resource_id="pool-h200-1",
        resource_type="compute.gpu",
        resource_subtype="h200",
        unit="count",
        value=1,
        state="available",
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
        },
    )


async def _seed_compute_listings(client: SQLiteClient, *, max_gpu_count: int) -> None:
    for gpu_count in range(1, max_gpu_count + 1):
        listing_id = f"listing-{gpu_count}x"
        await client.upsert_listing(
            listing_id=listing_id,
            status="open",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            offer_resource={
                "resource_id": "pool-h200-1",
                "gpu_model": "H200",
                "gpu_count": gpu_count,
                "region": "California, US",
                "sla": 99.0,
            },
            accepted_escrows=_compute_listing(gpu_count=gpu_count)["accepted_escrows"],
            demands=[],
            fulfillment_resource=None,
            max_duration_seconds=3600,
            seller="http://seller",
        )
        record_derived_listing(
            client.db_path,
            listing_id=listing_id,
            resource_id="pool-h200-1",
            gpu_count=gpu_count,
        )


def _compute_listing(*, gpu_count: int = 1) -> dict:
    return {
        "listing_id": f"listing-{gpu_count}x",
        "offer_resource": {
            "resource_id": "pool-h200-1",
            "gpu_model": "H200",
            "gpu_count": gpu_count,
            "region": "California, US",
            "sla": 99.0,
        },
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {
                    "token": "0x" + "22" * 20,
                },
                "rates": [{"amount": 100}],
            }
        ],
    }


@pytest.mark.asyncio
async def test_fulfill_compute_obligation_reports_error_when_onchain_fulfillment_fails(
    client,
    monkeypatch,
):
    class FakeProvisioningClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def register_lease(self, **kwargs):
            return {"id": "lease-1", **kwargs}

    await _seed_compute_pool(client)
    fake = FakeSite()
    fake.add_resource(
        "pool-h200-1", 1,
        attributes={"gpu_model": "H200", "region": "California, US", "vm_host": "host-1"},
    )
    monkeypatch.setattr(fulfillment_service, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(publication_service, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(
        provisioning_client,
        "ProvisioningClient",
        FakeProvisioningClient,
    )
    monkeypatch.setattr(
        fulfillment_service,
        "_do_provision",
        AsyncMock(return_value={"ssh": "ssh tenant@example"}),
    )
    monkeypatch.setattr(fulfillment_service, "_do_shutdown", AsyncMock())

    alkahest = MagicMock()
    alkahest.string_obligation.do_obligation = AsyncMock(
        side_effect=RuntimeError("contract reverted")
    )
    alkahest.oracle.request_arbitration = AsyncMock()

    with site_capacity(fake, sqlite_client_factory=lambda: client):
        result = await fulfillment_service.fulfill_compute_obligation(
            client=alkahest,
            escrow_uid="escrow-1",
            ssh_public_key="ssh-ed25519 AAAA",
            order=_compute_listing(),
            duration_seconds=3600,
            listing_id="listing-1",
        )

    assert result["status"] == "error"
    assert "contract reverted" in result["message"]
    assert result["connection_details"] is None
    alkahest.oracle.request_arbitration.assert_not_called()

    # The VM exists and the lease was committed before the on-chain step
    # failed — the ledger keeps the capacity held.
    assert fake._available("pool-h200-1") == 0
    states = {a["state"] for a in fake.allocations.values()}
    assert states == {"leased"}


@pytest.mark.asyncio
async def test_reservation_closes_oversized_dynamic_listings(client, monkeypatch):
    class FakeProvisioningClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def register_lease(self, **kwargs):
            return {"id": "lease-1", **kwargs}

    await _seed_compute_pool(client)
    await client.upsert_resource(
        resource_id="pool-h200-1",
        resource_type="compute.gpu",
        resource_subtype="h200",
        unit="count",
        value=4,
        state="available",
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
        },
    )
    await _seed_compute_listings(client, max_gpu_count=4)
    fake = FakeSite()
    fake.add_resource(
        "pool-h200-1", 4,
        attributes={"gpu_model": "H200", "region": "California, US", "vm_host": "host-1"},
    )
    monkeypatch.setattr(fulfillment_service, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(publication_service, "get_sqlite_client", lambda: client)
    monkeypatch.setattr(
        provisioning_client,
        "ProvisioningClient",
        FakeProvisioningClient,
    )
    monkeypatch.setattr(
        fulfillment_service,
        "_do_provision",
        AsyncMock(return_value={"ssh": "ssh tenant@example"}),
    )
    monkeypatch.setattr(fulfillment_service, "_do_shutdown", AsyncMock())

    with site_capacity(fake, sqlite_client_factory=lambda: client) as aggregate:
        result = await fulfillment_service.fulfill_compute_obligation(
            client=None,
            escrow_uid="escrow-2x",
            ssh_public_key="ssh-ed25519 AAAA",
            order=_compute_listing(gpu_count=2),
            duration_seconds=3600,
            listing_id="listing-2x",
        )
        # The poller delivers deltas in production; pump them here.
        await pump_events(aggregate, fake)

    assert result["status"] == "fulfilled"
    statuses = {
        gpu_count: (await client.load_listing(listing_id=f"listing-{gpu_count}x"))[
            "status"
        ]
        for gpu_count in range(1, 5)
    }
    assert statuses == {
        1: "open",
        2: "open",
        3: "closed",
        4: "closed",
    }
