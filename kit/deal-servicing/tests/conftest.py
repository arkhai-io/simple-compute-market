from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle.adapters import (
    DisputeAdapterTable, PaymentAdapterTable, PaymentSelector, OnceAccountingProjection, OnceAccountingRead,
)
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import Accepted, AuthorityView, PaymentEvent, PaymentPartObservation
from market_identity import Ed25519Signer

from market_deal_servicing import (
    DealWatch, DeliveryRecord, EndService, EndSession, SellerDeal, SellerServicing, SellerSession,
    create_page_position, create_payment_observations, create_schema,
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
        # The storefront chain's migrations, which a session does not run.
        create_schema(conn)
        create_payment_observations(conn)
        create_page_position(conn)
        EndSession(conn).register(DeliveryRecord(
            negotiation_id="deal", commitment_ref="commitment", seller=seller.identity,
            start_at=100, term_end=1000, committed_at=100, delivery_deadline_seconds=500,
        ))
        SellerSession(conn).register(deal)
    payment, dispute = AsyncMock(), AsyncMock()
    payment.read.return_value = AuthorityView(outcome=Accepted(), state="running")
    dispute.read.return_value = AuthorityView(outcome=Accepted())
    credentials = [True]

    def watch(deal=deal, payment=payment, dispute=dispute, **options):
        return DealWatch(
            path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
            payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
            seller_account="seller-account", actor=lambda _: authority_signer.identity, clock=lambda: clock[0],
            **options,
        )

    def service():
        return SellerServicing(
            path, payments=PaymentAdapterTable([(deal.payment, lambda _: payment)]),
            disputes=DisputeAdapterTable([(authority.interface, lambda _: dispute)]),
            credential_available=lambda _: credentials[0], watch_factory=watch, clock=lambda: clock[0],
        )

    return locals()


@pytest.fixture
def once_accounting(rig):
    """Neutral opt-in adapter fixture; it asserts no payment signature authority."""
    stop = PaymentEvent(
        negotiation_id="deal", commitment_ref="commitment", part="0", kind="stop",
        actor="fixture-payer", at=140, cause="payer", sequence=1,
        authority_record_ref="fixture-stop", settles_through="started_period",
    )
    view = AuthorityView(outcome=Accepted(), state="ended", events=[stop], parts=[
        PaymentPartObservation(part="0", started_at=100, final_stop=stop,
                               evidence_ref="fixture-payment-observation"),
    ])
    projection = OnceAccountingProjection(
        negotiation_id="deal", commitment_ref="commitment", seller_account="seller-account",
        minimum_sequence=0, latest_event_sequence=1, provider_observed_at=150,
        verified_signature_sha256="a" * 64, financial_facts_sha256="b" * 64,
        part_count=1, livemode=False, all_parts_terminal=True,
        accounting={"classification": "ACCOUNTING_TERMINAL", "returnAdmitted": False},
    )

    class Payment:
        async def read(self):
            return view

        async def read_with_once_accounting(self, *, minimum_sequence, read_started_at):
            return OnceAccountingRead(view, self.projection)

    payment = Payment()
    payment.projection = projection
    payment.read = AsyncMock(wraps=payment.read)
    payment.read_with_once_accounting = AsyncMock(wraps=payment.read_with_once_accounting)
    watch = rig["watch"](payment=payment)
    return payment, watch
