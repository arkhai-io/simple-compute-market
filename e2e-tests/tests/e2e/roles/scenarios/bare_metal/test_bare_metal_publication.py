"""Bare-metal publication from pool declarations, on the bare-metal lane.

Against a running site in the provisioning mock profile, a bare-metal
storefront, and a registry: the site's operator declares pools and whole-host
capacity, the storefront's administrator steps publication, and a buyer
discovers what it published. The scenario then withdraws the pool's
advertisement and restores it, and follows the one listing through a close and
a reopen at the registry.

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
from vm_provisioning_operator import PoolCreate, PoolUpdate

from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.scenarios.bare_metal.conftest import lane_setting

pytestmark = pytest.mark.e2e_bare_metal_publication

PUBLICATION = "publication"
BARE_METAL = "bare_metal"


@dataclass
class PublicationState:
    run: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    advertised_pool: str = ""
    dark_pool: str = ""
    advertised_resource: str = ""
    dark_resource: str = ""
    listing_id: str = ""
    withdrawn: bool = False


@pytest.fixture(scope="module")
def state() -> PublicationState:
    return PublicationState()


def _declarations(*, advertised: bool) -> dict[str, Any]:
    return {
        "deliverable_modes": [BARE_METAL],
        "advertisable_modes": [BARE_METAL] if advertised else [],
        "capacity_backing": "backed",
    }


def _whole_host(resource_id: str) -> dict[str, Any]:
    return {
        "physical_host_id": f"physical-{resource_id}",
        "allocation_mode": "exclusive",
        "bare_metal_publication": {
            "enabled": True,
            "access_methods": ["ssh"],
            "capabilities": {"gpu_model": "H200"},
        },
    }


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
                await bare_metal_site_capacity.register_resource(
                    resource_id,
                    pool_id=pool_id,
                    host_id=f"machine-{resource_id}",
                    total_units=1,
                    attributes=_whole_host(resource_id),
                )

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

        local = bare_metal_storefront_public.get_listing(state.listing_id)
        assert local.status == "open"


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
