"""Bare-metal surrender races, the servicing cycle's kit order and signed release
through the mounted application."""

import asyncio
import hashlib
import json
import logging
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
from market_alkahest import ALKAHEST_MECHANISM_ID
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.adapters import PaymentSelector
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_client import LifecycleClient, LifecycleClientError, SellerLifecycleClient
from market_deal_lifecycle_contracts.models import CommitMessage, LifecycleCommand
from market_deal_servicing import EndSession, PhysicalResult, SellerSession
from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import stable_ref
from market_core import VersionedEnvelope
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json
from pydantic import SecretStr
from site_trust import seeded_sites
from storefront_client import StorefrontClient, StorefrontClientError

from integration.test_payment_settlement_client import (
    ADMIN,
    BUYER,
    Provisioning,
    SELLER,
    _clone_row,
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


async def step(h, loop):
    """One cycle of the storefront's ``loop``, stepped through the typed admin
    client with every loop held, so no timer races the step."""
    async with StorefrontClient(
        "http://test", signer=ADMIN, caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=httpx.ASGITransport(app=h.app),
    ) as admin:
        await admin.admin_pause_lifecycle_loops()
        return await admin.admin_run_lifecycle_cycle(loop)


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
async def test_recovery_adopts_ready_fulfillment_without_buyer_status_poll(harness):
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
        await step(h, "delivery-recovery")
        assert (await buyer.read(h.negotiation_id)).delivery.progress == "active"
        with transaction(h.runtime.db.db_path) as conn:
            available_at = EndSession(conn).read(h.negotiation_id).available_at
        assert available_at is not None
        await step(h, "delivery-recovery")
        with transaction(h.runtime.db.db_path) as conn:
            assert EndSession(conn).read(h.negotiation_id).available_at == available_at
    assert len(provisioning.begin_calls) == 1
    assert provisioning.terminated == []


@pytest.mark.asyncio
async def test_recovery_finishes_receipt_after_availability_was_recorded(harness):
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
        await step(h, "delivery-recovery")
        assert db.interrupted
        assert await db.load_bare_metal_result(negotiation_id=h.negotiation_id) is not None
        assert await db.load_bare_metal_receipt(negotiation_id=h.negotiation_id) is None
        with transaction(db.db_path) as conn:
            first = EndSession(conn).read(h.negotiation_id).available_at
        assert first is not None
        await step(h, "delivery-recovery")
        assert await db.load_bare_metal_receipt(negotiation_id=h.negotiation_id) is not None
        with transaction(db.db_path) as conn:
            assert EndSession(conn).read(h.negotiation_id).available_at == first
    assert len(provisioning.begin_calls) == 1


@pytest.mark.asyncio
async def test_recovery_never_adopts_readiness_after_buyer_end(harness):
    """After the buyer's end the re-drive leaves the ready fulfillment alone, and
    the servicing cycle tears it down."""
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
        assert (await step(h, "delivery-recovery"))["redriven"] == 0
        await step(h, "deal-servicing")
        assert (await buyer.read(h.negotiation_id)).delivery.progress == "tearing_down"
        with transaction(h.runtime.db.db_path) as conn:
            assert EndSession(conn).read(h.negotiation_id).available_at is None
    assert len(provisioning.begin_calls) == len(provisioning.terminated) == 1


@pytest.mark.asyncio
async def test_the_four_servicing_loops_are_reported_and_deal_servicing_re_drives_nothing(harness):
    """The storefront reports the four loops both compute storefronts run, each
    held; a step of ``deal-servicing`` runs one servicing cycle — the payment
    authority read — and leaves a ready fulfillment undelivered until
    ``delivery-recovery`` re-drives it."""
    h = harness
    provisioning = ReadyProvisioning(state="dispatching")
    object.__setattr__(h.runtime, "fulfillment_client", provisioning)
    h.serve()
    async with peer(h) as buyer:
        await buyer.commit(CommitMessage(
            negotiation_id=h.negotiation_id, commitment_ref=h.data.transaction_id,
            operation_key="commit",
        ))
        provisioning.state = "active"
        reads = h.payments.count("get_transaction")

        serviced = await step(h, "deal-servicing")
        undelivered = (await buyer.read(h.negotiation_id)).delivery.progress
        async with StorefrontClient(
            "http://test", signer=ADMIN, caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
            transport=httpx.ASGITransport(app=h.app),
        ) as admin:
            status = await admin.get_system_status()
        redriven = await step(h, "delivery-recovery")
        delivered = (await buyer.read(h.negotiation_id)).delivery.progress

    assert {
        name: loop["state"] for name, loop in status.lifecycle.items()
        if name in ("deal_servicing", "delivery_recovery", "payment_reconciliation", "settlement_servicing")
    } == {"deal_servicing": "paused", "delivery_recovery": "paused", "payment_reconciliation": "paused",
          "settlement_servicing": "paused"}
    assert serviced == {"loop": "deal_servicing", "processed": 1}
    assert h.payments.count("get_transaction") > reads
    assert undelivered == "unstarted"
    assert redriven == {"loop": "delivery_recovery", "redriven": 1}
    assert delivered == "active"


@pytest.mark.asyncio
async def test_failed_readiness_observation_retries_without_starving_site_recovery(harness):
    """A re-drive whose result read fails leaves the deal for the next one, and
    the servicing cycle's site recovery still reads the lease."""
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
        await step(h, "delivery-recovery")
        assert (await buyer.read(h.negotiation_id)).delivery.progress == "unstarted"
        await step(h, "deal-servicing")
        assert provisioning.lease_reads == 1
        await step(h, "delivery-recovery")
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


class UnreachableSite:
    """The end service's physical port, failing its first ``failures`` calls
    as a site that cannot be reached, then reporting the resource released."""

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("site unreachable")
        return PhysicalResult(progress="released", done=True)


def _mediation(h):
    """Give the deal's dispute authority a usable credential whose client
    reaches the mediation fixture."""
    lifecycle = h.runtime.lifecycle
    agreement = json.loads(lifecycle.agreement_bytes(h.negotiation_id))
    authority = decode_terms(agreement["settlement"]["lifecycle"]).adjudication.dispute
    mediation = MediationContractFake()
    lifecycle.clients[authority.model_dump_json()] = MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
        transport=mediation.transport(),
    )
    lifecycle.credential_available = lambda candidate: candidate == authority
    lifecycle.seller.credential_available = lifecycle.credential_available
    return mediation


