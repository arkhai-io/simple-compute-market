"""Contract fixtures for the bare-metal publication view.

The view is what a site projects for each Physical Resource offered as a whole
machine, under ``publication_views["bare_metal.v2"]`` in the resource-pool
projection. The provisioning service produces it and a bare-metal storefront
derives listings from it. This domain package owns the vocabulary and both
sides install it, so the pair lives here:

- ``build_bare_metal_publication_view()`` constructs a canonical view for a
  consumer test to place in a projected resource's ``publication_views``.
- ``validate_bare_metal_publication_view()`` asserts that a view real code
  produced has that shape. The producer's capacity-inventory test calls it.
- ``build_bare_metal_projected_resource()`` wraps a view in the projected
  resource a site serves it in, with the declared capacity and attributes a
  listing's shape is read from.

Only what a consumer depends on is checked: the Physical Resource and host it
names, the pool it repeats, whether the whole machine is available, and the
public fields a listing is built from.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from arkhai_bare_metal.projections import BareMetalResourceProjection


def build_bare_metal_publication_view(
    physical_resource_id: str = "resource-1",
    *,
    pool_id: str | None = "pool-1",
    host_id: str = "machine-1",
    physical_host_id: str = "physical-host-1",
    available: bool = True,
    access_methods: Sequence[str] = ("ssh",),
    capacity: Mapping[str, Any] | None = None,
    capabilities: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One canonical view, as a site serializes it.

    The view repeats the declaration's capacity. It carries no publication-only
    ``capabilities`` unless a test supplies some to prove they are ignored.
    """
    return {
        "physical_resource_id": physical_resource_id,
        "pool_id": pool_id,
        "physical_host_id": physical_host_id,
        "host_id": host_id,
        "available": available,
        "allocation_mode": "exclusive",
        "access_methods": list(access_methods),
        "capacity": dict(capacity if capacity is not None else DEFAULT_CAPACITY),
        "capabilities": dict(capabilities or {}),
    }


#: A whole machine: one unit, holding eight GPUs and 2 TiB of memory.
DEFAULT_CAPACITY: Mapping[str, Any] = {"units": 1, "gpu_count": 8, "ram_gb": 2048}
DEFAULT_GPU_MODEL = "H200"


def build_bare_metal_projected_resource(
    physical_resource_id: str = "resource-1",
    *,
    pool_id: str = "pool-1",
    enabled: bool = True,
    capacity: Mapping[str, Any] | None = None,
    attributes: Mapping[str, Any] | None = None,
    view: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One projected resource carrying its declaration and its bare-metal view.

    ``attributes`` defaults to the declaration a whole-host seller registers:
    the GPU model admission matches, and the accounting facts the site reads.
    """
    declared_capacity = dict(capacity if capacity is not None else DEFAULT_CAPACITY)
    declared_attributes = dict(
        attributes
        if attributes is not None
        else {
            "gpu_model": DEFAULT_GPU_MODEL,
            "physical_host_id": "physical-host-1",
            "allocation_mode": "exclusive",
        }
    )
    return {
        "physical_resource_id": physical_resource_id,
        "pool_id": pool_id,
        "resource_type": "compute.bare-metal",
        "capacity": declared_capacity,
        "attributes": declared_attributes,
        "enabled": enabled,
        "publication_views": {
            "bare_metal.v2": dict(
                view
                if view is not None
                else build_bare_metal_publication_view(
                    physical_resource_id,
                    pool_id=pool_id,
                    available=enabled,
                    capacity=declared_capacity,
                )
            ),
        },
    }


def validate_bare_metal_publication_view(
    view: Mapping[str, Any],
    *,
    physical_resource_id: str | None = None,
    pool_id: str | None = None,
) -> None:
    """Assert a view real code produced has the shape consumers derive from.

    When the caller names the containing resource or pool, the view must
    repeat exactly those: a consumer refuses a site generation whose view
    disagrees with its container.
    """
    BareMetalResourceProjection.model_validate(view)
    assert isinstance(view.get("available"), bool), "view must state availability"
    for field in ("physical_resource_id", "host_id", "physical_host_id"):
        value = view.get(field)
        assert isinstance(value, str) and value.strip(), f"view must name its {field}"
    if physical_resource_id is not None:
        assert view["physical_resource_id"] == physical_resource_id, (
            f"view names {view['physical_resource_id']!r}, "
            f"its container {physical_resource_id!r}"
        )
    if pool_id is not None:
        assert view.get("pool_id") == pool_id, (
            f"view names pool {view.get('pool_id')!r}, its container {pool_id!r}"
        )


__all__ = [
    "DEFAULT_CAPACITY",
    "DEFAULT_GPU_MODEL",
    "build_bare_metal_projected_resource",
    "build_bare_metal_publication_view",
    "validate_bare_metal_publication_view",
]
