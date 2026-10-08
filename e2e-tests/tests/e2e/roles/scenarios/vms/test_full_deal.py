"""Full buyer-seller deal lifecycle — sequential e2e test suite.

VM's run of the compute family's canonical deal. The stages VM shares with
bare metal are defined once in ``helpers/compute_deal_stages.py`` and declared
here, in order, by subclassing; VM's own stages (00f, 02b, 03a, 03b, 09a2) are
inserted in place, and ``VmComputeDealDriver`` supplies VM's part of the shared
ones.

Stage map
---------
Phase 0 — E2E readiness (all services healthy, no state changes)
  00a  Storefront reachable:    GET /health → status=ok, database=ok
  00b  Registry reachable:      GET /api/v1/system/status → checks.registry=ok
  00c  Provisioning ready:      GET provisioning /api/v1/system/status →
                                checks.execution=ok, every component ready
  00c2 Contract pins agree:     storefront and provisioning report one major
  00d  Negotiation strategy viable: checks.negotiation_strategy not exit-on-probe
  00e  Provisioning mock mode:  GET /api/v1/system/status → execution.mocked
  00f  Resource seed:           POST /api/v1/admin/portfolio/resources/import
                                upserts the compute row this test needs
  00g  Alkahest configured:     GET /api/v1/system/status → checks.alkahest=ok
                                gates Phase 7b (on-chain escrow verification)
  00h  Provisioning→storefront: GET provisioning /api/v1/system/status →
                                checks.storefront=ok, checks.storefront_auth=ok

Phase 2 — Listing creation (paused)
  02b  Create listing paused + confirm:
         POST /listings/create paused=True → listing_id
         GET /api/v1/listings/{id} → status=open, paused=True
         GET registry/listings → listing absent (publish suppressed)

Phase 3 — Registry publication
  03a  Validate listing publishable: POST registry /api/v1/listings/validate-publish → valid=True
  03b  Resume + registry confirm:
         POST /api/v1/listings/{id}/resume → registry_status=published
         (the publisher is created lazily on this first signed publish)
         GET registry/listings → listing present

Phase 4 — Registry publication
  04a  Primary registry: listing visible in the registry used by this topology

Phase 5 — Negotiation lifecycle
  05a  Evaluate-negotiate dry-run:
         POST /api/v1/admin/listings/{id}/evaluate-negotiate → would_negotiate=True
  05b  Negotiation starts + visible + round confirmed:
         POST /api/v1/negotiate/new → negotiation_id
         GET /api/v1/listings/{id}/negotiations → thread visible
         stage_events: round_decided with decision != exit

Phase 6 — Negotiation settlement
  06b  Force-accept + terminal state:
         Guard: no exit events before force-accept
         POST .../force-accept → action=accept
         GET .../negotiations/{neg_id} → terminal_state=success;
                                          escrows=[] (none until phase 7)

Phase 7 — On-chain escrow + provisioning gate setup
  07   Create real escrow_uid; add provisioning mock rule (pause_before_result=True)
  07b  Verify escrow via storefront dry-run

Phase 8 — Settlement pipeline
  08b  Settlement submitted + fulfillment dispatched:
         POST /api/v1/settle/{uid} → status=provisioning
         wait_for_stage_event(provision, job_submitted)
         GET /settle/{uid}/status → fulfillment_id present, state=dispatching
         (resource identity is confirmed later, via admin introspection, at 09c)

Phase 9 — Provisioning completion
  09a  Release gate + job completes: resume_rule; wait_for_job → succeeded
  09b  Settlement ready + credentials + listing closed:
         wait_for_settlement (server-side long-poll) → ready=True, status=ready
         GET /settle/{uid}/status → status=ready, tenant_credentials present
         GET /api/v1/listings/{id} → status=closed
         GET .../negotiations/{neg_id} → primary escrow status=ready,
                                          fulfillment_uid populated
  09c  Lease recorded:
         GET provisioning /api/v1/leases/by-escrow/{uid} -> active/pending lease

Phase 10 — Lease expiry and durable teardown
  10a  Pause automatic lease servicing, arm the provider teardown gate, and
       back-date the lease end so the watchdog reads it as expired. Expiry is
       what ends a lease in production; admin interruption is an escape hatch
       for a deal sold as interruptible and is covered elsewhere.
  10b  Run one lease cycle → reservation releasing, fulfillment id recorded,
       fulfillment teardown_dispatch_pending, capacity still held.

Phase 11 — Fulfillment convergence and resource release
  11a  Run one fulfillment cycle → tearing_down while capacity remains held.
  11b  Complete provider teardown, converge to torn_down, run one lease cycle →
       released; observe storefront release, capacity reuse, and cleanup.
"""

