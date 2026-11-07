from core_storefront.models.negotiation_models import (
    NegotiateContinueResponse,
    NegotiateNewResponse,
)
from market_identity import Ed25519Signer


def test_negotiation_responses_carry_opaque_settlement_data() -> None:
    buyer = Ed25519Signer(bytes([1]) * 32).identity
    seller = Ed25519Signer(bytes([2]) * 32).identity
    settlement_data = {"mandate": {"transaction_id": "opaque"}}
    parties = {
        "buyer_principal": buyer,
        "seller_principal": seller,
        "settlement_data": settlement_data,
    }

    new_response = NegotiateNewResponse(
        negotiation_id="neg-1",
        action="accept",
        **parties,
    )
    continue_response = NegotiateContinueResponse(
        action="accept",
        **parties,
    )

    assert new_response.model_dump(mode="json")["settlement_data"] == settlement_data
    assert (
        continue_response.model_dump(mode="json")["settlement_data"]
        == settlement_data
    )
