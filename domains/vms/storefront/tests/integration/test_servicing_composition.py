"""VM authority observation through the composed watch and durable delivery view."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle.adapters import DisputeAdapterTable, PaymentAdapterTable
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_contracts.models import Accepted, AuthorityView, CaseRecord, DisputeEvent, PaymentEvent, Unknown
from market_deal_servicing import Classification, EndSession, FinalRequest, SellerSession
from market_deal_servicing.evidence import EvidenceSession, transaction
from market_identity import Identity

from tests.integration.test_payment_settlement import BUYER, SELLER, NEGOTIATION, make


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["payer", "payee", "terms", "authority", "ruling"])
async def test_recorded_end_retains_the_actual_actor(make, source):
    h = await make()
    h.serve()
    await h.settle()
    await h.delivered()
    lifecycle = h.lifecycle
    with transaction(lifecycle.path) as conn:
        deal = SellerSession(conn).read(NEGOTIATION)
    scheme, key = deal.dispute.record_key.split(":", 1)
    authority = Identity(scheme=scheme, identifier=key)
    actors = {
        "payer": (h.data.mandate.from_.root, BUYER.identity),
        "payee": (h.data.mandate.to.root, SELLER.identity),
        "terms": ("terms", SELLER.identity),
        "authority": (deal.dispute.account, authority),
        "ruling": (deal.dispute.account, authority),
    }
    account, expected = actors[source]
    now = lifecycle.clock()
    payment_view = AuthorityView(outcome=Accepted())
    dispute_view = AuthorityView(outcome=Accepted())
    if source == "ruling":
        dispute_view = AuthorityView(outcome=Accepted(), disputes=[DisputeEvent(
            negotiation_id=NEGOTIATION, commitment_ref=deal.commitment_ref,
            case_ref="case", kind="ruled", actor=account, at=now, sequence=1, record_ref="ruling",
            outcome=[{"effect_id": "end", "kind": "delivery_end", "at": now, "applied": True}],
        )])
    else:
        payment_view = AuthorityView(outcome=Accepted(), events=[PaymentEvent(
            negotiation_id=NEGOTIATION, commitment_ref=deal.commitment_ref, part="0",
            kind="stop", actor=account, at=now, cause=source, sequence=1, authority_record_ref="stop",
        )])
    payment = SimpleNamespace(read=AsyncMock(return_value=payment_view))
    dispute = SimpleNamespace(read=AsyncMock(return_value=dispute_view))
    await lifecycle.watch(deal, payment, dispute).poll()
    with transaction(lifecycle.path) as conn:
        recorded = EndSession(conn).view(NEGOTIATION).recorded_end
    assert recorded.actor == expected
    assert recorded.source == ("ruling" if source == "ruling" else "stop")
    assert recorded.cause == source


@pytest.mark.asyncio
async def test_seller_retention_waits_for_complete_financial_case_and_recovery_observations(make):
    h = await make()
    h.serve()
    await h.settle()
    await h.delivered()
    lifecycle = h.lifecycle
    negotiation_id = NEGOTIATION

    agreement = lifecycle.accepted(negotiation_id)[0]
    terms = decode_terms(agreement["settlement"]["lifecycle"])
    clock = [lifecycle.clock()]
    lifecycle.clock = lifecycle.seller.clock = lambda: clock[0]
    payment = SimpleNamespace(data=h.data, read=AsyncMock(return_value=AuthorityView(
        outcome=Accepted(), payouts={"0": None},
    )))
    dispute = SimpleNamespace(read=AsyncMock(return_value=AuthorityView(
        outcome=Accepted(), cases=[CaseRecord(case_ref="case", state="filed", record_ref="filed")],
    )))
    with transaction(lifecycle.path) as conn:
        deal = SellerSession(conn).read(negotiation_id)
        evidence = EvidenceSession(conn)
        evidence.capture(negotiation_id, evidence_id="opening", body=b"{}", headers={}, context={}, recorded_at=clock[0])
        evidence.accept(negotiation_id, message_id="opening", accepted_by=SELLER.identity,
                        expires_at=clock[0] + 60, terms=terms)
        end = EndSession(conn)
        end.record_end(FinalRequest(
            negotiation_id=negotiation_id, source_ref="surrender", ended_at=clock[0], observed_at=clock[0],
            actor=BUYER.identity, cause="buyer_surrender", source="end_delivery",
        ), now=clock[0], classification=Classification(kind="buyer_surrender", evidence_refs=["surrender"]))
    lifecycle.seller.payments = PaymentAdapterTable([(deal.payment, lambda _: payment)])
    lifecycle.seller.disputes = DisputeAdapterTable([(deal.dispute.interface, lambda _: dispute)])
    lifecycle.seller.credential_available = lambda _: True
    assert not await lifecycle.seller.prune(negotiation_id)
    payment.read.return_value = AuthorityView(outcome=Accepted(), payouts={"0": clock[0]})
    assert not await lifecycle.seller.prune(negotiation_id)
    dispute.read.return_value = AuthorityView(
        outcome=Accepted(), cases=[CaseRecord(case_ref="case", state="closed", record_ref="closed")],
        disputes=[DisputeEvent(negotiation_id=negotiation_id, commitment_ref=deal.commitment_ref,
                              case_ref="case", kind="closed", actor=deal.dispute.account,
                              at=clock[0], sequence=1, record_ref="closed")],
    )
    assert not await lifecycle.seller.prune(negotiation_id)
    with transaction(lifecycle.path) as conn:
        EndSession(conn).physical_progress(negotiation_id, "released")
    assert not await lifecycle.seller.prune(negotiation_id)
    clock[0] += terms.adjudication.dispute_window_seconds
    dispute.read.return_value = AuthorityView(outcome=Unknown(reason="authority unavailable"))
    assert not await lifecycle.seller.prune(negotiation_id)
    dispute.read.return_value = AuthorityView(
        outcome=Accepted(), cases=[CaseRecord(case_ref="case", state="closed", record_ref="closed")],
        disputes=[DisputeEvent(negotiation_id=negotiation_id, commitment_ref=deal.commitment_ref,
                              case_ref="case", kind="closed", actor=deal.dispute.account,
                              at=clock[0] - terms.adjudication.dispute_window_seconds,
                              sequence=1, record_ref="closed")],
    )
    lifecycle.seller.credential_available = lambda _: False
    assert not await lifecycle.seller.prune(negotiation_id)
    lifecycle.seller.credential_available = lambda _: True
    assert await lifecycle.seller.prune(negotiation_id)
    assert not (await lifecycle.evidence.read(negotiation_id)).items
