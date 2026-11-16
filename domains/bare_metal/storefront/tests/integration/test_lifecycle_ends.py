"""Signed site reports and surrender through the composed bare-metal app."""

import asyncio
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from compute_provisioning_contracts.lease_ends import LEASE_ENDED_CALLBACK, LeaseEndedEvent, sign_lease_end
from market_arkhai_payments import PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_contracts.models import CommitMessage
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import stable_ref
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json
from site_trust import seeded_sites
from storefront_client import StorefrontClient

from integration.test_payment_settlement_client import BUYER, SELLER, harness, enabled, _runtime
from integration.test_rate_delivery import PAYER as RATE_PAYER
from integration.test_rate_delivery import accepted_recurring_deal, approve
from recurring_world import MECHANISM, PAYMENTS_SERVICE, recurring_world
from test_http_system import SELLER_SIGNER

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


def recorded_end(path, negotiation_id):
    """The deal's selected end and its classification, ``None`` while pending."""
    with transaction(path) as conn:
        end = EndSession(conn)
        selected = end.selected_end(negotiation_id)
        return selected, end.classification(negotiation_id, selected.source_ref)


def filings(path, negotiation_id):
    with transaction(path) as conn:
        return [intent for intent in EndSession(conn).intents(negotiation_id) if intent.kind == "filing"]


async def withdraw(world, negotiation_id, *, at):
    """The world's site withdraws the deal's reservation at ``at``, pushing its
    signed report to the app's lease-ended callback; returns the report's source."""
    with sqlite3.connect(world.db.db_path) as conn:
        reservation, site_id = conn.execute(
            "SELECT capacity_reservation_id, site_id FROM bare_metal_fulfillment_lifecycle WHERE negotiation_id=?",
            (negotiation_id,),
        ).fetchone()
    bindings, peers = seeded_sites(world.db.db_path, {site_id: SITE.identity})
    object.__setattr__(world.runtime, "site_bindings", bindings)
    object.__setattr__(world.runtime, "service_peer_trust", peers)
    report = sign_lease_end(LeaseEndedEvent(
        event_id="site-withdrawal", capacity_reservation_id=reservation, site_id=site_id,
        effective_at=at, cause="force_release", source_state="leased",
        reason="site withdrawal", caller=SITE.identity,
    ), SITE)
    async with StorefrontClient(
        "http://test", signer=SITE, caller_role="service",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=world.app),
    ) as site:
        await site.authenticated_request(
            "POST", LEASE_ENDED_CALLBACK["path"].format(capacity_reservation_id=reservation),
            role="service", operation="lease_ended", resource=reservation, body=report.model_dump(mode="json"),
        )
    return "site-event:site-withdrawal"


async def accepted_once_deal(world):
    """Publish, then negotiate the once-only payments option to acceptance through the buyer's typed client."""
    report = await world.publish()
    (listing_id,) = [item["listing_id"] for item in report["actions"] if item["action"] == "publish"]
    options = (await world.admin.get_listing(listing_id)).extra["settlement_options"]
    once = next(
        option for option in options
        if option["settlement"]["schema"] == MECHANISM and "period" not in option["settlement"]
    )
    reply = await world.buyer.negotiate_new(
        listing_id=listing_id,
        # The whole hour at the clause's 2.5 an hour, in base units.
        initial_amount=2_500_000,
        provision_terms={"kind": "bare_metal.v2", "version": 1, "payload": {
            "duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 fixture", "access_method": "ssh",
        }},
        settlement_selection={
            "option_id": once["option_id"],
            "settlement": {"schema": MECHANISM, "payer_account": RATE_PAYER},
        },
        selection_only=True,
    )
    assert reply["action"] == "accept"
    negotiation_id = reply["agreement"]["negotiation_id"]
    thread = await world.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    raw = thread["settlement_data"]
    return negotiation_id, PaymentSettlementData.parse(json.loads(raw) if isinstance(raw, str) else raw)


@pytest.mark.asyncio
async def test_a_delivered_rate_deal_buyer_stop_is_an_entitled_stop_that_discharges_a_later_withdrawal(tmp_path):
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    async with recurring_world(tmp_path, payments=payments) as world:
        negotiation_id, data = await accepted_recurring_deal(world)
        approve(payments, data)
        await world.buyer.settle_agreement(negotiation_id)

        # The on-demand buyer stops at the payment authority; the servicing
        # cycle reads it there and records the stop.
        payments.observed_at = int(time.time())
        payments.engine.submit(data.transaction_id, {
            "account": RATE_PAYER, "requestId": "buyer-stop", "event": {"kind": "stop"},
        })
        await world.admin.admin_run_lifecycle_cycle("delivery-recovery")
        stop, classification = recorded_end(world.db.db_path, negotiation_id)
        assert stop.cause == "payer"
        assert classification.kind == "entitled_stop"

        # The site then withdraws the reservation: the seller failure is
        # recorded after the buyer's classified end, which discharges its filing.
        source = await withdraw(world, negotiation_id, at=world.runtime.lifecycle.clock())
        with transaction(world.db.db_path) as conn:
            end = EndSession(conn)
            assert end.classification(negotiation_id, source).kind == "unentitled_withdrawal"
            assert end.selected_end(negotiation_id) == stop
        assert filings(world.db.db_path, negotiation_id) == []


@pytest.mark.asyncio
async def test_a_once_only_deal_payment_term_end_is_the_term_end_and_a_later_withdrawal_files_nothing(tmp_path):
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    async with recurring_world(tmp_path, payments=payments) as world:
        negotiation_id, data = await accepted_once_deal(world)
        assert all(part.root.kind == "once" for part in data.mandate.parts)
        approve(payments, data)
        await world.buyer.settle_agreement(negotiation_id)
        with transaction(world.db.db_path) as conn:
            record = EndSession(conn).read(negotiation_id)
    assert record.available_at is not None

    # Past the Agreement's end the payments service records the part's term
    # end; the app, restarted then, reads it in its servicing cycle.
    at = record.term_end + 60
    payments.observed_at = at
    async with recurring_world(tmp_path, payments=payments, clock=lambda: at) as world:
        await world.admin.admin_run_lifecycle_cycle("delivery-recovery")
        with transaction(world.db.db_path) as conn:
            end = EndSession(conn)
            ends = {request.source_ref: (request, end.classification(negotiation_id, request.source_ref))
                    for request in end.requests(negotiation_id)}
        # The site withdraws after the term end: the seller failure follows a
        # classified end, so its filing is discharged.
        source = await withdraw(world, negotiation_id, at=record.term_end + 30)
        with transaction(world.db.db_path) as conn:
            withdrawal = EndSession(conn).classification(negotiation_id, source)
        withdrawn = filings(world.db.db_path, negotiation_id)
    [(stop, classification)] = [value for ref, value in ends.items() if ref.startswith("payment-stop:")]
    assert (stop.cause, classification.kind) == ("terms", "terms"), ends
    assert stop.ended_at >= record.term_end
    assert withdrawal.kind == "unentitled_withdrawal"
    assert withdrawn == []
