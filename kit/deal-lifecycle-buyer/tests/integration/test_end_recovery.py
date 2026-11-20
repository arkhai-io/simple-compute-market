"""Buyer surrender recovery preserves the seller's selected end and exact receipt."""

import asyncio
import base64
import json
import sqlite3

from market_deal_lifecycle.adapters import (
    DisputeAdapterTable, DisputeBinding, InterfaceRequest, PaymentAdapterTable, PaymentBinding, PaymentSelector,
)
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import (
    Accepted, EndDeliveryAcknowledgement, LifecycleCommand, SignedEndDeliveryReceipt, SubmitResponse, Unknown, PaymentEvent,
)
from market_identity import (
    Ed25519Signer, RequestEnvelope, ResponseEnvelope, canonical_body_hash, canonical_json, sign_request, sign_response,
)
from market_deal_lifecycle_buyer import BuyerDeal, BuyerLifecycle, FileEvidenceStore


# Public deterministic development seeds; never use on a public network.
BUYER, SELLER = Ed25519Signer(bytes([1]) * 32), Ed25519Signer(bytes([2]) * 32)
AUTHORITY = DisputeAuthority(interface="fixture.dispute.v1", origin="https://dispute.example",
                             account="authority", record_key="fixture", params={})


class Dispute:
    supported_commands = frozenset({"dispute"})
    supported_intents = frozenset({"delivery_end"})

    def __init__(self):
        self.commands = []

    def sign_delivery_end(self, intent, signer):
        return {"claim": intent.model_dump(mode="json")}

    def verify_delivery_end(self, signed, intent):
        return signed == self.sign_delivery_end(intent, SELLER)

    def concurrent_request(self, intent, signed):
        return InterfaceRequest(interface=AUTHORITY.interface, payload={
            "request": intent.model_dump(mode="json"), "concurrence": signed,
        })

    def build_request(self, intent):
        return self.concurrent_request(intent, None)

    def validate_request(self, request):
        return None

    async def submit(self, command, request, keys):
        self.commands.append(command)
        return Accepted()


class Peer:
    def __init__(self, *, lose_first=False, earlier_failure=False):
        self.lose_first = lose_first
        self.earlier_failure = earlier_failure
        self.keys = []
        self.receipt = None

    async def hint(self, message):
        return SubmitResponse(outcome=Accepted())

    async def end_delivery(self, negotiation_id, *, operation_key):
        self.keys.append(operation_key)
        request_body = {"kind": "end_delivery", "negotiation_id": negotiation_id, "operation_key": operation_key}
        end = {"ended_at": 101 if self.earlier_failure else 102,
               "actor": SELLER.identity.model_dump(mode="json") if self.earlier_failure else BUYER.identity.model_dump(mode="json"),
               "cause": "operator_end" if self.earlier_failure else "buyer_surrender", "source": "end_delivery"}
        claim = None if self.earlier_failure else {"claim": {
            "kind": "delivery_end", "ended_at": 102, "delivered": True, "cause": "payer",
        }}
        ack = EndDeliveryAcknowledgement(negotiation_id=negotiation_id, operation_key=operation_key,
                                        receipt_at=102, selected_end=end,
                                        delivery={"recorded_end": end, "progress": "end_recorded"},
                                        signed_delivery_end_claim=claim)
        request = sign_request(signer=BUYER, envelope=RequestEnvelope(
            role="buyer", principal=BUYER.identity, method="POST", operation="lifecycle_peer",
            resource=negotiation_id, request_id="request", timestamp=102, body_hash=canonical_body_hash(request_body)))
        response = sign_response(signer=SELLER, envelope=ResponseEnvelope(
            role="seller", principal=SELLER.identity, method="POST", operation="lifecycle_peer",
            resource=negotiation_id, request_id="request", timestamp=102, status=200, body_hash=canonical_body_hash(ack)))
        self.receipt = SignedEndDeliveryReceipt(request=request, response=response,
                                               request_body=base64.b64encode(canonical_json(request_body)),
                                               response_body=base64.b64encode(canonical_json(ack)))
        if self.lose_first:
            self.lose_first = False
            raise OSError("response lost after durable receipt")
        return ack

    def end_receipt(self, *args):
        return self.receipt


def half(root, peer, dispute, *, rate=False, payment=None):
    evidence = FileEvidenceStore(root)
    deal = BuyerDeal("deal", "commitment", PaymentBinding("deal", PaymentSelector("fixture.payment")),
                     DisputeBinding("deal", "commitment", AUTHORITY), BUYER.identity, SELLER.identity, rate=rate)
    return BuyerLifecycle(deal=lambda _: deal, payments=PaymentAdapterTable(
                              [(deal.payment.selector, lambda _: payment)] if payment else []),
                          disputes=DisputeAdapterTable([(AUTHORITY.interface, lambda _: dispute)]),
                          operations=evidence, peer=peer, evidence=evidence,
                          end_journal=evidence.end_journal, clock=lambda: 100)


