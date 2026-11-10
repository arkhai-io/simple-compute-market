"""Persisted filing, receipt and operator-key regressions at the servicing boundary."""

import asyncio
from unittest.mock import AsyncMock

import pytest
import httpx
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.adapters import (
    DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, InterfaceRequest,
    PaymentAdapterTable, PaymentSelector, submit_dispute,
)
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, EndDeliveryMessage, LifecycleCommand, Rejected,
)
from market_identity import Ed25519Signer, RequestEnvelope, canonical_body_hash, canonical_json, sign_request
from pydantic import SecretStr
from market_deal_servicing import (
    DealWatch, DeliveryIngress, DeliveryRecord, EndSession, SellerDeal, SellerServicing, SellerSession,
    SQLiteOperationStore, create_schema,
)
from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import Classification, FinalRequest


# Public deterministic development seeds; never use on a public network.
SELLER, BUYER = Ed25519Signer(bytes([1]) * 32), Ed25519Signer(bytes([2]) * 32)
AUTHORITY = DisputeAuthority(interface="fixture.dispute", origin="https://dispute.example", account="authority",
                             record_key="fixture", params={})


class Dispute:
    supported_commands = frozenset({"delivery_end"})
    supported_intents = frozenset({"delivery_end"})

    def __init__(self, rejected=False):
        self.calls = []
        self.rejected = rejected

    def build_request(self, intent):
        return InterfaceRequest(interface=AUTHORITY.interface, payload=intent.model_dump(mode="json"))

    def validate_request(self, request):
        return None

    async def submit(self, command, request, keys):
        self.calls.append(command)
        return Rejected(reason="authority refuses this filing") if self.rejected else Accepted()

    async def read(self):
        return AuthorityView(outcome=Accepted())


def service(path, dispute=None, *, delivered=True):
    dispute = dispute or Dispute()
    api = SellerServicing(path, payments=PaymentAdapterTable([]),
        disputes=DisputeAdapterTable([(AUTHORITY.interface, lambda _: dispute)]),
        credential_available=lambda _: True, clock=lambda: 120,
        watch_factory=lambda deal, payment, adapter: DealWatch(
            path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
            payment=payment, dispute=adapter, dispute_binding=deal.dispute_binding,
            seller_account="seller-account", actor=lambda _: SELLER.identity, clock=lambda: 120))
    with transaction(path) as conn:
        # The storefront chain's migration, which a session does not run.
        create_schema(conn)
        EndSession(conn).register(DeliveryRecord(negotiation_id="deal", seller=SELLER.identity,
            commitment_ref="commitment", start_at=100, term_end=1000, committed_at=100,
            available_at=101 if delivered else None))
        SellerSession(conn).register(SellerDeal(negotiation_id="deal", commitment_ref="commitment", domain="fixture",
            buyer=BUYER.identity, payment=PaymentSelector("fixture.payment"), dispute=AUTHORITY, once_only=True))
    return api


def failure(end, source="operator:first", *, observed=120, delivered=True):
    request = FinalRequest(negotiation_id="deal", source_ref=source, observed_at=observed, ended_at=observed,
                           actor=SELLER.identity, cause="operator_end", source="administrator", evidence_refs=[source])
    end.record_end(request, now=120,
                   classification=Classification(kind="unentitled_withdrawal", evidence_refs=[source]),
                   filing_intent=end.failure_filing(request, now=120, delivered=delivered))
    return request


@pytest.mark.parametrize("delivered", [False, True])
def test_site_echo_adopts_the_controlling_failure_filing(tmp_path, delivered):
    path = tmp_path / "servicing.sqlite"
    service(path, delivered=delivered)
    with transaction(path) as conn:
        end = EndSession(conn)
        original = failure(end, delivered=delivered)
    with transaction(path) as conn:
        end = EndSession(conn)
        echo = FinalRequest(negotiation_id="deal", source_ref="site:event", observed_at=120, ended_at=120,
                            actor=SELLER.identity, cause="termination", source="lease_ended",
                            evidence_refs=["site:event"], controlling_source_ref=original.source_ref)
        end.record_end(echo, now=120,
                       classification=Classification(kind="unentitled_withdrawal", evidence_refs=["site:event"]))
        assert len(end.requests("deal")) == 2
        assert len([intent for intent in end.intents("deal") if intent.kind == "filing"]) == 1


