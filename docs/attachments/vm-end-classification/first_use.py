"""Drive VM failure correction and delayed lawful report correlation.

All identities are public deterministic development fixtures, never suitable for
a public network. Each encounter owns temporary SQLite and in-process HTTP.
"""

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import tests.conftest  # noqa: F401 - explicit storefront domain selection
from compute_provisioning_contracts import LeaseEndedEvent, sign_lease_end
from core_storefront.service_peers import ServicePeerTrust
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import Classification, FinalRequest, stable_ref
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json
from market_storefront import container
from market_storefront.delivery_lifecycle import VmPhysicalEnd
from market_storefront.end_classification import classification_for, resolve_site_corrections
from market_storefront.failure_actions import FulfillmentFailureContext, apply_fulfillment_failure_policy
from tests._settings_overrides import settings_overrides
from tests.integration.test_payment_settlement import _harness, NEGOTIATION, LISTING, SELLER

SITE = Ed25519Signer(b"\x51" * 32)
SITE_ID = "site-test"
RESERVATION = "fixture-vm-reservation"


async def encounter(root, *, failure, site_first=True):
    h = await _harness(root)
    try:
        await h.db.update_listing(listing_id=LISTING, listing_resource={
            "gpu_model": "H200", "gpu_count": 1, "offering_mode": "vm",
            "pool_id": "pool-test", "resource_id": "resource-test",
            "sla": 99.0, "region": "development",
        })
        h.serve()
        await h.settle()
        await h.delivered()
        await h.db.save_capacity_hold(
            negotiation_id=NEGOTIATION, listing_id=LISTING, capacity_reservation_id=RESERVATION,
        )
        await h.db.update_vm_delivery(negotiation_id=NEGOTIATION, capacity_reservation_id=RESERVATION)
        trust = ServicePeerTrust(h.db.db_path, {
            "fixture-site": ("service", SITE_ID, TrustedIdentitySet(identities=(SITE.identity,))),
        })
        trust.seed()
        container.resolved_service_peer_trust = trust
        site = SimpleNamespace(list_reservations=AsyncMock(return_value=[{
            "capacity_reservation_id": RESERVATION,
            "deal_ref": {"negotiation_id": NEGOTIATION}, "state": "leased",
        }]))
        capacity = SimpleNamespace(
            client=lambda: SimpleNamespace(_sites={SITE_ID: site}),
            release=AsyncMock(side_effect=AssertionError("delivered capacity must await its callback")),
        )
        fulfillment = SimpleNamespace(terminate_lease=AsyncMock())
        h.lifecycle.end.physical = VmPhysicalEnd(h.db, capacity=capacity, fulfillment=fulfillment)
        now = h.lifecycle.clock()
        ref = "site-event:fixture-end"
        event = LeaseEndedEvent(
            event_id="fixture-end", capacity_reservation_id=RESERVATION, site_id=SITE_ID,
            effective_at=now, cause="force_release" if failure else "release",
            source_state="leased", caller=SITE.identity if failure else SELLER.identity,
            reason="development failure" if failure else stable_ref(NEGOTIATION, "terminate", "terminate"),
        )
        body = canonical_json(sign_lease_end(event, SITE))
        if site_first:
            h.lifecycle.ingress.site_report(NEGOTIATION, body=body, headers={})
        with transaction(h.db.db_path) as conn:
            end = EndSession(conn)
            classification = classification_for(end, NEGOTIATION, ref)
            if failure and site_first:
                assert classification.kind == "unentitled_withdrawal"
                assert len([intent for intent in end.intents(NEGOTIATION) if intent.kind == "filing"]) == 1
            elif not failure:
                assert classification is None
                request = FinalRequest(
                    negotiation_id=NEGOTIATION, source_ref="fixture-surrender", ended_at=now,
                    observed_at=now, actor=SELLER.identity, cause="buyer_surrender",
                    source="end_delivery", evidence_refs=["fixture-receipt"],
                )
                end.record_end(request, now=now, classification=Classification(
                    kind="buyer_surrender", evidence_refs=request.evidence_refs,
                ))
                resolve_site_corrections(end, NEGOTIATION, now=now)
                assert classification_for(end, NEGOTIATION, ref).kind == "buyer_surrender"
                assert not [intent for intent in end.intents(NEGOTIATION) if intent.kind == "filing"]
        # Recovery of the original report must not rewrite its initially absent
        # controlling-source field after later evidence resolves classification.
        if site_first:
            h.lifecycle.ingress.site_report(NEGOTIATION, body=body, headers={})
        await h.lifecycle.end.drive_physical(NEGOTIATION)
        with settings_overrides(**{"fulfillment.failure_policy.actions": ["release_capacity"]}):
            result = await apply_fulfillment_failure_policy(h.db, FulfillmentFailureContext(
                negotiation_id=NEGOTIATION, listing_id=LISTING,
                capacity_reservation_id=RESERVATION, reason="provisioning_failed",
                source="settlement_provisioning",
            ))
            assert result.state == "tearing_down"
        capacity.release.assert_not_awaited()
        assert fulfillment.terminate_lease.await_args.kwargs["reason"] == stable_ref(
            NEGOTIATION, "terminate", "terminate",
        )
        with transaction(h.db.db_path) as conn:
            end = EndSession(conn)
            assert len([intent for intent in end.intents(NEGOTIATION) if intent.kind == "terminate"]) == 1
            assert end.view(NEGOTIATION).progress == "tearing_down"
            correction = classification_for(end, NEGOTIATION, "fulfillment-failure:" + RESERVATION)
            assert correction.kind == ("provisioning_failure" if failure else "buyer_surrender")
            if not site_first:
                assert len([intent for intent in end.intents(NEGOTIATION) if intent.kind == "filing"]) == 1
                assert end.view(NEGOTIATION).recorded_end.source == "fulfillment_failure"
        h.lifecycle.capacity_released(RESERVATION, SITE_ID)
        with transaction(h.db.db_path) as conn:
            assert EndSession(conn).view(NEGOTIATION).progress == "released"
        print("seller failure journals correction" if failure else "pending report resolves to later lawful evidence without a filing")
        print("direct failure policy drives the shared end service; callback alone proves capacity return")
    finally:
        await h.coordinator.stop()
        await h.lifecycle.close()
        await h.buyer.close()
        await h.seller.close()
        await h.administrator.close()
        container.resolved_service_peer_trust = None


async def main():
    for failure, site_first in ((False, True), (True, True), (True, False)):
        with tempfile.TemporaryDirectory() as directory:
            await encounter(Path(directory), failure=failure, site_first=site_first)


if __name__ == "__main__":
    asyncio.run(main())
