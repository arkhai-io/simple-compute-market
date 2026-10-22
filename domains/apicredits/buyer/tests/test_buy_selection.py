"""`market credits buy` chooses settlement per listing before capping its tries.

`--max-matches` counts sellers the buyer can settle with: a listing with no
usable settlement choice is skipped without using a try, and selection stops
once the limit is reached, so no listing past it is evaluated.
"""

from __future__ import annotations

from typing import Any

from market_core.schemas import (
    RateValue,
    SettlementOption,
    SettlementSelection,
    derive_settlement_option_id,
)

from arkhai_apicredits_buyer.buy_cli import select_settlement_for_matches

_PARAMS = {"payee_account": "22222222-2222-4222-8222-222222222222", "asset": "USD/2"}


def _option(rate: int) -> SettlementOption:
    rates = [RateValue(field="amount", per="unit", value=rate)]
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="arkhai.payments.v1", asset="USD/2", rates=rates, params=_PARAMS
        ),
        mechanism="arkhai.payments.v1",
        asset="USD/2",
        rates=rates,
        params=dict(_PARAMS),
    )


def _listing(listing_id: str, option: SettlementOption | None) -> dict[str, Any]:
    return {
        "listing_id": listing_id,
        "accepted_escrows": [{"chain_name": "anvil", "price": "999"}],
        "settlement_options": [option.model_dump(mode="json")] if option else [],
    }


def _selection(option: SettlementOption) -> SettlementSelection:
    return SettlementSelection(mechanism=option.mechanism, option_id=option.option_id)


def test_unusable_listings_take_no_try_and_selection_stops_at_the_limit() -> None:
    options = {name: _option(rate) for name, rate in (("A", 100), ("B", 200), ("C", 300))}
    stale = _option(400)  # selected, but not what its listing advertises
    listings = [
        _listing("no-option", None),
        _listing("A", options["A"]),
        _listing("stale", options["B"]),
        _listing("B", options["B"]),
        _listing("C", options["C"]),
    ]
    proposals = {
        "no-option": None,
        "A": _selection(options["A"]),
        "stale": _selection(stale),
        "B": _selection(options["B"]),
        "C": _selection(options["C"]),
    }
    evaluated: list[str] = []

    def build(match: dict[str, Any]) -> SettlementSelection | None:
        evaluated.append(match["listing_id"])
        return proposals[match["listing_id"]]

    selected = select_settlement_for_matches(
        listings,
        build,
        encode_escrow_proposal=lambda _proposal: {},
        limit=2,
    )

    assert evaluated == ["no-option", "A", "stale", "B"]
    assert [match["listing_id"] for match in selected] == ["A", "B"]
    for match in selected:
        option = options[match["listing_id"]]
        # Pricing reads only the selected option, not the escrow beside it.
        assert match["settlement_options"] == [option.model_dump(mode="json")]
        assert match["accepted_escrows"] == []
        assert match["_selected_buyer_proposal"] == _selection(option)
    assert listings[1]["accepted_escrows"] == [{"chain_name": "anvil", "price": "999"}]
