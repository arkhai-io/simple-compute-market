"""Contract fixtures for the resource-pool projection.

The shape of ``SiteCapacityClient.resource_pool_projection()``: every Resource
Pool at a site with its metadata and projected members. A site authority produces
it, and a storefront derives listings from it. The pair keeps the two sides on one
shape:

- ``build_resource_pool_projection()`` and its row builders construct a canonical
  response for a consumer test to supply where a site would.
- ``validate_resource_pool_projection()`` asserts that a response real code
  produced has that shape. A producer test calls it on what the canonical client
  returned.

Only the fields a consumer depends on are checked: pool identity, enablement, the
advertisement, backing, and delivery declarations, and each member's identity,
resource kind, enablement, capacity, availability, and attributes. A storefront
judges whether a member can serve a listing's claim by its resource kind, so a
member must state one. A current producer projects
metadata on every pool; a producer that predates the declarations is a consumer
concern, read under the older-producer rule, and is not this contract.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

_BACKING_VALUES = frozenset({"backed", "unbacked"})


def build_projected_resource(
    physical_resource_id: str,
    *,
    capacity: Mapping[str, int] | None = None,
    available: Mapping[str, int] | None = None,
    attributes: Mapping[str, Any] | None = None,
    enabled: bool = True,
    resource_type: str = "compute.gpu",
    publication_views: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """One projected pool member. ``available`` defaults to its capacity.

    ``resource_type`` defaults to the kind a site ledger records for a
    declaration that names none. ``publication_views`` maps a view name to the
    domain-owned view the site projects for the member; each view's own shape
    is that domain's contract, not this one. A member with no views projects
    none, as a site does.
    """
    capacity = dict(capacity if capacity is not None else {"gpu_count": 1})
    resource: dict[str, Any] = {
        "physical_resource_id": physical_resource_id,
        "resource_type": resource_type,
        "resource_subtype": None,
        "capacity": capacity,
        "available": dict(available if available is not None else capacity),
        "attributes": dict(attributes or {}),
        "enabled": enabled,
    }
    if publication_views is not None:
        resource["publication_views"] = {
            str(name): dict(view) for name, view in publication_views.items()
        }
    return resource


def build_resource_pool_row(
    pool_id: str,
    *,
    capacity_backing: str = "backed",
    advertisable_modes: Sequence[str] = ("vm",),
    deliverable_modes: Sequence[str] | None = None,
    enabled: bool = True,
    policy_tags: Mapping[str, Any] | None = None,
    resources: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """One projected pool with both declarations.

    A backed pool delivers what it advertises unless told otherwise; an unbacked
    pool delivers nothing, as the pool contract requires.
    """
    if deliverable_modes is None:
        deliverable_modes = advertisable_modes if capacity_backing == "backed" else ()
    return {
        "pool_id": pool_id,
        "resources": [
            dict(resource)
            for resource in (
                resources
                if resources is not None
                else [build_projected_resource(f"{pool_id}-res")]
            )
        ],
        "pool_metadata": {
            "label": pool_id,
            "enabled": enabled,
            "mechanism": "ansible",
            "policy_tags": {
                "deliverable_modes": list(deliverable_modes),
                "advertisable_modes": list(advertisable_modes),
                "capacity_backing": capacity_backing,
                **dict(policy_tags or {}),
            },
            "pool_views": {},
        },
    }


def build_resource_pool_projection(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """A projection response carrying the given pool rows."""
    return {"resource_pools": [dict(row) for row in rows]}


def _modes(value: Any, field: str) -> None:
    assert isinstance(value, list), f"{field} must be a list, got {value!r}"
    assert all(isinstance(mode, str) and mode for mode in value), (
        f"{field} must name non-empty modes, got {value!r}"
    )


def _counts(value: Any, field: str) -> None:
    assert isinstance(value, Mapping), f"{field} must be a mapping, got {value!r}"
    assert all(
        isinstance(name, str) and isinstance(count, int) and not isinstance(count, bool)
        for name, count in value.items()
    ), f"{field} must map dimension names to integers, got {value!r}"


def validate_resource_pool_projection(response: Mapping[str, Any]) -> None:
    """Assert a real projection response has the shape consumers derive from."""
    rows = response.get("resource_pools")
    assert isinstance(rows, list), "response must carry a resource_pools list"
    for row in rows:
        pool_id = row.get("pool_id")
        assert isinstance(pool_id, str) and pool_id, f"pool without an id: {row!r}"
        metadata = row.get("pool_metadata")
        assert isinstance(metadata, Mapping), f"pool {pool_id} projects no metadata"
        assert isinstance(metadata.get("enabled"), bool), (
            f"pool {pool_id} must project its enablement"
        )
        tags = metadata.get("policy_tags")
        assert isinstance(tags, Mapping), f"pool {pool_id} projects no policy tags"
        assert tags.get("capacity_backing") in _BACKING_VALUES, (
            f"pool {pool_id} backing {tags.get('capacity_backing')!r}"
        )
        _modes(tags.get("advertisable_modes"), f"pool {pool_id} advertisable_modes")
        _modes(tags.get("deliverable_modes"), f"pool {pool_id} deliverable_modes")
        resources = row.get("resources")
        assert isinstance(resources, list), f"pool {pool_id} has no resource list"
        for resource in resources:
            resource_id = resource.get("physical_resource_id")
            assert isinstance(resource_id, str) and resource_id, (
                f"pool {pool_id} member without an id: {resource!r}"
            )
            resource_type = resource.get("resource_type")
            assert isinstance(resource_type, str) and resource_type.strip(), (
                f"member {resource_id} must project its resource_type"
            )
            assert isinstance(resource.get("enabled"), bool), (
                f"member {resource_id} must project its enablement"
            )
            _counts(resource.get("capacity"), f"member {resource_id} capacity")
            if "available" in resource:
                _counts(resource["available"], f"member {resource_id} available")
            assert isinstance(resource.get("attributes"), Mapping), (
                f"member {resource_id} must project its attributes"
            )


__all__ = [
    "build_projected_resource",
    "build_resource_pool_projection",
    "build_resource_pool_row",
    "validate_resource_pool_projection",
]
