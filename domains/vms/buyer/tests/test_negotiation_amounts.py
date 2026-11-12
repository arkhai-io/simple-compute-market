"""The VM amount codec anchors buyer bounds to the opening shape and caps payment."""

from __future__ import annotations

import math

import pytest
from arkhai_vms import make_vm_provision_terms
from arkhai_vms_negotiation.amounts import shape_hourly_amount
from core_buyer.policy_surface import derive_scalar_prices
from market_core.schemas import PriceBasis, RateValue, derive_settlement_option_id
from rich.console import Console

from arkhai_vms_buyer.negotiation_amounts import (
    amount_codec, priced_at_opening_shape, priced_unit_count,
)
from identity_helpers import SELLER_SIGNER

#: Deterministic development values; never a token or escrow on a public network.
TOKEN = "0x" + "ab" * 20
ESCROW = "0x" + "cd" * 20
#: The selected option's advertised hourly rate for the listing's whole shape.
HOURLY = 1000
#: At these family rates the advertised shape (one GPU, eight vCPUs) composes to
#: 60 + 8 x 5 = 100, so a four-vCPU shape is 80/100 of the advertised rate.
RATE_STRUCTURE = {
    "gpu": [{"asset": TOKEN, "rate": "60", "per": "hour"}],
    "cpu": [{"asset": TOKEN, "rate": "5", "per": "hour"}],
}
ADVERTISED = {"gpu_model": "H200", "gpu_count": 1, "vcpu_count": 8}


def _option() -> dict:
    entry = {
        "chain_name": "anvil", "escrow_address": ESCROW,
        "literal_fields": {"token": TOKEN},
        "rates": [{"field": "amount", "per": "hour", "value": str(HOURLY)}],
    }
    body = {
        "price": {"asset": TOKEN, "rates": [RateValue(field="amount", per="hour", value=HOURLY)]},
        "settlement": {"schema": "alkahest.v1", "accepted_escrow": entry},
    }
    option = {"option_id": derive_settlement_option_id(**body), **body}
    option["price"]["rates"] = [rate.model_dump(mode="json") for rate in option["price"]["rates"]]
    return option


def shape_priced_listing() -> dict:
    """A VM buyer's domain listing record: family rates in ``rate_structure``."""
    option = _option()
    return {
        "listing_id": "L-shape",
        "storefront_url": "http://seller.test",
        "seller_principal": SELLER_SIGNER.identity.model_dump(mode="json"),
        "listing_resource": {
            **ADVERTISED, "pool_id": "pool-1", "sla": 99.9, "region": "California, US",
        },
        "accepted_escrows": [option["settlement"]["accepted_escrow"]],
        "settlement_options": [option],
        "rate_structure": RATE_STRUCTURE,
    }


def with_advertised_rate(listing: dict, value: str) -> None:
    """Re-advertise the listing's option at ``value``, under its new canonical ID."""
    option = listing["settlement_options"][0]
    option["price"]["rates"][0]["value"] = value
    option["option_id"] = derive_settlement_option_id(
        price=option["price"], settlement=option["settlement"],
    )


def selection(listing: dict) -> dict:
    return {
        "option_id": listing["settlement_options"][0]["option_id"],
        "settlement": {"schema": "alkahest.v1"},
        "expiration_unix": 1_900_000_000,
    }


def _terms(duration_seconds: int | None = 3600, **compute) -> dict:
    return make_vm_provision_terms(
        duration_seconds=duration_seconds, ssh_public_key="",
        compute_resource=compute or None,
    ).model_dump(mode="json")


def test_bounds_without_an_opening_shape_are_anchored_to_the_advertised_shape():
    listing = shape_priced_listing()
    codec = amount_codec(listing, selection(listing), opening_terms=_terms())
    assert codec.scalar_from_price(HOURLY) == 10_000