from __future__ import annotations

import logging

import pytest
from market_alkahest.alkahest import get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from registry_client import ValidatePublishRequest

from tests.e2e.roles.helpers.compute_deal import advance_storefront, dry_run_storefront
from tests.e2e.roles.helpers.compute_deal_stages import (
    DEAL_TOKEN,
    DURATION_HOURS,
    LISTED_HOURLY_RATE,
    Stage00_LifecyclePause,
    Stage00a_StorefrontHealth,
    Stage00b_RegistryReachable,
    Stage00c_ProvisioningHealth,
    Stage00c2_ProvisioningContractPins,
    Stage00d_NegotiationStrategy,
    Stage00e_ProvisioningMockMode,
    Stage00f1_ExecutorHostRegistry,
    Stage00g_AlkahestConfigured,
    Stage00h_ProvisioningStorefrontLink,
    Stage04a_PrimaryRegistryPublish,
    Stage05a_EvaluateNegotiate,
    Stage05b_NegotiationStartsAndVisible,
    Stage06b_ForceAcceptAndTerminal,
    Stage07_OnChainEscrowAndProvGate,
    Stage07b_VerifyEscrow,
    Stage08a_EvaluateSettle,
    Stage08b_SettlementSubmittedAndJobQueued,
    Stage08c_EvaluateProvisioningJob,
    Stage09a_ProvisioningCompletes,
    Stage09b_SettlementReadyAndCredentials,
    Stage09bb_ClaimSubmittedForTheFulfilledEscrow,
    Stage09c_LeaseRecorded,
    Stage10a_LeaseExpirySetup,
    Stage10b_LeaseCycleBeginsTeardown,
    Stage11a_TeardownDispatch,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.scenarios.vms.compute_deal_driver import E2E_RESOURCE_ID
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.scenarios.vms.conftest import DealState, capacity_source_for, one_site

log = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.e2e_deal,
    # This module advances fulfillment convergence itself, so the
    # 30s timer is stopped for its duration -- otherwise a timer
    # cycle can claim a row mid-provider-call and the module's own
    # explicit cycle reaches nothing.
    pytest.mark.usefixtures("convergence_advanced_explicitly"),
]

# ---------------------------------------------------------------------------
# VM's listing: the offer, its escrow advertisement, and its resource row
# ---------------------------------------------------------------------------

OFFER_RESOURCE = {
    # The storefront refuses a listing whose resource does not declare the
    # offering mode its domain binding selected.
    "offering_mode": "vm",
    "interruptible": True,
    # Matches E2E_RESOURCE_CSV below. The test imports that CSV through the
    # storefront admin API so it does not depend on a mounted resource file.
    "resource_id": "compute-e2e-deal-001",
    "gpu_model": "RTX 5080",
    "gpu_count": 1,
    "sla": 90.0,
    "region": "California, US",
}
# The canonical deal's token, at the asking rate every lane's listing advertises.
DEMAND_RESOURCE = {"token": DEAL_TOKEN, "amount": LISTED_HOURLY_RATE}
# Listing-side accepted_escrows advertisement. The escrow_address here is a
# stub — the buyer sends the placeholder zero address on its EscrowProposal
# (see negotiate_new's defaults), which skips the accepted-escrow
# (chain, address) strict match; field-level equality on
# literal_fields["token"] is what gates the proposal. The real
# escrow_address used on-chain is what the buyer's CLI resolves through
# alkahest at settle time.
ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": DEMAND_RESOURCE["token"]["contract_address"]},
    "rates": [{"field": "amount", "per": "hour", "value": str(DEMAND_RESOURCE["amount"])}],
}]

_ALKAHEST_ADDRESSES_PATH = str(anvil_address_book_path())


def _recipient_demands(seller_wallet: str) -> list[dict]:
    return [{
        "chain_name": "anvil",
        "arbiter": get_recipient_arbiter(
            "anvil", config_path=_ALKAHEST_ADDRESSES_PATH,
        ).lower(),
        "demand_data": {"recipient": seller_wallet.lower()},
    }]


