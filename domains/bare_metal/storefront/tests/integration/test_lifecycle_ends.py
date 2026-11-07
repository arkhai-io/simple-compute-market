"""Signed site reports and surrender through the composed bare-metal app."""

import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest
from compute_provisioning_contracts.lease_ends import LEASE_ENDED_CALLBACK, LeaseEndedEvent, sign_lease_end
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_contracts.models import CommitMessage
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import stable_ref
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json
from site_trust import seeded_sites
from storefront_client import StorefrontClient

from integration.test_payment_settlement_client import BUYER, SELLER, harness, enabled, _runtime

# Public deterministic development identity; never use on a public network.
SITE = Ed25519Signer(bytes.fromhex("44" * 32))


@pytest.mark.asyncio
async def test_surrender_before_dispatch_correlates_direct_release_push_and_pull(harness, tmp_path):
    h = harness
    loop_thread = threading.get_ident()
    verifier = h.runtime.lifecycle.ingress.verify_site
    verification_threads = []

    def verify(*args):
        verification_threads.append(threading.get_ident())
        return verifier(*args)

    h.runtime.lifecycle.ingress.verify_site = verify
    h.serve()
    started, release = asyncio.Event(), asyncio.Event()
    schedule = h.provisioning.schedule_resource
    releases = []

    async def paused(request):
        started.set()
        await release.wait()
        return await schedule(request)

    async def released(**request):
        releases.append(request)
        return {"capacity_reservation_id": request["capacity_reservation_id"], "site": request["site_id"]}

    h.provisioning.schedule_resource = paused
    h.runtime.capacity_client.release = released
    trust = TrustedIdentitySet(identities=(SELLER.identity,))
    transport = httpx.ASGITransport(app=h.app)
    bindings, peers = seeded_sites(h.runtime.db.db_path, {"site-a": SITE.identity})
    object.__setattr__(h.runtime, "site_bindings", bindings)
    object.__setattr__(h.runtime, "service_peer_trust", peers)
    async with LifecycleClient("http://test", BUYER, trust, transport=transport) as buyer:
        pending = asyncio.create_task(buyer.commit(CommitMessage(
            negotiation_id=h.negotiation_id, commitment_ref=h.data.transaction_id, operation_key="commit",
        )))
        try:
            await asyncio.wait_for(started.wait(), 5)
            ack = await buyer.end_delivery(h.negotiation_id, operation_key="end")
            assert ack.delivery.progress == "end_recorded"
        finally:
            release.set()
        assert (await pending).outcome.status == "rejected"
        assert h.provisioning.begin_calls == []
        command = stable_ref(h.negotiation_id, "terminate", "terminate")
        assert len(releases) == 1
        assert releases[0]["failure_reason"] == command
        restarted, provisioning = _runtime(tmp_path, h.payments)
        await restarted.settlement_service().reconcile_payments_once()
        assert provisioning.begin_calls == []
        await restarted.lifecycle.close()
        report = sign_lease_end(LeaseEndedEvent(
            event_id="direct-release", capacity_reservation_id="reservation-pay", site_id="site-a",
            effective_at=ack.receipt_at, cause="release", source_state="leased", reason=command,
        ), SITE)
        async with StorefrontClient("http://test", signer=SITE, caller_role="service",
                                    expected_publishers=trust, transport=transport) as site:
            for _ in range(2):
                await site.authenticated_request(
                    "POST", LEASE_ENDED_CALLBACK["path"].format(capacity_reservation_id="reservation-pay"),
                    role="service", operation="lease_ended", resource="reservation-pay",
                    body=report.model_dump(mode="json"),
                )
        async def lease(_):
            return SimpleNamespace(end_reports=[report], status="released")
        h.provisioning.get_lease = lease
        await h.runtime.lifecycle.recover_site(h.negotiation_id)
        assert verification_threads and all(value != loop_thread for value in verification_threads)
        read = await buyer.read(h.negotiation_id)
        assert read.delivery.progress == "released"
        assert len(read.delivery.site_reports) == 1
        assert read.delivery.site_reports[0].body == canonical_json(report)
        with transaction(h.runtime.db.db_path) as conn:
            end = EndSession(conn)
            source = "site-event:direct-release"
            assert h.runtime.lifecycle.classification_for(end, h.negotiation_id, source).kind == "buyer_surrender"
            assert next(request for request in end.requests(h.negotiation_id) if request.source_ref == source).controlling_source_ref == "buyer-surrender:end"
            assert not [intent for intent in end.intents(h.negotiation_id) if intent.kind == "filing"]


@pytest.mark.asyncio
async def test_ambiguous_release_waits_for_lawful_controlling_evidence(harness):
    h = harness
    h.serve()
    await h.settle()
    lifecycle = h.runtime.lifecycle
    bindings, peers = seeded_sites(h.runtime.db.db_path, {"site-a": SITE.identity})
    object.__setattr__(h.runtime, "site_bindings", bindings)
    object.__setattr__(h.runtime, "service_peer_trust", peers)
    now = lifecycle.clock()
    report = sign_lease_end(LeaseEndedEvent(
        event_id="early-report", capacity_reservation_id="reservation-pay", site_id="site-a",
        effective_at=now, cause="release", source_state="leased", caller=SELLER.identity,
        reason=stable_ref(h.negotiation_id, "terminate", "terminate"),
    ), SITE)
    body = canonical_json(report)
    lifecycle.ingress.site_report(h.negotiation_id, body=body, headers={})
    with transaction(lifecycle.path) as conn:
        end = EndSession(conn)
        assert lifecycle.classification_for(end, h.negotiation_id, "site-event:early-report") is None
        assert not [intent for intent in end.intents(h.negotiation_id) if intent.kind == "filing"]
    lifecycle.clock = lambda: now
    lifecycle.ingress.clock = lifecycle.clock
    async with LifecycleClient("http://test", BUYER, TrustedIdentitySet(identities=(SELLER.identity,)),
                               transport=httpx.ASGITransport(app=h.app)) as buyer:
        await buyer.end_delivery(h.negotiation_id, operation_key="later-end")
    with transaction(lifecycle.path) as conn:
        end = EndSession(conn)
        lifecycle.resolve_site_corrections(end, h.negotiation_id, now=now)
        assert lifecycle.classification_for(end, h.negotiation_id, "site-event:early-report").kind == "buyer_surrender"
        assert not [intent for intent in end.intents(h.negotiation_id) if intent.kind == "filing"]
    # Replay preserves the original immutable request even after its correction.
    lifecycle.ingress.site_report(h.negotiation_id, body=body, headers={})
