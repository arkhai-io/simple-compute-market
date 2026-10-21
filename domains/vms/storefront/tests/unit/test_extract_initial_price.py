"""Tests for the seller's price-extraction logic.

``extract_initial_price_from_order`` reads the price floor of the settlement
option the buyer's proposal selects, from that option's first rate; the helper
below selects this listing's one accepted escrow. Tristate semantics:

  * positive int — public price, returned directly.
  * ``0``         — free / public-test offering, returned as 0.
  * empty rates  — hidden reserve, falls back to
    ``[pricing].default_min_price``; raises ValueError if that's also
    unset (sync_negotiation translates to a 409 refusal).
"""
from __future__ import annotations

import asyncio

import pytest

from arkhai_vms_listings.models import (
    ComputeResource,
    GPUModel,
    Listing,
    Region,
)
from fractions import Fraction

from arkhai_vms_listings.pricing import extract_initial_price_from_order
from arkhai_vms_negotiation.storefront_round import (
    _run_default_seller_round_policy,
    _seller_reference_amount,
)
from market_policy.listing_source import ListingSourceVerdict
from market_policy.negotiation_middleware import NegotiationRound
from market_identity import Ed25519Signer
from market_storefront.utils.config import settings
from tests._settings_overrides import settings_overrides


_TOKEN_ADDR = "0x1234567890123456789012345678901234567890"


def _make_listing(*, demand_amount: int | None) -> Listing:
    """Build a minimal compute-for-token listing."""
    compute = ComputeResource(
        gpu_model=GPUModel.H200,
        gpu_count=1,
        sla=99.0,
        region=Region.CALIFORNIA_US,
        resource_id="resource-price-test",
    )
    rates = (
        []
        if demand_amount is None
        else [{"field": "amount", "per": "hour", "value": str(demand_amount)}]
    )
    return Listing(
        listing_id="lst-1",
        listing_resource=compute,
        accepted_escrows=[{
            "chain_name": "test_chain",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {"token": _TOKEN_ADDR},
            "rates": rates,
        }],
        storefront_url="http://seller:8001",
        seller_principal=Ed25519Signer(b"\x31" * 32).identity,
    )


def _extract_initial_price_from_order(order: Listing) -> int | Fraction:
    """The floor for the listing's one accepted escrow, as a buyer selecting it gets."""
    return extract_initial_price_from_order(
        order,
        default_min_price=settings.pricing.default_min_price,
        selected_option=order.accepted_escrows[0],
    )


class TestExtractInitialPrice:
    def test_public_price_returned_directly(self):
        """Listing with a positive demand.amount returns it directly."""
        listing = _make_listing(demand_amount=1000)
        assert _extract_initial_price_from_order(listing) == 1000

    def test_free_offering_returns_zero(self):
        """Listing with demand.amount=0 (explicit free) returns 0 — does
        NOT fall back to default_min_price."""
        listing = _make_listing(demand_amount=0)
        with settings_overrides(**{"pricing.default_min_price": "500"}):
            assert _extract_initial_price_from_order(listing) == 0

    def test_hidden_reserve_falls_back_to_default_min_price(self):
        listing = _make_listing(demand_amount=None)
        with settings_overrides(**{"pricing.default_min_price": "500"}):
            assert _extract_initial_price_from_order(listing) == 500

    def test_hidden_reserve_without_default_raises(self):
        listing = _make_listing(demand_amount=None)
        with settings_overrides(**{"pricing.default_min_price": ""}):
            with pytest.raises(ValueError, match="default_min_price"):
                _extract_initial_price_from_order(listing)

    def test_hidden_reserve_with_zero_default_raises(self):
        """Default of "0" is treated as 'no fallback'."""
        listing = _make_listing(demand_amount=None)
        with settings_overrides(**{"pricing.default_min_price": "0"}):
            with pytest.raises(ValueError, match="default_min_price"):
                _extract_initial_price_from_order(listing)

    def test_hidden_reserve_with_garbage_default_raises(self):
        listing = _make_listing(demand_amount=None)
        with settings_overrides(**{"pricing.default_min_price": "not-a-number"}):
            with pytest.raises(ValueError, match="not a valid number"):
                _extract_initial_price_from_order(listing)

    def test_floor_is_parsed_exactly_from_long_decimal_text(self):
        listing = _make_listing(demand_amount=None)
        text = "123456789012345678901234567890.123456789"
        with settings_overrides(**{"pricing.default_min_price": text}):
            assert _extract_initial_price_from_order(listing) == Fraction(text)

    def test_float_floor_is_refused(self):
        listing = _make_listing(demand_amount=None)
        with settings_overrides(**{"pricing.default_min_price": 1.5}):
            with pytest.raises(ValueError, match="decimal text"):
                _extract_initial_price_from_order(listing)

    def test_nothing_selected_is_priced_from_no_rate_and_no_floor(self):
        listing = _make_listing(demand_amount=900)
        with pytest.raises(ValueError, match="selects no settlement option"):
            extract_initial_price_from_order(
                listing, default_min_price="7", selected_option=None
            )


