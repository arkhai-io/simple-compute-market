"""Tests for the seller's price-extraction logic.

`_extract_initial_price_from_order(order)` is the seller's read of the
listing's price floor. For "price-less" listings (advertised
`demand.amount=0`), it falls back to `[seller.pricing].default_min_price`
so the negotiation strategy doesn't accept any positive offer. If
neither source has a usable price, raises ValueError so the negotiation
exits cleanly upstream.
"""
from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest

from market_storefront.models.domain_models import (
    ComputeResource,
    ERC20TokenMetadata,
    GPUModel,
    Listing,
    Region,
    TokenResource,
)
from market_storefront.utils.action_executor import _extract_initial_price_from_order
from market_storefront.utils.config import CONFIG


_TOKEN = ERC20TokenMetadata(
    symbol="MOCK",
    contract_address="0x1234567890123456789012345678901234567890",
    decimals=6,
)


def _make_listing(*, demand_amount: int) -> Listing:
    """Build a minimal compute-for-token listing."""
    compute = ComputeResource(
        gpu_model=GPUModel.H200,
        gpu_count=1,
        sla=99.0,
        region=Region.CALIFORNIA_US,
    )
    token = TokenResource(token=_TOKEN, amount=demand_amount)
    return Listing(
        listing_id="lst-1",
        offer_resource=compute,
        demand_resource=token,
        seller="http://seller:8001",
    )


def _patched_config(**overrides):
    return dataclasses.replace(CONFIG, **overrides)


class TestExtractInitialPrice:
    def test_advertised_price_used_when_set(self):
        """Listing with a positive demand.amount returns it directly."""
        listing = _make_listing(demand_amount=1000)
        assert _extract_initial_price_from_order(listing) == 1000

    def test_priceless_falls_back_to_default_min_price(self):
        """Listing with amount=0 and a configured default_min_price
        returns the default."""
        listing = _make_listing(demand_amount=0)
        cfg = _patched_config(default_min_price="500")
        with patch("market_storefront.utils.action_executor.CONFIG", cfg, create=False):
            # action_executor imports CONFIG lazily inside the function;
            # patching the utils.config module is the reachable surface.
            with patch("market_storefront.utils.config.CONFIG", cfg):
                assert _extract_initial_price_from_order(listing) == 500

    def test_priceless_without_default_raises(self):
        """Listing with amount=0 and no default_min_price raises ValueError
        with a message the negotiation layer translates to a 409 refusal."""
        listing = _make_listing(demand_amount=0)
        cfg = _patched_config(default_min_price=None)
        with patch("market_storefront.utils.config.CONFIG", cfg):
            with pytest.raises(ValueError, match="default_min_price"):
                _extract_initial_price_from_order(listing)

    def test_priceless_with_zero_default_raises(self):
        """Default of "0" is treated as 'no fallback'."""
        listing = _make_listing(demand_amount=0)
        cfg = _patched_config(default_min_price="0")
        with patch("market_storefront.utils.config.CONFIG", cfg):
            with pytest.raises(ValueError, match="default_min_price"):
                _extract_initial_price_from_order(listing)

    def test_priceless_with_garbage_default_raises(self):
        """Garbage default surfaces a clear parse error."""
        listing = _make_listing(demand_amount=0)
        cfg = _patched_config(default_min_price="not-a-number")
        with patch("market_storefront.utils.config.CONFIG", cfg):
            with pytest.raises(ValueError, match="not a valid integer"):
                _extract_initial_price_from_order(listing)
