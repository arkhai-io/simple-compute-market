"""Tests for filter-aware discovery + auto/interactive price derivation
on `market buy`.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any
from unittest import mock

import pytest

from market_buyer.buy_orchestrator import (
    BuyConfig,
    BuyConstraints,
    extract_seller_min_price,
    query_registry_for_matches,
    run_buy,
)


# ---------------------------------------------------------------------------
# extract_seller_min_price
# ---------------------------------------------------------------------------


class TestExtractSellerMinPrice:
    def test_dict_demand_with_amount(self):
        listing = {"demand_resource": {"amount": 1500, "token": "USDC"}}
        assert extract_seller_min_price(listing) == 1500

    def test_string_json_demand(self):
        listing = {"demand_resource": json.dumps({"amount": 9000, "token": "MOCK"})}
        assert extract_seller_min_price(listing) == 9000

    def test_missing_amount_returns_none(self):
        listing = {"demand_resource": {"token": "USDC"}}
        assert extract_seller_min_price(listing) is None

    def test_unparseable_amount_returns_none(self):
        listing = {"demand_resource": {"amount": "not-a-number"}}
        assert extract_seller_min_price(listing) is None

    def test_missing_demand_resource_returns_none(self):
        assert extract_seller_min_price({}) is None


# ---------------------------------------------------------------------------
# query_registry_for_matches with filters
# ---------------------------------------------------------------------------


class TestQueryRegistryFilters:
    def _patch_urlopen(self, monkeypatch, body=b'{"items":[]}'):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            return mock.MagicMock(
                __enter__=lambda self: mock.MagicMock(read=lambda: body),
                __exit__=lambda *a: False,
            )

        monkeypatch.setattr("market_buyer.buy_orchestrator.urllib.request.urlopen", fake_urlopen)
        return captured

    def test_no_filters_sends_only_status(self, monkeypatch):
        captured = self._patch_urlopen(monkeypatch)
        query_registry_for_matches("http://reg")
        parsed = urllib.parse.urlparse(captured["url"])
        params = urllib.parse.parse_qs(parsed.query)
        assert params == {"status": ["open"]}

    def test_filters_serialized_as_query_params(self, monkeypatch):
        captured = self._patch_urlopen(monkeypatch)
        query_registry_for_matches(
            "http://reg",
            filters={
                "gpu_model": "H200",
                "gpu_count_min": 4,
                "datacenter_grade": True,
                "static_ip": False,
                "region": None,  # dropped
            },
        )
        params = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)
        assert params["gpu_model"] == ["H200"]
        assert params["gpu_count_min"] == ["4"]
        assert params["datacenter_grade"] == ["true"]
        assert params["static_ip"] == ["false"]
        assert "region" not in params  # None filtered out

    def test_returns_items_list(self, monkeypatch):
        items = [{"listing_id": "a"}, {"listing_id": "b"}]
        body = json.dumps({"items": items}).encode("utf-8")
        self._patch_urlopen(monkeypatch, body=body)
        result = query_registry_for_matches("http://reg")
        assert result == items


# ---------------------------------------------------------------------------
# run_buy with derive_prices callback
# ---------------------------------------------------------------------------


class TestRunBuyDerivePrices:
    def test_derive_prices_overrides_constants(self, monkeypatch):
        """When derive_prices is supplied, BuyConstraints prices are ignored."""
        seen_prices: list[tuple[int, int]] = []

        def fake_negotiate(**kwargs):
            seen_prices.append((kwargs["initial_price"], kwargs["max_price"]))
            from market_buyer.buyer_client import NegotiationOutcome
            return NegotiationOutcome(
                status="exited", agreed_price=None, rounds=1, reason="exited",
                negotiation_id="neg-1", duration_seconds=3600,
            )

        monkeypatch.setattr(
            "market_buyer.buy_orchestrator.negotiate_with_seller",
            fake_negotiate,
        )
        monkeypatch.setattr(
            "market_buyer.buy_orchestrator._resolve_seller_wallet",
            lambda url, timeout=5.0: "0x" + "0" * 40,
        )

        constraints = BuyConstraints(duration_seconds=3600)  # prices None
        config = BuyConfig(
            registry_url="http://reg",
            buyer_address="0x" + "1" * 40,
            buyer_private_key="0x" + "2" * 64,
            ssh_public_key="ssh-ed25519 AAAA",
        )
        matches = [
            {"listing_id": "L1", "seller": "http://s1", "demand_resource": {"amount": 100}},
            {"listing_id": "L2", "seller": "http://s2", "demand_resource": {"amount": 200}},
        ]

        def derive(match):
            base = extract_seller_min_price(match)
            return base, base * 2

        result = run_buy(
            config=config, constraints=constraints,
            create_escrow=lambda terms: pytest.fail("escrow shouldn't run on exited"),
            matches=matches, max_matches_to_try=2,
            derive_prices=derive,
        )

        assert seen_prices == [(100, 200), (200, 400)]
        assert result.status == "exited"

    def test_no_derive_prices_and_missing_constants_records_error(self, monkeypatch):
        """Missing prices + no derive callback → per-listing error, no negotiation."""
        called = {"negotiate": False}

        def fake_negotiate(**kwargs):
            called["negotiate"] = True
            from market_buyer.buyer_client import NegotiationOutcome
            return NegotiationOutcome(status="exited", rounds=0)

        monkeypatch.setattr(
            "market_buyer.buy_orchestrator.negotiate_with_seller", fake_negotiate,
        )

        constraints = BuyConstraints(duration_seconds=3600)
        config = BuyConfig(
            registry_url="http://reg",
            buyer_address="0x" + "1" * 40,
            buyer_private_key="0x" + "2" * 64,
            ssh_public_key="ssh-ed25519 AAAA",
        )
        matches = [{"listing_id": "L1", "seller": "http://s1"}]
        result = run_buy(
            config=config, constraints=constraints,
            create_escrow=lambda terms: pytest.fail("never"),
            matches=matches, max_matches_to_try=1,
        )
        assert called["negotiate"] is False
        assert result.status == "exited"
        assert any(
            "BuyConstraints.initial_price and max_price are None" in (a.get("error") or "")
            for a in result.attempts
        )


# ---------------------------------------------------------------------------
# run_buy with confirm_settlement gate
# ---------------------------------------------------------------------------


def _agree_negotiate_factory(price: int = 100):
    """Build a fake negotiate_with_seller that always agrees at the given price."""
    def fake(**kwargs):
        from market_buyer.buyer_client import NegotiationOutcome
        return NegotiationOutcome(
            status="agreed", agreed_price=price, rounds=2, reason=None,
            negotiation_id="neg-id", duration_seconds=kwargs.get("duration_seconds"),
        )
    return fake


class TestConfirmSettlementGate:
    def _setup_orchestrator(self, monkeypatch, agree_price: int = 100):
        monkeypatch.setattr(
            "market_buyer.buy_orchestrator.negotiate_with_seller",
            _agree_negotiate_factory(agree_price),
        )
        monkeypatch.setattr(
            "market_buyer.buy_orchestrator._resolve_seller_wallet",
            lambda url, timeout=5.0: "0x" + "f" * 40,
        )

    def _config(self):
        return BuyConfig(
            registry_url="http://reg",
            buyer_address="0x" + "1" * 40,
            buyer_private_key="0x" + "2" * 64,
            ssh_public_key="ssh-ed25519 AAAA",
        )

    def _constraints(self):
        return BuyConstraints(duration_seconds=3600, initial_price=50, max_price=200)

    def test_confirm_returning_false_aborts_before_escrow(self, monkeypatch):
        """User decline keeps the on-chain side completely untouched."""
        self._setup_orchestrator(monkeypatch)
        events: list[tuple[str, dict]] = []
        matches = [{"listing_id": "L1", "seller": "http://s1"}]

        result = run_buy(
            config=self._config(),
            constraints=self._constraints(),
            create_escrow=lambda terms: pytest.fail("escrow MUST NOT run when declined"),
            matches=matches, max_matches_to_try=1,
            on_event=lambda stage, body: events.append((stage, body)),
            confirm_settlement=lambda terms, listing: False,
        )

        assert result.status == "exited"
        assert result.reason == "user_declined"
        assert result.agreed_price == 100
        # Settlement-decline event was emitted; escrow_create_start was NOT.
        stages = [s for s, _ in events]
        assert "settlement_declined" in stages
        assert "escrow_create_start" not in stages

    def test_confirm_returning_true_proceeds_to_escrow(self, monkeypatch):
        """User approval lets the rest of the pipeline run."""
        self._setup_orchestrator(monkeypatch)
        escrow_calls: list[Any] = []

        def fake_create(terms):
            escrow_calls.append(terms)
            return "escrow-uid-1"

        # Settlement submit + poll need stubbing too — short-circuit to "ready".
        monkeypatch.setattr(
            "market_buyer.buy_orchestrator.submit_settlement",
            lambda **kw: {"status": "queued"},
        )
        monkeypatch.setattr(
            "market_buyer.buy_orchestrator.wait_for_settlement",
            lambda **kw: {"status": "ready", "result": {"connection_details": "ssh ..."}},
        )

        matches = [{"listing_id": "L1", "seller": "http://s1"}]
        result = run_buy(
            config=self._config(),
            constraints=self._constraints(),
            create_escrow=fake_create,
            matches=matches, max_matches_to_try=1,
            confirm_settlement=lambda terms, listing: True,
        )

        assert len(escrow_calls) == 1, "escrow ran exactly once after approval"
        assert result.status == "ready"
        assert result.escrow_uid == "escrow-uid-1"

    def test_no_callback_skips_gate(self, monkeypatch):
        """Default behavior (no callback) doesn't add a confirmation step."""
        self._setup_orchestrator(monkeypatch)
        monkeypatch.setattr(
            "market_buyer.buy_orchestrator.submit_settlement",
            lambda **kw: {"status": "queued"},
        )
        monkeypatch.setattr(
            "market_buyer.buy_orchestrator.wait_for_settlement",
            lambda **kw: {"status": "ready", "result": {}},
        )
        escrow_count = {"n": 0}

        def fake_create(terms):
            escrow_count["n"] += 1
            return "uid"

        matches = [{"listing_id": "L1", "seller": "http://s1"}]
        result = run_buy(
            config=self._config(),
            constraints=self._constraints(),
            create_escrow=fake_create,
            matches=matches, max_matches_to_try=1,
        )
        assert escrow_count["n"] == 1
        assert result.status == "ready"

    def test_confirm_callback_raising_aborts_safely(self, monkeypatch):
        """Exceptions in the confirm callback don't reach the chain."""
        self._setup_orchestrator(monkeypatch)
        matches = [{"listing_id": "L1", "seller": "http://s1"}]

        def boom(terms, listing):
            raise RuntimeError("user pressed ctrl-c")

        result = run_buy(
            config=self._config(),
            constraints=self._constraints(),
            create_escrow=lambda terms: pytest.fail("never"),
            matches=matches, max_matches_to_try=1,
            confirm_settlement=boom,
        )
        assert result.status == "exited"
        assert "confirm_settlement_callback_raised" in (result.reason or "")
