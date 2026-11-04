"""Bare-metal surrender races and signed release through the mounted application."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from compute_provisioning_contracts.lease_ends import (
    LEASE_ENDED_CALLBACK,
    LeaseEndedEvent,
    sign_lease_end,
)
from market_deal_lifecycle_client import LifecycleClient, LifecycleClientError
from market_deal_lifecycle_contracts.models import CommitMessage
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import stable_ref
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json
from site_trust import seeded_sites
from storefront_client import StorefrontClient, StorefrontClientError

from integration.test_payment_settlement_client import (
    ADMIN,
    BUYER,
    SELLER,
)
from integration.test_payment_settlement_client import enabled as enabled
from integration.test_payment_settlement_client import harness as harness

# Public deterministic development site; never use on a public network.
SITE = Ed25519Signer(bytes.fromhex("44" * 32))


def peer(h, signer=BUYER):
    return LifecycleClient(
        "http://test", signer, TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=httpx.ASGITransport(app=h.app),
    )


@pytest.mark.asyncio
async def test_end_during_create_adopts_and_terminates_once_without_waiting(harness):
    h = harness
    h.serve()
    h.provisioning.started, h.provisioning.release = asyncio.Event(), asyncio.Event()
    async with peer(h) as buyer:
        pending = asyncio.create_task(buyer.commit(CommitMessage(
            negotiation_id=h.negotiation_id, commitment_ref=h.data.transaction_id,
            operation_key="commit",
        )))
        try:
            await asyncio.wait_for(h.provisioning.started.wait(), 5)
            ack = await buyer.end_delivery(h.negotiation_id, operation_key="end")
            assert ack.delivery.progress == "end_recorded"
            assert h.provisioning.terminated == []
        finally:
            h.provisioning.release.set()
        assert (await asyncio.wait_for(pending, 5)).outcome.status == "accepted"
        retry = await buyer.end_delivery(h.negotiation_id, operation_key="end")
        assert retry.receipt_at == ack.receipt_at
        assert retry.delivery.progress == "tearing_down"
    assert len(h.provisioning.begin_calls) == len(h.provisioning.terminated) == 1
    assert h.provisioning.terminated[0][1] == stable_ref(h.negotiation_id, "terminate", "terminate")
    with transaction(h.runtime.db.db_path) as conn:
        end = EndSession(conn)
        assert len(end.requests(h.negotiation_id)) == 1
        assert end.selected_end(h.negotiation_id).actor == BUYER.identity
        assert not [intent for intent in end.intents(h.negotiation_id) if intent.kind == "filing"]
    assert h.payments.count("reverse") == 0


@pytest.mark.asyncio
async def test_owner_refusal_repeated_teardown_exact_report_and_callback_only_release(harness):
    h = harness
    h.serve()
    await h.settle()
    async with peer(h, ADMIN) as stranger:
        with pytest.raises(LifecycleClientError) as refused:
            await stranger.end_delivery(h.negotiation_id, operation_key="wrong-buyer")
        assert refused.value.status_code == 403
    assert h.provisioning.terminated == []
    with transaction(h.runtime.db.db_path) as conn:
        assert EndSession(conn).requests(h.negotiation_id) == []
    bindings, peers = seeded_sites(h.runtime.db.db_path, {"site-a": SITE.identity})
    object.__setattr__(h.runtime, "site_bindings", bindings)
    object.__setattr__(h.runtime, "service_peer_trust", peers)
    async with peer(h) as buyer:
        ack = await buyer.end_delivery(h.negotiation_id, operation_key="end")
        retry = await buyer.end_delivery(h.negotiation_id, operation_key="end")
        assert ack.receipt_at == retry.receipt_at
        assert ack.selected_end.actor == BUYER.identity
        assert retry.delivery.progress == "tearing_down"
        assert len(h.provisioning.terminated) == 1
        report = sign_lease_end(LeaseEndedEvent(
            event_id="ended", capacity_reservation_id="reservation-pay", site_id="site-a",
            effective_at=ack.receipt_at, cause="termination", source_state="active",
            reason=stable_ref(h.negotiation_id, "terminate", "terminate"), caller=SELLER.identity,
        ), SITE)
        callback = LEASE_ENDED_CALLBACK["path"].format(capacity_reservation_id="reservation-pay")
        trust = TrustedIdentitySet(identities=(SELLER.identity,))
        transport = httpx.ASGITransport(app=h.app)
        async def send(signer):
            async with StorefrontClient("http://test", signer=signer, caller_role="service",
                                        expected_publishers=trust, transport=transport) as site:
                return await site.authenticated_request(
                    "POST", callback, role="service", operation="lease_ended",
                    resource="reservation-pay", body=report.model_dump(mode="json"),
                )
        with pytest.raises(StorefrontClientError) as refused:
            await send(ADMIN)
        assert refused.value.status_code == 403
        await send(SITE)
        await send(SITE)
        before = await buyer.read(h.negotiation_id)
        assert before.delivery.progress == "tearing_down"
        assert len(before.delivery.site_reports) == 1
        assert before.delivery.site_reports[0].body == canonical_json(report)
        async def lease(_):
            return SimpleNamespace(end_reports=[report], status="releasing")
        h.provisioning.get_lease = lease
        await h.runtime.lifecycle.recover_site(h.negotiation_id)
        assert (await buyer.read(h.negotiation_id)).delivery.site_reports == before.delivery.site_reports
        async with StorefrontClient("http://test", signer=SITE, caller_role="service",
                                    expected_publishers=trust, transport=transport) as site:
            await site.notify_capacity_released("reservation-pay", site_id="site-a")
        after = await buyer.read(h.negotiation_id)
        assert after.delivery.progress == "released"
        assert after.delivery.site_reports == before.delivery.site_reports
    assert h.payments.count("reverse") == 0
