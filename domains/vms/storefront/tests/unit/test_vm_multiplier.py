"""VM multiplier arithmetic: the exact quote, the seller's floor, the rate pin."""
from fractions import Fraction
import hashlib
import math

import pytest
from dynaconf import Dynaconf
from arkhai_vms_negotiation.amounts import (
    multiplier_floor,
    quote_from_multiplier,
    rate_structure_digest,
    selected_billing_basis,
)
from market_core.schemas import PriceBasis, derive_settlement_option_id
from market_identity import canonical_json
from market_storefront.utils.config import negotiation_multiplier_floor
from tests.unit import test_sync_negotiation_seller_round_hook as fixture


def _negotiation(**values) -> Dynaconf:
    source = Dynaconf(environments=False)
    if values:
        source.set("negotiation", values)
    return source


@pytest.mark.parametrize("floor", [0, 8000, 10_000])
def test_a_floor_up_to_the_advertised_rates_is_read(floor):
    assert negotiation_multiplier_floor(_negotiation(multiplier_floor_bps=floor)) == floor
    assert multiplier_floor({"multiplier_floor_bps": floor}) == floor


def test_an_unstated_floor_is_the_advertised_rates():
    assert negotiation_multiplier_floor(_negotiation()) == 10_000


@pytest.mark.parametrize("floor", [10_001, -1, 9_999.5, "10000", True])
def test_a_floor_above_the_advertised_rates_or_not_an_integer_is_refused_by_key(floor):
    with pytest.raises(ValueError, match=r"^\[negotiation\]\.multiplier_floor_bps must be"):
        negotiation_multiplier_floor(_negotiation(multiplier_floor_bps=floor))
    with pytest.raises(ValueError, match="multiplier_floor_bps"):
        multiplier_floor({"multiplier_floor_bps": floor})


def test_the_rate_pin_digests_the_canonical_rate_structure_alone():
    structure = {
        "gpu": [{"asset": fixture._TOKEN, "rate": "60", "per": "hour"}],
        "cpu": [{"per": "hour", "rate": "10", "asset": fixture._TOKEN}],
    }
    reordered = {"cpu": structure["cpu"], "gpu": structure["gpu"]}
    digest = rate_structure_digest({"listing_id": "L-1", "rate_structure": structure})
    assert digest == hashlib.sha256(canonical_json(structure)).hexdigest()
    assert rate_structure_digest({"listing_id": "L-2", "rate_structure": reordered}) == digest
    assert rate_structure_digest({"rate_structure": {**structure, "cpu": []}}) != digest
    assert rate_structure_digest({"listing_id": "L-1"}) is None
    assert rate_structure_digest({"rate_structure": {}}) is None


def _priced_listing(hourly: int) -> tuple[dict, dict]:
    """A one-option listing advertising ``hourly`` for its whole shape, and its option."""
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
    return listing, option


@pytest.mark.parametrize(("period", "seconds", "expected"), [
    # 2,500,000 an hour: 625,000 a quarter hour exactly; 41,666.67 a minute,
    # rounded up once to 41,667.
    ("PT15M", 900, 625_000), ("PT1M", 60, 41_667),
])
def test_a_recurring_quote_prices_one_period_whatever_the_horizon(period, seconds, expected):
    listing, option = _priced_listing(2_500_000)
    proposal = fixture._selected_proposal(10_000)
    proposal["settlement_selection"]["option_id"] = option["option_id"]
    basis = PriceBasis(unit="per_period", period=period, period_seconds=seconds)
    for horizon in (7200, 172_800, None):
        assert quote_from_multiplier(listing, proposal, 10_000, horizon, price_basis=basis) == expected
    # A whole-term quote over two hours, by contrast, prices the horizon.
    assert quote_from_multiplier(listing, proposal, 10_000, 7200) == 5_000_000


def test_the_selected_option_s_installed_projection_is_its_billing_basis():
    listing, option = _priced_listing(2_500_000)
    proposal = fixture._selected_proposal(10_000)
    proposal["settlement_selection"]["option_id"] = option["option_id"]
    basis = PriceBasis(unit="per_period", period="PT15M", period_seconds=900)
    seen = []

    def project(selected):
        seen.append(selected.option_id)
        return basis

    assert selected_billing_basis(listing, proposal, project) == basis
    assert seen == [option["option_id"]]
    # A legacy raw escrow entry names no option: a whole-term total, unprojected.
    legacy = {**listing, "settlement_options": [], "accepted_escrows": [option["settlement"]["accepted_escrow"]]}
    raw = {
        "fields": {"amount": "10000"},
        "chain_name": option["settlement"]["accepted_escrow"]["chain_name"],
        "escrow_address": option["settlement"]["accepted_escrow"]["escrow_address"],
    }
    assert selected_billing_basis(legacy, raw, project) == PriceBasis(unit="total")
    assert seen == [option["option_id"]]


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