#: A proposal selecting the listing's one accepted escrow.
_ESCROW_PROPOSAL = {"chain_name": "test_chain", "escrow_address": "0x" + "11" * 20}
_EXPIRATION = {"expiration_unix": 2_000_000_000}


class TestSellerReferenceAmount:
    def test_long_rate_over_a_year_is_exact(self):
        """A 21-significant-digit base-unit rate over one year needs 29 digits,
        which a 28-digit decimal context would round."""
        rate = 123456789012345678901
        year = 365 * 24 * 3600
        listing = _make_listing(demand_amount=rate)
        assert (
            _seller_reference_amount(listing, year, proposal=_ESCROW_PROPOSAL)
            == rate * year // 3600
        )

    def test_amount_truncates_to_whole_base_units(self):
        listing = _make_listing(demand_amount=7)
        assert _seller_reference_amount(listing, 1800, proposal=_ESCROW_PROPOSAL) == 3

    def test_floor_reference_amount_is_exact(self):
        listing = _make_listing(demand_amount=None)
        with settings_overrides(**{"pricing.default_min_price": "1.5"}):
            amount = _seller_reference_amount(
                listing,
                7200,
                default_min_price=settings.pricing.default_min_price,
                proposal=_ESCROW_PROPOSAL,
            )
        assert amount == 3
        assert isinstance(amount, int)

    @pytest.mark.parametrize(
        "proposal",
        [
            pytest.param(None, id="no proposal"),
            pytest.param({**_ESCROW_PROPOSAL, "escrow_address": "0x" + "00" * 20}, id="unpinned"),
            pytest.param({**_ESCROW_PROPOSAL, "escrow_address": "0x" + "22" * 20}, id="unlisted"),
            pytest.param({**_ESCROW_PROPOSAL, "chain_name": "other_chain"}, id="another chain"),
        ],
    )
    def test_a_proposal_selecting_nothing_is_priced_from_no_entry(self, proposal):
        """Not from the listing's first accepted escrow, nor from the floor."""
        listing = _make_listing(demand_amount=900)
        assert (
            _seller_reference_amount(
                listing, 3600, default_min_price="7", proposal=proposal
            )
            == 0
        )

    def test_a_listing_accepting_no_escrow_prices_an_escrow_from_no_entry(self):
        listing = _make_listing(demand_amount=900).model_dump(mode="json")
        listing["accepted_escrows"] = []
        assert (
            _seller_reference_amount(
                listing, 3600, default_min_price="7", proposal=_ESCROW_PROPOSAL
            )
            == 0
        )


def _round(sender: str, action: str, proposal: dict, number: int) -> NegotiationRound:
    return NegotiationRound(
        round_number=number, sender=sender, action=action, proposal=proposal
    )


def _seller_round(history: list[NegotiationRound], listing=None):
    return asyncio.run(
        _run_default_seller_round_policy(
            listing=listing if listing is not None else _make_listing(demand_amount=900),
            history=history,
            requested_duration_seconds=3600,
            strategy_label="maximize",
            default_min_price="7",
            # The listing's source is not under test: it matches.
            listing_source=ListingSourceVerdict("matches"),
        )
    )


#: A second accepted escrow on the listing, with no amount rate.
_SECOND_ESCROW = {"chain_name": "test_chain", "escrow_address": "0x" + "22" * 20}


def _two_escrow_listing() -> dict:
    listing = _make_listing(demand_amount=900).model_dump(mode="json")
    listing["accepted_escrows"].append(
        {**_SECOND_ESCROW, "literal_fields": {"token": _TOKEN_ADDR}, "rates": []}
    )
    return listing


