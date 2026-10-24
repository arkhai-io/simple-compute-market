"""What a listing publishes for the escrow: accepted escrows and their release conditions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_alkahest.alkahest import get_erc20_escrow_obligation_default
from market_alkahest.dev_chain import anvil_address_book_path

from arkhai_api_selling_alkahest.publication import (
    accepted_escrow,
    release_conditions,
    seed_accepted_escrows,
)

# Placeholder development addresses, never used on a public network.
TOKEN = "0x" + "01" * 20
BOOK = str(anvil_address_book_path())
CHAINS = {"anvil": SimpleNamespace(alkahest_address_config_path=BOOK)}


def test_an_accepted_escrow_defaults_to_the_chains_erc20_escrow_obligation():
    escrow = accepted_escrow(chain_name="anvil", address_config_path=BOOK, token=TOKEN, price_per_token="7")

    assert escrow == {
        "chain_name": "anvil",
        "escrow_address": get_erc20_escrow_obligation_default("anvil", config_path=BOOK).lower(),
        "literal_fields": {"token": TOKEN},
        "rates": [{"field": "amount", "per": "token", "value": "7"}],
    }


def test_a_stated_escrow_address_is_kept_lowercased():
    escrow = accepted_escrow(
        chain_name="anvil", address_config_path=None, token=TOKEN, price_per_token="1",
        escrow_address="0x" + "AB" * 20,
    )

    assert escrow["escrow_address"] == "0x" + "ab" * 20


def test_a_seed_on_an_unconfigured_chain_is_refused():
    with pytest.raises(RuntimeError, match="seed chain 'base' is not configured"):
        seed_accepted_escrows({"chain": "base", "token": TOKEN}, CHAINS)

    assert seed_accepted_escrows({"token": TOKEN}, CHAINS)[0]["rates"][0]["value"] == "1"


def test_release_conditions_refuse_an_escrow_on_an_unconfigured_chain():
    with pytest.raises(ValueError, match="names chain 'base'"):
        release_conditions(
            SimpleNamespace(mechanism_config=lambda _key: None), chains=CHAINS,
            wallet_address="", accepted_escrows=[{"chain_name": "base"}],
        )

    assert release_conditions(
        SimpleNamespace(mechanism_config=lambda _key: None), chains=CHAINS,
        wallet_address="", accepted_escrows=[],
    ) == []
