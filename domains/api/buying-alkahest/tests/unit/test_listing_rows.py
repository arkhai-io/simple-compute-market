"""The Alkahest stage describes a listing's accepted escrows."""

from __future__ import annotations

from arkhai_api_buying_alkahest.stage import AlkahestBuyerStage, format_accepted_escrows

# Deterministic development addresses for these tests only; never used on any network.
_ESCROWS = [
    {
        "chain_name": "anvil",
        "escrow_address": "0x" + "cd" * 20,
        "literal_fields": {"token": "0x" + "ab" * 20},
        "rates": [{"field": "amount", "per": "token", "value": 3}],
    }
]


def test_accepted_escrow_summary_names_chain_and_rate():
    rendered = format_accepted_escrows(_ESCROWS)
    assert "anvil" in rendered
    assert "3/token" in rendered


def test_an_unpriced_escrow_reads_as_a_hidden_reserve():
    assert "(hidden reserve)" in format_accepted_escrows([{**_ESCROWS[0], "rates": []}])
    assert format_accepted_escrows([]) == "-"


def test_the_stage_contributes_the_accepted_escrows_row():
    (row,) = AlkahestBuyerStage().listing_rows({"accepted_escrows": _ESCROWS})
    assert row[0] == "Accepted escrows"
    assert "anvil" in row[1]
