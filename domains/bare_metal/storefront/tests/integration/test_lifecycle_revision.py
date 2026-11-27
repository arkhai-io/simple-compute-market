"""A changed delivery-end claim reaches the dispute authority as a case of its own.

The buyer ended delivery and filed its ``delivery_end(cause=payer)`` case; the
site's signed report then proves the seller failed earlier. Application
integration: the bare-metal app over the mediation contract's in-process peer,
each cycle stepped and each outcome read through the typed clients. All
principals are public deterministic development fixtures; never use them on a
public network.
"""

import json

import httpx
import injected_time
import pytest
from compute_provisioning_contracts.lease_ends import LEASE_ENDED_CALLBACK, LeaseEndedEvent, sign_lease_end
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import INTERFACE
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.adapters import DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, submit_dispute
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_client import SellerLifecycleClient
from market_deal_lifecycle_contracts.models import LifecycleCommand
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_identity import Ed25519Signer, TrustedIdentitySet
from pydantic import SecretStr
from site_trust import seeded_sites
from storefront_client import StorefrontClient

from integration.test_lifecycle_dispatch import UnreachableSite, _mediation, peer, step
from integration.test_payment_settlement_client import ADMIN, SELLER
from integration.test_payment_settlement_client import enabled as enabled
from integration.test_payment_settlement_client import harness as harness

SITE = Ed25519Signer(bytes.fromhex("44" * 32))


class Operations:
    """The buyer's own operation store."""

    def __init__(self):
        self.commands = {}

    async def check_and_record(self, negotiation_id, operation_key, digest):
        return self.commands.setdefault((negotiation_id, operation_key), digest) == digest


async def file_buyer_case(mediation, h, commitment_ref, ended_at):
    """The buyer's ``delivery_end(cause=payer)`` filing, through its own adapter."""
    authority = DisputeAuthority.model_validate(mediation.authority)
    binding = DisputeBinding(h.negotiation_id, commitment_ref, authority)
    agreement = json.loads(h.runtime.lifecycle.agreement_bytes(h.negotiation_id))
    async with MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payer")),
        transport=mediation.transport(),
    ) as client:
        adapter = MediationAdapter(binding, agreement, client, clock=injected_time.now)
        return await submit_dispute(LifecycleCommand(
            negotiation_id=h.negotiation_id, kind="delivery_end", operation_key="buyer-surrender",
            payload=DeliveryEndIntent(ended_at=ended_at, delivered=True, cause="payer").model_dump(mode="json"),
        ), binding, DisputeAdapterTable([(INTERFACE, lambda _: adapter)]), Operations())


@pytest.mark.asyncio
async def test_a_payee_revision_after_the_buyer_s_case_is_filed_and_its_ruling_recorded(injected_source, harness):
    """The storefront files the payee's earlier end as a second case, lists the
    deal with that case open and never repair required, and records the
    delivery end the case's programmed ruling applies, classified as a ruling,
    sending no stop or reverse of its own."""
    h = harness
    h.serve()
    await h.settle()
    mediation = _mediation(h)
    h.runtime.lifecycle.end.physical = UnreachableSite(failures=0)
    bindings, peers = seeded_sites(h.runtime.db.db_path, {"site-a": SITE.identity})
    object.__setattr__(h.runtime, "site_bindings", bindings)
    object.__setattr__(h.runtime, "service_peer_trust", peers)
    # The harness's provisioning grants nothing, so the availability the
    # delivery path records for a delivered host is recorded here.
    started = injected_source.now()
    with transaction(h.runtime.db.db_path) as conn:
        end = EndSession(conn)
        record = end.read(h.negotiation_id)
        end.available(h.negotiation_id, at=started, expected_revision=record.revision, now=started)
    trust = TrustedIdentitySet(identities=(SELLER.identity,))
    transport = httpx.ASGITransport(app=h.app)

    # The buyer ends delivery and files its case.
    injected_source.set(started + 60)
    async with peer(h) as buyer:
        ack = await buyer.end_delivery(h.negotiation_id, operation_key="end")
    surrender = await file_buyer_case(mediation, h, record.commitment_ref, ack.receipt_at)
    assert surrender.status == "accepted"

    # The site's report then proves the seller failed before the buyer ended.
    failed_at = started + 30
    report = sign_lease_end(LeaseEndedEvent(
        event_id="host-failure", capacity_reservation_id="reservation-pay", site_id="site-a",
        effective_at=failed_at, cause="force_release", source_state="active",
        caller=SITE.identity, reason="host failed",
    ), SITE)
    async with StorefrontClient("http://test", signer=SITE, caller_role="service",
                                expected_publishers=trust, transport=transport) as site:
        await site.authenticated_request(
            "POST", LEASE_ENDED_CALLBACK["path"].format(capacity_reservation_id="reservation-pay"),
            role="service", operation="lease_ended", resource="reservation-pay",
            body=report.model_dump(mode="json"),
        )
    injected_source.set(started + 90)
    payment_writes = [name for name, _ in h.payments.calls if name in {"submit", "submit_event", "reverse"}]
    async with StorefrontClient("http://test", signer=ADMIN, caller_role="admin",
                                expected_publishers=trust, transport=transport) as admin:
        seller = SellerLifecycleClient(admin)
        # One cycle files the revision; the next reads the authority's record.
        await step(h, "deal-servicing")
        await step(h, "deal-servicing")
        [summary] = (await seller.list()).deals
        filed = [record["entry"] for record in mediation.entries if record["entry"]["kind"] == "filed"]
        assert [(entry["filing"]["request"]["cause"], entry["filing"]["request"]["ended_at"]) for entry in filed] == [
            ("payer", ack.receipt_at), ("payee", failed_at),
        ]
        revision = filed[1]["case_ref"]
        assert summary.state == "ending" and "case_open" in summary.ending
        assert revision in summary.open_cases
        assert [filing.outcome.status for filing in summary.filings] == ["accepted"]

        # The authority rules the revision; the storefront records its end.
        mediation.decide(revision, [{
            "id": "revision-end", "state": "applied", "effect": {"kind": "end_delivery", "at": failed_at},
        }])
        injected_source.set(started + 120)
        await step(h, "deal-servicing")
        read = await seller.read(h.negotiation_id)
    assert read.authority.outcome.status == "accepted"
    assert next(case for case in read.authority.cases if case.case_ref == revision).state == "closed"
    with transaction(h.runtime.db.db_path) as conn:
        end = EndSession(conn)
        [ruled] = [request for request in end.requests(h.negotiation_id) if request.cause == "ruling"]
        classification = end.classification(h.negotiation_id, ruled.source_ref)
    assert (ruled.ended_at, classification.kind) == (failed_at, "ruling")
    # The storefront computed and sent no remedy of its own.
    assert [name for name, _ in h.payments.calls if name in {"submit", "submit_event", "reverse"}] == payment_writes
