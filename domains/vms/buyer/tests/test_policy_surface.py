"""BuyerPolicy objects: registry, format compatibility, tuple selection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from market_policy.buyer_policy import (
    BuyerPolicy,
    buyer_policy_names,
    get_buyer_policy,
)

from domains.vms.buyer.policy_surface import (
    BISECTION_POLICY,
    LISTED_PRICE_POLICY,
    configured_buyer_policy,
    entry_uses_scalar_amount,
)
from domains.vms.settlement import select_escrow_entry


_TOKEN = "0x" + "22" * 20


def _scalar_entry(chain: str = "anvil") -> dict:
    return {
        "chain_name": chain,
        "escrow_address": "0x" + "11" * 20,
        "literal_fields": {"token": _TOKEN},
        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
    }


def _exact_entry(chain: str = "anvil") -> dict:
    return {
        "chain_name": chain,
        "escrow_address": "0x" + "33" * 20,
        "literal_fields": {"token": _TOKEN, "tokenId": "7"},
        "rates": [],
    }


def test_scalar_policies_are_registered():
    assert {"listed_price", "bisection"} <= set(buyer_policy_names())
    assert get_buyer_policy("listed_price") is LISTED_PRICE_POLICY
    assert get_buyer_policy("bisection") is BISECTION_POLICY


def test_unknown_policy_names_the_registered_ones():
    with pytest.raises(KeyError, match="listed_price"):
        get_buyer_policy("haggle-3000")


def test_configured_policy_defaults_to_listed_price():
    assert configured_buyer_policy().name == "listed_price"


def test_configured_policy_reads_buyer_toml():
    with patch(
        "domains.vms.buyer.common.resolve_config_value",
        return_value="bisection",
    ):
        assert configured_buyer_policy().name == "bisection"


def test_entry_compatibility_is_shape_based():
    assert entry_uses_scalar_amount(_scalar_entry())
    assert not entry_uses_scalar_amount(_exact_entry())
    # Fungible token literal without rates still counts as scalar.
    assert entry_uses_scalar_amount({
        "chain_name": "anvil",
        "escrow_address": "0x" + "11" * 20,
        "literal_fields": {"token": _TOKEN},
        "rates": [],
    })


def test_selection_offers_only_compatible_formats():
    listing = {"accepted_escrows": [_exact_entry(), _scalar_entry()]}
    picked = select_escrow_entry(
        listing,
        chain_name="anvil",
        token_contract_filter=None,
        assume_yes=True,
        rpc_url="http://unused",
        buyer_address="0x" + "44" * 20,
        compatible=LISTED_PRICE_POLICY.compatible,
    )
    assert picked is not None
    assert entry_uses_scalar_amount(picked)


def test_selection_refuses_incompatible_only_listings():
    listing = {"accepted_escrows": [_exact_entry()]}
    picked = select_escrow_entry(
        listing,
        chain_name="anvil",
        token_contract_filter=None,
        assume_yes=True,
        rpc_url="http://unused",
        buyer_address="0x" + "44" * 20,
        compatible=LISTED_PRICE_POLICY.compatible,
    )
    assert picked is None


def test_chain_terminal_follows_the_configured_policy():
    from domains.vms.buyer.buyer_client import _load_buyer_chain
    from domains.vms.negotiation.policies import (
        bisection_middleware,
        listed_price_middleware,
    )

    assert _load_buyer_chain()[-1] is listed_price_middleware
    with patch(
        "domains.vms.buyer.common.resolve_config_value",
        return_value="bisection",
    ):
        assert _load_buyer_chain()[-1] is bisection_middleware


def test_policy_without_derivation_passes_explicit_values_through():
    from domains.vms.buyer.cli_helpers import resolve_prices_from_matches
    from rich.console import Console

    opaque = BuyerPolicy(name="opaque-test", middlewares=("listed_price",))
    with patch(
        "domains.vms.buyer.policy_surface.configured_buyer_policy",
        return_value=opaque,
    ):
        assert resolve_prices_from_matches(
            matches=[], console=Console(), price_markup=1.5,
            initial_price=7, max_price=9,
        ) == (7, 9)