def test_bounds_are_anchored_to_the_partial_opening_shape_the_seller_completes():
    listing = shape_priced_listing()
    # Four vCPUs, the GPU inherited from the listing: 80/100 of the advertised rate.
    codec = amount_codec(listing, selection(listing), opening_terms=_terms(vcpu_count=4))
    assert codec.scalar_from_price(800) == 10_000
    assert codec.scalar_from_price(HOURLY) == 12_500


def test_bound_conversion_rounds_down():
    listing = shape_priced_listing()
    codec = amount_codec(listing, selection(listing), opening_terms=_terms(vcpu_count=4))
    # 801 x 10,000 / 800 is 10,012.5: rounding up would bind the buyer above 801.
    assert codec.scalar_from_price(801) == 10_012


def test_a_resumed_run_anchors_to_the_sellers_complete_round_zero_echo():
    listing = shape_priced_listing()
    echo = _terms(gpu_model="H200", gpu_count=1, vcpu_count=4)
    codec = amount_codec(listing, selection(listing), opening_terms=echo)
    assert codec.scalar_from_price(800) == 10_000


def test_payment_within_the_ceiling_is_derived_from_the_accepted_shape():
    listing = shape_priced_listing()
    codec = amount_codec(
        listing, selection(listing), opening_terms=_terms(vcpu_count=4), max_price=800,
    )
    accepted = _terms(gpu_model="H200", gpu_count=1, vcpu_count=4)
    assert codec.payment_from_scalar(10_000, accepted) == 800


def test_an_acceptance_whose_payment_exceeds_the_ceiling_is_refused():
    listing = shape_priced_listing()
    codec = amount_codec(
        listing, selection(listing), opening_terms=_terms(vcpu_count=4), max_price=800,
    )
    # The scalar is within the buyer's bound, but the accepted shape is the
    # advertised one, which prices at 1,000 an hour against an 800 ceiling.
    larger = _terms(gpu_model="H200", gpu_count=1, vcpu_count=8)
    with pytest.raises(RuntimeError, match="exceeds the buyer's ceiling of 800"):
        codec.payment_from_scalar(10_000, larger)


def test_the_ceiling_admits_the_quotes_one_upward_rounding():
    listing = shape_priced_listing()
    codec = amount_codec(
        listing, selection(listing), opening_terms=_terms(1801, vcpu_count=4), max_price=800,
    )
    accepted = _terms(1801, gpu_model="H200", gpu_count=1, vcpu_count=4)
    # 800 x 1801 / 3600 is 400.2: the seller's quote rounds it up to 401.
    assert codec.payment_from_scalar(10_000, accepted) == math.ceil(800 * 1801 / 3600) == 401


#: A recurring option's billing basis, as its mechanism projects it.
QUARTER_HOUR = PriceBasis(unit="per_period", period="PT15M", period_seconds=900)


def _billed(basis: PriceBasis):
    return lambda _option: basis


@pytest.mark.parametrize("horizon", [3600, 7200, 172_800, None])
def test_a_recurring_payment_is_one_period_s_price_whatever_the_horizon(horizon):
    listing = shape_priced_listing()
    codec = amount_codec(listing, selection(listing), project_billing=_billed(QUARTER_HOUR))
    # 1,000 an hour is 250 a quarter hour, never 250 per hour of the horizon.
    assert codec.payment_from_scalar(10_000, _terms(horizon)) == 250
    minute = PriceBasis(unit="per_period", period="PT1M", period_seconds=60)
    codec = amount_codec(listing, selection(listing), project_billing=_billed(minute))
    # 1,000 x 60 / 3,600 is 16.67: rounded up once to 17.
    assert codec.payment_from_scalar(10_000, _terms(horizon)) == 17


