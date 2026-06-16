"""Filter mapping + rendering helpers for `market tokens listing`."""

from __future__ import annotations

from domains.apitokens.buyer.common import (
    build_token_filter_params,
    resolve_key_disposition,
)
from domains.apitokens.buyer.listing_cli import (
    format_accepted_escrows,
    format_offer,
    format_unit_price,
)


_LISTING = {
    "listing_id": "lst-1",
    "offer_resource": {
        "kind": "api_tokens.v1",
        "service_name": "weather-api",
        "description": "Forecasts, 1 token per call",
        "openapi_url": "http://api.example/openapi.json",
        "base_url": "http://api.example",
    },
    "accepted_escrows": [
        {
            "chain_name": "anvil",
            "escrow_address": "0x" + "cd" * 20,
            "literal_fields": {"token": "0x" + "ab" * 20},
            "rates": [{"field": "amount", "per": "token", "value": 3}],
        }
    ],
}


def test_filter_params_map_service_name():
    assert build_token_filter_params(service_name="weather") == {
        "service_name": "weather",
    }
    assert build_token_filter_params() == {}


def test_offer_and_unit_price_rendering():
    assert "weather-api" in format_offer(_LISTING["offer_resource"])
    assert format_unit_price(_LISTING) == "3 / token"
    # Hidden reserve (no rates) renders as unpriced, not 0.
    assert format_unit_price({"accepted_escrows": [
        {"chain_name": "anvil", "escrow_address": "0x" + "cd" * 20,
         "literal_fields": {"token": "0x" + "ab" * 20}, "rates": []},
    ]}) == "-"


def test_accepted_escrow_summary_names_chain_and_rate():
    rendered = format_accepted_escrows(_LISTING["accepted_escrows"])
    assert "anvil" in rendered
    assert "3/token" in rendered


def test_key_disposition_flags():
    import pytest
    import typer

    assert resolve_key_disposition(new_key=False, key_id=None) == ("new", None)
    assert resolve_key_disposition(new_key=True, key_id=None) == ("new", None)
    assert resolve_key_disposition(new_key=False, key_id="ak_1") == ("existing", "ak_1")
    with pytest.raises(typer.Exit):
        resolve_key_disposition(new_key=True, key_id="ak_1")
