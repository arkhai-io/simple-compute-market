from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from market_alkahest.aggregation import (
    best_price,
    cheapest_first,
    extract_advertised_scalar_price,
    priceless_last,
)


@dataclass
class Outcome:
    status: str
    agreed_amount: int | None = None


def _match(listing_id: str, *, price: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "chain_name": "anvil",
        "escrow_address": "0xE",
        "literal_fields": {"token": "0xT"},
        "rates": [],
    }
    if price is not None:
        entry["rates"] = [
            {"field": "amount", "per": "hour", "value": str(price)}
        ]
    return {"listing_id": listing_id, "accepted_escrows": [entry]}


@pytest.mark.asyncio
async def test_cheapest_first_uses_alkahest_advertised_scalar_rate():
    seen: list[str] = []

    async def negotiate(candidate: dict[str, Any]) -> Outcome:
        seen.append(candidate["listing_id"])
        return Outcome(status="exited")

    await cheapest_first(
        [_match("expensive", price=300), _match("cheap", price=100)],
        negotiate,
    )

    assert seen == ["cheap", "expensive"]


@pytest.mark.asyncio
async def test_priceless_last_orders_hidden_reserve_after_priced():
    seen: list[str] = []

    async def negotiate(candidate: dict[str, Any]) -> Outcome:
        seen.append(candidate["listing_id"])
        return Outcome(status="exited")

    await priceless_last(
        [_match("hidden"), _match("priced", price=100)],
        negotiate,
    )

    assert seen == ["priced", "hidden"]


@pytest.mark.asyncio
async def test_best_price_picks_lowest_agreed_amount():
    async def negotiate(candidate: dict[str, Any]) -> Outcome:
        return Outcome(status="agreed", agreed_amount=candidate["agreed"])

    result = await best_price(
        [
            {"listing_id": "a", "agreed": 200},
            {"listing_id": "b", "agreed": 100},
        ],
        negotiate,
    )

    assert result is not None
    winner, outcome = result
    assert winner["listing_id"] == "b"
    assert outcome.agreed_amount == 100


def test_extract_advertised_scalar_price_reads_first_accepted_escrow():
    assert extract_advertised_scalar_price(_match("priced", price=123)) == 123
    assert extract_advertised_scalar_price(_match("hidden")) is None
