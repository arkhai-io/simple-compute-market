from __future__ import annotations

from market_identity import Ed25519Signer

from core_storefront.models.settle_models import SettleRequest


def test_mechanism_neutral_settlement_request_needs_no_mechanism_fields() -> None:
    buyer = Ed25519Signer(bytes(range(32))).identity

    request = SettleRequest(
        negotiation_id="negotiation-1",
        buyer_principal=buyer,
    )

    assert request.buyer_principal == buyer
    assert set(request.model_dump()) == {"negotiation_id", "buyer_principal"}
