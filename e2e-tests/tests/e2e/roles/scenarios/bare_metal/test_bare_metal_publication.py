"""Bare-metal publication from pool declarations, on the bare-metal lane.

Against a running site in the provisioning mock profile, a bare-metal
storefront, and a registry: the site's operator declares pools and whole-host
capacity, the storefront's administrator steps publication, and a buyer
discovers what it published. A buyer finds the listing by
the hardware its declaration states, through the registry's own filter
vocabulary. The scenario then withdraws the pool's advertisement and restores
it, following the one listing through a close and a reopen at the registry. It
then prices the machine: the pool declares an asking rate, a storefront override
replaces it and its lease bound, and deleting the override restores the pool's.
Each change refreshes the same listing in place, and a buyer finds it by rate
through the registry's filter vocabulary. Finally it declares a pool that states
no region and observes it held.

Publication has no timer; each step is one explicit pass, so every transition
here is invoked by the scenario. Registry convergence after a missed close,
and holding a site whose projection cannot be read, are proven by the
storefront's own cycle tests: this lane cannot inject a registry fault or stop
a service mid-run.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from arkhai_bare_metal import derive_bare_metal_shape
from market_pool_overrides import SyncPoolOverrideClient, pool_override_statuses
from registry_client.query import compile_resource_query
from market_resource_pools_contracts import PoolCreate, PoolUpdate

from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.scenarios.bare_metal.conftest import lane_setting

pytestmark = pytest.mark.e2e_bare_metal_publication

PUBLICATION = "publication"
BARE_METAL = "bare_metal"
REGION = "us-west"
# One whole machine: the unit a bare-metal claim reserves, and the hardware it
# contains, which the listing publishes where the compute filters read it.
WHOLE_HOST_CAPACITY = {"units": 1, "gpu_count": 8, "ram_gb": 2048}
GPU_MODEL = "H200"
# The shape a whole-host declaration reads as, which an asking rate is keyed by.
MACHINE_SHAPE = derive_bare_metal_shape(WHOLE_HOST_CAPACITY, {"gpu_model": GPU_MODEL})
RATE_QUERY = "asking_rate_asset=usd asking_rate_period=hour"


@dataclass
class PublicationState:
    run: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    advertised_pool: str = ""
    dark_pool: str = ""
    advertised_resource: str = ""
    dark_resource: str = ""
    listing_id: str = ""
    withdrawn: bool = False
    reinstated: bool = False
    priced: bool = False
    overridden: bool = False
    regionless_pool: str = ""


@pytest.fixture(scope="module")
def state() -> PublicationState:
    return PublicationState()


def _declarations(
    *, advertised: bool, region: str | None = REGION, asking_rate: str | None = None
) -> dict[str, Any]:
    declarations: dict[str, Any] = {
        "deliverable_modes": [BARE_METAL],
        "advertisable_modes": [BARE_METAL] if advertised else [],
        "capacity_backing": "backed",
    }
    if region is not None:
        declarations["region"] = region
    if asking_rate is not None:
        declarations["asking_rates"] = {BARE_METAL: [_rate(asking_rate)]}
    return declarations


def _rate(amount: str) -> dict[str, Any]:
    return {"shape": MACHINE_SHAPE, "amount": amount, "asset": "usd", "period": "hour"}


def _found(registry, query: str) -> set[str]:
    """Listings a buyer finds, compiled against the registry's own specification."""
    compiled = compile_resource_query(
        query, filter_spec=registry.get_filter_spec(), registry_url=lane_setting("registry_url")
    )
    response = registry.list_listings(
        offering_mode=BARE_METAL, etag=compiled.etag, **compiled.as_params()
    )
    return {listing.id for listing in response.listings}


def _refreshed_fields(report: dict[str, Any], listing_id: str) -> list[str]:
    (refresh,) = [
        item for item in _with_listing(report, listing_id) if item["action"] == "refresh"
    ]
    return sorted(refresh["fields"])


def _whole_host(resource_id: str) -> dict[str, Any]:
    """A whole-host declaration's attributes: the GPU model admission matches,
    the accounting facts the site reads, and the bare-metal view's switch."""
    return {
        "gpu_model": GPU_MODEL,
        "physical_host_id": f"physical-{resource_id}",
        "allocation_mode": "exclusive",
        "bare_metal_publication": {"enabled": True, "access_methods": ["ssh"]},
    }


async def _declare_whole_host(capacity_client, resource_id: str, pool_id: str) -> None:
    await capacity_client.register_resource(
        resource_id,
        pool_id=pool_id,
        host_id=f"machine-{resource_id}",
        capacity=dict(WHOLE_HOST_CAPACITY),
        attributes=_whole_host(resource_id),
    )


def _step(storefront_admin) -> dict[str, Any]:
    return storefront_admin.admin_run_lifecycle_cycle(PUBLICATION)


