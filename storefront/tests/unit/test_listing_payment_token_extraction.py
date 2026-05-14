"""``_extract_listing_payment_token`` prefers ``accepted_escrows[0]``.

The negotiation validator reads the expected payment token off the
listing to compare against the buyer's escrow proposal. Under the new
shape it reads from ``accepted_escrows[0].fields.payment_token``; for
pre-migration rows (where the column is NULL) it falls back to the
legacy ``demand_resource.token.contract_address``.

These tests pin the read precedence so the validator's behavior stays
deterministic during the migration window.
"""

from __future__ import annotations

import json

from market_storefront.utils.sync_negotiation import _extract_listing_payment_token


_TOKEN_NEW = "0x" + "ab" * 20
_TOKEN_LEGACY = "0x" + "cd" * 20


def test_prefers_accepted_escrows_when_present():
    listing = {
        "accepted_escrows": [{
            "chain_name": "base_sepolia",
            "escrow_address": "0xescrow",
            "fields": {"payment_token": _TOKEN_NEW},
            "price_per_hour": 1000,
        }],
        # Legacy field still populated — we should NOT use it when
        # accepted_escrows is present.
        "demand_resource": {
            "token": {"contract_address": _TOKEN_LEGACY},
            "amount": 999,
        },
    }
    assert _extract_listing_payment_token(listing) == _TOKEN_NEW


def test_accepted_escrows_as_json_string_is_parsed():
    """SQLite returns accepted_escrows as a JSON string for legacy
    rows that bypassed the deserializer; the validator must handle both
    shapes."""
    listing = {
        "accepted_escrows": json.dumps([{
            "chain_name": "base_sepolia",
            "escrow_address": "0xescrow",
            "fields": {"payment_token": _TOKEN_NEW},
            "price_per_hour": 1000,
        }]),
    }
    assert _extract_listing_payment_token(listing) == _TOKEN_NEW


def test_falls_back_to_demand_resource_when_accepted_escrows_null():
    listing = {
        "accepted_escrows": None,
        "demand_resource": {
            "token": {"contract_address": _TOKEN_LEGACY},
            "amount": 999,
        },
    }
    assert _extract_listing_payment_token(listing) == _TOKEN_LEGACY


def test_falls_back_when_accepted_escrows_empty_list():
    listing = {
        "accepted_escrows": [],
        "demand_resource": {
            "token": {"contract_address": _TOKEN_LEGACY},
        },
    }
    assert _extract_listing_payment_token(listing) == _TOKEN_LEGACY


def test_falls_back_when_accepted_escrows_missing_payment_token():
    """Entry exists but has no payment_token field — fall through to
    demand_resource."""
    listing = {
        "accepted_escrows": [{
            "chain_name": "base_sepolia",
            "escrow_address": "0xescrow",
            "fields": {},  # no payment_token
        }],
        "demand_resource": {
            "token": {"contract_address": _TOKEN_LEGACY},
        },
    }
    assert _extract_listing_payment_token(listing) == _TOKEN_LEGACY


def test_returns_none_for_compute_listing_with_no_token():
    """Compute-only listing (no token side, no accepted_escrows)."""
    listing = {
        "demand_resource": {
            "gpu_model": "H200", "gpu_count": 1, "sla": 0.99, "region": "California, US",
        },
    }
    assert _extract_listing_payment_token(listing) is None


def test_returns_none_when_demand_resource_missing():
    assert _extract_listing_payment_token({}) is None
