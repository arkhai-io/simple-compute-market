"""Tests for filter-aware discovery + auto/interactive price derivation
on `market buy`.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any
from unittest import mock

import pytest
import typer

from market_core.schemas import EscrowProposal, EscrowTerms
from arkhai_vms_common import VmProvisionTerms, make_vm_provision_terms
from domains.vms.buyer.buy_orchestrator import (
    BuyConfig,
    BuyConstraints,
    extract_seller_min_price,
    make_legacy_negotiate_hook,
    make_legacy_settle_hook,
    query_registry_for_matches,
    run_buy,
)
from domains.vms.buyer.cli_helpers import parse_filter_options


def _escrow_proposal() -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "cd" * 20,
        fields={"token": "0x" + "ab" * 20},
        demands=[{
            "chain_name": "anvil",
            "arbiter": "0x" + "cd" * 20,
            "demand_data": {"recipient": "0x" + "f" * 40},
        }],
        expiration_unix=1_800_000_000,
    )


def _build_escrow_proposal():
    return lambda _match: _escrow_proposal()


def _stub_build_escrow_terms(proposal, seller_wallet, agreed_amount, duration_seconds):
    return [EscrowTerms(
        maker="buyer",
        escrow_contract="0x" + "ee" * 20,
        obligation_data={
            "arbiter": "0x" + "cd" * 20,
            "demand": "0x" + "00" * 32,
            "token": proposal.fields["token"],
            "amount": int(float(agreed_amount) * max(duration_seconds, 1) / 3600),
        },
        expiration_unix=proposal.expiration_unix,
    )]


def _fail_build_escrow_terms(*_a, **_kw):
    pytest.fail("build_escrow_terms shouldn't run")


def _run_buy_with_legacy_hooks(
    *,
    config,
    constraints,
    provision,
    build_escrow_proposal,
    build_escrow_terms,
    create_escrow,
    matches=None,
    max_matches_to_try=5,
    max_negotiation_rounds=10,
    settlement_poll_interval=0,
    settlement_total_timeout=600,
    on_event=None,
    sleep=lambda _s: None,
    derive_prices=None,
    confirm_settlement=None,
    chain=None,
):
    negotiate = make_legacy_negotiate_hook(
        config=config,
        constraints=constraints,
        provision=provision,
        build_escrow_proposal=build_escrow_proposal,
        max_negotiation_rounds=max_negotiation_rounds,
        derive_prices=derive_prices,
        chain=chain,
    )
    settle = make_legacy_settle_hook(
        config=config,
        provision=provision,
        build_escrow_terms=build_escrow_terms,
        create_escrow=create_escrow,
        confirm_settlement=confirm_settlement,
        settlement_poll_interval=settlement_poll_interval,
        settlement_total_timeout=settlement_total_timeout,
        sleep=sleep,
    )
    return run_buy(
        config=config,
        constraints=constraints,
        provision=provision,
        negotiate=negotiate,
        settle=settle,
        matches=matches,
        max_matches_to_try=max_matches_to_try,
        on_event=on_event,
    )


# ---------------------------------------------------------------------------
# extract_seller_min_price
# ---------------------------------------------------------------------------


class TestExtractSellerMinPrice:
    def test_list_with_rate(self):
        listing = {"accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0xE",
                                          "rates": [{"field": "amount", "per": "hour", "value": "1500"}]}]}
        assert extract_seller_min_price(listing) == 1500

    def test_string_json_list(self):
        listing = {"accepted_escrows": json.dumps([{"chain_name": "anvil", "escrow_address": "0xE",
                                                     "rates": [{"field": "amount", "per": "hour", "value": "9000"}]}])}
        assert extract_seller_min_price(listing) == 9000

    def test_missing_rate_returns_none(self):
        listing = {"accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0xE"}]}
        assert extract_seller_min_price(listing) is None

    def test_unparseable_rate_returns_none(self):
        listing = {"accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0xE",
                                          "rates": [{"field": "amount", "per": "hour", "value": "not-a-number"}]}]}
        assert extract_seller_min_price(listing) is None

    def test_empty_accepted_escrows_returns_none(self):
        assert extract_seller_min_price({}) is None
        assert extract_seller_min_price({"accepted_escrows": []}) is None


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

        monkeypatch.setattr("core_buyer.orchestration.urllib.request.urlopen", fake_urlopen)
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


def test_parse_filter_options_accepts_repeatable_key_value_pairs():
    assert parse_filter_options(["gpu_model=H200", "custom_axis=in:[a,b]"]) == {
        "gpu_model": "H200",
        "custom_axis": "in:[a,b]",
    }


def test_parse_filter_options_rejects_malformed_value():
    with pytest.raises(typer.Exit):
        parse_filter_options(["gpu_model"])


# ---------------------------------------------------------------------------
# run_buy with derive_prices callback
# ---------------------------------------------------------------------------


class TestRunBuyDerivePrices:
    def test_derive_prices_overrides_constants(self, monkeypatch):
        """When derive_prices is supplied, BuyConstraints prices are ignored."""
        seen_prices: list[tuple[int, int]] = []

        def fake_negotiate(**kwargs):
            seen_prices.append((kwargs["initial_price"], kwargs["max_price"]))
            from domains.vms.buyer.buyer_client import NegotiationOutcome
            return NegotiationOutcome(
                status="exited", agreed_amount=None, rounds=1, reason="exited",
                negotiation_id="neg-1", duration_seconds=3600,
            )

        monkeypatch.setattr(
            "core_buyer.orchestration.negotiate_with_seller",
            fake_negotiate,
        )

        constraints = BuyConstraints()  # prices None
        provision = make_vm_provision_terms(duration_seconds=3600, ssh_public_key="ssh-ed25519 AAAA")
        config = BuyConfig(
            registry_urls=["http://reg"],
            buyer_address="0x" + "1" * 40,
            buyer_private_key="0x" + "2" * 64,
        )
        matches = [
            {"listing_id": "L1", "seller": "http://s1",
             "accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0xE",
                                    "rates": [{"field": "amount", "per": "hour", "value": "100"}]}]},
            {"listing_id": "L2", "seller": "http://s2",
             "accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0xE",
                                    "rates": [{"field": "amount", "per": "hour", "value": "200"}]}]},
        ]

        def derive(match):
            base = extract_seller_min_price(match)
            return base, base * 2

        result = _run_buy_with_legacy_hooks(
            config=config, constraints=constraints, provision=provision,
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_fail_build_escrow_terms,
            create_escrow=lambda escrows: pytest.fail("escrow shouldn't run on exited"),
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
            from domains.vms.buyer.buyer_client import NegotiationOutcome
            return NegotiationOutcome(status="exited", rounds=0)

        monkeypatch.setattr(
            "core_buyer.orchestration.negotiate_with_seller", fake_negotiate,
        )

        constraints = BuyConstraints()
        provision = make_vm_provision_terms(duration_seconds=3600, ssh_public_key="ssh-ed25519 AAAA")
        config = BuyConfig(
            registry_urls=["http://reg"],
            buyer_address="0x" + "1" * 40,
            buyer_private_key="0x" + "2" * 64,
        )
        matches = [{"listing_id": "L1", "seller": "http://s1"}]
        result = _run_buy_with_legacy_hooks(
            config=config, constraints=constraints, provision=provision,
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_fail_build_escrow_terms,
            create_escrow=lambda escrows: pytest.fail("never"),
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
        from domains.vms.buyer.buyer_client import NegotiationOutcome
        provision_terms = kwargs.get("provision_terms")
        escrow_proposal = kwargs.get("escrow_proposal")
        return NegotiationOutcome(
            status="agreed", agreed_amount=price, rounds=2, reason=None,
            negotiation_id="neg-id",
            duration_seconds=(
                provision_terms.duration_seconds if provision_terms is not None else None
            ),
            accepted_provision_terms=provision_terms,
            accepted_escrow_proposal=escrow_proposal,
        )
    return fake


class TestConfirmSettlementGate:
    def _setup_orchestrator(self, monkeypatch, agree_price: int = 100):
        monkeypatch.setattr(
            "core_buyer.orchestration.negotiate_with_seller",
            _agree_negotiate_factory(agree_price),
        )

    def _config(self):
        return BuyConfig(
            registry_urls=["http://reg"],
            buyer_address="0x" + "1" * 40,
            buyer_private_key="0x" + "2" * 64,
        )

    def _constraints(self):
        return BuyConstraints(initial_price=50, max_price=200)

    def _provision(self):
        return make_vm_provision_terms(duration_seconds=3600, ssh_public_key="ssh-ed25519 AAAA")

    def test_confirm_returning_false_aborts_before_escrow(self, monkeypatch):
        """User decline keeps the on-chain side completely untouched."""
        self._setup_orchestrator(monkeypatch)
        events: list[tuple[str, dict]] = []
        matches = [{"listing_id": "L1", "seller": "http://s1"}]

        result = _run_buy_with_legacy_hooks(
            config=self._config(),
            constraints=self._constraints(),
            provision=self._provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_fail_build_escrow_terms,
            create_escrow=lambda escrows: pytest.fail("escrow MUST NOT run when declined"),
            matches=matches, max_matches_to_try=1,
            on_event=lambda stage, body: events.append((stage, body)),
            confirm_settlement=lambda terms, listing: False,
        )

        assert result.status == "exited"
        assert result.reason == "user_declined"
        assert result.agreed_amount == 100
        # Settlement-decline event was emitted; escrow_create_start was NOT.
        stages = [s for s, _ in events]
        assert "settlement_declined" in stages
        assert "escrow_create_start" not in stages

    def test_confirm_returning_true_proceeds_to_escrow(self, monkeypatch):
        """User approval lets the rest of the pipeline run."""
        self._setup_orchestrator(monkeypatch)
        escrow_calls: list[Any] = []

        def fake_create(escrows):
            escrow_calls.append(escrows)
            return ["escrow-uid-1"]

        # Settlement submit + poll need stubbing too — short-circuit to "ready".
        monkeypatch.setattr(
            "core_buyer.orchestration.submit_settlement",
            lambda **kw: {"status": "queued"},
        )
        monkeypatch.setattr(
            "core_buyer.orchestration.wait_for_settlement",
            lambda **kw: {"status": "ready", "result": {"connection_details": "ssh ..."}},
        )

        matches = [{"listing_id": "L1", "seller": "http://s1"}]
        result = _run_buy_with_legacy_hooks(
            config=self._config(),
            constraints=self._constraints(),
            provision=self._provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_stub_build_escrow_terms,
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
            "core_buyer.orchestration.submit_settlement",
            lambda **kw: {"status": "queued"},
        )
        monkeypatch.setattr(
            "core_buyer.orchestration.wait_for_settlement",
            lambda **kw: {"status": "ready", "result": {}},
        )
        escrow_count = {"n": 0}

        def fake_create(escrows):
            escrow_count["n"] += 1
            return ["uid"]

        matches = [{"listing_id": "L1", "seller": "http://s1"}]
        result = _run_buy_with_legacy_hooks(
            config=self._config(),
            constraints=self._constraints(),
            provision=self._provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_stub_build_escrow_terms,
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

        result = _run_buy_with_legacy_hooks(
            config=self._config(),
            constraints=self._constraints(),
            provision=self._provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_fail_build_escrow_terms,
            create_escrow=lambda escrows: pytest.fail("never"),
            matches=matches, max_matches_to_try=1,
            confirm_settlement=boom,
        )
        assert result.status == "exited"
        assert "confirm_settlement_callback_raised" in (result.reason or "")
