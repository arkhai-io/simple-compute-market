"""A mock-provisioned whole-host deal, on the bare-metal lane.

Bare metal's run of the compute family's canonical deal, stage for stage with
VM's typed-client deal. The stages bare metal shares with VM are defined once in
``helpers/compute_deal_stages.py`` and declared here, in order, by subclassing;
``BareMetalComputeDealDriver`` supplies bare metal's part of them. Bare metal's
own stages are inserted in place:

  03a  Publication preview:  the dry run would publish the deal's machine
  03b  Publication step:     one pass publishes it
  09a2 Publication closes:   the dry run then the step close the held machine's
                             listing as unavailable
  09bb Evidence published:   one servicing step publishes the lease-ready
                             evidence's digest; the buyer resolves the evidence
  12a  Publication reopens:  after the release, a pass reopens the listing
  12b  Second deal accepted: a second negotiation on the freed machine
  12c  Second deal active:   escrowed, settled, and converged with no gate held
  12d  Teardown sent twice:  the buyer's repeated teardown is the same operation
  12e  Released once:        the site releases the machine once, and the
                             storefront records one release

Every transition is previewed where a preview exists, then advanced explicitly:
the storefront's loops are held from stage 00, fulfillment convergence for the
whole module, and the lease watchdog while a stage drives it.
"""

from __future__ import annotations

import logging
import time

import pytest
from arkhai_bare_metal.evidence_routes import SyncBareMetalEvidenceClient

from tests.e2e.roles.helpers.compute_deal import (
    advance_fulfillment_to,
    advance_storefront,
    dry_run_storefront,
    wait_for_stage_event,
)
from tests.e2e.roles.helpers.compute_deal_stages import (
    BUYER_INITIAL_PRICE,
    BUYER_MAX_PRICE,
    DEAL_TOKEN,
    DURATION_HOURS,
    ESCROW_TTL_SECONDS,
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
    Stage09c_LeaseRecorded,
    Stage10a_LeaseExpirySetup,
    Stage10b_LeaseCycleBeginsTeardown,
    Stage11a_TeardownDispatch,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.escrow import create_buyer_escrow, read_string_obligation
from tests.e2e.roles.scenarios.bare_metal.conftest import BareMetalDealState

log = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.e2e_bare_metal_mock_deal,
    # This module advances fulfillment convergence itself, so its timer is
    # stopped for the module's duration.
    pytest.mark.usefixtures("convergence_advanced_explicitly"),
]

PUBLICATION = "publication"


def _actions(report: dict, action: str) -> list[dict]:
    return [item for item in report.get("actions") or [] if item.get("action") == action]


def _ours(items: list[dict], resource_id: str) -> list[dict]:
    return [
        item for item in items
        if (item.get("source") or {}).get("physical_resource_id") == resource_id
    ]


def _with_listing(report: dict, listing_id: str) -> list[dict]:
    return [
        item for item in report.get("actions") or [] if item.get("listing_id") == listing_id
    ]


# ===========================================================================
# Phase 0 — readiness
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


class TestStage00f1_ExecutorHostRegistry(Stage00f1_ExecutorHostRegistry):
    pass


class TestStage00g_AlkahestConfigured(Stage00g_AlkahestConfigured):
    pass


class TestStage00h_ProvisioningStorefrontLink(Stage00h_ProvisioningStorefrontLink):
    pass


# ===========================================================================
# Phase 3 — publication (bare metal's own)
# ===========================================================================

class TestStage03a_PublicationDryRun:
    def test_03a_the_preview_would_publish_the_deals_machine(
        self, storefront_admin_client, deal_driver, deal_state: BareMetalDealState
    ):
        """The publication dry run reports the deal's machine as a publish.

        Bare metal's publication has no timer: each pass is one an operator, or
        this scenario, asks for. The preview names the cause the step will act
        on, before anything reaches the registry.
        """
        require_state(
            deal_state, "_lifecycle_paused", "_supply_seeded", "_registry_reachable"
        )
        preview = dry_run_storefront(storefront_admin_client, PUBLICATION)
        assert preview.get("dry_run") is True, preview
        ours = _ours(_actions(preview, "publish"), deal_driver.reserved_resource_id)
        assert len(ours) == 1, preview
        assert ours[0]["source"]["pool_id"] == deal_driver.pool_id, ours
        deal_state._publication_previewed = True


class TestStage03b_PublicationStepPublishes:
    def test_03b_one_step_publishes_the_deals_listing(
        self, storefront_admin_client, deal_driver, deal_state: BareMetalDealState
    ):
        require_state(deal_state, "_publication_previewed")
        report = advance_storefront(storefront_admin_client, PUBLICATION)
        (ours,) = _ours(_actions(report, "publish"), deal_driver.reserved_resource_id)
        assert ours["status"] == "published", ours
        listing_id = str(ours["listing_id"])
        assert not [
            item for item in _with_listing(report, listing_id) if item["action"] == "fail"
        ], report

        listing = storefront_admin_client.get_listing(listing_id)
        assert listing.status == "open", listing
        deal_state.seller_listing_id = listing_id
        deal_state.listing_published = True
        log.info("[03b] Listing %s published for %s", listing_id, deal_driver.reserved_resource_id)


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