def _actions(report: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [item for item in report["actions"] if item["action"] == action]


def _with_listing(report: dict[str, Any], listing_id: str) -> list[dict[str, Any]]:
    return [item for item in report["actions"] if item.get("listing_id") == listing_id]


class TestStage00_Preconditions:
    def test_00_the_site_projection_is_loaded(self, bare_metal_storefront_public):
        """The storefront reads its one site's resource-pool projection."""
        health = bare_metal_storefront_public.get_health()
        site = health.site_projections[lane_setting("site_id")]["resource_pool"]
        assert site["state"] == "loaded", site


class TestStage01_DeclareSupply:
    def test_01_declare_pools_and_whole_host_capacity(
        self,
        bare_metal_site_operator,
        bare_metal_site_capacity,
        state: PublicationState,
    ):
        """One pool advertises bare metal; another delivers it and advertises
        nothing. Each gets one whole-host declaration carrying a bare-metal view."""
        state.advertised_pool = f"bm-advertised-{state.run}"
        state.dark_pool = f"bm-dark-{state.run}"
        state.advertised_resource = f"bm-advertised-host-{state.run}"
        state.dark_resource = f"bm-dark-host-{state.run}"
        for pool_id, advertised in (
            (state.advertised_pool, True),
            (state.dark_pool, False),
        ):
            bare_metal_site_operator.create_pool(
                PoolCreate(
                    id=pool_id,
                    label=pool_id,
                    provider="bare_metal.ansible",
                    policy_tags=_declarations(advertised=advertised),
                    provider_config={},
                )
            )

        async def declare() -> None:
            for resource_id, pool_id in (
                (state.advertised_resource, state.advertised_pool),
                (state.dark_resource, state.dark_pool),
            ):
                await _declare_whole_host(bare_metal_site_capacity, resource_id, pool_id)

        asyncio.run(declare())


class TestStage02_Publish:
    def test_02_one_step_publishes_only_the_advertised_resource(
        self, bare_metal_storefront_admin, state: PublicationState
    ):
        require_state(state, "advertised_resource")
        report = _step(bare_metal_storefront_admin)

        published = _actions(report, "publish")
        sources = [item["source"]["physical_resource_id"] for item in published]
        assert state.advertised_resource in sources, report
        assert state.dark_resource not in sources, report
        (ours,) = [
            item
            for item in published
            if item["source"]["physical_resource_id"] == state.advertised_resource
        ]
        assert ours["source"]["pool_id"] == state.advertised_pool
        assert ours["status"] == "published", ours
        assert _actions(report, "fail") == [], report
        state.listing_id = str(ours["listing_id"])


class TestStage03_Discover:
    def test_03_the_registry_and_the_storefront_return_the_listing_open(
        self,
        bare_metal_registry,
        bare_metal_storefront_public,
        state: PublicationState,
    ):
        require_state(state, "listing_id")
        listing = bare_metal_registry.get_listing(state.listing_id)

        assert listing.status == "open"
        assert listing.storefront_url.rstrip("/") == lane_setting("storefront_url")
        resource = listing.listing_resource
        assert resource["offering_mode"] == BARE_METAL
        assert resource["capacity_backing"] == "backed"
        assert resource["host_id"] == f"machine-{state.advertised_resource}"
        assert resource["physical_host_id"] == f"physical-{state.advertised_resource}"
        assert (resource["gpu_count"], resource["gpu_model"], resource["ram_gb"]) == (
            8, GPU_MODEL, 2048,
        )
        assert resource["region"] == REGION
        assert "capabilities" not in resource

        local = bare_metal_storefront_public.get_listing(state.listing_id)
        assert local.status == "open"


class TestStage03b_DiscoverByHardware:
    def test_03b_a_hardware_query_finds_the_listing_and_a_larger_one_does_not(
        self, bare_metal_registry, state: PublicationState
    ):
        """Compiled against the registry's own filter specification, as the
        bare-metal buyer's ``list --resource`` compiles it."""
        require_state(state, "listing_id")
        assert state.listing_id in _found(
            bare_metal_registry, f"gpu_model={GPU_MODEL} gpu_count>=8 region={REGION}"
        )
        assert state.listing_id not in _found(
            bare_metal_registry, f"gpu_model={GPU_MODEL} gpu_count>=9"
        )


class TestStage04_Withdraw:
    def test_04_a_pool_that_stops_advertising_closes_its_listing(
        self,
        bare_metal_site_operator,
        bare_metal_storefront_admin,
        bare_metal_registry,
        state: PublicationState,
    ):
        require_state(state, "listing_id")
        bare_metal_site_operator.patch_pool(
            state.advertised_pool,
            PoolUpdate(policy_tags=_declarations(advertised=False)),
        )

        report = _step(bare_metal_storefront_admin)

        assert _with_listing(report, state.listing_id) == [
            {"action": "close", "listing_id": state.listing_id, "reason": "source_gone"}
        ], report
        assert bare_metal_registry.get_listing(state.listing_id).status == "closed"
        state.withdrawn = True


class TestStage05_Reinstate:
    def test_05_advertising_again_reopens_the_same_listing(
        self,
        bare_metal_site_operator,
        bare_metal_storefront_admin,
        bare_metal_registry,
        bare_metal_storefront_public,
        state: PublicationState,
    ):
        require_state(state, "withdrawn")
        bare_metal_site_operator.patch_pool(
            state.advertised_pool,
            PoolUpdate(policy_tags=_declarations(advertised=True)),
        )

        report = _step(bare_metal_storefront_admin)

        reopened = [
            item
            for item in _with_listing(report, state.listing_id)
            if item["action"] == "reopen"
        ]
        assert reopened, report
        assert not [
            item
            for item in _actions(report, "publish")
            if item["source"]["physical_resource_id"] == state.advertised_resource
        ], "the reopened resource must not publish a second listing"
        assert bare_metal_registry.get_listing(state.listing_id).status == "open"
        assert bare_metal_storefront_public.get_listing(state.listing_id).status == "open"
        state.reinstated = True


class TestStage05b_PriceThePool:
    def test_05b_a_declared_rate_refreshes_the_listing_and_is_found_by_rate(
        self,
        bare_metal_site_operator,
        bare_metal_storefront_admin,
        bare_metal_registry,
        state: PublicationState,
    ):
        require_state(state, "reinstated")
        bare_metal_site_operator.patch_pool(
            state.advertised_pool,
            PoolUpdate(policy_tags=_declarations(advertised=True, asking_rate="12.50")),
        )

        report = _step(bare_metal_storefront_admin)

        assert _refreshed_fields(report, state.listing_id) == ["asking_rate"], report
        listing = bare_metal_registry.get_listing(state.listing_id)
        assert listing.listing_resource["asking_rate"] == {
            "amount": "12.50", "asset": "usd", "period": "hour",
        }
        assert state.listing_id in _found(bare_metal_registry, f"asking_rate<=12.50 {RATE_QUERY}")
        assert state.listing_id not in _found(
            bare_metal_registry, f"asking_rate<=12.49 {RATE_QUERY}"
        )
        assert state.listing_id not in _found(
            bare_metal_registry, f"asking_rate_min>12.50 {RATE_QUERY}"
        )
        state.priced = True


class TestStage05c_OverrideThePrice:
    def test_05c_a_storefront_override_replaces_the_rate_and_bound(
        self, bare_metal_storefront_admin, bare_metal_registry, state: PublicationState
    ):
        require_state(state, "priced")
        SyncPoolOverrideClient(bare_metal_storefront_admin).put_pool_override(
            {
                "site_id": lane_setting("site_id"),
                "pool_id": state.advertised_pool,
                "offering_mode": BARE_METAL,
                "asking_rates": [_rate("9.00")],
                "terms": {"max_duration_seconds": 7200},
            }
        )

        report = _step(bare_metal_storefront_admin)

        assert "asking_rate" in _refreshed_fields(report, state.listing_id), report
        listing = bare_metal_registry.get_listing(state.listing_id)
        assert listing.listing_resource["asking_rate"]["amount"] == "9.00"
        assert listing.max_duration_seconds == 7200
        statuses = pool_override_statuses(bare_metal_storefront_admin.get_system_status())
        assert (state.advertised_pool, "applied") in {
            (item["pool_id"], item["state"]) for item in statuses or []
        }, statuses
        state.overridden = True


class TestStage05d_DeleteTheOverride:
    def test_05d_deleting_the_override_restores_the_pools_rate(
        self, bare_metal_storefront_admin, bare_metal_registry, state: PublicationState
    ):
        require_state(state, "overridden")
        SyncPoolOverrideClient(bare_metal_storefront_admin).delete_pool_override(
            lane_setting("site_id"), state.advertised_pool, BARE_METAL
        )

        report = _step(bare_metal_storefront_admin)

        assert "asking_rate" in _refreshed_fields(report, state.listing_id), report
        listing = bare_metal_registry.get_listing(state.listing_id)
        assert listing.listing_resource["asking_rate"]["amount"] == "12.50"
        assert listing.status == "open"


class TestStage06_RegionlessPool:
    def test_06_a_pool_stating_no_region_is_held_and_publishes_nothing(
        self,
        bare_metal_site_operator,
        bare_metal_site_capacity,
        bare_metal_storefront_admin,
        state: PublicationState,
    ):
        require_state(state, "listing_id")
        state.regionless_pool = f"bm-regionless-{state.run}"
        resource_id = f"bm-regionless-host-{state.run}"
        bare_metal_site_operator.create_pool(
            PoolCreate(
                id=state.regionless_pool,
                label=state.regionless_pool,
                provider="bare_metal.ansible",
                policy_tags=_declarations(advertised=True, region=None),
                provider_config={},
            )
        )
        asyncio.run(
            _declare_whole_host(bare_metal_site_capacity, resource_id, state.regionless_pool)
        )

        report = _step(bare_metal_storefront_admin)

        assert not [
            item
            for item in _actions(report, "publish")
            if item["source"]["pool_id"] == state.regionless_pool
        ], report
        assert any(
            item.get("pool_id") == state.regionless_pool
            and item["reason"] == "pool_region_missing"
            for item in _actions(report, "hold")
        ), report
