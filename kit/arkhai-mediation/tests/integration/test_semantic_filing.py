"""Delivery-end callers converge on signed authority cases, never caller-key
duplicates, and a changed claim is filed at once as a case of its own."""

import asyncio
import hashlib

import httpx
from market_identity import canonical_json
from pydantic import SecretStr

from market_deal_lifecycle.adapters import DeliveryEndIntent, DisputeAdapterTable, submit_dispute
from market_deal_lifecycle_contracts.models import LifecycleCommand
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import INTERFACE, wire
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.models import Filing
from .test_adapter import Operations, Scenario


class Buyer:
    """The payer's own adapter over the scenario's Agreement, with its own
    operation store, as the buyer kit composes it."""

    def __init__(self, s):
        self.binding = s.binding
        # Public deterministic contract-fake credential; never use on a public network.
        self.client = MediationClient(
            s.authority, MediationCredential(s.authority.identity, token=SecretStr("fixture-payer")),
            transport=s.peer.transport(),
        )
        self.adapter = MediationAdapter(
            s.binding, s.peer.data["filing"]["request"]["agreement"], self.client, clock=lambda: 1800001800,
        )
        self.table = DisputeAdapterTable([(INTERFACE, lambda _: self.adapter)])
        self.operations = Operations()

    async def submit(self, key, intent):
        return await submit_dispute(LifecycleCommand(
            negotiation_id=self.binding.negotiation_id, kind="delivery_end", operation_key=key,
            payload=intent.model_dump(mode="json"),
        ), self.binding, self.table, self.operations)


def filed_claims(peer):
    return [(record["entry"]["actor"], record["entry"]["filing"]["request"])
            for record in peer.entries if record["entry"]["kind"] == "filed"]


def test_online_recovery_and_reconstructed_caller_adopt_one_semantic_case():
    async def drive():
        # The peer answers a read of the Agreement 404 invalid_request until the
        # first filing makes it known, as the authority does.
        peer = MediationContractFake()
        s = Scenario(peer=peer)
        intent = DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee")
        try:
            unfiled = await s.adapter.read()
            assert unfiled.outcome.status == "accepted" and unfiled.cases == []
            first = await s.submit("delivery_end", "online", intent.model_dump(mode="json"))
            second = await s.submit("delivery_end", "operator", intent.model_dump(mode="json"))
            assert first.status == second.status == "accepted"
            assert (await s.adapter.read()).outcome.status == "accepted"
            assert first.filing.case_ref == second.filing.case_ref
            assert len(s.peer.cases) == 1
            assert len([r for r in s.peer.requests if r.method == "POST"]) == 1
        finally:
            await s.client.close()
    asyncio.run(drive())


def test_a_changed_claim_after_a_filed_one_is_filed_as_its_own_case():
    """The seller's original filing reached the authority though its answer was
    lost; a changed claim is filed at once as a second case, never refused, and
    the original is still adopted under its own claim."""
    async def drive():
        s = Scenario()
        intent = DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee")
        try:
            s.peer.lose_next_response = True
            assert (await s.submit("delivery_end", "online", intent.model_dump(mode="json"))).status == "unknown"
            revised = intent.model_copy(update={"ended_at": 1799999000})
            filed = await s.submit("delivery_end", "operator-revision", revised.model_dump(mode="json"))
            assert filed.status == "accepted" and len(s.peer.cases) == 2
            adopted = await s.submit("delivery_end", "operator", intent.model_dump(mode="json"))
            assert adopted.status == "accepted" and adopted.filing.case_ref != filed.filing.case_ref
            assert len(s.peer.cases) == 2
            # The second filing names no earlier case: it is the claim alone.
            assert [claim for _, claim in filed_claims(s.peer)] == [
                intent.model_dump(mode="json") | {"kind": "delivery_end"},
                revised.model_dump(mode="json") | {"kind": "delivery_end"},
            ]
        finally:
            await s.client.close()
    asyncio.run(drive())


def test_a_changed_claim_behind_an_earlier_filing_of_unknown_outcome_stays_pending():
    """The seller's original filing never reached the authority and its outcome
    is unknown; a changed claim waits for it, and once the original is filed
    under its key the changed claim is filed after it."""
    async def drive():
        peer = MediationContractFake()
        drop = [True]

        def handle(request):
            if request.method == "POST" and drop[0]:
                drop[0] = False
                raise httpx.ConnectError("connection reset before the authority read it", request=request)
            return peer.handle(request)

        s = Scenario(peer=peer, transport=httpx.MockTransport(handle))
        intent = DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee")
        revised = intent.model_copy(update={"ended_at": 1799999000})
        try:
            assert (await s.submit("delivery_end", "online", intent.model_dump(mode="json"))).status == "unknown"
            assert peer.cases == {}
            waiting = await s.submit("delivery_end", "revision", revised.model_dump(mode="json"))
            assert waiting.status == "pending" and "earlier delivery-end filing" in waiting.reason
            assert peer.cases == {}
            assert (await s.submit("delivery_end", "online", intent.model_dump(mode="json"))).status == "accepted"
            filed = await s.submit("delivery_end", "revision", revised.model_dump(mode="json"))
            assert filed.status == "accepted"
            assert [claim["ended_at"] for _, claim in filed_claims(peer)] == [1800000000, 1799999000]
        finally:
            await s.client.close()
    asyncio.run(drive())


