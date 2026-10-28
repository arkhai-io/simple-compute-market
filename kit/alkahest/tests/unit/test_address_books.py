"""Resolving a chain's Alkahest address book from ``[Settlement.alkahest]``."""

from __future__ import annotations

import pytest
from market_alkahest import (
    AlkahestSettlementConfig,
    alkahest_address_book,
    create_alkahest_registration,
    retired_address_book_keys,
)
from pydantic import ValidationError

ANVIL_BOOK = "/etc/arkhai/alkahest/anvil.json"


def test_a_seller_trading_on_two_chains_resolves_only_the_named_chains_book() -> None:
    """Spec scenario "A seller trades on two chains", at the resolver: ``anvil``
    has its book, and ``base_sepolia``, which the table does not name, uses the
    SDK's built-in addresses."""
    section = AlkahestSettlementConfig(enabled=True, address_books={"anvil": ANVIL_BOOK})

    assert alkahest_address_book(section, "anvil") == ANVIL_BOOK
    assert alkahest_address_book(section, "base_sepolia") is None


def test_claims_on_each_chain_are_serviced_against_that_chains_book() -> None:
    """Spec scenario "A seller trades on two chains", for claim servicing: the
    conditional-escrow client the registration builds holds ``anvil``'s book
    and none for ``base_sepolia``."""
    client = create_alkahest_registration().client_factory(
        AlkahestSettlementConfig(enabled=True, address_books={"anvil": ANVIL_BOOK}),
        {
            "clients": {"anvil": object(), "base_sepolia": object()},
            "chains": {"anvil": {}, "base_sepolia": {}},
        },
        "seller",
    )

    assert client._config_paths == {"anvil": ANVIL_BOOK, "base_sepolia": None}


def test_an_unparsed_section_resolves_as_its_parsed_form_would() -> None:
    assert alkahest_address_book({"address_books": {"anvil": ANVIL_BOOK}}, "anvil") == (
        ANVIL_BOOK
    )


def test_a_role_with_no_alkahest_section_resolves_no_book() -> None:
    assert alkahest_address_book(None, "anvil") is None


def test_each_retired_key_is_found_in_any_spelling() -> None:
    assert retired_address_book_keys(
        {"Alkahest": {"Address_Config_Path": "/book.json"}},
        {
            "anvil": {"rpc_url": "x", "ALKAHEST_ADDRESS_CONFIG_PATH": "/book.json"},
            "base_sepolia": {"rpc_url": "y"},
        },
    ) == [
        "[Chains.anvil].alkahest_address_config_path",
        "[Settlement.alkahest].address_config_path",
    ]
    assert retired_address_book_keys(
        {"alkahest": {"address_books": {"anvil": "/book.json"}}},
        {"anvil": {"rpc_url": "x"}},
    ) == []
    assert retired_address_book_keys(None, None) == []


def test_the_section_refuses_its_retired_key_naming_the_table() -> None:
    with pytest.raises(ValidationError) as refused:
        AlkahestSettlementConfig.model_validate({"address_config_path": "/book.json"})

    message = str(refused.value)
    assert "[Settlement.alkahest].address_config_path is retired" in message
    assert "[Settlement.alkahest.address_books]" in message
