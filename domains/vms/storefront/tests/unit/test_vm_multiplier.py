"""A complete VM multiplier quote rounds once without losing large integers."""
from fractions import Fraction
import math

import pytest
from arkhai_vms_negotiation.amounts import quote_from_multiplier
from market_core.schemas import derive_settlement_option_id
from tests.unit import test_sync_negotiation_seller_round_hook as fixture


@pytest.mark.parametrize("bps", [9999, 10000, 10001, 12345])
def test_quote_rounds_only_the_final_product_and_refuses_overflow(bps):
    hourly = 10**30 + 7
    option = fixture._option().model_dump(mode="json")
    option["price"]["rates"][0]["value"] = str(hourly)
    option["settlement"]["accepted_escrow"]["rates"][0]["value"] = str(hourly)
    option.pop("option_id")
    option["option_id"] = derive_settlement_option_id(**option)
    listing = {
        "listing_id": "L-quote", "storefront_url": "http://seller.test",
        "seller_principal": fixture._SELLER.model_dump(mode="json"),
        "listing_resource": {
            "gpu_model": "H200", "gpu_count": 1, "vcpu_count": 4,
            "pool_id": "public-development-pool", "sla": 99.9, "region": "California, US",
        },
        "settlement_options": [option],
        "rate_structure": {
            "gpu": [{"asset": fixture._TOKEN, "rate": "60", "per": "hour"}],
            "cpu": [{"asset": fixture._TOKEN, "rate": "10", "per": "hour"}],
        },
    }
    proposal = fixture._selected_proposal(bps)
    proposal["settlement_selection"]["option_id"] = option["option_id"]
    shape = {"gpu": {"model": "H200", "count": 1}, "cpu": {"count": 3}}
    expected = math.ceil(Fraction(hourly * 9 * 1801 * bps, 10 * 3600 * 10000))
    assert quote_from_multiplier(listing, proposal, bps, 1801, shape) == expected
    with pytest.raises(ValueError, match="shape_price_overflow"):
        quote_from_multiplier(listing, proposal, 2**256, 3600, shape)
