from __future__ import annotations

from arkhai_bare_metal import (
    BARE_METAL_SCHEMA_KIND,
    available_bare_metal_listings,
    bare_metal_listing_key,
)


def _resource(
    resource_id: str,
    *,
    available_units: int = 1,
    enabled: bool = True,
    attributes: dict | None = None,
) -> dict:
    return {
        "resource_id": resource_id,
        "available_units": available_units,
        "enabled": enabled,
        "attributes": attributes or {},
    }


def test_available_bare_metal_listings_derive_exclusive_host_payloads():
    listings = available_bare_metal_listings(
        [
            _resource(
                "bare-metal-node-1",
                attributes={
                    "allocation_mode": "exclusive",
                    "physical_host_id": "host-physical-1",
                    "machine_id": "bm-node-1",
                    "gpu_model": "H200",
                    "ram_gb": 512,
                },
            ),
        ],
        min_duration_seconds=3600,
        max_duration_seconds=7200,
        site={"region": "us-west"},
    )

    assert len(listings) == 1
    listing = listings[0]
    assert listing.kind == BARE_METAL_SCHEMA_KIND
    assert listing.machine_id == "bm-node-1"
    assert listing.physical_host_id == "host-physical-1"
    assert listing.min_duration_seconds == 3600
    assert listing.max_duration_seconds == 7200
    assert listing.site == {"region": "us-west"}
    assert listing.capabilities == {"gpu_model": "H200", "ram_gb": 512}


def test_available_bare_metal_listings_skip_shareable_vm_slices():
    listings = available_bare_metal_listings(
        [
            _resource(
                "host-1-vm-gpus",
                attributes={
                    "allocation_mode": "shareable",
                    "physical_host_id": "host-physical-1",
                    "vm_host": "kvm1",
                },
            ),
        ]
    )

    assert listings == []


def test_available_bare_metal_listings_skip_conflict_blocked_or_disabled_hosts():
    listings = available_bare_metal_listings(
        [
            _resource(
                "blocked",
                available_units=0,
                attributes={
                    "allocation_mode": "exclusive",
                    "physical_host_id": "host-physical-1",
                },
            ),
            _resource(
                "disabled",
                enabled=False,
                attributes={
                    "allocation_mode": "exclusive",
                    "physical_host_id": "host-physical-2",
                },
            ),
        ]
    )

    assert listings == []


def test_available_bare_metal_listings_defaults_machine_id_to_resource_id():
    listings = available_bare_metal_listings(
        [
            _resource(
                "bare-metal-node-1",
                attributes={
                    "allocation_mode": "exclusive",
                    "physical_host_id": "host-physical-1",
                },
            ),
        ]
    )

    assert listings[0].machine_id == "bare-metal-node-1"


def test_bare_metal_listing_key_is_stable_per_machine():
    assert bare_metal_listing_key("bm-node-1") == "bare-metal:bm-node-1"