def test_lost_surrender_response_restarts_before_fixing_a_contested_claim(tmp_path):
    async def drive():
        peer, dispute = Peer(lose_first=True), Dispute()
        first = await half(tmp_path, peer, dispute).end_delivery("deal")
        assert first.delivery.status == "unknown"
        assert first.case.status == "pending" and dispute.commands == []
        recovered = await half(tmp_path, peer, dispute).end_delivery("deal")
        assert recovered.delivery.status == recovered.case.status == "accepted"
        assert "contested" not in recovered.model_dump()
        assert peer.keys[0] == peer.keys[1]
        command = dispute.commands[0]
        assert command.payload["payload"]["request"]["ended_at"] == 102
        assert command.payload["payload"]["concurrence"] is not None
        # Kept progress may contain the redundant flag; replay derives evidence
        # from the acknowledgement and immutable command instead.
        with sqlite3.connect(tmp_path / "evidence.sqlite3") as db:
            plan = json.loads(db.execute("SELECT plan FROM buyer_delivery_ends").fetchone()[0])
            plan["progress"]["contested"] = False
            db.execute("UPDATE buyer_delivery_ends SET plan=?", (json.dumps(plan),))
        replayed = await half(tmp_path, peer, dispute).end_delivery("deal")
        assert replayed == recovered
    asyncio.run(drive())


def test_an_earlier_seller_end_never_automatically_files_a_payer_claim(tmp_path):
    async def drive():
        peer, dispute = Peer(earlier_failure=True), Dispute()
        result = await half(tmp_path, peer, dispute).end_delivery("deal")
        assert result.delivery.status == "accepted"
        assert result.acknowledgement.selected_end.cause == "operator_end"
        assert result.case.status == "rejected" and dispute.commands == []
    asyncio.run(drive())


class RateStop:
    supported_commands = frozenset({"stop"})

    def __init__(self, root, outcomes):
        self.root, self.outcomes, self.commands = root, list(outcomes), []

    def validate(self, command):
        return None

    async def submit(self, command, keys):
        with sqlite3.connect(self.root / "evidence.sqlite3") as db:
            plan = json.loads(db.execute("SELECT plan FROM buyer_delivery_ends").fetchone()[0])
        assert plan["stop"] == command.model_dump(mode="json")
        self.commands.append(command)
        return self.outcomes.pop(0)


def test_normal_rate_end_restarts_stop_then_hint_without_surrender_or_case(tmp_path):
    async def drive():
        peer, dispute = Peer(), Dispute()
        hints = []

        async def unavailable_hint(message):
            hints.append(message)
            raise OSError("storefront down")

        peer.hint = unavailable_hint
        accepted = Accepted(records=[PaymentEvent(
            negotiation_id="deal", commitment_ref="commitment", part="0", kind="stop_request",
            actor="payer", cause="payer", at=400, sequence=1, authority_record_ref="stop-record",
        )])
        payment = RateStop(tmp_path, [Unknown(reason="payment authority down"), accepted])
        first = await half(tmp_path, peer, dispute, rate=True, payment=payment).end("deal")
        assert first.mode == "normal_stop" and first.payment.status == "unknown"
        assert first.hint.status == "unknown" and peer.keys == [] and dispute.commands == []
        second = await half(tmp_path, peer, dispute, rate=True, payment=payment).end("deal")
        assert second.payment == accepted and second.hint.status == "unknown"
        replay = await half(tmp_path, peer, dispute, rate=True, payment=payment).end("deal")
        assert replay.payment == accepted and len(payment.commands) == 2
        assert payment.commands[0] == payment.commands[1]
        assert all(message == hints[0] for message in hints)
        assert replay.delivery.status == "pending" and replay.acknowledgement is None
        assert peer.keys == [] and dispute.commands == []
    asyncio.run(drive())


def test_explicit_rate_surrender_reuses_the_stop_and_keeps_foundation_receipt_filing(tmp_path):
    async def drive():
        peer, dispute = Peer(), Dispute()
        payment = RateStop(tmp_path, [Accepted()])
        normal = await half(tmp_path, peer, dispute, rate=True, payment=payment).end("deal")
        assert normal.mode == "normal_stop" and peer.keys == []
        surrendered = await half(tmp_path, peer, dispute, rate=True, payment=payment).end("deal", surrender=True)
        assert surrendered.mode == "immediate_surrender"
        assert surrendered.delivery.status == surrendered.case.status == "accepted"
        assert len(payment.commands) == len(peer.keys) == len(dispute.commands) == 1
        assert surrendered.acknowledgement.receipt_at == 102
        await half(tmp_path, peer, dispute, rate=True, payment=payment).end("deal")
        assert len(payment.commands) == len(peer.keys) == len(dispute.commands) == 1
    asyncio.run(drive())
