from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any
import sys

import pytest

from market_alkahest.aggregation import (
    best_price,
    best_price_from_config,
    cheapest_first,
    extract_advertised_scalar_price,
    priceless_last,
    resolve_best_price_timeout,
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


def test_resolve_best_price_timeout_from_config(monkeypatch):
    package = ModuleType("market_config")
    config_loader = ModuleType("market_config.config_loader")
    config_loader.load_user_config = lambda: {  # type: ignore[attr-defined]
        "aggregation": {"best_price_timeout": "0.25"}
    }
    config_loader.get_dotted = (  # type: ignore[attr-defined]
        lambda cfg, key: cfg["aggregation"]["best_price_timeout"]
    )
    package.config_loader = config_loader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "market_config", package)
    monkeypatch.setitem(sys.modules, "market_config.config_loader", config_loader)

    assert resolve_best_price_timeout() == 0.25


@pytest.mark.asyncio
async def test_best_price_from_config_applies_timeout(monkeypatch):
    monkeypatch.setattr(
        "market_alkahest.aggregation.resolve_best_price_timeout",
        lambda: 0.01,
    )

    async def negotiate(candidate: dict[str, Any]) -> Outcome:
        if candidate["listing_id"] == "slow":
            import asyncio

            await asyncio.sleep(0.1)
            return Outcome(status="agreed", agreed_amount=1)
        return Outcome(status="agreed", agreed_amount=2)

    result = await best_price_from_config(
        [{"listing_id": "slow"}, {"listing_id": "fast"}],
        negotiate,
    )

    assert result is not None
    winner, outcome = result
    assert winner["listing_id"] == "fast"
    assert outcome.agreed_amount == 2
