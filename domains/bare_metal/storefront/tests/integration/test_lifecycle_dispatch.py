"""Bare-metal surrender races and signed release through the mounted application."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from compute_provisioning_contracts import (
    ACCESS_DELIVERY_KIND,
    ACCESS_DELIVERY_SCHEMA_VERSION,
    FulfillmentStatusResponse,
)
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
from market_core import VersionedEnvelope
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json
from site_trust import seeded_sites
from storefront_client import StorefrontClient, StorefrontClientError

from integration.test_payment_settlement_client import (
    ADMIN,
    BUYER,
    Provisioning,
    SELLER,
)
from integration.test_payment_settlement_client import enabled as enabled
from integration.test_payment_settlement_client import harness as harness
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

# Public deterministic development site; never use on a public network.
SITE = Ed25519Signer(bytes.fromhex("44" * 32))


def peer(h, signer=BUYER):
    return LifecycleClient(
        "http://test", signer, TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=httpx.ASGITransport(app=h.app),
    )


class ReadyProvisioning(Provisioning):
    """The external site completes the already dispatched physical grant, once
    ``state`` says so."""

    def __init__(self, state: str = "active"):
        super().__init__()
        self.lease_reads = 0
        self.state = state

    async def get_fulfillment_status(self, fulfillment_id, *, capacity_reservation_id):
        assert (fulfillment_id, capacity_reservation_id) == ("fulfillment-pay", "reservation-pay")
        return FulfillmentStatusResponse(
            fulfillment_id=fulfillment_id, capacity_reservation_id=capacity_reservation_id,
            state=self.state,
        )

    async def get_fulfillment_result(self, fulfillment_id, *, capacity_reservation_id):
        assert (fulfillment_id, capacity_reservation_id) == ("fulfillment-pay", "reservation-pay")
        return VersionedEnvelope(
            kind="fulfillment.result.v1", schema_version=1,
            payload={
                "fulfillment_id": fulfillment_id,
                "capacity_reservation_id": capacity_reservation_id,
                "state": "active",
                "domain_result": {
                    "kind": ACCESS_DELIVERY_KIND,
                    "schema_version": ACCESS_DELIVERY_SCHEMA_VERSION,
                    "payload": {
                        # Documentation-only endpoint; never use on a public network.
                        "endpoints": [{"protocol": "ssh", "host": "192.0.2.1", "port": 22, "user": "example-user"}],
                        "ready_at": "2026-01-01T00:00:00Z",
                    },
                },
            },
        )

    async def get_lease(self, capacity_reservation_id):
        assert capacity_reservation_id == "reservation-pay"
        self.lease_reads += 1
        return SimpleNamespace(end_reports=[], status="active")


class InterruptedReceiptStore(SQLiteClient):
    """A real database whose first receipt write is interrupted."""

    interrupted = False

    async def save_bare_metal_receipt(self, **kwargs):
        if not self.interrupted:
            self.interrupted = True
            raise RuntimeError("fixture receipt persistence interruption")
        await super().save_bare_metal_receipt(**kwargs)


class DelayedResultProvisioning(ReadyProvisioning):
    """The site's first result read fails while its lease API stays reachable."""

    result_reads = 0

    async def get_fulfillment_result(self, fulfillment_id, *, capacity_reservation_id):
        self.result_reads += 1
        if self.result_reads == 1:
            raise RuntimeError("fixture result transport interruption")
        return await super().get_fulfillment_result(
            fulfillment_id, capacity_reservation_id=capacity_reservation_id,
        )


