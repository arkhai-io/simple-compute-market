"""The Alkahest delivery facts' lease terms for a VM listing.

The terms state what the deal committed to, so a GPU field the listing does not
state is left out, never written as ``null``.
"""

from __future__ import annotations

import json

from arkhai_vms_listings.models import ComputeResource, ERC20TokenMetadata, TokenResource
from arkhai_vms_settlement import encode_compute_lease

# A deterministic development token address; never used on any network.
_TOKEN = TokenResource(
    token=ERC20TokenMetadata(
        symbol="USDT", contract_address="0x" + "11" * 20, decimals=6
    ),
    amount=2_000_000,
)

_GPU = {"gpu_model": "H100", "gpu_count": 2, "sla": 99.0, "region": "us-east"}


def test_a_listing_without_gpus_states_no_gpu_term():
    resource = ComputeResource(vcpu_count=8, ram_gb=32, sla=99.0, region="us-east")

    terms = json.loads(encode_compute_lease(resource, _TOKEN, 7200))

    assert "gpu_model" not in terms and "gpu_count" not in terms
    with_gpus = json.loads(encode_compute_lease(ComputeResource(**_GPU), _TOKEN, 7200))
    assert terms == {
        key: value for key, value in with_gpus.items() if key not in ("gpu_model", "gpu_count")
    }


def test_a_gpu_listings_terms_are_the_same_bytes():
    encoded = encode_compute_lease(ComputeResource(**_GPU), _TOKEN, 7200)

    assert encoded == json.dumps(
        {
            "gpu_model": "H100",
            "region": "us-east",
            "gpu_count": 2,
            "sla": 99.0,
            "duration_seconds": 7200,
            "token_symbol": "USDT",
            "token_address": "0x" + "11" * 20,
            "price_per_hour_decimal": 2.0,
            "total_price_decimal": 4.0,
            "total_price_int": 4_000_000,
        }
    ).encode("utf-8")