E2E_RESOURCE_CSV = """resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host
compute-e2e-deal-001,compute.gpu,rtx5080,count,1,available,10,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,RTX 5080,90.0,"California, US",kvm1
"""

# ===========================================================================
# Phase 0 — E2E readiness
# ===========================================================================

class TestStage00_LifecyclePause(Stage00_LifecyclePause):
    pass


class TestStage00a_StorefrontHealth(Stage00a_StorefrontHealth):
    pass


class TestStage00b_RegistryReachable(Stage00b_RegistryReachable):
    pass


class TestStage00c_ProvisioningHealth(Stage00c_ProvisioningHealth):
    pass


class TestStage00c2_ProvisioningContractPins(Stage00c2_ProvisioningContractPins):
    pass


class TestStage00d_NegotiationStrategy(Stage00d_NegotiationStrategy):
    pass


class TestStage00e_ProvisioningMockMode(Stage00e_ProvisioningMockMode):
    pass


class TestStage00f_ResourceSeed:
    def test_00f_imports_e2e_resource_inventory(
        self, storefront_admin_client, deal_state: DealState
    ):
        """Import the compute resource row required by this scenario.

        The e2e deal should not depend on a container-mounted CSV. Importing
        an inline fixture through the admin API keeps this scenario
        self-contained while exercising the same upsert path operators use.
        """
        require_state(
            deal_state, "_storefront_healthy", "_provisioning_mock_mode",
            "_contract_pins_agree",
        )

        result = storefront_admin_client.admin_import_resources(
            E2E_RESOURCE_CSV.encode("utf-8"),
            filename="e2e-deal-resources.csv",
        )
        assert result.failed_count == 0, (
            f"E2E resource import failed for {result.failed_count} row(s): {result}"
        )
        assert result.imported_count >= 1, (
            f"Expected at least one imported resource row, got: {result}"
        )

        status = storefront_admin_client.get_system_status()
        assert (status.resource_count or 0) >= 1, (
            f"Storefront still reports no resources after import: {status}"
        )

        deal_state._resources_seeded = True
        log.info(
            "[00f] Imported e2e resource inventory row %s (resource_count=%s)",
            E2E_RESOURCE_ID,
            status.resource_count,
        )


class TestStage00f1_ExecutorHostRegistry(Stage00f1_ExecutorHostRegistry):
    pass


class TestStage00g_AlkahestConfigured(Stage00g_AlkahestConfigured):
    pass


class TestStage00h_ProvisioningStorefrontLink(Stage00h_ProvisioningStorefrontLink):
    pass



# ===========================================================================
# Phase 2 — Listing creation (paused)
# ===========================================================================

class TestStage02b_CreateListingPaused:
    def test_02b_create_listing_paused_local_only(
        self, storefront_admin_client,
        storefront_seller_client, seller_wallet, registry_client, deal_state: DealState
    ):
        """Create listing with paused=True; confirm locally visible and registry absent.

        Three assertions in one advance step — all validate the single decision
        that paused=True suppresses registry publication:
          1. listing_id returned from create
          2. local GET shows status=open, paused=True
          3. registry GET does NOT contain the listing
        """
        require_state(
            deal_state, "_resources_seeded", "_registry_reachable", "_supply_seeded",
        )

        resp = storefront_seller_client.create_listing(
            listing_resource=OFFER_RESOURCE,
            capacity_source=capacity_source_for(OFFER_RESOURCE),
            accepted_escrows=ACCEPTED_ESCROWS,
            demands=_recipient_demands(seller_wallet),
            max_duration_seconds=DURATION_HOURS * 3600,
            paused=True,
        )
        listing_id = resp.listing_id
        assert listing_id, (
            f"No listing_id in response — listing-create returned no id.\n"
            f"Response: {resp}\n"
            f"Check storefront logs for create_listing errors."
        )

        # Confirm locally visible with paused=True
        listing = storefront_admin_client.get_listing(listing_id)
        assert listing.status == "open", (
            f"Expected status=open, got {listing.status!r}"
        )
        assert listing.paused is True, (
            f"Expected paused=True after paused create, got paused={listing.paused}"
        )

        # Confirm registry does NOT yet contain the listing
        result = registry_client.list_listings(status="open", limit=200)
        ids = {o.id for o in result.listings}
        assert listing_id not in ids, (
            f"Listing {listing_id} found in registry before resume — "
            f"paused=True did not suppress the publish."
        )

        deal_state.seller_listing_id = listing_id
        log.info("[02b] Listing %s created (paused=True, absent from registry)", listing_id)


