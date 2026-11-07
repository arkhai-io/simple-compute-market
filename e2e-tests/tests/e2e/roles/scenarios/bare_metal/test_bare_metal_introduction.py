"""A bare-metal introduction and its retention, on the bare-metal lane.

Against a mock-profile site, the bare-metal storefront, and its registry: the
site's operator declares one pool with two whole hosts, and a storefront pool
override offers that pool by introduction alone. A buyer discovers each
listing, negotiates it, and reveals the introduction through the production
buyer's own transport, reading the retention window on the storefront's
public readiness before committing a contact and again in the reveal. The
scenario ends with an operator deleting the first introduction's payloads. The
held retention sweep is defined by its window passing, which no stage waits
for: the storefronts' integration tests prove it, back-dating a reveal and
stepping the held sweep
(`domains/bare_metal/storefront/tests/test_http_introductions.py`).

Two hosts rather than one listing taken twice: each whole host is one exclusive
unit, so each introduction gets a listing of its own. Re-delivery is a command
run inside the storefront's container, which this pod cannot reach; its refusal
after deletion is proven by the storefront's own tests.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from core_buyer.introductions import IntroductionPayloadsDeleted, IntroductionTransport
from market_contact_exchange import SyncIntroductionAdminClient
from market_identity import Identity, TrustedIdentitySet, create_signer
from market_pool_overrides import SyncPoolOverrideClient
from market_settlement_runtime import derive_obligation_ref
from storefront_client import SyncStorefrontClient
from market_resource_pools_contracts import PoolCreate

from tests.e2e.roles.helpers.compute_deal import assert_storefront_loops_held
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.hosts import register_e2e_host
from tests.e2e.roles.scenarios.bare_metal.conftest import lane_setting

pytestmark = [
    # Listed first, so the holds are taken before, and released after, every
    # other fixture of the module. Every bare-metal-lane module holds the lane's
    # timers, so no cycle a stage did not ask for runs while it observes the
    # stack.
    pytest.mark.usefixtures(
        "storefront_loops_held", "fulfillment_convergence_held", "lease_watchdog_held",
    ),
    pytest.mark.e2e_bare_metal_introduction,
]

BARE_METAL = "bare_metal"
CONTACT_MECHANISM = "contact-exchange.v1"
PUBLICATION = "publication"
SITE_PROJECTIONS = "site-projections"
REGION = "us-west"
GPU_MODEL = "H200"
WHOLE_HOST_CAPACITY = {"units": 1, "gpu_count": 8, "ram_gb": 2048}
# Development fixtures on a reserved domain, never to be used on a public network.
BUYER_CONTACT = {"email": "buyer@bare-metal-e2e.invalid"}
BUYER_AGENT_URL = "https://buyer.bare-metal-e2e.invalid"


@dataclass
class IntroductionState:
    run: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    pool_id: str = ""
    resources: list[str] = field(default_factory=list)
    listing_ids: list[str] = field(default_factory=list)
    negotiations: list[str] = field(default_factory=list)
    obligation_refs: list[str] = field(default_factory=list)
    disclosure: dict[str, Any] = field(default_factory=dict)
    revealed: bool = False
    operator_deleted: bool = False


@pytest.fixture(scope="module")
def state() -> IntroductionState:
    return IntroductionState()


@pytest.fixture(scope="module")
def buyer_storefront():
    """The buyer's storefront client, negotiating as the lane's buyer."""
    client = SyncStorefrontClient(
        lane_setting("storefront_url"),
        create_signer(lane_setting("buyer_scheme"), lane_setting("buyer_credential")),
        caller_role="buyer",
        expected_publishers=_storefront_principals(),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def introductions() -> IntroductionTransport:
    """The production buyer's introduction transport."""
    signer = create_signer(lane_setting("buyer_scheme"), lane_setting("buyer_credential"))
    return IntroductionTransport(
        seller_url=lane_setting("storefront_url"),
        principal=signer.identity,
        signer=signer,
        resolve_seller_principals=_storefront_principals,
    )


def _storefront_principals() -> TrustedIdentitySet:
    return TrustedIdentitySet(
        identities=(
            Identity(
                scheme=lane_setting("storefront_scheme"),
                identifier=lane_setting("storefront_identifier"),
            ),
        )
    )


def _seller_contact() -> dict[str, str]:
    return {"email": lane_setting("seller_contact_email")}


def _expected_disclosure() -> dict[str, Any]:
    return {
        "window_seconds": int(lane_setting("introduction_retention_seconds")),
        "basis": "current_policy",
        "scope": "introduction_record",
    }


def _whole_host(resource_id: str) -> dict[str, Any]:
    return {
        "gpu_model": GPU_MODEL,
        "physical_host_id": f"physical-{resource_id}",
        "allocation_mode": "exclusive",
        "bare_metal_publication": {"enabled": True, "access_methods": ["ssh"]},
    }


def _introduction_option(listing: Any) -> dict[str, Any]:
    options = [
        dict(option)
        for option in listing.settlement_options
        if dict(option)["settlement"].get("schema") == CONTACT_MECHANISM
    ]
    assert len(options) == 1, listing.settlement_options
    return options[0]


class TestStage00_DisclosureBeforeCommitment:
    def test_00_readiness_discloses_the_window_without_authentication(
        self, bare_metal_storefront_public, bare_metal_storefront_admin,
        state: IntroductionState,
    ):
        """A buyer reads the retention window before handing over a contact;
        the module's loops are held, so every publication is a stepped one."""
        assert_storefront_loops_held(bare_metal_storefront_admin)
        health = bare_metal_storefront_public.get_health()
        disclosure = health.disclosures.get("introduction_retention")
        assert disclosure == _expected_disclosure(), health.disclosures
        state.disclosure = disclosure


class TestStage01_OfferIntroduction:
    def test_01_a_pool_override_offers_two_hosts_by_introduction(
        self,
        bare_metal_site_operator,
        bare_metal_site_capacity,
        provisioning_client,
        bare_metal_storefront_admin,
        state: IntroductionState,
    ):
        state.pool_id = f"bm-intro-{state.run}"
        state.resources = [f"bm-intro-host-{state.run}-{index}" for index in (1, 2)]
        bare_metal_site_operator.create_pool(
            PoolCreate(
                id=state.pool_id,
                label=state.pool_id,
                provider="bare_metal.ansible",
                policy_tags={
                    "deliverable_modes": [BARE_METAL],
                    "advertisable_modes": [BARE_METAL],
                    "capacity_backing": "backed",
                    "region": REGION,
                },
                provider_config={},
            )
        )

        async def declare() -> None:
            for resource_id in state.resources:
                # The pool is backed and its provider delivers through a host,
                # so each machine is offered only while its host is registered
                # and enabled. Nothing connects to it under the mock profile.
                register_e2e_host(
                    provisioning_client,
                    name=f"machine-{resource_id}",
                    pool_id=state.pool_id,
                )
                await bare_metal_site_capacity.register_resource(
                    resource_id,
                    pool_id=state.pool_id,
                    host_id=f"machine-{resource_id}",
                    capacity=dict(WHOLE_HOST_CAPACITY),
                    attributes=_whole_host(resource_id),
                )

        asyncio.run(declare())
        # The held poller does not see the new pool; one step of it does.
        bare_metal_storefront_admin.admin_run_lifecycle_cycle(SITE_PROJECTIONS)
        # Only this pool offers introduction: the lane's configured clauses are
        # Alkahest-only, so every other scenario's listings are untouched.
        SyncPoolOverrideClient(bare_metal_storefront_admin).put_pool_override(
            {
                "site_id": lane_setting("site_id"),
                "pool_id": state.pool_id,
                "offering_mode": BARE_METAL,
                "settlements": [
                    {
                        "mechanism": CONTACT_MECHANISM,
                        "asset": "introduction",
                        "mechanism_input": {"profile": "default"},
                    }
                ],
            }
        )

        report = bare_metal_storefront_admin.admin_run_lifecycle_cycle(PUBLICATION)

        published = {
            item["source"]["physical_resource_id"]: str(item["listing_id"])
            for item in report["actions"]
            if item["action"] == "publish"
            and item["source"]["physical_resource_id"] in state.resources
        }
        assert sorted(published) == sorted(state.resources), report
        state.listing_ids = [published[resource] for resource in state.resources]


class TestStage02_Reveal:
    def test_02_the_buyer_negotiates_and_reveals_each_introduction(
        self,
        bare_metal_registry,
        buyer_storefront,
        introductions: IntroductionTransport,
        state: IntroductionState,
    ):
        require_state(state, "listing_ids")
        for listing_id in state.listing_ids:
            option = _introduction_option(bare_metal_registry.get_listing(listing_id))
            accepted = buyer_storefront.negotiate_new(
                listing_id=listing_id,
                initial_amount=None,
                provision_terms={
                    "kind": "bare_metal.v2",
                    "version": 1,
                    "payload": {"duration_seconds": 3600, "access_method": "none"},
                },
                proposal_fields={},
                settlement_selection={
                    "option_id": option["option_id"],
                    "settlement": {"schema": CONTACT_MECHANISM},
                    "expiration_unix": int(time.time()) + 3600,
                },
                selection_only=True,
                buyer_agent_url=BUYER_AGENT_URL,
            )
            assert accepted["action"] == "accept", accepted
            negotiation_id = accepted["negotiation_id"]
            obligation_ref = derive_obligation_ref(
                negotiation_id, 0, accepted["settlement_plan"]["obligations"][0]
            )
            revealed = introductions.start(
                negotiation_id=negotiation_id,
                obligation_ref=obligation_ref,
                contact_payload=dict(BUYER_CONTACT),
            )
            assert revealed["revealed"] is True
            assert revealed["counterparty_contact"] == _seller_contact()
            # The reveal discloses the same window readiness did.
            assert revealed["retention"] == state.disclosure
            state.negotiations.append(negotiation_id)
            state.obligation_refs.append(obligation_ref)
        state.revealed = True


class TestStage03_OperatorDeletion:
    def test_03_an_operator_deletes_one_introduction(
        self,
        bare_metal_storefront_admin,
        introductions: IntroductionTransport,
        state: IntroductionState,
    ):
        require_state(state, "revealed")
        first = state.obligation_refs[0]

        deleted = SyncIntroductionAdminClient(
            bare_metal_storefront_admin
        ).delete_introduction_payloads(first)

        assert deleted.obligation_ref == first
        assert deleted.redacted is True
        assert deleted.payloads_deleted_at
        with pytest.raises(IntroductionPayloadsDeleted) as on_read:
            introductions.read(obligation_ref=first)
        assert on_read.value.payloads_deleted_at == deleted.payloads_deleted_at
        # A fresh start, not an exact replay, reveals nothing either.
        with pytest.raises(IntroductionPayloadsDeleted):
            introductions.start(
                negotiation_id=state.negotiations[0],
                obligation_ref=first,
                contact_payload=dict(BUYER_CONTACT),
            )
        state.operator_deleted = True
