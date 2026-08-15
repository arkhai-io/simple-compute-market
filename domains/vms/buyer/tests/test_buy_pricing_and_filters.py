"""Tests for filter-aware discovery + auto/interactive price derivation
on `market buy`.
"""

from __future__ import annotations

import uuid
import json
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from arkhai_vms import make_vm_provision_terms
from core_buyer.action_policy import BuyerActionPolicy
from core_buyer.registry_config import RegistryAuthority
from domains.vms.buyer.buy_cli import _make_hosted_settle_hook
from domains.vms.buyer.negotiate_cli import _pricing_listing_for_selection
from domains.vms.buyer.buy_orchestrator import (
    BuyConfig,
    BuyConstraints,
    NegotiationResult,
    extract_seller_min_price,
    make_legacy_negotiate_hook,
    make_legacy_settle_hook,
    query_registry_for_matches,
    run_buy,
)
from domains.vms.buyer.settlement_composition import resolve_buyer_settlement_policy
from registry_client import FilterSpecResponse
from identity_helpers import BUYER_SIGNER, seller_principals
from market_core.schemas import (
    EscrowProposal,
    EscrowTerms,
    RateValue,
    SettlementOption,
    derive_settlement_option_id,
)


def _config(registry_url: str = "http://reg") -> BuyConfig:
    return BuyConfig(
        registry_urls=[registry_url],
        registry_authorities={
            registry_url: RegistryAuthority(
                authority="registry",
                principals=seller_principals(),
            )
        },
        principal=BUYER_SIGNER.identity,
        buyer_profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        signer=BUYER_SIGNER,
    )


def _listing_with_identity(listing, registry_url: str = "http://reg"):
    enriched = dict(listing)
    seller_url = (
        enriched.get("storefront_url")
        or enriched.get("seller")
        or enriched.get("seller_url")
        or "http://seller"
    )
    enriched.update(
        publisher_id=enriched.get(
            "publisher_id", f"publisher-{enriched.get('listing_id', 'seller')}"
        ),
        storefront_url=seller_url,
        publisher_principals=seller_principals().model_dump(mode="json"),
        source_registry_url=registry_url,
        source_registry_authority="registry",
    )
    return enriched


def _escrow_proposal() -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "cd" * 20,
        fields={"token": "0x" + "ab" * 20},
        demands=[
            {
                "chain_name": "anvil",
                "arbiter": "0x" + "cd" * 20,
                "demand_data": {"recipient": "0x" + "f" * 40},
            }
        ],
        expiration_unix=1_800_000_000,
    )


def _hosted_option() -> SettlementOption:
    rates = [RateValue(field="amount", value=125)]
    params = {"account_ref": "acct-seller"}
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="fiat.stripe.v1",
            asset="usd",
            rates=rates,
            params=params,
        ),
        mechanism="fiat.stripe.v1",
        asset="usd",
        rates=rates,
        params=params,
    )


def test_select_hosted_option_pins_exact_listed_choice():
    option = _hosted_option()
    listing = {"settlement_options": [option.model_dump(mode="json")]}
    policy = resolve_buyer_settlement_policy(
        {
            "Settlement": {
                "priority": ["fiat.stripe.v1"],
                "stripe": {"enabled": True},
            }
        }
    )

    selected = policy.select(
        listing,
        clauses=(f"option_id={option.option_id}",),
        expiration_unix=1_800_000_000,
    )

    assert selected is not None
    assert selected.selection.option_id == option.option_id
    assert selected.selection.expiration_unix == 1_800_000_000


def test_select_hosted_option_rejects_unlisted_choice():
    option = _hosted_option()
    policy = resolve_buyer_settlement_policy(
        {
            "Settlement": {
                "priority": ["fiat.stripe.v1"],
                "stripe": {"enabled": True},
            }
        }
    )

    assert (
        policy.select(
            {"settlement_options": [option.model_dump(mode="json")]},
            clauses=('option_id="' + "0" * 64 + '"',),
            expiration_unix=1_800_000_000,
        )
        is None
    )