class TestStage09a2_PublicationClosesTheListing:
    def test_09a2_publication_closes_the_held_machines_listing(
        self, storefront_admin_client, registry_client, deal_state: BareMetalDealState
    ):
        """The machine is held by the deal, so a pass closes its listing.

        Dry run first, while the listing is still open: that is the cause,
        named, and separable from the effect 09b asserts.
        """
        require_state(deal_state, "seller_listing_id", "provisioning_result_injected")
        listing_id = deal_state.seller_listing_id
        preview = dry_run_storefront(storefront_admin_client, PUBLICATION)
        assert _with_listing(preview, listing_id) == [
            {"action": "close", "listing_id": listing_id, "reason": "unavailable"}
        ], preview
        assert storefront_admin_client.get_listing(listing_id).status == "open"

        report = advance_storefront(storefront_admin_client, PUBLICATION)
        assert _with_listing(report, listing_id) == [
            {"action": "close", "listing_id": listing_id, "reason": "unavailable"}
        ], report
        assert registry_client.get_listing(listing_id).status == "closed"
        deal_state._listing_reconciled = True


class TestStage09b_SettlementReadyAndCredentials(Stage09b_SettlementReadyAndCredentials):
    pass


class TestStage09bb_EvidencePublishedForTheFulfilledEscrow:
    def test_09bb_servicing_publishes_the_lease_ready_evidence(
        self, storefront_client, storefront_admin_client, buyer_fulfillment,
        buyer_config, deal_state: BareMetalDealState,
    ):
        """One servicing step publishes the deal's evidence on chain.

        Bare metal's own stage: its servicing pass after the lease is active is
        what stores the lease-ready evidence and publishes its digest on chain
        as the escrow's fulfillment, where VM records a seller claim. A stored
        digest is not publication, since a rejected submission leaves one
        behind to retry, so publication is read from the chain: the attestation
        settlement recorded holds the digest and references the escrow.
        Asserts publication, not collection: collection waits on a chain
        condition this scenario does not control.
        """
        require_state(deal_state, "real_escrow_uid", "settlement_status", "negotiation_id")
        result = advance_storefront(storefront_admin_client, "settlement-servicing")
        assert result.get("loop") == "settlement_servicing", result

        status = buyer_fulfillment.status(deal_state.negotiation_id)
        digest = status.get("evidence_digest")
        assert digest, f"no lease-ready evidence was stored: {status}"
        attestation_uid = status.get("evidence_attestation_uid")
        assert attestation_uid, (
            f"settlement recorded no published attestation for the evidence: {status}"
        )
        published = read_string_obligation(
            attestation_uid,
            private_key=buyer_config["private_key"],
            rpc_url=buyer_config["rpc_url"],
        )
        assert published["uid"].lower() == attestation_uid.lower(), published
        assert published["ref_uid"].lower() == deal_state.real_escrow_uid.lower(), published
        assert published["item"] == digest, published
        assert not published["revoked"], published

        signed = SyncBareMetalEvidenceClient(
            storefront_client, role="buyer"
        ).lease_ready_evidence(digest)
        evidence = signed.evidence
        assert evidence.evidence_digest == digest
        assert evidence.agreement_ref == deal_state.negotiation_id
        assert evidence.condition_anchor == deal_state.real_escrow_uid

        system = storefront_admin_client.get_system_status()
        assert system.settlement_manual_required == 0, system
        log.info(
            "[09bb] Evidence %s published as %s for %s",
            digest, attestation_uid, deal_state.real_escrow_uid,
        )


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


# ===========================================================================
# Phase 12 — a second deal on the freed machine (bare metal's own)
# ===========================================================================

class TestStage12a_PublicationReopensTheListing:
    def test_12a_a_pass_reopens_the_released_machines_listing(
        self, storefront_admin_client, registry_client, deal_state: BareMetalDealState
    ):
        require_state(deal_state, "seller_listing_id", "teardown_fulfillment_id", "deal_lease")
        lease = deal_state.deal_lease.refresh()
        assert lease.get("status") == "released", (
            f"the first deal's lease is not released, so its machine is not free: {lease}"
        )
        listing_id = deal_state.seller_listing_id
        preview = dry_run_storefront(storefront_admin_client, PUBLICATION)
        assert [item["action"] for item in _with_listing(preview, listing_id)] == [
            "reopen"
        ], preview

        report = advance_storefront(storefront_admin_client, PUBLICATION)
        assert [item["action"] for item in _with_listing(report, listing_id)] == [
            "reopen"
        ], report
        assert registry_client.get_listing(listing_id).status == "open"
        assert storefront_admin_client.get_listing(listing_id).status == "open"
        deal_state._listing_reopened = True


