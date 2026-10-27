"""Per-credit pricing and the seller's reference amount, under a neutral domain's bundle."""

from __future__ import annotations

import pytest
from market_core.schemas import RateValue, derive_settlement_option_id
from market_negotiation_runtime import NegotiationTerms

from arkhai_api.purchase import provision_terms_model
from arkhai_api_selling.negotiation import RoundSettings, reference_amount, seller_reference_amount
from arkhai_api_selling.pricing import (
    checked_credit_total,
    determine_strategy,
    domain_listing_resource,
    extract_unit_price_from_order,
)
from tests.bundles import EXAMPLE

# Deterministic development values for these tests only; never used on any network.
_TOKEN = "0x" + "01" * 20
_ESCROW = "0x" + "11" * 20
#: The floor setting as a neutral storefront spells it.
FLOOR = "quota.floor"


def _listing(rate="100"):
    return {
        "listing_id": "L-example",
        "status": "open",
        "listing_resource": {"product": "Example", "quota": "quota-a"},
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": _ESCROW,
                "literal_fields": {"token": _TOKEN},
                "rates": [{"field": "amount", "per": "token", "value": rate}],
            }
        ],
    }


def _rated_option(rate=None):
    rates = [RateValue(field="amount", per="credit", value=rate)] if rate else []
    option = {
        "mechanism": "example.rated.v1",
        "asset": "usd",
        "rates": [r.model_dump(mode="json") for r in rates],
        "params": {},
    }
    option["option_id"] = derive_settlement_option_id(
        mechanism="example.rated.v1", asset="usd", rates=rates, params={}
    )
    return option


def _selecting(option):
    return {
        "settlement_selection": {
            "mechanism": option["mechanism"],
            "option_id": option["option_id"],
            "expiration_unix": 2_000_000_000,
        }
    }


def test_unit_price_from_advertised_rate():
    assert extract_unit_price_from_order(_listing(rate="250"), noun="credit", floor_key=FLOOR) == 250


def test_unit_price_hidden_reserve_falls_back_then_refuses():
    listing = _listing()
    listing["accepted_escrows"][0]["rates"] = []
    assert extract_unit_price_from_order(listing, default_min_price="7", noun="credit", floor_key=FLOOR) == 7
    with pytest.raises(ValueError, match="hidden reserve"):
        extract_unit_price_from_order(listing, noun="credit", floor_key=FLOOR)


def test_float_floor_is_refused():
    hidden = _listing()
    hidden["accepted_escrows"][0]["rates"] = []
    with pytest.raises(ValueError, match="decimal text"):
        extract_unit_price_from_order(hidden, default_min_price=1.5, noun="credit", floor_key=FLOOR)


def test_a_credit_total_is_exact_and_bounded():
    assert checked_credit_total(3, 4, noun="credit") == 12
    for rate, quantity in ((1.5, 2), (True, 1), (-1, 1), (1, 0), (2**256, 1)):
        with pytest.raises(ValueError):
            checked_credit_total(rate, quantity, noun="credit")


def test_the_strategy_maximizes_only_the_domains_listings():
    assert determine_strategy(EXAMPLE, _listing()) == "maximize"
    assert determine_strategy(EXAMPLE, {"listing_resource": {"gpu_model": "H200"}}) is None
    assert determine_strategy(EXAMPLE, None) is None


def test_a_stored_listing_resource_is_read_through_the_domains_schema():
    assert domain_listing_resource(EXAMPLE, '{"product": "Example"}') == {
        "product": "Example",
        "quota": None,
        "url": None,
        "offering_mode": None,
    }
    assert domain_listing_resource(EXAMPLE, "not json") is None


def test_round_reference_amount_is_exact_for_a_rational_floor_and_a_long_rate():
    hidden = _listing()
    hidden["accepted_escrows"][0]["rates"] = []
    assert seller_reference_amount(hidden, 3, noun="credit", floor_key=FLOOR, default_min_price="1.5") == 4

    long_rate = "123456789012345678901234567"
    assert seller_reference_amount(_listing(rate=long_rate), 1000, noun="credit", floor_key=FLOOR) == int(long_rate) * 1000


