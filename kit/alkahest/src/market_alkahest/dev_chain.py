"""The local development chain's Alkahest deployment."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

#: The address book's file name, which deployments also mount it under.
ANVIL_ADDRESS_BOOK = "alkahest_anvil_addresses.json"


def anvil_address_book_path() -> Path:
    """Where the installed kit holds the development chain's address book.

    Development-only contracts at deterministic addresses: never for a public
    network. A deployment reads it from a path its configuration names; this
    is for a process that runs from the installed kit, such as a test.
    """
    return Path(str(resources.files("market_alkahest.data").joinpath(ANVIL_ADDRESS_BOOK)))


__all__ = ["ANVIL_ADDRESS_BOOK", "anvil_address_book_path"]
