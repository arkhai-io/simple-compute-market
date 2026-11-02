"""Bare-metal authority observation retains its actor in the durable end."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle_contracts.models import Accepted, AuthorityView, DisputeEvent, PaymentEvent
from market_deal_servicing import EndSession, SellerSession
from market_deal_servicing.evidence import transaction
from market_identity import Identity

from integration.test_payment_settlement_client import BUYER, SELLER, harness, enabled


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["payer", "payee", "terms", "authority", "ruling"])
async def test_recorded_end_retains_the_actual_actor(harness, source):
    h = harness
    h.serve()
    await h.settle()
    lifecycle = h.runtime.lifecycle
    negotiation_id = h.negotiation_id
    with transaction(lifecycle.path) as conn:
        deal = SellerSession(conn).read(negotiation_id)
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
            negotiation_id=negotiation_id, commitment_ref=deal.commitment_ref,
            case_ref="case", kind="ruled", actor=account, at=now, sequence=1, record_ref="ruling",
            outcome=[{"effect_id": "end", "kind": "delivery_end", "at": now, "applied": True}],
        )])
    else:
        payment_view = AuthorityView(outcome=Accepted(), events=[PaymentEvent(
            negotiation_id=negotiation_id, commitment_ref=deal.commitment_ref, part="0",
            kind="stop", actor=account, at=now, cause=source, sequence=1, authority_record_ref="stop",
        )])
    payment = SimpleNamespace(data=h.data, read=AsyncMock(return_value=payment_view))
    dispute = SimpleNamespace(read=AsyncMock(return_value=dispute_view))
    await lifecycle.watch(deal, payment, dispute).poll()
    with transaction(lifecycle.path) as conn:
        recorded = EndSession(conn).view(negotiation_id).recorded_end
    assert recorded.actor == expected
    assert recorded.source == ("ruling" if source == "ruling" else "stop")
    assert recorded.cause == source
