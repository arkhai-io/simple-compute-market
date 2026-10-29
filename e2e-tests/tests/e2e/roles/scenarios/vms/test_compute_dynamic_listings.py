"""Compute dynamic listing lifecycle e2e scenario.

This scenario isolates storefront listing reconciliation from the full
buyer/settlement flow:

1. Declare one 4x GPU resource at the site.
2. Create one live listing for each 1x, 2x, 3x, and 4x slice.
3. Admin-reserve 2 GPUs and verify 3x/4x listings close.
4. Release the capacity and verify 3x/4x reopen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pytest
from market_pool_overrides import SyncPoolOverrideClient

from e2e_harness.settings import settings
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_DYNAMIC_HOST,
    E2E_FUNGIBLE_HOSTS,
    provision_e2e_executor,
    refresh_storefront_projections,
)
from tests.e2e.roles.helpers.compute_deal import assert_storefront_loops_held
from tests.e2e.roles.scenarios.vms.conftest import capacity_site_id, capacity_source_for, require_state

log = logging.getLogger(__name__)

pytestmark = [
    # Listed first, so the hold is taken before, and released after, every
    # other fixture of the module; the lane's cleanup follows it, so it runs
    # while the hold stands.
    pytest.mark.usefixtures(
        "storefront_loops_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
    ),
    pytest.mark.e2e_compute_dynamic_listings,
]


#: This scenario's own pool. One pool per scenario: a pool's `listing_mode`
#: is resolved per pool and its structural default flips above one member, so
#: sharing one would let adding a scenario change how another publishes.
DYNAMIC_POOL_ID = "compute-e2e-dynamic-pool"
DYNAMIC_RESOURCE_ID = "compute-e2e-dynamic-4x"
FUNGIBLE_POOL_ID = "compute-e2e-fungible-pool"
ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"},
    "rates": [{"field": "amount", "per": "hour", "value": "10000"}],
}]


@dataclass
class DynamicListingState:
    storefront_held: bool = False
    supply_declared: bool = False
    listing_ids_by_gpu_count: dict[int, str] = field(default_factory=dict)
    capacity_reservation_id: str | None = None
    reserve_closed_listing_ids: list[str] = field(default_factory=list)


@dataclass
class FungiblePoolState:
    supply_declared: bool = False
    listing_ids_by_gpu_count: dict[int, str] = field(default_factory=dict)
    reservation_2x_id: str | None = None
    reservation_4x_id: str | None = None


@pytest.fixture(scope="module")
def dynamic_state() -> DynamicListingState:
    return DynamicListingState()


@pytest.fixture(scope="module")
def fungible_state() -> FungiblePoolState:
    return FungiblePoolState()


@pytest.fixture(scope="module")
def seller_wallet() -> str:
    wallet = str(settings.SELLER.WALLET_ADDRESS or "")
    if not wallet:
        pytest.skip("SELLER.WALLET_ADDRESS not configured")
    return wallet


def _offer(gpu_count: int) -> dict:
    return {
        # The storefront refuses a listing whose resource does not declare the
        # offering mode its domain binding selected.
        "offering_mode": "vm",
        "resource_id": DYNAMIC_RESOURCE_ID,
        # Resource-keyed *and* pool-bound: a `specific_resource` candidate is
        # still a member of its pool, and the durable binding keys on
        # (site, pool[, resource]).
        "pool_id": DYNAMIC_POOL_ID,
        "gpu_model": "H200",
        "gpu_count": gpu_count,
        "sla": 99.0,
        "region": "California, US",
    }


def _pool_offer(gpu_count: int) -> dict:
    return {
        "offering_mode": "vm",
        "pool_id": FUNGIBLE_POOL_ID,
        "gpu_model": "H200",
        "gpu_count": gpu_count,
        "sla": 99.0,
        "region": "California, US",
    }


def _declare_pool_sla(storefront_admin_client, pool_id: str) -> None:
    """State the pool's SLA as the storefront's own term for it.

    A pool's own `sla` hint is consulted only by a storefront configured to
    trust it, so the storefront states the SLA these listings advertise.
    """
    SyncPoolOverrideClient(storefront_admin_client).put_pool_override(
        {
            "site_id": capacity_site_id(),
            "pool_id": pool_id,
            "offering_mode": "vm",
            "terms": {"sla": 99.0},
        }
    )


def _listing_statuses(storefront_admin_client, ids_by_gpu_count: dict[int, str]) -> dict[int, str]:
    return {
        gpu_count: storefront_admin_client.get_listing(listing_id).status
        for gpu_count, listing_id in ids_by_gpu_count.items()
    }


class TestComputeDynamicListings:
    def test_00_the_storefront_loops_are_held(
        self, storefront_admin_client, dynamic_state: DynamicListingState
    ):
        """The storefront's timer loops are held for this scenario.

        The module holds them through ``storefront_loops_held``; this stage
        asserts the hold because every later assertion depends on it: with the
        loops running, a listing status read after a reserve races the capacity
        poller's next cycle. Advances are explicit from here on.
        """
        assert_storefront_loops_held(storefront_admin_client)
        dynamic_state.storefront_held = True

    def test_00a_registers_executor_host_and_syncs_projection(
        self, provisioning_client, storefront_admin_client,
        site_capacity_admin_client, dynamic_state: DynamicListingState,
    ):
        """Declare this scenario's resource at the site, with its executor host.

        The site authority projects capacity by iterating host rows, so with no
        host registered the projection is empty and `test_02`'s reserve is
        refused with "No available compute VM matched required attributes".

        Registered through the admin API rather than a mounted inventory file:
        `inventory_path` is docker-compose-specific while the canonical Helm
        deployment supplies inventory as an inline secret, and a mount is shared
        state no scenario declares. The projection pull that follows is asserted
        rather than slept out.
        """
        require_state(dynamic_state, "storefront_held")

        # `reserve` matches CapacityBucket rows, which only a capacity declaration
        # creates: a host record declares nothing. The declaration's attributes
        # mirror the listing so a claim built from it matches by equality.
        host = provision_e2e_executor(
            provisioning_client,
            site_capacity_admin_client,
            host=E2E_DYNAMIC_HOST,
            resource_id=DYNAMIC_RESOURCE_ID,
            sellable_units=4,
            pool_id=DYNAMIC_POOL_ID,
            listing_mode="specific_resource",
            region="California, US",
            attributes={
                "gpu_model": "H200",
                "region": "California, US",
                "sla": "99.0",
            },
        )
        assert host.host_id == E2E_DYNAMIC_HOST

        sites = refresh_storefront_projections(storefront_admin_client)
        _declare_pool_sla(storefront_admin_client, DYNAMIC_POOL_ID)
        dynamic_state.supply_declared = True

        # The cardinality hint above was declared under `listing_mode`, the
        # deprecated ingestion spelling, which makes this pool an unupgraded
        # producer: every other renamed boundary in the vocabulary cutover is
        # loud on skew, and this one alone stays accepted so a site does not
        # have to move in lockstep. Asserting it here is what makes the
        # concession evidence rather than an assumption -- the listings this
        # scenario goes on to create are the cardinality being honoured
        # end to end, across the site authority, the projection, and the
        # storefront's publication.
        #
        # The notice is the other half. A pool whose value arrived under the
        # deprecated key earns an operator-visible entry naming what to
        # change, so an alias that silently worked forever would be a defect
        # of its own.
        status = storefront_admin_client.get_system_status()
        explanations = status.listing_cardinality_mode_explanations or {}
        notices = {
            pool_id: notice
            for site_notices in explanations.values()
            for pool_id, notice in (site_notices or {}).items()
        }
        assert DYNAMIC_POOL_ID in notices, (
            f"pool {DYNAMIC_POOL_ID!r} declared its cardinality under the "
            f"deprecated `listing_mode` key, so the storefront owes an "
            f"operator notice naming it; got {notices!r}"
        )
        assert "listing_mode" in notices[DYNAMIC_POOL_ID], (
            f"the notice for {DYNAMIC_POOL_ID!r} should name the deprecated "
            f"key an operator must change: {notices[DYNAMIC_POOL_ID]!r}"
        )

        dynamic_state.executor_host_registered = True
        log.info(
            "[dynamic] executor host %s registered; projections "
            "confirmed for %s; deprecated cardinality key reported for %s",
            E2E_DYNAMIC_HOST, sorted(sites), DYNAMIC_POOL_ID,
        )

    def test_01_creates_slice_listings(
        self,
        storefront_admin_client, storefront_seller_client,
        seller_wallet: str,
        dynamic_state: DynamicListingState,
    ):
        require_state(dynamic_state, "supply_declared")

        for gpu_count in range(1, 5):
            resp = storefront_seller_client.create_listing(
                listing_resource=_offer(gpu_count),
                capacity_source=capacity_source_for(_offer(gpu_count)),
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

        assert result.capacity_reservation_id
        # `pool_id` rather than a resource: the boundary reports pool membership
        # and withholds physical identity, and the claim below already pinned
        # the resource it had to match.
        assert result.pool_id == DYNAMIC_POOL_ID
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
        dynamic_state.capacity_reservation_id = result.capacity_reservation_id
        dynamic_state.reserve_closed_listing_ids = list(
            expected_closed.intersection(result.closed_listing_ids)
        )
        log.info("[dynamic] reserved reservation %s; statuses=%s", result.capacity_reservation_id, statuses)

    def test_04_capacity_release_reopens_oversized_listings(
        self, storefront_admin_client, storefront_service_client, dynamic_state: DynamicListingState
    ):
        require_state(dynamic_state, "capacity_reservation_id")

        result = storefront_service_client.notify_capacity_released(
            dynamic_state.capacity_reservation_id,
            site_id=capacity_site_id(),
            released_at="2026-01-01T00:00:00Z",
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
        log.info("[dynamic] released reservation %s; statuses=%s", dynamic_state.capacity_reservation_id, statuses)


class TestFungibleComputeDynamicListings:
    def test_00a_registers_executor_hosts_and_syncs_projection(
        self, provisioning_client, storefront_admin_client,
        site_capacity_admin_client, fungible_state: FungiblePoolState,
    ):
        """Register one executor per pool member, each with its own declaration.

        A fungible pool is several executors with one capacity declaration each. Two
        declarations on one executor would advertise eight GPUs on a four-GPU
        machine, and the site authority refuses that correlation outright — so the
        member count is what makes the pool fungible, not the row count.

        The grouped-capacity projection collapses the two identically-shaped
        declarations into one entry carrying `resource_count`, which is the source
        the storefront publishes a fungible listing from.

        Registered through the admin APIs rather than a mounted inventory file:
        `inventory_path` is docker-compose-specific while the canonical Helm
        deployment supplies inventory as an inline secret, and a mount is shared
        state no scenario declares. The projection pull that follows is asserted
        rather than slept out.
        """
        members = ("compute-e2e-fungible-a", "compute-e2e-fungible-b")
        hosts = []
        for host_name, member in zip(E2E_FUNGIBLE_HOSTS, members):
            hosts.append(provision_e2e_executor(
                provisioning_client,
                site_capacity_admin_client,
                host=host_name,
                resource_id=member,
                sellable_units=4,
                pool_id=FUNGIBLE_POOL_ID,
                listing_mode="fungible",
                region="California, US",
                attributes={
                    "gpu_model": "H200",
                    "region": "California, US",
                    "sla": "99.0",
                },
            ))

        assert [host.host_id for host in hosts] == list(E2E_FUNGIBLE_HOSTS)

        sites = refresh_storefront_projections(storefront_admin_client)
        _declare_pool_sla(storefront_admin_client, FUNGIBLE_POOL_ID)

        fungible_state.supply_declared = True
        log.info(
            "[fungible] executor hosts %s registered; projections confirmed for %s",
            list(E2E_FUNGIBLE_HOSTS), sorted(sites),
        )

    def test_01_creates_one_pool_listing_set(
        self,
        storefront_admin_client, storefront_seller_client,
        seller_wallet: str,
        fungible_state: FungiblePoolState,
    ):
        require_state(fungible_state, "supply_declared")

        for gpu_count in range(1, 5):
            resp = storefront_seller_client.create_listing(
                listing_resource=_pool_offer(gpu_count),
                capacity_source=capacity_source_for(_pool_offer(gpu_count)),
                accepted_escrows=ACCEPTED_ESCROWS,
                max_duration_seconds=3600,
            )
            assert resp.listing_id, f"create_listing returned no id for {gpu_count}x: {resp}"
            listing = storefront_admin_client.get_listing(resp.listing_id)
            assert listing.status == "open"
            fungible_state.listing_ids_by_gpu_count[gpu_count] = resp.listing_id

        assert set(fungible_state.listing_ids_by_gpu_count) == {1, 2, 3, 4}

    def test_02_reserve_2x_keeps_large_slices_open(
        self, storefront_admin_client, fungible_state: FungiblePoolState
    ):
        require_state(fungible_state, "listing_ids_by_gpu_count")

        result = storefront_admin_client.admin_reserve_capacity(
            required_attributes={
                "pool_id": FUNGIBLE_POOL_ID,
                "gpu_count": 2,
            },
            listing_id=fungible_state.listing_ids_by_gpu_count[2],
            escrow_uid="e2e-fungible-reserve-2x",
        )

        assert result.capacity_reservation_id
        assert result.extra.get("pool_id") == FUNGIBLE_POOL_ID or result.pool_id == FUNGIBLE_POOL_ID
        assert result.gpu_count == 2
        assert result.closed_listing_ids == []
        statuses = _listing_statuses(
            storefront_admin_client,
            fungible_state.listing_ids_by_gpu_count,
        )
        assert statuses == {1: "open", 2: "open", 3: "open", 4: "open"}
        fungible_state.reservation_2x_id = result.capacity_reservation_id

    def test_03_reserve_4x_closes_oversized_pool_slices(
        self, storefront_admin_client, fungible_state: FungiblePoolState
    ):
        require_state(fungible_state, "reservation_2x_id")

        result = storefront_admin_client.admin_reserve_capacity(
            required_attributes={
                "pool_id": FUNGIBLE_POOL_ID,
                "gpu_count": 4,
            },
            listing_id=fungible_state.listing_ids_by_gpu_count[4],
            escrow_uid="e2e-fungible-reserve-4x",
        )

        assert result.capacity_reservation_id
        assert result.gpu_count == 4
        expected_closed = {
            fungible_state.listing_ids_by_gpu_count[3],
            fungible_state.listing_ids_by_gpu_count[4],
        }
        assert expected_closed.issubset(set(result.closed_listing_ids))
        statuses = _listing_statuses(
            storefront_admin_client,
            fungible_state.listing_ids_by_gpu_count,
        )
        assert statuses == {
            1: "open",
            2: "open",
            3: "closed",
            4: "closed",
        }
        fungible_state.reservation_4x_id = result.capacity_reservation_id