# ===========================================================================
# Phase 3 — Registry publication
# ===========================================================================

# ===========================================================================
# Phase 3a — Validate publish payload (registry dry-run)
# ===========================================================================

class TestStage03a_ValidatePublish:
    def test_03a_listing_payload_validates_against_registry(
        self, registry_client, registry_seller_client, deal_state: DealState
    ):
        """POST registry /api/v1/listings/validate-publish → valid=True (dry-run).

        Structural pre-flight: confirms the listing's listing_resource/escrows payload
        is recognisable to the registry before resume triggers the actual
        publish. Uses the same ``ACCEPTED_ESCROWS`` constant the create_listing
        call advertised so the dry-run matches the to-be-published shape.
        """
        require_state(deal_state, "seller_listing_id")
        req = ValidatePublishRequest(
            listing_id=deal_state.seller_listing_id,
            storefront_url="http://bob-storefront:8001/",
            listing_resource=OFFER_RESOURCE,
            accepted_escrows=ACCEPTED_ESCROWS,
            max_duration_seconds=DURATION_HOURS * 3600,
        )
        result = registry_seller_client.validate_publish_listing(req)
        assert result.valid, (
            f"Registry validate-publish returned valid=False for listing "
            f"{deal_state.seller_listing_id}.\n"
            f"Errors: {result.errors}\n"
            f"accepted_escrows_count={result.accepted_escrows_count}"
        )
        deal_state._registry_validate_passed = True
        log.info("[03a] Registry validate-publish: valid=%s escrows=%d",
                 result.valid, result.accepted_escrows_count)


class TestStage03b_ResumePublishesToRegistry:
    def test_03b_resume_listing_publishes_and_registry_confirms(
        self, storefront_admin_client, registry_client, deal_state: DealState
    ):
        """Resume listing → registry_status=published; registry confirms immediately.

        Combined advance + confirm: resume_listing awaits publish_order_to_registry
        synchronously, so when registry_status=published is in the response the
        registry row already exists — no polling required.
        """
        require_state(deal_state, "seller_listing_id", "_registry_validate_passed")

        result = storefront_admin_client.resume_listing(deal_state.seller_listing_id)
        assert result.paused is False, (
            f"Expected paused=False after resume, got: {result}"
        )
        assert result.registry_status == "published", (
            f"Registry publish failed during resume. registry_status={result.registry_status!r}.\n"
            f"Check that registry.url in config.toml is reachable from the storefront container.\n"
            f"Run GET /api/v1/system/status and inspect checks.registry for diagnosis.\n"
            f"Current response: {result}"
        )

        # Confirm local paused flag cleared
        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.paused is False, (
            f"Local listing still shows paused=True after resume: {listing}"
        )

        # Confirm registry now contains the listing (synchronous — publish already committed)
        reg_result = registry_client.list_listings(status="open", limit=200)
        ids = {o.id for o in reg_result.listings}
        assert deal_state.seller_listing_id in ids, (
            f"Listing {deal_state.seller_listing_id} absent from registry immediately after "
            f"resume.\nregistry_status was 'published' but listing not found — "
            f"possible registry indexing inconsistency.\n"
            f"Registry returned {len(ids)} open listings."
        )

        deal_state.listing_published = True
        log.info("[03b] Listing %s resumed; registry_status=%s, registry confirmed",
                 deal_state.seller_listing_id, result.registry_status)


# ===========================================================================
# Phases 4 to 9 — publication seen, negotiation, settlement, delivery
# ===========================================================================

class TestStage04a_PrimaryRegistryPublish(Stage04a_PrimaryRegistryPublish):
    pass


class TestStage05a_EvaluateNegotiate(Stage05a_EvaluateNegotiate):
    pass


class TestStage05b_NegotiationStartsAndVisible(Stage05b_NegotiationStartsAndVisible):
    pass


class TestStage06b_ForceAcceptAndTerminal(Stage06b_ForceAcceptAndTerminal):
    pass


