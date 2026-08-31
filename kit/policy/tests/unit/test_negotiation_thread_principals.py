from __future__ import annotations

from typing import Any

import pytest
from market_identity import Identity
from market_policy.identity import Identity as LocalIdentity
from market_policy.negotiation_thread import NegotiationThreadStore


class RecordingPersistence:
    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None
        self.message: dict[str, Any] | None = None

    async def create_negotiation_thread(self, **values: Any) -> None:
        self.created = values

    async def save_negotiation_message(self, **values: Any) -> int:
        self.message = values
        return 0


@pytest.mark.asyncio
async def test_thread_store_preserves_exact_principals_and_sender_role() -> None:
    persistence = RecordingPersistence()
    store = NegotiationThreadStore(
        persistence,  # type: ignore[arg-type]
        LocalIdentity(agent_url="https://seller.example"),
    )
    buyer = Identity(scheme="eip191", identifier="0x" + "11" * 20)
    seller = Identity(scheme="eip191", identifier="0x" + "22" * 20)

    await store.create_thread(
        negotiation_id="neg-1",
        our_listing_id="listing-1",
        their_listing_id="offer-1",
        our_agent_id="https://seller.example",
        their_agent_id="https://buyer.example",
        buyer_principal=buyer,
        seller_principal=seller,
        owner_id="https://seller.example",
    )
    await store.add_message(
        negotiation_id="neg-1",
        sender_principal=buyer,
        sender_role="buyer",
        our_price=10,
        their_price=9,
        proposed_price=9,
        action_taken="make_offer",
    )

    assert persistence.created is not None
    assert persistence.created["buyer_principal"] == buyer
    assert persistence.created["seller_principal"] == seller
    assert persistence.message is not None
    assert persistence.message["sender_principal"] == buyer
    assert persistence.message["sender_role"] == "buyer"
    assert "sender" not in persistence.message
