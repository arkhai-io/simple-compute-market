from __future__ import annotations

import json
from unittest.mock import patch

from market_core.buyer import (
    BuyConfig,
    BuyConstraints,
    BuyResult,
    NegotiationResult,
    query_registry_for_matches_multi,
    run_buy,
)


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _config() -> BuyConfig:
    return BuyConfig(
        registry_urls=["http://registry"],
        buyer_address="0xBuyer",
        buyer_private_key="0xKey",
    )


def test_run_buy_returns_no_matches_without_invoking_hooks() -> None:
    with patch(
        "market_core.buyer.orchestrator.urllib.request.urlopen",
        return_value=_FakeResp({"items": []}),
    ):
        result = run_buy(
            config=_config(),
            constraints=BuyConstraints(),
            provision={"duration_seconds": 3600},
            negotiate=lambda _matches, _emit: (_ for _ in ()).throw(AssertionError()),
            settle=lambda _negotiation, _emit: (_ for _ in ()).throw(AssertionError()),
        )

    assert result.status == "no_matches"


def test_run_buy_composes_injected_negotiate_and_settle_hooks() -> None:
    matches = [
        {"listing_id": "L1", "seller": "http://seller"},
        {"listing_id": "L2", "seller": "http://other"},
    ]
    events: list[tuple[str, dict]] = []

    def negotiate(candidate_matches, emit) -> NegotiationResult:
        emit("domain_negotiate", {"count": len(candidate_matches)})
        return NegotiationResult(
            match=candidate_matches[0],
            outcome={"negotiation_id": "N1", "amount": 10},
            attempts=[{"listing_id": "L1", "status": "agreed"}],
        )

    def settle(negotiation, emit) -> BuyResult:
        emit("domain_settle", {"listing_id": negotiation.match["listing_id"]})
        return BuyResult(
            status="ready",
            negotiation_id=negotiation.outcome["negotiation_id"],
            seller_url=negotiation.match["seller"],
            agreed_amount=negotiation.outcome["amount"],
            attempts=negotiation.attempts,
        )

    result = run_buy(
        config=BuyConfig(
            registry_urls=["http://registry"],
            buyer_address="0xBuyer",
            buyer_private_key="0xKey",
            aggregation_policy="domain-policy",
        ),
        constraints=BuyConstraints(max_price=100),
        provision={"duration_seconds": 3600},
        negotiate=negotiate,
        settle=settle,
        matches=matches,
        max_matches_to_try=1,
        on_event=lambda name, body: events.append((name, body)),
    )

    assert result.status == "ready"
    assert result.negotiation_id == "N1"
    assert result.seller_url == "http://seller"
    assert ("aggregated", {"policy": "domain-policy", "match_count_after_cap": 1}) in events
    assert ("domain_negotiate", {"count": 1}) in events
    assert ("domain_settle", {"listing_id": "L1"}) in events


def test_query_registry_for_matches_multi_dedupes_first_seen_listing() -> None:
    responses = iter([
        _FakeResp({"items": [{"listing_id": "L1", "seller": "http://r1"}]}),
        _FakeResp({"items": [
            {"listing_id": "L1", "seller": "http://r2"},
            {"listing_id": "L2", "seller": "http://r2"},
        ]}),
    ])

    with patch(
        "market_core.buyer.orchestrator.urllib.request.urlopen",
        side_effect=lambda *_args, **_kwargs: next(responses),
    ):
        result = query_registry_for_matches_multi(["http://r1", "http://r2"])

    assert result == [
        {"listing_id": "L1", "seller": "http://r1"},
        {"listing_id": "L2", "seller": "http://r2"},
    ]
