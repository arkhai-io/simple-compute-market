"""Tests for the seller's price-extraction logic.

``_extract_initial_price_from_order(order)`` is the seller's configured read of the
listing's price floor. Source is ``accepted_escrows[0].rates[0].value``.
Tristate semantics:

  * positive int — public price, returned directly.
  * ``0``         — free / public-test offering, returned as 0.
  * empty rates  — hidden reserve, falls back to
    ``[pricing].default_min_price``; raises ValueError if that's also
    unset (sync_negotiation translates to a 409 refusal).
"""
from __future__ import annotations

import pytest

from arkhai_vms_listings.models import (
    ComputeResource,
    GPUModel,
    Listing,
    Region,
)
from fractions import Fraction

from arkhai_vms_listings.pricing import extract_initial_price_from_order
from arkhai_vms_negotiation.storefront_round import _seller_reference_amount
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


def _extract_initial_price_from_order(order: Listing | dict) -> int | Fraction:
    return extract_initial_price_from_order(
        order,
        default_min_price=settings.pricing.default_min_price,
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


class TestSellerReferenceAmount:
    def test_long_rate_over_a_year_is_exact(self):
        """A 21-significant-digit base-unit rate over one year needs 29 digits,
        which a 28-digit decimal context would round."""
        rate = 123456789012345678901
        year = 365 * 24 * 3600
        listing = _make_listing(demand_amount=rate)
        assert _seller_reference_amount(listing, year) == rate * year // 3600

    def test_amount_truncates_to_whole_base_units(self):
        listing = _make_listing(demand_amount=7)
        assert _seller_reference_amount(listing, 1800) == 3

    def test_floor_reference_amount_is_exact(self):
        listing = _make_listing(demand_amount=None)
        with settings_overrides(**{"pricing.default_min_price": "1.5"}):
            amount = _seller_reference_amount(
                listing, 7200, default_min_price=settings.pricing.default_min_price
            )
        assert amount == 3
        assert isinstance(amount, int)


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

    def test_an_escrow_proposal_is_referenced_against_its_matched_escrow(self):
        listing = _with_options(_make_listing(demand_amount=900), _RATED_OPTION)
        proposal = {"chain_name": "test_chain", "escrow_address": "0x" + "11" * 20}
        assert _seller_reference_amount(listing, 3600, proposal=proposal) == 900
