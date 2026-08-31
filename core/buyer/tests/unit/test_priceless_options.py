"""Option-only listings without an amount rate order as priceless."""

from __future__ import annotations

from core_buyer.policy_surface import extract_seller_min_price


def test_non_scalar_option_listing_is_priceless() -> None:
    listing = {
        "settlement_options": [
            {
                "option_id": "bb" * 32,
                "mechanism": "contact-exchange.v1",
                "asset": "introduction",
                "rates": [],
                "params": {"terms": "prose"},
            }
        ]
    }
    assert extract_seller_min_price(listing) is None


def test_scalar_option_listing_extracts_rate() -> None:
    listing = {
        "settlement_options": [
            {
                "option_id": "aa" * 32,
                "mechanism": "fiat.stripe.v1",
                "asset": "usd",
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
                "params": {},
            }
        ]
    }
    assert extract_seller_min_price(listing) == 100.0
