"""The unit price a listing advertises and the key disposition a buy states."""

from __future__ import annotations

import pytest
import typer

from arkhai_api_buying.common import resolve_key_disposition
from arkhai_api_buying.listing import format_unit_price, shorten


# Deterministic development addresses for these tests only; never used on any network.
def _escrow(rates):
    return {
        "chain_name": "anvil",
        "escrow_address": "0x" + "cd" * 20,
        "literal_fields": {"token": "0x" + "ab" * 20},
        "rates": rates,
    }


def test_unit_price_reads_the_advertised_rate_and_renders_a_hidden_reserve_unpriced():
    assert format_unit_price(
        {"accepted_escrows": [_escrow([{"field": "amount", "per": "token", "value": 3}])]}
    ) == "3 / token"
    assert format_unit_price({"accepted_escrows": [_escrow([])]}) == "-"


def test_shorten_keeps_short_text_and_ellipsizes_long_text():
    assert shorten("abc", 5) == "abc"
    assert shorten("abcdef", 5) == "abcd…"


def test_key_disposition_flags():
    assert resolve_key_disposition(new_key=False, key_id=None) == ("new", None)
    assert resolve_key_disposition(new_key=True, key_id=None) == ("new", None)
    assert resolve_key_disposition(new_key=False, key_id="ak_1") == ("existing", "ak_1")
    with pytest.raises(typer.Exit):
        resolve_key_disposition(new_key=True, key_id="ak_1")
