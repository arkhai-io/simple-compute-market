"""Bare-metal publication and evidence stages shared by mock and real execution."""
from __future__ import annotations

import logging
from arkhai_bare_metal.evidence_routes import SyncBareMetalEvidenceClient
from tests.e2e.roles.helpers.compute_deal import advance_storefront, dry_run_storefront
from tests.e2e.roles.helpers.compute_deal_stages import ComputeDealState
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.escrow import read_string_obligation

log = logging.getLogger(__name__)
PUBLICATION = "publication"
SITE_PROJECTIONS = "site-projections"


def _with_listing(report: dict, listing_id: str) -> list[dict]:
    return [item for item in report.get("actions") or [] if item.get("listing_id") == listing_id]


class BareMetalPublicationClosesListing:
    def test_09a2_publication_closes_the_held_machines_listing(
        self, storefront_admin_client, registry_client, deal_state: ComputeDealState
    ):
        """The machine is held by the deal, so a pass closes its listing.

        Dry run first, while the listing is still open: that is the cause,
        named, and separable from the effect 09b asserts.
        """
        require_state(deal_state, "seller_listing_id", "provisioning_result_injected")
        listing_id = deal_state.seller_listing_id
        # The deal's lease took the machine at the site; the held poller sees
        # it only when stepped.
        advance_storefront(storefront_admin_client, SITE_PROJECTIONS)
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


class BareMetalEvidencePublished:
    def test_09bb_servicing_publishes_the_lease_ready_evidence(
        self, storefront_client, storefront_admin_client, buyer_fulfillment,
        buyer_config, deal_state: ComputeDealState,
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