def test_standalone_pricing_uses_selected_option_rate_and_units():
    option = _hosted_option()
    legacy_alkahest_entry = {
        "chain_name": "anvil",
        "escrow_address": "0x" + "aa" * 20,
        "literal_fields": {"token": "0x" + "bb" * 20},
        "rates": [{"field": "amount", "per": "hour", "value": "999000000"}],
    }
    listing = {
        "accepted_escrows": [legacy_alkahest_entry],
        "settlement_options": [option.model_dump(mode="json")],
    }
    policy = resolve_buyer_settlement_policy(
        {
            "Settlement": {
                "schema_version": 1,
                "priority": ["fiat.stripe.v1"],
                "stripe": {"enabled": True},
            }
        }
    )
    selected = policy.select(listing, expiration_unix=1_800_000_000)
    assert selected is not None

    pricing_listing = _pricing_listing_for_selection(
        listing,
        selected,
        accepted_escrow=None,
    )

    assert pricing_listing["accepted_escrows"] == []
    assert extract_seller_min_price(pricing_listing) == 125


def test_hosted_settle_uses_storefront_and_never_calls_authority_directly(
    monkeypatch,
):
    from domains.vms.buyer.buyer_client import NegotiationOutcome
    from market_core.schemas import SettlementObligation, SettlementPlan

    monkeypatch.setattr(
        "domains.vms.buyer.buy_cli.make_publisher_trust_resolver",
        lambda **_kwargs: seller_principals,
    )

    starts: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "domains.vms.buyer.buy_cli.start_hosted_settlement",
        lambda **kwargs: (
            starts.append(kwargs)
            or {
                "settlement_ref": "settlement-1",
                "status": "requires_action",
                "action": {
                    "kind": "redirect",
                    "url": "https://checkout.example/session",
                    "expires_at_unix": 1_800_000_000,
                },
                "action_kind": "redirect",
                "action_expires_at_unix": 1_800_000_000,
            }
        ),
    )
    monkeypatch.setattr(
        "domains.vms.buyer.buy_cli.wait_for_hosted_settlement",
        lambda **_kwargs: {"status": "ready"},
    )
    opened: list[str] = []
    events: list[tuple[str, dict[str, Any]]] = []
    hook = _make_hosted_settle_hook(
        config=_config("http://registry"),
        provision=make_vm_provision_terms(
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 AAAA",
        ),
        poll_interval=0,
        total_timeout=5,
        sleep=lambda _seconds: None,
        action_policy=BuyerActionPolicy.OPEN,
        open_url=lambda url: opened.append(url),
        print_url=lambda _url: None,
    )
    outcome = NegotiationOutcome(
        status="agreed",
        negotiation_id="neg-1",
        agreed_amount=125,
        settlement_plan=SettlementPlan(
            obligations=[
                SettlementObligation(
                    payer="buyer",
                    claimant="seller",
                    payer_principal=BUYER_SIGNER.identity.model_dump(mode="json"),
                    claimant_principal=seller_principals()
                    .identities[0]
                    .model_dump(mode="json"),
                    amount=125,
                    asset="usd",
                    expiration_unix=1_800_000_000,
                    mechanism="fiat.stripe.v1",
                )
            ]
        ),
    )

    result = hook(
        NegotiationResult(
            match=_listing_with_identity(
                {"listing_id": "L1", "seller": "http://seller"},
                "http://registry",
            ),
            outcome=outcome,
        ),
        lambda stage, body: events.append((stage, body)),
    )

    assert opened == ["https://checkout.example/session"]
    assert starts[0]["negotiation_id"] == "neg-1"
    assert len(starts[0]["obligation_ref"]) == 64
    assert starts[0]["payer_principal"] == BUYER_SIGNER.identity
    assert starts[0]["claimant_principal"] == seller_principals().identities[0]
    assert result.status == "ready"
    assert result.escrow_uid == "settlement-1"
    assert all("url" not in body for _, body in events)


def _build_escrow_proposal():
    return lambda _match: _escrow_proposal()