def test_a_recurring_ceiling_caps_one_period_not_the_horizon():
    listing = shape_priced_listing()
    codec = amount_codec(
        listing, selection(listing), opening_terms=_terms(None, vcpu_count=4), max_price=800,
        project_billing=_billed(QUARTER_HOUR),
    )
    accepted = _terms(172_800, gpu_model="H200", gpu_count=1, vcpu_count=4)
    # 800 an hour over one quarter-hour period is 200, the whole limit.
    assert codec.payment_from_scalar(10_000, accepted) == 200
    larger = _terms(172_800, gpu_model="H200", gpu_count=1, vcpu_count=8)
    with pytest.raises(RuntimeError, match=r"ceiling of 200 \(800 per hour for 900s\)"):
        codec.payment_from_scalar(10_000, larger)


def test_bounds_scale_by_one_period_for_a_recurring_selection():
    listing = shape_priced_listing()
    for horizon in (None, 7200, 172_800):
        assert priced_unit_count(
            listing, selection(listing), horizon, project_billing=_billed(QUARTER_HOUR),
        ) == 0.25
    whole_term = _billed(PriceBasis(unit="total"))
    assert priced_unit_count(listing, selection(listing), 7200, project_billing=whole_term) == 2.0
    with pytest.raises(ValueError, match="reserved selections require an explicit positive duration"):
        priced_unit_count(listing, selection(listing), None, project_billing=whole_term)


def test_without_a_ceiling_payment_is_not_checked():
    listing = shape_priced_listing()
    codec = amount_codec(listing, selection(listing), opening_terms=_terms(vcpu_count=4))
    larger = _terms(gpu_model="H200", gpu_count=1, vcpu_count=8)
    assert codec.payment_from_scalar(10_000, larger) == HOURLY


def test_a_negative_bound_is_refused():
    listing = shape_priced_listing()
    codec = amount_codec(listing, selection(listing))
    with pytest.raises(RuntimeError, match="non-negative"):
        codec.scalar_from_price(-1)


def test_a_price_for_the_opening_shape_scales_the_selected_option_and_rounds_up():
    listing = shape_priced_listing()
    with_advertised_rate(listing, "999")
    priced = priced_at_opening_shape(listing, {"vcpu_count": 4})
    # 999 x 80/100 is 799.2: rounded up, so the derived ceiling converts to at
    # least the advertised minimum for the opening shape.
    assert priced["settlement_options"][0]["price"]["rates"][0]["value"] == "800"
    assert priced["accepted_escrows"] == []
    assert listing["settlement_options"][0]["price"]["rates"][0]["value"] == "999"
    codec = amount_codec(listing, selection(listing), opening_terms=_terms(vcpu_count=4))
    assert codec.scalar_from_price(800) >= 10_000


def test_a_large_derived_price_keeps_every_base_unit():
    listing = shape_priced_listing()
    with_advertised_rate(listing, str(10**18 + 3))
    priced = priced_at_opening_shape(listing, {"vcpu_count": 4})
    initial, ceiling = derive_scalar_prices(
        params={}, matches=[priced], console=Console(quiet=True),
    )
    # 0.8 x (10**18 + 3) rounds up to ...003; through a float it would become
    # 8 x 10**17, which converts to 9,999 basis points.
    assert initial == ceiling == 800_000_000_000_000_003
    codec = amount_codec(listing, selection(listing), opening_terms=_terms(vcpu_count=4))
    assert codec.scalar_from_price(ceiling) == 10_000


def test_an_option_advertising_no_rate_cannot_price_a_shape():
    listing = shape_priced_listing()
    listing["settlement_options"][0]["price"]["rates"] = []
    with pytest.raises(ValueError, match="selected option advertises no rate"):
        shape_hourly_amount(listing, {"settlement_selection": selection(listing)})


def test_without_a_shape_or_family_rates_the_candidate_prices_as_advertised():
    listing = shape_priced_listing()
    assert priced_at_opening_shape(listing, None) == listing
    flat = {key: value for key, value in listing.items() if key != "rate_structure"}
    assert priced_at_opening_shape(flat, {"vcpu_count": 4}) == flat
