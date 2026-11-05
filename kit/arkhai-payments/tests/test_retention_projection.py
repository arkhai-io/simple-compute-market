"""Verified once-part completion is exposed without forecasting release times."""

import asyncio

from market_arkhai_payments.adapter import PaymentAdapter, pinned_snapshot_verifier
from market_arkhai_payments.agreement import PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_deal_lifecycle_contracts.models import Accepted

from payment_terms import SERVICE, agreement, config


def test_retention_projection_requires_observed_completion_of_every_part():
    terms, settings = agreement(), config()
    data = PaymentSettlementData.for_agreement(terms, settings)
    peer = FakePaymentsClient(signer=SERVICE)
    receipt = peer.approve(data.mandate)
    peer.observed_at = receipt.receipt.approvedAt
    adapter = PaymentAdapter(
        terms, data, account=data.mandate.to.root, client_for_owner=peer,
        verify_snapshot=pinned_snapshot_verifier(terms, data, settings),
    )
    held = asyncio.run(adapter.read())
    assert isinstance(held.outcome, Accepted) and held.payouts == {"0": None}
    peer.observed_at += 8 * 86400
    released = asyncio.run(adapter.read())
    assert isinstance(released.outcome, Accepted) and released.payouts == {"0": peer.observed_at}
    peer.unavailable = True
    unavailable = asyncio.run(adapter.read())
    assert not isinstance(unavailable.outcome, Accepted) and unavailable.payouts is None