def test_semantic_adoption_coordinates_reconstructed_durable_callers(tmp_path):
    async def drive():
        path = tmp_path / "operations.sqlite"
        with transaction(path) as conn:
            create_schema(conn)
        peer = MediationContractFake()
        entered, proceed = asyncio.Event(), asyncio.Event()
        async def handle(request):
            if request.method == "POST":
                entered.set()
                await proceed.wait()
            return peer.handle(request)
        authority = DisputeAuthority.model_validate(peer.authority)
        filing = peer.data["filing"]["request"]
        binding = DisputeBinding("deal", filing["transaction"], authority)
        async with MediationClient(authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
            transport=httpx.MockTransport(handle)) as client:
            table = DisputeAdapterTable([(authority.interface, lambda _: MediationAdapter(binding, filing["agreement"],
                                                                                       client, clock=lambda: 1800001800))])
            async def submit(key):
                return await submit_dispute(LifecycleCommand(negotiation_id="deal", kind="delivery_end", operation_key=key,
                    payload=DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee").model_dump(mode="json")),
                    binding, table, SQLiteOperationStore(path))
            first = asyncio.create_task(submit("online"))
            try:
                await entered.wait()
                concurrent = await asyncio.wait_for(submit("operator"), timeout=5)
                assert concurrent.status == "pending" and "resolve" in concurrent.reason
                proceed.set()
                accepted = await first
                adopted = await submit("operator")
                assert accepted.status == adopted.status == "accepted"
                assert accepted.filing.case_ref == adopted.filing.case_ref
                assert len(peer.cases) == 1
            finally:
                proceed.set()
                if not first.done():
                    first.cancel()
                await asyncio.gather(first, return_exceptions=True)
    asyncio.run(drive())


def test_late_recorded_prestart_failure_keeps_agreement_start_basis(tmp_path):
    path = tmp_path / "servicing.sqlite"
    service(path, delivered=False)
    with transaction(path) as conn:
        failure(EndSession(conn), observed=90, delivered=False)
    with transaction(path) as conn:
        filings = [intent for intent in EndSession(conn).intents("deal") if intent.kind == "filing"]
        assert filings[0].payload["payload"]["ended_at"] == 100
        assert filings[0].not_before >= 100


def test_receipt_does_not_sign_over_an_earlier_seller_end(tmp_path):
    path = tmp_path / "servicing.sqlite"
    service(path)
    claims = []
    def sign_claim(*args):
        claims.append(args)
        return {"claim": "payer"}
    ingress = DeliveryIngress(path, clock=lambda: 120, verify_site=lambda *_: None, receipt_claim=sign_claim)
    with transaction(path) as conn:
        failure(EndSession(conn), observed=110)
    message = EndDeliveryMessage(negotiation_id="deal", operation_key="surrender")
    request = sign_request(signer=BUYER, envelope=RequestEnvelope(
        role="buyer", principal=BUYER.identity, method="POST", operation="lifecycle_peer", resource="deal",
        request_id="request", timestamp=120, body_hash=canonical_body_hash(message)))
    receipt = ingress.end_delivery(request, body=canonical_json(message), headers={})
    assert receipt.selected_end.cause == "operator_end"
    assert receipt.signed_delivery_end_claim is None and claims == []


def test_receipt_retry_keeps_first_instant_and_signed_claim(tmp_path):
    path = tmp_path / "servicing.sqlite"
    service(path)
    now, claims = [120], []
    def claim(*args):
        claims.append(args)
        return {"claim": str(args)}
    ingress = DeliveryIngress(path, clock=lambda: now[0], verify_site=lambda *_: None, receipt_claim=claim)
    message = EndDeliveryMessage(negotiation_id="deal", operation_key="surrender")
    def surrender():
        request = sign_request(signer=BUYER, envelope=RequestEnvelope(
            role="buyer", principal=BUYER.identity, method="POST", operation="lifecycle_peer", resource="deal",
            request_id="request:" + str(now[0]), timestamp=now[0], body_hash=canonical_body_hash(message)))
        return ingress.end_delivery(request, body=canonical_json(message), headers={})
    first = surrender()
    now[0] += 10
    second = surrender()
    assert first.receipt_at == second.receipt_at == 120
    assert first.signed_delivery_end_claim == second.signed_delivery_end_claim
    assert len(claims) == 1


def test_rejected_operator_request_does_not_consume_its_key(tmp_path):
    async def drive():
        api = service(tmp_path / "servicing.sqlite")
        command = LifecycleCommand(negotiation_id="deal", kind="delivery_end", operation_key="operator")
        bad = command.model_copy(update={"at": 100})
        assert (await api.submit(bad, actor=SELLER.identity, reason="maintenance")).status == "rejected"
        assert (await api.submit(command, actor=SELLER.identity, reason="maintenance")).status == "accepted"
    asyncio.run(drive())


def test_operator_end_returns_only_its_own_filing_outcome(tmp_path):
    async def drive():
        path = tmp_path / "servicing.sqlite"
        api = service(path, Dispute(rejected=True))
        first = LifecycleCommand(negotiation_id="deal", kind="delivery_end", operation_key="first")
        assert (await api.submit(first, actor=SELLER.identity, reason="first failure")).status == "rejected"
        api.clock = lambda: 130
        later = first.model_copy(update={"operation_key": "later"})
        assert (await api.submit(later, actor=SELLER.identity, reason="later end")).status == "accepted"
        assert (await api.submit(first, actor=SELLER.identity, reason="first failure")).status == "rejected"
    asyncio.run(drive())


def test_repair_reason_has_exactly_one_prefix(tmp_path):
    async def drive():
        path = tmp_path / "servicing.sqlite"
        dispute = Dispute()
        dispute.submit = AsyncMock(return_value=Rejected(reason="repair required: unsupported revision"))
        api = service(path, dispute)
        with transaction(path) as conn:
            failure(EndSession(conn))
        await api.dispatch_filings("deal")
        assert (await api.read("deal")).authority.outcome.reason == "repair required: unsupported revision"
    asyncio.run(drive())


def test_rejected_filings_are_terminal_and_visible_with_every_outcome(tmp_path):
    async def drive():
        path = tmp_path / "servicing.sqlite"
        dispute = Dispute(rejected=True)
        api = service(path, dispute)
        with transaction(path) as conn:
            failure(EndSession(conn), "failure:one")
            failure(EndSession(conn), "failure:two", observed=110)
        first = await api.dispatch_filings("deal")
        assert len(first) == 2 and all(item.outcome.status == "rejected" for item in first)
        assert len(dispute.calls) == 2
        restarted = service(path, dispute)
        assert await restarted.dispatch_filings("deal") == first
        assert len(dispute.calls) == 2
        read = await restarted.read("deal")
        assert read.authority.state == "repair_required"
        assert read.filings == first
        page = await restarted.list()
        assert page.deals[0].state == "repair_required" and page.deals[0].filings == first
    asyncio.run(drive())