def test_a_selected_escrow_other_than_the_first_is_the_reference():
    listing = _listing(rate="100")
    second = dict(listing["accepted_escrows"][0])
    second.update(
        escrow_address="0x" + "22" * 20,
        rates=[{"field": "amount", "per": "token", "value": "250"}],
    )
    listing["accepted_escrows"].append(second)
    proposal = {"chain_name": "anvil", "escrow_address": "0x" + "22" * 20}

    assert seller_reference_amount(listing, 2, noun="credit", floor_key=FLOOR, proposal=proposal) == 500


def test_a_selected_settlement_option_is_the_reference():
    option = _rated_option(rate=40)
    listing = {**_listing(rate="100"), "settlement_options": [option]}

    assert seller_reference_amount(listing, 3, noun="credit", floor_key=FLOOR, proposal=_selecting(option)) == 120


def test_a_selected_rateless_option_uses_the_floor():
    option = _rated_option()
    listing = {**_listing(rate="100"), "settlement_options": [option]}

    assert seller_reference_amount(
        listing, 3, noun="credit", floor_key=FLOOR, default_min_price="7", proposal=_selecting(option)
    ) == 21


def test_the_runtimes_reference_reads_the_whole_pinned_proposal():
    option = _rated_option(rate=40)
    listing = {**_listing(rate="100"), "settlement_options": [option]}
    terms = NegotiationTerms(
        decoded=provision_terms_model(EXAMPLE.kind).purchase(quantity=3), wire=None
    )

    assert reference_amount(EXAMPLE, lambda: RoundSettings(floor_key=FLOOR), listing, {}, terms, True, _selecting(option)) == 120
    assert reference_amount(EXAMPLE, lambda: RoundSettings(floor_key=FLOOR), listing, {}, terms, False, None) == 0


def _escrow_listing(*rates):
    listing = _listing()
    listing["accepted_escrows"][0]["rates"] = list(rates)
    return listing


AMOUNT = {"field": "amount", "per": "token", "value": "100"}
DURATION = {"field": "duration_seconds", "per": "token", "value": "7"}


def test_an_escrows_amount_rate_is_its_price_wherever_it_sits_in_the_list():
    assert extract_unit_price_from_order(_escrow_listing(DURATION, AMOUNT), noun="credit", floor_key=FLOOR) == 100
    assert extract_unit_price_from_order(_escrow_listing(AMOUNT, DURATION), noun="credit", floor_key=FLOOR) == 100


def test_an_escrow_with_no_amount_rate_falls_to_the_floor():
    assert extract_unit_price_from_order(
        _escrow_listing(DURATION), noun="credit", floor_key=FLOOR, default_min_price="9"
    ) == 9


@pytest.mark.parametrize(
    ("rates", "refusal"),
    [
        ((AMOUNT, {**AMOUNT, "value": "200"}), "more than one amount rate"),
        (({**AMOUNT, "per": "hour"},), "rate is not per credit"),
        (({**AMOUNT, "value": "1.5"},), "rate and quantity must be integers"),
    ],
    ids=["duplicate-amount", "invalid-unit", "invalid-value"],
)
def test_an_ambiguous_or_invalid_escrow_rate_is_refused(rates, refusal):
    with pytest.raises(ValueError, match=refusal):
        extract_unit_price_from_order(_escrow_listing(*rates), noun="credit", floor_key=FLOOR, default_min_price="9")


def test_refusals_name_what_is_sold_by_the_noun_they_are_given():
    with pytest.raises(ValueError, match="^widget rate and quantity must be integers$"):
        checked_credit_total(True, 1, noun="widget")
    with pytest.raises(ValueError, match="^selected widget escrow rate is not per credit$"):
        extract_unit_price_from_order(
            _escrow_listing({**AMOUNT, "per": "hour"}), noun="widget", floor_key=FLOOR
        )
