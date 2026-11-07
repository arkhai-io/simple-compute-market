"""The token a VM lease is paid in, read from the accepted escrow.

An escrow naming no token is a native-token escrow when its address is one the
chain's address book names as such; the storefront hands that book over as the
mapping it resolved from ``[Settlement.alkahest.address_books]``. The addresses
here are the development chain's, never used on a public network.
"""

from __future__ import annotations

from arkhai_vms_settlement import token_resource_from_accepted_escrow
from market_alkahest.alkahest import get_native_token_escrow_obligation_default
from market_alkahest.dev_chain import anvil_address_book_path

_BOOK = str(anvil_address_book_path())


def _native_escrow() -> dict:
    return {
        "chain_name": "anvil",
        "escrow_address": get_native_token_escrow_obligation_default(
            "anvil", config_path=_BOOK
        ),
        "literal_fields": {},
        "rates": [{"field": "amount", "per": "hour", "value": "7"}],
    }


def test_a_native_escrow_is_read_through_its_chains_book() -> None:
    token = token_resource_from_accepted_escrow(
        _native_escrow(), chain_config_paths={"anvil": _BOOK}
    )

    assert token is not None
    assert token.token.contract_address == "native"
    assert token.amount == 7


def test_a_native_escrow_on_a_chain_with_no_book_is_not_read() -> None:
    """The development chain has no built-in addresses, so without its book
    nothing identifies the escrow as native-token."""
    assert token_resource_from_accepted_escrow(
        _native_escrow(), chain_config_paths={"anvil": None}
    ) is None
