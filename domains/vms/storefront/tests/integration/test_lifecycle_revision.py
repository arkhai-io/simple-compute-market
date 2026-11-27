"""A changed delivery-end claim reaches the dispute authority as a case of its own.

The buyer ended delivery and filed its ``delivery_end(cause=payer)`` case; the
site's signed report then proves the seller failed earlier. Application
integration: the storefront's composed lifecycle over the mediation contract's
in-process peer, its outcome read through the seller's typed client. All
principals are public deterministic development fixtures; never use them on a
public network.
"""

from datetime import datetime, timezone

import injected_time
import pytest
from compute_provisioning_contracts import LeaseEndedEvent, sign_lease_end
from core_storefront.service_peers import ServicePeerTrust
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import INTERFACE
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.adapters import DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, submit_dispute
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_client import LifecycleClient, SellerLifecycleClient
from market_deal_lifecycle_contracts.models import LifecycleCommand
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json
from pydantic import SecretStr

from market_storefront import container
from tests.integration.test_lifecycle_cycle import ReleasingSite, _dispute_credential
from tests.integration.test_payment_settlement import BUYER, LISTING, NEGOTIATION, SELLER
from tests.integration.test_payment_settlement import make as make

SITE = Ed25519Signer(b"\x51" * 32)
SITE_ID = "site-test"
RESERVATION = "fixture-vm-reservation"


class Operations:
    """The buyer's own operation store."""

    def __init__(self):
        self.commands = {}

    async def check_and_record(self, negotiation_id, operation_key, digest):
        return self.commands.setdefault((negotiation_id, operation_key), digest) == digest


async def file_buyer_case(peer, agreement, commitment_ref, ended_at):
    """The buyer's ``delivery_end(cause=payer)`` filing, through its own adapter."""
    authority = DisputeAuthority.model_validate(peer.authority)
    binding = DisputeBinding(NEGOTIATION, commitment_ref, authority)
    async with MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payer")),
        transport=peer.transport(),
    ) as client:
        adapter = MediationAdapter(binding, agreement, client, clock=injected_time.now)
        return await submit_dispute(LifecycleCommand(
            negotiation_id=NEGOTIATION, kind="delivery_end", operation_key="buyer-surrender",
            payload=DeliveryEndIntent(ended_at=ended_at, delivered=True, cause="payer").model_dump(mode="json"),
        ), binding, DisputeAdapterTable([(INTERFACE, lambda _: adapter)]), Operations())


@pytest.mark.asyncio
async def test_a_payee_revision_after_the_buyer_s_case_is_filed_and_its_ruling_recorded(injected_source, make):
    """The storefront files the payee's earlier end as a second case, lists the
    deal with that case open and never repair required, and records the
    delivery end the case's programmed ruling applies, classified as a ruling,
    sending no stop or reverse of its own."""
    peer = MediationContractFake()
    # The Agreement starts at the storefront's injected instant, two minutes
    # behind the wall clock the buyer signs on.
    h = await make(
        physical=lambda *_: ReleasingSite(), disputes=_dispute_credential(peer),
        mediation_transport=peer.transport(),
        start=datetime.fromtimestamp(injected_source.now(), timezone.utc),
    )
    h.serve()
    await h.settle()
    await h.delivered()
    # The harness's delivery stands in for the delivery path, so the
    # availability that path records for a delivered VM is recorded here.
    delivered_at = injected_source.now()
    with transaction(h.lifecycle.path) as conn:
        end = EndSession(conn)
        end.available(
            NEGOTIATION, at=delivered_at, expected_revision=end.read(NEGOTIATION).revision, now=delivered_at,
        )
    await h.db.save_capacity_hold(
        negotiation_id=NEGOTIATION, listing_id=LISTING, capacity_reservation_id=RESERVATION,
    )
    await h.db.update_vm_delivery(negotiation_id=NEGOTIATION, capacity_reservation_id=RESERVATION)
    trust = ServicePeerTrust(h.db.db_path, {
        "fixture-site": ("service", SITE_ID, TrustedIdentitySet(identities=(SITE.identity,))),
    })
    trust.seed()
    container.resolved_service_peer_trust = trust
    try:
        # The buyer ends delivery and files its case.
        injected_source.set(delivered_at + 60)
        async with LifecycleClient("http://test", BUYER, TrustedIdentitySet(identities=(SELLER.identity,)),
                                   transport=h.transport) as buyer:
            ack = await buyer.end_delivery(NEGOTIATION, operation_key="end")
        agreement, _ = h.lifecycle.accepted(NEGOTIATION)
        with transaction(h.lifecycle.path) as conn:
            commitment_ref = EndSession(conn).read(NEGOTIATION).commitment_ref
        surrender = await file_buyer_case(peer, agreement, commitment_ref, ack.receipt_at)
        assert surrender.status == "accepted"

        # The site's report then proves the seller failed before the buyer ended.
        failed_at = delivered_at + 30
        h.lifecycle.ingress.site_report(NEGOTIATION, body=canonical_json(sign_lease_end(LeaseEndedEvent(
            event_id="host-failure", capacity_reservation_id=RESERVATION, site_id=SITE_ID,
            effective_at=failed_at, cause="force_release", source_state="leased",
            caller=SITE.identity, reason="host failed",
        ), SITE)), headers={})
        injected_source.set(delivered_at + 90)
        payment_writes = [name for name, _ in h.payments.calls if name in {"submit", "submit_event", "reverse"}]
        # One cycle files the revision; the next reads the authority's record.
        await h.lifecycle.cycle()
        await h.lifecycle.cycle()

        seller = SellerLifecycleClient(h.administrator)
        [summary] = (await seller.list()).deals
        filed = [record["entry"] for record in peer.entries if record["entry"]["kind"] == "filed"]
        assert [(entry["filing"]["request"]["cause"], entry["filing"]["request"]["ended_at"]) for entry in filed] == [
            ("payer", ack.receipt_at), ("payee", failed_at),
        ]
        revision = filed[1]["case_ref"]
        assert summary.state == "ending" and "case_open" in summary.ending
        assert revision in summary.open_cases
        assert [filing.outcome.status for filing in summary.filings] == ["accepted"]

        # The authority rules the revision; the storefront records its end.
        peer.decide(revision, [{
            "id": "revision-end", "state": "applied", "effect": {"kind": "end_delivery", "at": failed_at},
        }])
        injected_source.set(delivered_at + 120)
        await h.lifecycle.cycle()
        read = await seller.read(NEGOTIATION)
        assert read.authority.outcome.status == "accepted"
        assert next(case for case in read.authority.cases if case.case_ref == revision).state == "closed"
        with transaction(h.lifecycle.path) as conn:
            end = EndSession(conn)
            [ruled] = [request for request in end.requests(NEGOTIATION) if request.cause == "ruling"]
            classification = end.classification(NEGOTIATION, ruled.source_ref)
        assert (ruled.ended_at, classification.kind) == (failed_at, "ruling")
        # The storefront computed and sent no remedy of its own.
        assert [name for name, _ in h.payments.calls if name in {"submit", "submit_event", "reverse"}] == payment_writes
    finally:
        container.resolved_service_peer_trust = None
