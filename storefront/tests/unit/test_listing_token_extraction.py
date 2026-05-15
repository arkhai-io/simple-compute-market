"""``_extract_listing_token`` reads ``accepted_escrows[0]``.

The negotiation validator pulls the expected payment token off the
listing to compare against the buyer's escrow proposal. Post the
demand_resource cutover the only source is
``accepted_escrows[0].fields.token``; listings without an
entry (synthesis failed at publish, compute-for-compute) return
``None``.
"""

from __future__ import annotations

import json

from market_storefront.utils.sync_negotiation import _extract_listing_token


_TOKEN_NEW = "0x" + "ab" * 20


def test_reads_accepted_escrows_token():
    listing = {
        "accepted_escrows": [{
            "chain_name": "base_sepolia",
            "escrow_address": "0xescrow",
            "fields": {"token": _TOKEN_NEW},
            "price_per_hour": 1000,
        }],
    }
    assert _extract_listing_token(listing) == _TOKEN_NEW


def test_accepted_escrows_as_json_string_is_parsed():
    """SQLite returns accepted_escrows as a JSON string for legacy
    rows that bypassed the deserializer; the validator must handle both
    shapes."""
    listing = {
        "accepted_escrows": json.dumps([{
            "chain_name": "base_sepolia",
            "escrow_address": "0xescrow",
            "fields": {"token": _TOKEN_NEW},
            "price_per_hour": 1000,
        }]),
    }
    assert _extract_listing_token(listing) == _TOKEN_NEW


def test_returns_none_when_accepted_escrows_null():
    assert _extract_listing_token({"accepted_escrows": None}) is None


def test_returns_none_when_accepted_escrows_empty_list():
    assert _extract_listing_token({"accepted_escrows": []}) is None


def test_returns_none_when_entry_lacks_token():
    listing = {
        "accepted_escrows": [{
            "chain_name": "base_sepolia",
            "escrow_address": "0xescrow",
            "fields": {},
        }],
    }
    assert _extract_listing_token(listing) is None


def test_returns_none_for_empty_listing():
    assert _extract_listing_token({}) is None