def _stub_build_escrow_terms(proposal, seller_wallet, agreed_amount, duration_seconds):
    return [
        EscrowTerms(
            maker="buyer",
            escrow_contract="0x" + "ee" * 20,
            obligation_data={
                "arbiter": "0x" + "cd" * 20,
                "demand": "0x" + "00" * 32,
                "token": proposal.fields["token"],
                "amount": int(float(agreed_amount) * max(duration_seconds, 1) / 3600),
            },
            expiration_unix=proposal.expiration_unix,
        )
    ]


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
    if matches is not None:
        matches = [
            _listing_with_identity(match, config.registry_urls[0]) for match in matches
        ]
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
        buyer_evm_address="0x" + "cc" * 20,
        build_escrow_terms=build_escrow_terms,
        create_escrow=create_escrow,
        confirm_settlement=confirm_settlement,
        settlement_poll_interval=settlement_poll_interval,
        settlement_total_timeout=settlement_total_timeout,
        sleep=sleep,
    )
    with mock.patch(
        "core_buyer.orchestration.make_publisher_trust_resolver",
        return_value=seller_principals,
    ):
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
        listing = {
            "accepted_escrows": [
                {
                    "chain_name": "anvil",
                    "escrow_address": "0xE",
                    "rates": [{"field": "amount", "per": "hour", "value": "1500"}],
                }
            ]
        }
        assert extract_seller_min_price(listing) == 1500

    def test_string_json_list(self):
        listing = {
            "accepted_escrows": json.dumps(
                [
                    {
                        "chain_name": "anvil",
                        "escrow_address": "0xE",
                        "rates": [{"field": "amount", "per": "hour", "value": "9000"}],
                    }
                ]
            )
        }
        assert extract_seller_min_price(listing) == 9000

    def test_missing_rate_returns_none(self):
        listing = {
            "accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0xE"}]
        }
        assert extract_seller_min_price(listing) is None

    def test_unparseable_rate_returns_none(self):
        listing = {
            "accepted_escrows": [
                {
                    "chain_name": "anvil",
                    "escrow_address": "0xE",
                    "rates": [
                        {"field": "amount", "per": "hour", "value": "not-a-number"}
                    ],
                }
            ]
        }
        assert extract_seller_min_price(listing) is None

    def test_empty_accepted_escrows_returns_none(self):
        assert extract_seller_min_price({}) is None
        assert extract_seller_min_price({"accepted_escrows": []}) is None


# ---------------------------------------------------------------------------
# query_registry_for_matches with typed resource queries
# ---------------------------------------------------------------------------


