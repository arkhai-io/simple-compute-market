"""A VM listing as a registry publication carries it.

The listing model splits what it stores into the capacity description and the
one ``pricing`` object a registry publication carries; the storefront's
candidate codec composes both onto the publication.
"""

from __future__ import annotations

from arkhai_vms_listings.models import Listing

_RATE = {"amount": "2.10", "asset": "usd", "period": "hour"}
_STRUCTURE = {
    "gpu": [{"asset": "usd", "rate": "80", "per": "hour"}],
    "memory": [{"asset": "usd", "rate": "1", "per": "hour"}],
}


def _listing(*, asking_rate=None, rate_structure=None) -> Listing:
    resource = {
        "resource_type": "compute",
        "gpu_model": "H200",
        "gpu_count": 1,
        "region": "California, US",
        "sla": 99.0,
        "pool_id": "pool-A",
    }
    if asking_rate is not None:
        resource["asking_rate"] = asking_rate
    return Listing.model_validate(
        {
            "listing_id": "lst-test",
            "storefront_url": "http://seller.test",
            "seller_principal": {
                "scheme": "eip191",
                "identifier": "0x2222222222222222222222222222222222222222",
            },
            "listing_resource": resource,
            "accepted_escrows": [],
            "rate_structure": rate_structure,
        }
    )


def test_a_listing_stating_no_price_publishes_no_pricing() -> None:
    assert _listing().published_pricing() is None


def test_an_asking_rate_alone_is_published_in_pricing() -> None:
    assert _listing(asking_rate=_RATE).published_pricing() == {"asking_rate": _RATE}


def test_a_rate_structure_alone_is_published_in_pricing() -> None:
    assert _listing(rate_structure=_STRUCTURE).published_pricing() == {
        "rate_structure": _STRUCTURE
    }


def test_both_prices_travel_together() -> None:
    assert _listing(asking_rate=_RATE, rate_structure=_STRUCTURE).published_pricing() == {
        "asking_rate": _RATE,
        "rate_structure": _STRUCTURE,
    }


def test_the_published_capacity_states_no_price_and_no_null() -> None:
    listing = _listing(asking_rate=_RATE)

    published = listing.published_listing_resource()

    assert "asking_rate" not in published
    assert None not in published.values()
    assert published["gpu_model"] == "H200"
    # The stored view keeps the rate beside the shape it prices.
    assert listing.listing_resource.asking_rate.amount == "2.10"