class TestStage07_OnChainEscrowAndProvGate(Stage07_OnChainEscrowAndProvGate):
    pass


class TestStage07b_VerifyEscrow(Stage07b_VerifyEscrow):
    pass


class TestStage08a_EvaluateSettle(Stage08a_EvaluateSettle):
    pass


class TestStage08c_EvaluateProvisioningJob(Stage08c_EvaluateProvisioningJob):
    pass


class TestStage08b_SettlementSubmittedAndJobQueued(Stage08b_SettlementSubmittedAndJobQueued):
    pass


class TestStage09a_ProvisioningCompletes(Stage09a_ProvisioningCompletes):
    pass


class TestStage09a2_CapacityEventCycle:
    def test_09a2_capacity_events_dry_run_then_advance(
        self, storefront_admin_client, deal_state: DealState
    ):
        """Step the capacity-event loop before asserting its effect.

        VM's listing-reconciliation stage. The deal holds this scenario's
        sellable unit, so its listing is no longer satisfiable. The settle path reserves capacity and leaves the
        derived-listing reconciliation to the capacity-delta subscriber, which
        this scenario holds paused -- so 09b's `status=closed` is only true
        once a cycle has run, and this stage is where it is asked for.

        Dry run first, while the listing is still open: that is the cause,
        named, and separable from the effect 09b asserts.
        """
        require_state(deal_state, "seller_listing_id", "provisioning_result_injected")

        preview = dry_run_storefront(storefront_admin_client, "capacity-events")
        pending = one_site(preview)
        assert pending["error"] is None, (
            f"capacity-event dry run failed for site {pending['site']!r}: "
            f"{pending['error']}"
        )
        assert not pending["would_position"], (
            "the dry run would position at the feed head rather than apply "
            "this deal's events, so the poller's cursor was lost"
        )
        assert pending["pending_count"] >= 1, (
            "the deal reserved capacity, so its authority has events waiting; "
            f"the feed reports none (cursor={pending['cursor']!r} "
            f"head={pending['feed_head']!r})"
        )

        # Projections before deltas. With `use_site_projection_for_listings`
        # on (the shipped default) the close path decides from the
        # storefront's own projection cache, and only the site-projections
        # loop refills it -- held here like every other loop. Applying the
        # deltas against a pre-deal projection closes nothing however many of
        # them there are, which is exactly what the previous run showed: four
        # events applied, listing still open.
        projections = advance_storefront(storefront_admin_client, "site-projections")
        assert projections.get("sites"), (
            "the site-projections advance reported no site state, so the "
            "projection the close path reads was not refreshed and the "
            "capacity cycle below would decide from stale availability"
        )

        applied_total = 0
        for step in range(5):
            cycle = one_site(
                advance_storefront(storefront_admin_client, "capacity-events")
            )
            assert cycle["error"] is None, (
                f"capacity-event cycle {step} failed for site "
                f"{cycle['site']!r}: {cycle['error']}"
            )
            applied_total += int(cycle["applied_count"])
            if not cycle["truncated"]:
                break
        else:
            raise AssertionError(
                "capacity-event feed still reports a truncated page after "
                f"five cycles (applied {applied_total} events)"
            )
        assert applied_total >= pending["pending_count"], (
            f"the advance applied {applied_total} event(s) where the dry run "
            f"named {pending['pending_count']} pending"
        )
        deal_state._listing_reconciled = True
        log.info(
            "[09a2] Capacity events stepped: %s pending, %s applied",
            pending["pending_count"], applied_total,
        )


class TestStage09b_SettlementReadyAndCredentials(Stage09b_SettlementReadyAndCredentials):
    pass


class TestStage09bb_ClaimSubmittedForTheFulfilledEscrow(Stage09bb_ClaimSubmittedForTheFulfilledEscrow):
    pass


class TestStage09c_LeaseRecorded(Stage09c_LeaseRecorded):
    pass


# ===========================================================================
# Phases 10 and 11 — lease expiry, teardown, and release
# ===========================================================================

class TestStage10a_LeaseExpirySetup(Stage10a_LeaseExpirySetup):
    pass


class TestStage10b_LeaseCycleBeginsTeardown(Stage10b_LeaseCycleBeginsTeardown):
    pass


class TestStage11a_TeardownDispatch(Stage11a_TeardownDispatch):
    pass


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass
