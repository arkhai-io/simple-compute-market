"""A bare-metal introduction and its retention, on the bare-metal lane.

Against a mock-profile site, the bare-metal storefront, and its registry: the
site's operator declares one pool with two whole hosts, and a storefront pool
override offers that pool by introduction alone. A buyer discovers each
listing, negotiates it, and reveals the introduction through the production
buyer's own transport, reading the retention window on the storefront's
public readiness before committing a contact and again in the reveal. An
operator deletes the first introduction's payloads; the retention sweep, held
and stepped, deletes the second's once its window has passed.

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
from market_identity import Identity, TrustedIdentitySet, create_signer
from market_pool_overrides import SyncPoolOverrideClient
from market_settlement_runtime import derive_obligation_ref
from storefront_client import SyncStorefrontClient
from vm_provisioning_operator import PoolCreate

from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.scenarios.bare_metal.conftest import lane_setting

pytestmark = [
    pytest.mark.e2e_bare_metal_introduction,
    pytest.mark.usefixtures("held_loops"),
]

BARE_METAL = "bare_metal"
CONTACT_MECHANISM = "contact-exchange.v1"
PUBLICATION = "publication"
RETENTION = "introduction-retention"
REGION = "us-west"
GPU_MODEL = "H200"
WHOLE_HOST_CAPACITY = {"units": 1, "gpu_count": 8, "ram_gb": 2048}
# Development fixtures on a reserved domain, never to be used on a public network.
BUYER_CONTACT = {"email": "buyer@bare-metal-e2e.invalid"}
BUYER_AGENT_URL = "https://buyer.bare-metal-e2e.invalid"
# How long to wait for the retention window to pass before the preview reports
# an introduction: the window is seconds long, so this bounds a failure rather
# than paces a success.
EXPIRY_DEADLINE_SECONDS = 60.0
EXPIRY_POLL_SECONDS = 0.5


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
def held_loops(bare_metal_storefront_admin):
    """Hold the storefront's timer loops for this module and resume afterwards.

    The scenario steps the retention sweep itself, so its timer must not run
    the cycle the scenario is about to observe. Resumed in a finaliser so a
    failing stage does not leave the next module with the loops stopped.
    """
    held = bare_metal_storefront_admin.admin_pause_lifecycle_loops()
    assert held["loops"].get("introduction_retention") == "paused", held
    yield
    bare_metal_storefront_admin.admin_resume_lifecycle_loops()


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
        if dict(option).get("mechanism") == CONTACT_MECHANISM
    ]
    assert len(options) == 1, listing.settlement_options
    return options[0]


class TestStage00_DisclosureBeforeCommitment:
    def test_00_readiness_discloses_the_window_without_authentication(
        self, bare_metal_storefront_public, state: IntroductionState
    ):
        """A buyer reads the retention window before handing over a contact."""
        health = bare_metal_storefront_public.get_health()
        disclosure = health.disclosures.get("introduction_retention")
        assert disclosure == _expected_disclosure(), health.disclosures
        state.disclosure = disclosure


class TestStage01_OfferIntroduction:
    def test_01_a_pool_override_offers_two_hosts_by_introduction(
        self,
        bare_metal_site_operator,
        bare_metal_site_capacity,
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
                await bare_metal_site_capacity.register_resource(
                    resource_id,
                    pool_id=state.pool_id,
                    host_id=f"machine-{resource_id}",
                    capacity=dict(WHOLE_HOST_CAPACITY),
                    attributes=_whole_host(resource_id),
                )

        asyncio.run(declare())
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
                    "mechanism": CONTACT_MECHANISM,
                    "option_id": option["option_id"],
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

        deleted = bare_metal_storefront_admin.admin_delete_introduction_payloads(first)

        assert deleted["obligation_ref"] == first
        assert deleted["redacted"] is True
        assert deleted["payloads_deleted_at"]
        with pytest.raises(IntroductionPayloadsDeleted) as on_read:
            introductions.read(obligation_ref=first)
        assert on_read.value.payloads_deleted_at == deleted["payloads_deleted_at"]
        # A fresh start, not an exact replay, reveals nothing either.
        with pytest.raises(IntroductionPayloadsDeleted):
            introductions.start(
                negotiation_id=state.negotiations[0],
                obligation_ref=first,
                contact_payload=dict(BUYER_CONTACT),
            )
        state.operator_deleted = True


class TestStage04_RetentionSweep:
    def test_04_the_held_sweep_previews_then_deletes_the_expired_introduction(
        self,
        bare_metal_storefront_admin,
        introductions: IntroductionTransport,
        state: IntroductionState,
    ):
        require_state(state, "operator_deleted")
        second = state.obligation_refs[1]

        # The preview is the observable transition: it names the introduction
        # once its reveal is a window old, and writes nothing while it waits.
        deadline = time.monotonic() + EXPIRY_DEADLINE_SECONDS
        while True:
            preview = bare_metal_storefront_admin.admin_dry_run_lifecycle_cycle(RETENTION)
            if second in preview["eligible"]:
                break
            assert time.monotonic() < deadline, preview
            time.sleep(EXPIRY_POLL_SECONDS)
        # The operator-deleted introduction is no longer eligible: only the
        # one whose window passed is.
        assert preview["eligible"] == [second], preview

        stepped = bare_metal_storefront_admin.admin_run_lifecycle_cycle(RETENTION)

        assert stepped == {"loop": "introduction_retention", "deleted": 1}, stepped
        with pytest.raises(IntroductionPayloadsDeleted):
            introductions.read(obligation_ref=second)
