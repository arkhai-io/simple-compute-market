"""Tests for the seller's price-extraction logic.

``_extract_initial_price_from_order(order)`` is the seller's read of the
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

from domains.vms.listings.models import (
    ComputeResource,
    GPUModel,
    Listing,
    Region,
)
from market_storefront.utils.action_executor import _extract_initial_price_from_order
from tests._settings_overrides import settings_overrides


_TOKEN_ADDR = "0x1234567890123456789012345678901234567890"


def _make_listing(*, demand_amount: int | None) -> Listing:
    """Build a minimal compute-for-token listing."""
    compute = ComputeResource(
        gpu_model=GPUModel.H200,
        gpu_count=1,
        sla=99.0,
        region=Region.CALIFORNIA_US,
    )
    rates = (
        []
        if demand_amount is None
        else [{"field": "amount", "per": "hour", "value": str(demand_amount)}]
    )
    return Listing(
        listing_id="lst-1",
        offer_resource=compute,
        accepted_escrows=[{
            "chain_name": "test_chain",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {"token": _TOKEN_ADDR},
            "rates": rates,
        }],
        seller="http://seller:8001",
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
