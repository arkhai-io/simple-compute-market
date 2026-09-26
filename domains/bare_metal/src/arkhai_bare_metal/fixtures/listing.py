"""Contract fixtures for the bare-metal listing payload.

``build_bare_metal_listing_resource()`` constructs the listing resource a
bare-metal storefront publishes, for consumer tests that need a valid listing
without deriving one; ``LISTING_HARDWARE`` is the published shape and region
alone, for tests that build the rest themselves. The storefront's publication
tests assert real derivation against ``BareMetalListing`` itself, which is the
validator here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The region and whole-machine shape a default fixture listing publishes.
LISTING_HARDWARE: Mapping[str, Any] = {
    "region": "us-west",
    "gpu_count": 8,
    "gpu_model": "H200",
    "ram_gb": 2048,
}


def build_bare_metal_listing_resource(**overrides: Any) -> dict[str, Any]:
    """A complete bare-metal listing resource; ``overrides`` replace fields."""
    return {
        "capacity_backing": "backed",
        "host_id": "machine-1",
        "physical_host_id": "physical-host-1",
        **LISTING_HARDWARE,
        **overrides,
    }


__all__ = ["LISTING_HARDWARE", "build_bare_metal_listing_resource"]