@pytest.mark.asyncio
async def test_a_failing_physical_end_still_dispatches_the_deals_filing_in_the_same_cycle(harness):
    h = harness
    h.serve()
    await h.settle()
    mediation = _mediation(h)
    command = LifecycleCommand(negotiation_id=h.negotiation_id, operation_key="operator-failure", kind="delivery_end")
    assert await h.runtime.lifecycle.seller.record_operator_end(
        command, actor=ADMIN.identity, reason="fixture failure",
    ) is None
    site = UnreachableSite(failures=2)
    h.runtime.lifecycle.end.physical = site

    await h.runtime.lifecycle.cycle()

    assert site.calls == 2
    # The filing reached the authority, which holds its case, and its
    # outcome is recorded against the journaled intent.
    assert len(mediation.cases) == 1
    assert mediation.entries[0]["entry"]["filing"]["request"]["cause"] == "payee"
    with transaction(h.runtime.db.db_path) as conn:
        [filing] = [intent for intent in EndSession(conn).intents(h.negotiation_id) if intent.kind == "filing"]
    assert filing.result is not None


@pytest.mark.asyncio
async def test_a_released_deal_whose_authority_holds_no_record_is_listed_ended(harness):
    """A settled once-only deal ended by its buyer and released, on which nobody
    has filed: the authority answers its record read 404 invalid_request, which
    the servicing cycle saves as a read showing no case, so the seller's typed
    list shows the deal ended and its read an accepted dispute outcome."""
    h = harness
    h.serve()
    await h.settle()
    mediation = _mediation(h)
    h.runtime.lifecycle.end.physical = UnreachableSite(failures=0)
    async with peer(h) as buyer:
        await buyer.end_delivery(h.negotiation_id, operation_key="end")
    async with StorefrontClient(
        "http://test", signer=ADMIN, caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=httpx.ASGITransport(app=h.app),
    ) as admin:
        seller = SellerLifecycleClient(admin)
        [before] = (await seller.list()).deals
        assert (before.state, "case_unobserved" in before.ending) == ("ending", True)

        await step(h, "deal-servicing")

        [summary] = (await seller.list()).deals
        read = await seller.read(h.negotiation_id)
    # The cycle read the Agreement's record at its pinned authority, which holds
    # none: nobody filed.
    digest = hashlib.sha256(canonical_json(
        json.loads(h.runtime.lifecycle.agreement_bytes(h.negotiation_id)),
    )).hexdigest()
    assert ("/record", digest) in [
        (request.url.path, request.url.params.get("agreement")) for request in mediation.requests
    ]
    assert mediation.entries == []
    assert (summary.negotiation_id, summary.state, summary.ending) == (h.negotiation_id, "ended", [])
    assert summary.open_cases == []
    assert read.authority.outcome.status == "accepted"
    assert read.authority.cases == [] and read.authority.disputes == []


