"""Option-only listings without an amount rate order as priceless."""

from __future__ import annotations

from core_buyer.policy_surface import extract_seller_min_price


def test_non_scalar_option_listing_is_priceless() -> None:
    listing = {
        "settlement_options": [
            {
                "option_id": "bb" * 32,
                "settlement": {
                    "schema": "contact-exchange.v1",
                    **({"terms": "prose"} or {}),
                },
            }
        ]
    }
    assert extract_seller_min_price(listing) is None
