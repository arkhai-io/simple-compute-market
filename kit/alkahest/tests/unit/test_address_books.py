"""Resolving a chain's Alkahest address book from ``[Settlement.alkahest]``."""

from __future__ import annotations

from market_alkahest import (
    AlkahestSettlementConfig,
    alkahest_address_book,
    create_alkahest_registration,
)

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