@pytest.mark.asyncio
async def test_servicing_adopts_ready_fulfillment_without_buyer_status_poll(harness):
    h = harness
    provisioning = ReadyProvisioning(state="dispatching")
    object.__setattr__(h.runtime, "fulfillment_client", provisioning)
    h.serve()
    async with peer(h) as buyer:
        committed = await buyer.commit(CommitMessage(
            negotiation_id=h.negotiation_id, commitment_ref=h.data.transaction_id,
            operation_key="commit",
        ))
        assert committed.outcome.status == "accepted"
        assert (await buyer.read(h.negotiation_id)).delivery.progress == "unstarted"
        provisioning.state = "active"
        await h.runtime.lifecycle.cycle()
        assert (await buyer.read(h.negotiation_id)).delivery.progress == "active"
        with transaction(h.runtime.db.db_path) as conn:
            available_at = EndSession(conn).read(h.negotiation_id).available_at
        assert available_at is not None
        await h.runtime.lifecycle.cycle()
        with transaction(h.runtime.db.db_path) as conn:
            assert EndSession(conn).read(h.negotiation_id).available_at == available_at
    assert len(provisioning.begin_calls) == 1
    assert provisioning.terminated == []


@pytest.mark.asyncio
async def test_servicing_finishes_receipt_after_availability_was_recorded(harness):
    h = harness
    provisioning = ReadyProvisioning(state="dispatching")
    db = InterruptedReceiptStore(h.runtime.db.db_path, domain=h.runtime.domain)
    object.__setattr__(h.runtime, "db", db)
    object.__setattr__(h.runtime, "fulfillment_client", provisioning)
    h.serve()
    async with peer(h) as buyer:
        await buyer.commit(CommitMessage(
            negotiation_id=h.negotiation_id, commitment_ref=h.data.transaction_id,
            operation_key="commit",
        ))
        provisioning.state = "active"
        await h.runtime.lifecycle.cycle()
        assert db.interrupted
        assert await db.load_bare_metal_result(negotiation_id=h.negotiation_id) is not None
        assert await db.load_bare_metal_receipt(negotiation_id=h.negotiation_id) is None
        with transaction(db.db_path) as conn:
            first = EndSession(conn).read(h.negotiation_id).available_at
        assert first is not None
        await h.runtime.lifecycle.cycle()
        assert await db.load_bare_metal_receipt(negotiation_id=h.negotiation_id) is not None
        with transaction(db.db_path) as conn:
            assert EndSession(conn).read(h.negotiation_id).available_at == first
    assert len(provisioning.begin_calls) == 1


@pytest.mark.asyncio
async def test_servicing_never_adopts_readiness_after_buyer_end(harness):
    h = harness
    provisioning = ReadyProvisioning(state="dispatching")
    object.__setattr__(h.runtime, "fulfillment_client", provisioning)
    h.serve()
    async with peer(h) as buyer:
        await buyer.commit(CommitMessage(
            negotiation_id=h.negotiation_id, commitment_ref=h.data.transaction_id,
            operation_key="commit",
        ))
        await buyer.end_delivery(h.negotiation_id, operation_key="end")
        provisioning.state = "active"
        await h.runtime.lifecycle.cycle()
        assert (await buyer.read(h.negotiation_id)).delivery.progress == "tearing_down"
        with transaction(h.runtime.db.db_path) as conn:
            assert EndSession(conn).read(h.negotiation_id).available_at is None
    assert len(provisioning.begin_calls) == len(provisioning.terminated) == 1


@pytest.mark.asyncio
async def test_failed_readiness_observation_retries_without_starving_site_recovery(harness):
    h = harness
    provisioning = DelayedResultProvisioning(state="dispatching")
    object.__setattr__(h.runtime, "fulfillment_client", provisioning)
    h.serve()
    async with peer(h) as buyer:
        await buyer.commit(CommitMessage(
            negotiation_id=h.negotiation_id, commitment_ref=h.data.transaction_id,
            operation_key="commit",
        ))
        provisioning.state = "active"
        await h.runtime.lifecycle.cycle()
        assert provisioning.lease_reads == 1
        assert (await buyer.read(h.negotiation_id)).delivery.progress == "unstarted"
        await h.runtime.lifecycle.cycle()
        assert (await buyer.read(h.negotiation_id)).delivery.progress == "active"
    assert len(provisioning.begin_calls) == 1


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