def test_an_original_reserved_by_the_released_adapter_holds_a_changed_claim_back():
    """A store written by marketplace 0.4.0's adapter holds one writer per
    Agreement and no order slots; while its original is not on the record, a
    changed claim waits, and the original itself is still filed."""
    async def drive():
        s = Scenario()
        intent = DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee")
        revised = intent.model_copy(update={"ended_at": 1799999000})
        identity = hashlib.sha256(canonical_json({
            "commitment": s.binding.commitment_ref, "agreement": s.adapter.agreement_digest,
            "authority": s.binding.authority.model_dump(mode="json"),
        })).hexdigest()
        original = LifecycleCommand(
            negotiation_id=s.binding.negotiation_id, kind="delivery_end", operation_key="online",
            payload=intent.model_dump(mode="json"),
        )
        filing = Filing.model_validate({
            **s.adapter.build_request(intent).payload, "transaction": s.binding.commitment_ref,
            "agreement": s.peer.data["filing"]["request"]["agreement"],
        })
        await s.operations.check_and_record(
            s.binding.negotiation_id, "mediation-delivery-end:" + identity,
            hashlib.sha256(canonical_json({"operation_key": "online", "filing": wire(filing)})).hexdigest(),
        )
        try:
            waiting = await s.submit("delivery_end", "revision", revised.model_dump(mode="json"))
            assert waiting.status == "pending" and s.peer.cases == {}
            assert (await s.submit("delivery_end", "online", original.payload)).status == "accepted"
            assert (await s.submit("delivery_end", "revision", revised.model_dump(mode="json"))).status == "accepted"
            assert len(s.peer.cases) == 2
        finally:
            await s.client.close()
    asyncio.run(drive())


def test_a_payee_claim_after_the_buyer_s_case_is_filed_as_a_new_case():
    """The buyer's ``delivery_end(cause=payer)`` case is on the Agreement; the
    seller's payee claim for an earlier failure is filed as a second case."""
    async def drive():
        s = Scenario()
        buyer = Buyer(s)
        surrender = DeliveryEndIntent(ended_at=1800000000, delivered=True, cause="payer")
        failure = DeliveryEndIntent(ended_at=1799999000, delivered=True, cause="payee")
        try:
            assert (await buyer.submit("surrender", surrender)).status == "accepted"
            filed = await s.submit("delivery_end", "site-failure", failure.model_dump(mode="json"))
            assert filed.status == "accepted"
            assert [(actor, claim["cause"]) for actor, claim in filed_claims(s.peer)] == [
                (s.peer.payer, "payer"), (s.peer.payee, "payee"),
            ]
        finally:
            await buyer.client.close()
            await s.client.close()
    asyncio.run(drive())


def test_a_buyer_claim_after_the_seller_s_case_is_filed_too():
    async def drive():
        s = Scenario()
        buyer = Buyer(s)
        failure = DeliveryEndIntent(ended_at=1800000000, delivered=True, cause="payee")
        surrender = DeliveryEndIntent(ended_at=1799999000, delivered=True, cause="payer")
        try:
            assert (await s.submit("delivery_end", "failure", failure.model_dump(mode="json"))).status == "accepted"
            filed = await buyer.submit("surrender", surrender)
            assert filed.status == "accepted" and len(s.peer.cases) == 2
        finally:
            await buyer.client.close()
            await s.client.close()
    asyncio.run(drive())


def test_an_equal_claim_adopts_the_case_whoever_filed_it():
    async def drive():
        s = Scenario()
        buyer = Buyer(s)
        claim = DeliveryEndIntent(ended_at=1800000000, delivered=True, cause="payee")
        try:
            first = await buyer.submit("buyer-copy", claim)
            assert first.status == "accepted"
            posts = len([request for request in s.peer.requests if request.method == "POST"])
            adopted = await s.submit("delivery_end", "seller", claim.model_dump(mode="json"))
            assert adopted.status == "accepted" and adopted.filing.case_ref == first.filing.case_ref
            assert len([request for request in s.peer.requests if request.method == "POST"]) == posts
        finally:
            await buyer.client.close()
            await s.client.close()
    asyncio.run(drive())


def test_existing_case_pending_protection_is_not_refiled():
    async def drive():
        peer = MediationContractFake()
        def handle(request):
            if request.url.path.startswith("/cases/"):
                return httpx.Response(200, json={
                    "status": "pending", "case_ref": next(iter(peer.cases)),
                })
            return peer.handle(request)
        s = Scenario(peer=peer, transport=httpx.MockTransport(handle))
        intent = DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee")
        try:
            first = await s.submit("delivery_end", "online", intent.model_dump(mode="json"))
            assert first.status == "accepted"
            recovered = await s.submit("delivery_end", "recovery", intent.model_dump(mode="json"))
            assert recovered.status == "pending" and "protection pending" in recovered.reason
            assert len(peer.cases) == 1
            assert len([r for r in peer.requests if r.method == "POST"]) == 1
        finally:
            await s.client.close()
    asyncio.run(drive())


def test_concurrent_callers_coordinate_before_authority_write():
    async def drive():
        entered, proceed = asyncio.Event(), asyncio.Event()
        peer = MediationContractFake()
        async def handle(request):
            if request.method == "POST":
                entered.set()
                await proceed.wait()
            return peer.handle(request)
        s = Scenario(peer=peer, transport=httpx.MockTransport(handle))
        intent = DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee").model_dump(mode="json")
        try:
            first = asyncio.create_task(s.submit("delivery_end", "online", intent))
            await entered.wait()
            second = await asyncio.wait_for(s.submit("delivery_end", "recovery", intent), timeout=1)
            assert second.status == "pending" and "resolve" in second.reason
            proceed.set()
            assert (await first).status == "accepted"
            assert (await s.submit("delivery_end", "recovery", intent)).status == "accepted"
            assert len(peer.cases) == 1
        finally:
            proceed.set()
            if not first.done():
                first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await s.client.close()
    asyncio.run(drive())
