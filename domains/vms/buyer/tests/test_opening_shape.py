"""The buyer's opening shape and its domain record of a registry listing."""

from __future__ import annotations

import pytest
import typer
from arkhai_vms_listings.models import Listing

from arkhai_vms_buyer.negotiation_amounts import amount_codec
from arkhai_vms_buyer.opening_shape import parse_shape_option, shape_excess
from arkhai_vms_buyer.registry_listing import domain_listing_record
from identity_helpers import seller_principals
from test_negotiation_amounts import HOURLY, RATE_STRUCTURE, selection, shape_priced_listing


def registry_listing() -> dict:
    """A listing as a registry's discovery serves it.

    Family rates only in its pricing, and the publisher's identity as the
    registry states it, never the storefront ``Listing``'s ``seller_principal``.
    """
    listing = shape_priced_listing()
    listing["pricing"] = {"rate_structure": listing.pop("rate_structure")}
    del listing["seller_principal"]
    listing["publisher_id"] = "publisher-1"
    listing["publisher_principals"] = seller_principals().model_dump(mode="json")
    return listing


def test_a_shape_option_states_positive_quantities():
    assert parse_shape_option(None) is None
    assert parse_shape_option("gpu_count=1, vcpu_count=8,ram_gb=64") == {
        "gpu_count": 1, "vcpu_count": 8, "ram_gb": 64,
    }


@pytest.mark.parametrize("raw,named", [
    ("vcpu_count", "not a quantity=value pair"),
    ("vcpu_count=4,", "not a quantity=value pair"),
    ("gpu_model=H200", "not a capacity quantity"),
    ("vcpu_count=4,vcpu_count=8", "stated twice"),
    ("vcpu_count=0", "positive whole number"),
    ("ram_gb=1.5", "positive whole number"),
])
def test_a_malformed_shape_option_is_refused(raw, named):
    with pytest.raises(typer.BadParameter, match=named):
        parse_shape_option(raw)


def test_a_shape_within_the_advertised_one_has_no_excess():
    assert shape_excess({"gpu_count": 1, "vcpu_count": 4}, shape_priced_listing()) == ()


def test_each_quantity_above_the_advertised_one_is_named():
    assert shape_excess({"vcpu_count": 16, "ram_gb": 64}, shape_priced_listing()) == (
        "vcpu_count 16 exceeds the advertised 8",
        "ram_gb 64 exceeds the advertised 0",
    )


def test_the_domain_record_reads_family_rates_from_the_registrys_pricing():
    served = registry_listing()
    record = domain_listing_record(served)
    assert record["rate_structure"] == RATE_STRUCTURE
    assert "rate_structure" not in served
    assert domain_listing_record({"listing_id": "L-flat"}) == {"listing_id": "L-flat"}


def test_a_registry_listing_negotiates_in_multiplier_mode_through_its_domain_record():
    served = registry_listing()
    assert amount_codec(served, selection(served)) is None
    codec = amount_codec(domain_listing_record(served), selection(served))
    assert codec.scalar_from_price(HOURLY) == 10_000


def test_the_listing_model_reads_and_publishes_the_registry_format():
    stored = {
        **registry_listing(),
        "seller_principal": shape_priced_listing()["seller_principal"],
    }
    listing = Listing.model_validate(stored)
    assert listing.rate_structure == RATE_STRUCTURE
    assert listing.published_pricing() == {"rate_structure": RATE_STRUCTURE}
