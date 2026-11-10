from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle.adapters import DisputeAdapterTable, PaymentAdapterTable, PaymentSelector
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import Accepted, AuthorityView
from market_identity import Ed25519Signer

from market_deal_servicing import (
    DealWatch, DeliveryRecord, EndService, EndSession, SellerDeal, SellerServicing, SellerSession,
    create_schema,
)
from market_deal_servicing.evidence import transaction


@pytest.fixture
def rig(tmp_path):
    # Public deterministic development seeds; never use on a public network.
    buyer, seller, authority_signer = (Ed25519Signer(bytes([n]) * 32) for n in (1, 2, 3))
    authority = DisputeAuthority.model_validate({
        "interface": "fixture.dispute.v1", "origin": "https://dispute.example",
        "account": "authority", "record_key": "ed25519:" + authority_signer.identity.identifier, "params": {},
    })
    path = tmp_path / "storefront.sqlite"
    clock = [150]
    physical = AsyncMock()
    end = EndService(path, physical, clock=lambda: clock[0])
    deal = SellerDeal(
        negotiation_id="deal", commitment_ref="commitment", domain="fixture",
        buyer=buyer.identity, payment=PaymentSelector("fixture.payment.v1"), dispute=authority, once_only=True,
    )
    with transaction(path) as conn:
        # The storefront chain's migration, which a session does not run.
        create_schema(conn)
        EndSession(conn).register(DeliveryRecord(
            negotiation_id="deal", commitment_ref="commitment", seller=seller.identity,
            start_at=100, term_end=1000, committed_at=100, delivery_deadline_seconds=500,
        ))
        SellerSession(conn).register(deal)
    payment, dispute = AsyncMock(), AsyncMock()
    payment.read.return_value = AuthorityView(outcome=Accepted(), state="running")
    dispute.read.return_value = AuthorityView(outcome=Accepted())
    credentials = [True]

    def watch(deal=deal, payment=payment, dispute=dispute):
        return DealWatch(
            path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
            payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
            seller_account="seller-account", actor=lambda _: authority_signer.identity, clock=lambda: clock[0],
        )

    def service():
        return SellerServicing(
            path, payments=PaymentAdapterTable([(deal.payment, lambda _: payment)]),
            disputes=DisputeAdapterTable([(authority.interface, lambda _: dispute)]),
            credential_available=lambda _: credentials[0], watch_factory=watch, clock=lambda: clock[0],
        )

    return locals()
