"""Listing token extraction reads ``accepted_escrows[0]``.

The negotiation validator pulls the expected payment token off the
listing to compare against the buyer's escrow proposal. The only source
is ``accepted_escrows[0].literal_fields.token``; listings without an
entry (synthesis failed at publish, compute-for-compute) return
``None``.
"""

from __future__ import annotations

import json

import pytest

from market_storefront.utils.escrow_verification import (
    EscrowVerificationError,
    _extract_token_contract_from_listing,
)


_TOKEN_NEW = "0x" + "ab" * 20


def test_reads_accepted_escrows_token():
    listing = {
        "accepted_escrows": [{
            "chain_name": "base_sepolia",
            "escrow_address": "0xescrow",
            "literal_fields": {"token": _TOKEN_NEW},
            "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
        }],
    }
    assert _extract_token_contract_from_listing(listing) == _TOKEN_NEW.lower()


def test_accepted_escrows_as_json_string_is_parsed():
    """SQLite returns accepted_escrows as a JSON string for legacy
    rows that bypassed the deserializer; the validator must handle both
    shapes."""
    listing = {
        "accepted_escrows": json.dumps([{
            "chain_name": "base_sepolia",
            "escrow_address": "0xescrow",
            "literal_fields": {"token": _TOKEN_NEW},
            "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
        }]),
    }
    assert _extract_token_contract_from_listing(listing) == _TOKEN_NEW.lower()


def test_raises_when_accepted_escrows_null():
    with pytest.raises(EscrowVerificationError, match="no accepted_escrows"):
        _extract_token_contract_from_listing({"accepted_escrows": None})


def test_raises_when_accepted_escrows_empty_list():
    with pytest.raises(EscrowVerificationError, match="no accepted_escrows"):
        _extract_token_contract_from_listing({"accepted_escrows": []})


def test_raises_when_entry_lacks_token():
    listing = {
        "accepted_escrows": [{
            "chain_name": "base_sepolia",
            "escrow_address": "0xescrow",
            "literal_fields": {},
        }],
    }
    with pytest.raises(EscrowVerificationError, match="no accepted_escrows"):
        _extract_token_contract_from_listing(listing)


def test_raises_for_empty_listing():
    with pytest.raises(EscrowVerificationError, match="no accepted_escrows"):
        _extract_token_contract_from_listing({})
