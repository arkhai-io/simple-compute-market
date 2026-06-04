"""Compute dynamic listing lifecycle e2e scenario.

This scenario isolates storefront listing reconciliation from the full
buyer/settlement flow:

1. Import one 4x GPU resource.
2. Create one live listing for each 1x, 2x, 3x, and 4x slice.
3. Admin-reserve 2 GPUs and verify 3x/4x listings close.
4. Mark usage started, then capacity released, and verify 3x/4x reopen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pytest

from src.settings import settings
from tests.e2e.roles.scenarios.conftest import require_state

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_compute_dynamic_listings


DYNAMIC_RESOURCE_ID = "compute-e2e-dynamic-4x"
DYNAMIC_RESOURCE_CSV = """resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host
compute-e2e-dynamic-4x,compute.gpu,h200,count,4,available,10000,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,H200,99.0,"California, US",kvm1
"""

ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"},
    "rates": [{"field": "amount", "per": "hour", "value": "10000"}],
}]


@dataclass
class DynamicListingState:
    resources_seeded: bool = False
    listing_ids_by_gpu_count: dict[int, str] = field(default_factory=dict)
    allocation_id: str | None = None
    reserve_closed_listing_ids: list[str] = field(default_factory=list)
    usage_started: bool = False


@pytest.fixture(scope="module")
def dynamic_state() -> DynamicListingState:
    return DynamicListingState()


@pytest.fixture(scope="module")
def seller_wallet() -> str:
    wallet = str(settings.SELLER.WALLET_ADDRESS or "")
    if not wallet:
        pytest.skip("SELLER.WALLET_ADDRESS not configured")
    return wallet


def _offer(gpu_count: int) -> dict:
    return {
        "resource_id": DYNAMIC_RESOURCE_ID,
        "gpu_model": "H200",
        "gpu_count": gpu_count,
        "sla": 99.0,
        "region": "California, US",
    }


def _listing_statuses(storefront_admin_client, ids_by_gpu_count: dict[int, str]) -> dict[int, str]:
    return {
        gpu_count: storefront_admin_client.get_listing(listing_id).status
        for gpu_count, listing_id in ids_by_gpu_count.items()
    }


class TestComputeDynamicListings:
    def test_00_imports_4x_compute_resource(
        self, storefront_admin_client, dynamic_state: DynamicListingState
    ):
        result = storefront_admin_client.admin_import_resources(
            DYNAMIC_RESOURCE_CSV.encode("utf-8"),
            filename="e2e-dynamic-listings.csv",
        )

        assert result.failed_count == 0, (
            f"Dynamic resource import failed for {result.failed_count} row(s): {result}"
        )
        assert result.imported_count >= 1
        dynamic_state.resources_seeded = True
        log.info("[dynamic] imported resource %s", DYNAMIC_RESOURCE_ID)

    def test_01_creates_slice_listings(
        self,
        storefront_admin_client,
        seller_wallet: str,
        dynamic_state: DynamicListingState,
    ):
        require_state(dynamic_state, "resources_seeded")

        for gpu_count in range(1, 5):
            resp = storefront_admin_client.create_listing(
                agent_wallet_address=seller_wallet,
                offer=_offer(gpu_count),
                accepted_escrows=ACCEPTED_ESCROWS,
                max_duration_seconds=3600,
            )
            assert resp.listing_id, f"create_listing returned no id for {gpu_count}x: {resp}"
            listing = storefront_admin_client.get_listing(resp.listing_id)
            assert listing.status == "open"
            dynamic_state.listing_ids_by_gpu_count[gpu_count] = resp.listing_id

        assert set(dynamic_state.listing_ids_by_gpu_count) == {1, 2, 3, 4}
        log.info("[dynamic] created slice listings: %s", dynamic_state.listing_ids_by_gpu_count)

    def test_02_admin_reserve_2x_closes_oversized_listings(
        self, storefront_admin_client, dynamic_state: DynamicListingState
    ):
        require_state(dynamic_state, "listing_ids_by_gpu_count")

        listing_2x = dynamic_state.listing_ids_by_gpu_count[2]
        result = storefront_admin_client.admin_reserve_capacity(
            required_attributes={
                "resource_id": DYNAMIC_RESOURCE_ID,
                "gpu_count": 2,
            },
            listing_id=listing_2x,
            escrow_uid="e2e-dynamic-reserve-2x",
        )

        assert result.allocation_id
        assert result.resource_id == DYNAMIC_RESOURCE_ID
        assert result.gpu_count == 2
        expected_closed = {
            dynamic_state.listing_ids_by_gpu_count[3],
            dynamic_state.listing_ids_by_gpu_count[4],
        }
        assert expected_closed.issubset(set(result.closed_listing_ids))

        statuses = _listing_statuses(
            storefront_admin_client,
            dynamic_state.listing_ids_by_gpu_count,
        )
        assert statuses == {
            1: "open",
            2: "open",
            3: "closed",
            4: "closed",
        }
        dynamic_state.allocation_id = result.allocation_id
        dynamic_state.reserve_closed_listing_ids = list(result.closed_listing_ids)
        log.info("[dynamic] reserved allocation %s; statuses=%s", result.allocation_id, statuses)

    def test_03_usage_started_keeps_oversized_listings_closed(
        self, storefront_admin_client, dynamic_state: DynamicListingState
    ):
        require_state(dynamic_state, "allocation_id")

        result = storefront_admin_client._post(
            "/api/v1/admin/fulfillment/events/usage-started",
            {
                "allocation_id": dynamic_state.allocation_id,
                "escrow_uid": "e2e-dynamic-reserve-2x",
            },
            extra_headers=storefront_admin_client._admin_headers(),
        )

        assert result["state"] == "leased"
        statuses = _listing_statuses(
            storefront_admin_client,
            dynamic_state.listing_ids_by_gpu_count,
        )
        assert statuses == {
            1: "open",
            2: "open",
            3: "closed",
            4: "closed",
        }
        dynamic_state.usage_started = True

    def test_04_capacity_release_reopens_oversized_listings(
        self, storefront_admin_client, dynamic_state: DynamicListingState
    ):
        require_state(dynamic_state, "allocation_id", "usage_started")

        result = storefront_admin_client._post(
            "/api/v1/admin/fulfillment/events/capacity-released",
            {
                "allocation_id": dynamic_state.allocation_id,
                "released_at": "2026-01-01T00:00:00Z",
            },
            extra_headers=storefront_admin_client._admin_headers(),
        )

        assert result["state"] == "released"
        assert set(dynamic_state.reserve_closed_listing_ids).issubset(
            set(result["reopened_listing_ids"])
        )
        statuses = _listing_statuses(
            storefront_admin_client,
            dynamic_state.listing_ids_by_gpu_count,
        )
        assert statuses == {
            1: "open",
            2: "open",
            3: "open",
            4: "open",
        }
        log.info("[dynamic] released allocation %s; statuses=%s", dynamic_state.allocation_id, statuses)