class TestRoundReference:
    """The round hook prices the buyer's pinned opening, which acceptance settles."""

    @pytest.mark.parametrize(
        "counter_fields",
        [
            pytest.param({"amount": "1"}, id="with an amount"),
            pytest.param({}, id="without one"),
        ],
    )
    def test_a_counter_naming_another_accepted_escrow_keeps_the_pinned_reference(
        self, counter_fields
    ):
        """Neither the amount priced nor whether the round bargains one follows
        the counter, whose escrow advertises no amount rate."""
        opening = {**_ESCROW_PROPOSAL, **_EXPIRATION, "fields": {"amount": "900"}}
        counter = {**_SECOND_ESCROW, **_EXPIRATION, "fields": counter_fields}
        result = _seller_round(
            [
                _round("them", "initial", opening, 0),
                _round("us", "counter", {"fields": {"amount": "900"}}, 1),
                _round("them", "counter", counter, 2),
            ],
            listing=_two_escrow_listing(),
        )

        assert result.our_amount == 900
        assert result.intermediate["uses_scalar_amount"] is True
        assert result.decision.action != "accept"

    def test_an_opening_naming_an_escrow_the_listing_does_not_accept_is_refused(self):
        unlisted = {
            **_ESCROW_PROPOSAL,
            **_EXPIRATION,
            "escrow_address": "0x" + "22" * 20,
            "fields": {"amount": "900"},
        }
        result = _seller_round([_round("them", "initial", unlisted, 0)])

        assert result.our_amount == 0
        assert result.decision.action == "reject"
        assert result.decision.reason.startswith("escrow_not_in_accepted_set")


_RATED_OPTION = {
    "option_id": "a" * 64,
    "mechanism": "example.rated.v1",
    "asset": "usd",
    "rates": [{"field": "amount", "per": "hour", "value": "10000"}],
    "params": {},
}
_RATELESS_OPTION = {
    "option_id": "b" * 64,
    "mechanism": "example.rated.v1",
    "asset": "usd",
    "rates": [],
    "params": {},
}


def _selection(option: dict) -> dict:
    return {
        "settlement_selection": {
            "mechanism": option["mechanism"],
            "option_id": option["option_id"],
            "expiration_unix": 2_000_000_000,
        }
    }


def _with_options(listing: Listing, *options: dict, escrows: bool = True) -> dict:
    data = listing.model_dump(mode="json")
    data["settlement_options"] = list(options)
    if not escrows:
        data["accepted_escrows"] = []
    return data


class TestSelectedOptionReference:
    def test_a_rated_selection_is_referenced_against_its_own_rate(self):
        """Not the Alkahest rate the listing also offers, in another asset."""
        listing = _with_options(_make_listing(demand_amount=10**20), _RATED_OPTION)
        assert _seller_reference_amount(
            listing, 7200, proposal=_selection(_RATED_OPTION)
        ) == 20000

    def test_a_rated_only_listing_never_uses_the_floor(self):
        listing = _with_options(
            _make_listing(demand_amount=None), _RATED_OPTION, escrows=False
        )
        assert _seller_reference_amount(
            listing, 3600, default_min_price="1", proposal=_selection(_RATED_OPTION)
        ) == 10000

    def test_a_rateless_selected_option_uses_the_floor(self):
        listing = _with_options(
            _make_listing(demand_amount=None), _RATELESS_OPTION, escrows=False
        )
        assert _seller_reference_amount(
            listing, 3600, default_min_price="7", proposal=_selection(_RATELESS_OPTION)
        ) == 7

    def test_a_selection_matching_no_option_is_priced_from_no_entry(self):
        """Not from the floor: the opening guard refuses it."""
        listing = _with_options(
            _make_listing(demand_amount=None), _RATELESS_OPTION, escrows=False
        )
        unknown = {**_RATELESS_OPTION, "option_id": "f" * 64}
        assert _seller_reference_amount(
            listing, 3600, default_min_price="7", proposal=_selection(unknown)
        ) == 0

    def test_an_escrow_proposal_is_referenced_against_its_matched_escrow(self):
        listing = _with_options(_make_listing(demand_amount=900), _RATED_OPTION)
        proposal = {"chain_name": "test_chain", "escrow_address": "0x" + "11" * 20}
        assert _seller_reference_amount(listing, 3600, proposal=proposal) == 900