class TestStage12b_SecondDealAccepted:
    def test_12b_a_second_negotiation_is_accepted(
        self, storefront_client, storefront_admin_client, deal_driver,
        deal_state: BareMetalDealState,
    ):
        require_state(deal_state, "_listing_reopened")
        # The second deal's jobs run as a buyer's would, with no gate held.
        deal_driver.disarm_gates()
        deal_state._second_escrow_expiration_unix = int(time.time()) + ESCROW_TTL_SECONDS
        opened = storefront_client.negotiate_new(
            listing_id=deal_state.seller_listing_id,
            initial_amount=BUYER_INITIAL_PRICE,
            escrow_expiration_unix=deal_state._second_escrow_expiration_unix,
            provision_terms=deal_driver.provision_terms(),
            token=DEAL_TOKEN["contract_address"],
        )
        negotiation_id = opened.get("negotiation_id") if isinstance(opened, dict) else None
        assert negotiation_id, opened
        agreed = (BUYER_INITIAL_PRICE + BUYER_MAX_PRICE) // 2
        accepted = storefront_admin_client.force_accept_negotiation(
            deal_state.seller_listing_id, negotiation_id, amount=agreed
        )
        assert accepted.action == "accept", accepted
        detail = storefront_admin_client.get_negotiation(
            deal_state.seller_listing_id, negotiation_id
        )
        assert detail.terminal_state == "success", detail
        deal_state.second_negotiation_id = negotiation_id


class TestStage12c_SecondDealActive:
    def test_12c_the_second_deal_settles_and_its_lease_becomes_active(
        self, storefront_client, provisioning_client, provisioning_test_client,
        buyer_config, seller_wallet, buyer_fulfillment, deal_state: BareMetalDealState,
    ):
        require_state(deal_state, "second_negotiation_id", "_second_escrow_expiration_unix")
        escrow_uid = create_buyer_escrow(
            buyer_private_key=buyer_config["private_key"],
            seller_wallet_address=seller_wallet,
            agreed_amount=(BUYER_INITIAL_PRICE + BUYER_MAX_PRICE) // 2,
            duration_seconds=DURATION_HOURS * 3600,
            token_contract_address=DEAL_TOKEN["contract_address"],
            rpc_url=buyer_config["rpc_url"],
            expiration_unix=deal_state._second_escrow_expiration_unix,
        )
        settled = storefront_client.settle_evm(
            escrow_uid,
            negotiation_id=deal_state.second_negotiation_id,
            buyer_evm_address=buyer_config["wallet_address"],
        )
        assert settled.status == "settlement_verified", settled
        fulfillment_id = buyer_fulfillment.status(deal_state.second_negotiation_id).get(
            "fulfillment_id"
        )
        assert fulfillment_id, "the second settlement began no fulfillment"

        provisioning_test_client.drain(timeout=30)
        advance_fulfillment_to(provisioning_client, str(fulfillment_id), "active")
        status = buyer_fulfillment.status(deal_state.second_negotiation_id)
        assert status.get("state") == "active", status
        deal_state.second_fulfillment_id = str(fulfillment_id)
        deal_state._second_deal_active = True


class TestStage12d_BuyerTeardownSentTwice:
    def test_12d_a_repeated_teardown_is_the_same_operation(
        self, provisioning_client, buyer_fulfillment, deal_state: BareMetalDealState
    ):
        """The buyer's teardown, sent again, returns the operation it began.

        The lease watchdog is held from here until 12e has released the
        machine, so the release is the step 12e asks for, not a timer's.
        """
        require_state(deal_state, "_second_deal_active")
        assert provisioning_client.pause_lease_watchdog().get("paused") is True
        first = buyer_fulfillment.teardown(deal_state.second_negotiation_id)
        again = buyer_fulfillment.teardown(deal_state.second_negotiation_id)
        assert first.get("state") == "terminating", first
        # Termination can already have dispatched teardown when the retry
        # observes it; its durable identities establish the same operation.
        assert again.get("state") in {"terminating", "teardown_dispatch_pending"}, again
        for name in ("negotiation_id", "capacity_reservation_id", "fulfillment_id"):
            assert again.get(name) == first.get(name), (name, first, again)
        deal_state.second_teardown = first


class TestStage12e_CapacityReleasedOnce:
    def test_12e_the_site_releases_the_machine_once(
        self, provisioning_client, storefront_admin_client, buyer_fulfillment,
        deal_state: BareMetalDealState,
    ):
        require_state(deal_state, "second_teardown", "second_fulfillment_id")
        negotiation_id = deal_state.second_negotiation_id
        try:
            advance_fulfillment_to(
                provisioning_client, deal_state.second_fulfillment_id, "torn_down"
            )
            provisioning_client.check_leases()
            wait_for_stage_event(
                storefront_admin_client, "fulfillment", "capacity_released",
                negotiation_id=negotiation_id, timeout=10.0,
            )
        finally:
            provisioning_client.resume_lease_watchdog()

        events = storefront_admin_client.get_events(
            stage="fulfillment", negotiation_id=negotiation_id
        )
        released = [event for event in events.events if event.event == "capacity_released"]
        assert len(released) == 1, events.events
        assert (
            released[0].data.get("capacity_reservation_id")
            == deal_state.second_teardown.get("capacity_reservation_id")
        ), released
        assert buyer_fulfillment.status(negotiation_id).get("state") == "released"
