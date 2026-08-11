from __future__ import annotations

import pytest
from arkhai_vms.listing_models import Listing
from pydantic import ValidationError


def _listing(pool_id=None, resource_id=None):
    return {
        "listing_id": "lst-test",
        "seller": "http://seller.test",
        "offer_resource": {
            "resource_type": "compute",
            "gpu_model": "H200",
            "gpu_count": 1,
            "region": "California, US",
            "sla": 99.0,
            "pool_id": pool_id,
            "resource_id": resource_id,
        },
        "accepted_escrows": [],
    }


@pytest.mark.parametrize(
    ("pool_id", "resource_id"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        (None, ""),
        ("bad/id", None),
        (None, "bad id"),
    ],
)
def test_compute_listing_rejects_missing_blank_or_malformed_identity(
    pool_id, resource_id
):
    with pytest.raises(ValidationError):
        Listing.model_validate(_listing(pool_id=pool_id, resource_id=resource_id))


def test_compute_listing_normalizes_capacity_identity_whitespace():
    listing = Listing.model_validate(_listing(pool_id="  pool-A  "))
    assert listing.offer_resource.pool_id == "pool-A"


def test_compute_listing_allows_both_capacity_identities():
    listing = Listing.model_validate(_listing(pool_id="pool-A", resource_id="res-1"))
    assert listing.offer_resource.pool_id == "pool-A"
    assert listing.offer_resource.resource_id == "res-1"