class TestQueryRegistryResources:
    def _patch_client(self, monkeypatch, items=()):
        captured = {}

        class FakeRegistryClient:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def get_filter_spec(self):
                return FilterSpecResponse.from_dict(
                    {
                        "version": 1,
                        "etag": "vm-v1",
                        "filters": [
                            {
                                "name": "gpu_model",
                                "op": "in",
                                "value_type": "string",
                            },
                            {
                                "name": "gpu_count_min",
                                "query_name": "gpu_count",
                                "query_aliases": ["gpu_count_min"],
                                "op": "range",
                                "value_type": "integer",
                                "alias_kind": "lower_bound",
                            },
                            {
                                "name": "datacenter_grade",
                                "op": "in",
                                "value_type": "boolean",
                            },
                            {
                                "name": "static_ip",
                                "op": "in",
                                "value_type": "boolean",
                            },
                        ],
                    }
                )

            def list_listings(self, **kwargs):
                captured["params"] = kwargs
                return SimpleNamespace(
                    listings=[
                        SimpleNamespace(to_dict=lambda item=item: item)
                        for item in items
                    ]
                )

        monkeypatch.setattr(
            "core_buyer.orchestrator.SyncRegistryClient",
            FakeRegistryClient,
        )
        return captured

    def _query(self, *, resource_query=None):
        return query_registry_for_matches(
            "http://reg",
            signer=BUYER_SIGNER,
            registry_authority=RegistryAuthority(
                authority="registry",
                principals=seller_principals(),
            ),
            resource_query=resource_query,
        )

    def test_no_resource_query_sends_only_common_parameters(self, monkeypatch):
        captured = self._patch_client(monkeypatch)
        self._query()
        assert captured["params"] == {
            "status": "open",
            "limit": 100,
            "offset": 0,
            "etag": None,
        }

    def test_resource_query_is_compiled_to_typed_parameters(self, monkeypatch):
        captured = self._patch_client(monkeypatch)
        self._query(
            resource_query=(
                "gpu_model=H200 gpu_count>=4 datacenter_grade=true static_ip=false"
            )
        )
        assert captured["params"] == {
            "status": "open",
            "limit": 100,
            "offset": 0,
            "etag": "vm-v1",
            "gpu_model": "H200",
            "gpu_count_min": "4",
            "datacenter_grade": "true",
            "static_ip": "false",
        }

    def test_returns_items_list(self, monkeypatch):
        items = [{"listing_id": "a"}, {"listing_id": "b"}]
        self._patch_client(monkeypatch, items)
        assert self._query() == items


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
                status="exited",
                agreed_amount=None,
                rounds=1,
                reason="exited",
                negotiation_id="neg-1",
                duration_seconds=3600,
            )

        monkeypatch.setattr(
            "core_buyer.orchestration.negotiate_with_seller",
            fake_negotiate,
        )

        constraints = BuyConstraints()  # prices None
        provision = make_vm_provision_terms(
            duration_seconds=3600, ssh_public_key="ssh-ed25519 AAAA"
        )
        config = _config()
        matches = [
            {
                "listing_id": "L1",
                "seller": "http://s1",
                "accepted_escrows": [
                    {
                        "chain_name": "anvil",
                        "escrow_address": "0xE",
                        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
                    }
                ],
            },
            {
                "listing_id": "L2",
                "seller": "http://s2",
                "accepted_escrows": [
                    {
                        "chain_name": "anvil",
                        "escrow_address": "0xE",
                        "rates": [{"field": "amount", "per": "hour", "value": "200"}],
                    }
                ],
            },
        ]

        def derive(match):
            base = extract_seller_min_price(match)
            return base, base * 2

        result = _run_buy_with_legacy_hooks(
            config=config,
            constraints=constraints,
            provision=provision,
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_fail_build_escrow_terms,
            create_escrow=lambda escrows: pytest.fail("escrow shouldn't run on exited"),
            matches=matches,
            max_matches_to_try=2,
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
            "core_buyer.orchestration.negotiate_with_seller",
            fake_negotiate,
        )

        constraints = BuyConstraints()
        provision = make_vm_provision_terms(
            duration_seconds=3600, ssh_public_key="ssh-ed25519 AAAA"
        )
        config = _config()
        matches = [{"listing_id": "L1", "seller": "http://s1"}]
        result = _run_buy_with_legacy_hooks(
            config=config,
            constraints=constraints,
            provision=provision,
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_fail_build_escrow_terms,
            create_escrow=lambda escrows: pytest.fail("never"),
            matches=matches,
            max_matches_to_try=1,
        )
        assert called["negotiate"] is False
        assert result.status == "exited"
        assert any(
            "BuyConstraints.initial_price and max_price are None"
            in (a.get("error") or "")
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
            status="agreed",
            agreed_amount=price,
            rounds=2,
            reason=None,
            negotiation_id="neg-id",
            duration_seconds=(
                provision_terms.duration_seconds
                if provision_terms is not None
                else None
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
        return _config()

    def _constraints(self):
        return BuyConstraints(initial_price=50, max_price=200)

    def _provision(self):
        return make_vm_provision_terms(
            duration_seconds=3600, ssh_public_key="ssh-ed25519 AAAA"
        )

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
            create_escrow=lambda escrows: pytest.fail(
                "escrow MUST NOT run when declined"
            ),
            matches=matches,
            max_matches_to_try=1,
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
            "core_buyer.orchestration.submit_settlement_request",
            lambda **kw: {"status": "queued"},
        )
        monkeypatch.setattr(
            "core_buyer.orchestration.wait_for_settlement",
            lambda **kw: {
                "status": "ready",
                "result": {"connection_details": "ssh ..."},
            },
        )

        matches = [{"listing_id": "L1", "seller": "http://s1"}]
        result = _run_buy_with_legacy_hooks(
            config=self._config(),
            constraints=self._constraints(),
            provision=self._provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_stub_build_escrow_terms,
            create_escrow=fake_create,
            matches=matches,
            max_matches_to_try=1,
            confirm_settlement=lambda terms, listing: True,
        )

        assert len(escrow_calls) == 1, "escrow ran exactly once after approval"
        assert result.status == "ready"
        assert result.escrow_uid == "escrow-uid-1"

    def test_no_callback_skips_gate(self, monkeypatch):
        """Default behavior (no callback) doesn't add a confirmation step."""
        self._setup_orchestrator(monkeypatch)
        monkeypatch.setattr(
            "core_buyer.orchestration.submit_settlement_request",
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
            matches=matches,
            max_matches_to_try=1,
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
            matches=matches,
            max_matches_to_try=1,
            confirm_settlement=boom,
        )
        assert result.status == "exited"
        assert "confirm_settlement_callback_raised" in (result.reason or "")