@pytest.mark.asyncio
async def test_an_uncommitted_surrender_gets_its_physical_end_from_the_cycle(harness):
    """The buyer ends the deal before committing it, while the site cannot be
    reached; the cycle, paging every registered deal, drives its end."""
    h = harness
    site = UnreachableSite(failures=1)
    h.runtime.lifecycle.end.physical = site
    async with peer(h) as buyer:
        ack = await buyer.end_delivery(h.negotiation_id, operation_key="end")
    assert ack.delivery.progress == "end_recorded"
    assert site.calls == 1

    assert await h.runtime.lifecycle.cycle() == 1

    assert site.calls == 2
    with transaction(h.runtime.db.db_path) as conn:
        end = EndSession(conn)
        assert end.read(h.negotiation_id).committed_at is None
        [termination] = [intent for intent in end.intents(h.negotiation_id) if intent.kind == "terminate"]
        assert end.read(h.negotiation_id).progress == "released"
    assert termination.state == "done"
    assert h.payments.count("get_transaction") == 0


@pytest.mark.asyncio
async def test_respondent_discovery_runs_once_per_authority_with_an_alkahest_deal_first(harness, caplog):
    """An Alkahest deal under the payments deal's authority sorts first on the
    page; discovery lists the authority's cases once, needing no payment account."""
    h = harness
    h.serve()
    await h.settle()
    mediation = _mediation(h)
    alkahest, commitment = "0-alkahest", "a" * 64
    assert alkahest < h.negotiation_id
    _clone_row(h.runtime.db.db_path, "negotiation_threads", h.negotiation_id, alkahest)
    with transaction(h.runtime.db.db_path) as conn:
        end = EndSession(conn)
        end.register(end.read(h.negotiation_id).model_copy(update={
            "negotiation_id": alkahest, "commitment_ref": commitment, "revision": 0,
        }))
        sellers = SellerSession(conn)
        sellers.register(sellers.read(h.negotiation_id).model_copy(update={
            "negotiation_id": alkahest, "commitment_ref": commitment,
            "payment": PaymentSelector(ALKAHEST_MECHANISM_ID),
        }))

    with caplog.at_level(logging.ERROR):
        assert await h.runtime.lifecycle.cycle() == 2

    assert [request.url.path for request in mediation.requests if request.url.path == "/respondent"] == [
        "/respondent",
    ]
    assert not [record for record in caplog.records if "respondent discovery" in record.getMessage()]


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
