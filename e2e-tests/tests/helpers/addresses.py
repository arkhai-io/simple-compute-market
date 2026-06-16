"""
tests/helpers/addresses.py
--------------------------
Utilities for Ethereum address validation used across test modules.
"""

from __future__ import annotations

from web3 import Web3


def is_non_zero_address(address: str) -> bool:
    """Return True iff *address* is a valid, non-zero Ethereum address."""
    zero = "0x" + "0" * 40
    try:
        checksummed = Web3.to_checksum_address(address)
        return checksummed != Web3.to_checksum_address(zero)
    except Exception:
        return False


def require_non_zero(address: str, label: str) -> str:
    """
    Assert *address* is non-zero and return its checksummed form.
    Raises ValueError with a descriptive message otherwise.
    """
    if not address or not is_non_zero_address(address):
        raise ValueError(
            f"{label} is not set or is the zero address. "
            "Ensure it is configured in your environment's config file."
        )
    return Web3.to_checksum_address(address)
