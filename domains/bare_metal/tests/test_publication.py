from __future__ import annotations

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import (
    available_bare_metal_listings,
    bare_metal_listing_key,
    trusted_bare_metal_projection,
)


def _view(**overrides):
    value = {
        "physical_resource_id": "resource-1",
        "physical_host_id": "physical-host-1",
        "machine_id": "machine-1",
        "available": True,
        "allocation_mode": "exclusive",
        "access_methods": ["ssh", "serial-console"],
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "capabilities": {"gpu_model": "H200", "ram_gb": 512},
    }
    value.update(overrides)
    return value


def _resource(view=None, **overrides):
    value = {
        "physical_resource_id": "resource-1",
        "publication_views": {"bare_metal.v1": view or _view()},
    }
    value.update(overrides)
    return value


def test_interpreter_preserves_distinct_identities_and_listing_semantics():
    generation = trusted_bare_metal_projection(
        site_id="site-a",
        revision=3,
        digest="generation-3",
        resource_pools=[{"resource_pool_id": "pool-1", "resources": [_resource()]}],
        complete=True,
    )

    listings = available_bare_metal_listings(generation.resources)

    assert generation.site_id == "site-a"
    assert generation.resources[0].physical_resource_id == "resource-1"
    assert listings[0].machine_id == "machine-1"
    assert listings[0].physical_host_id == "physical-host-1"
    assert listings[0].access_methods == ["ssh", "serial-console"]
    assert listings[0].capabilities == {
        "gpu_count": 8,
        "ram_gb": 512,
        "gpu_model": "H200",
    }
    assert listings[0].site is None


def test_unavailable_resource_is_not_listed():
    generation = trusted_bare_metal_projection(
        site_id="site-a",
        revision=4,
        digest="generation-4",
        resource_pools=[{
            "resource_pool_id": "pool-1",
            "resources": [_resource(_view(available=False))],
        }],
        complete=True,
    )

    assert available_bare_metal_listings(generation.resources) == []


def test_incomplete_generation_ignores_partial_remote_rows():
    generation = trusted_bare_metal_projection(
        site_id="site-a",
        revision=4,
        digest="unavailable",
        resource_pools=[{"resources": [_resource()]}],
        complete=False,
    )

    assert generation.complete is False
    assert generation.resources == []


def test_authoritative_empty_generation_remains_complete():
    generation = trusted_bare_metal_projection(
        site_id="site-a",
        revision=5,
        digest="empty",
        resource_pools=[],
        complete=True,
    )

    assert generation.complete is True
    assert generation.resources == []


def test_stale_complete_generation_remains_usable():
    generation = trusted_bare_metal_projection(
        site_id="site-a",
        revision=3,
        digest="generation-3",
        resource_pools=[{"resources": [_resource()]}],
        complete=True,
        stale=True,
    )

    assert generation.stale is True
    assert len(available_bare_metal_listings(generation.resources)) == 1


def test_interpreter_rejects_conflicting_containing_resource_identity():
    with pytest.raises(ValueError, match="conflicts"):
        trusted_bare_metal_projection(
            site_id="site-a",
            revision=1,
            digest="bad",
            resource_pools=[{
                "resources": [
                    _resource(physical_resource_id="different-resource"),
                ],
            }],
            complete=True,
        )


def test_interpreter_requires_explicit_machine_identity():
    view = _view()
    view.pop("machine_id")

    with pytest.raises(ValidationError):
        trusted_bare_metal_projection(
            site_id="site-a",
            revision=1,
            digest="bad",
            resource_pools=[{"resources": [_resource(view)]}],
            complete=True,
        )


def test_derivation_key_is_site_and_resource_scoped():
    assert bare_metal_listing_key(
        site_id="site-a",
        physical_resource_id="resource-1",
    ) != bare_metal_listing_key(
        site_id="site-b",
        physical_resource_id="resource-1",
    )


def test_derivation_key_requires_nonempty_site_id():
    with pytest.raises(ValueError):
        bare_metal_listing_key(site_id="", physical_resource_id="resource-1")


def test_derivation_key_requires_nonempty_physical_resource_id():
    with pytest.raises(ValueError):
        bare_metal_listing_key(site_id="site-a", physical_resource_id="   ")


def test_no_collision_when_a_colon_shifts_the_field_boundary():
    """site_id/physical_resource_id are operator-chosen strings with no
    character restrictions -- a naive colon-delimited join would let
    (site_id='a', physical_resource_id='b:c') and
    (site_id='a:b', physical_resource_id='c') produce an identical
    string. The length-prefixed encoding must not collide here."""
    assert bare_metal_listing_key(
        site_id="a", physical_resource_id="b:c",
    ) != bare_metal_listing_key(
        site_id="a:b", physical_resource_id="c",
    )


def test_no_collision_across_many_boundary_shifts():
    pairs = [
        ("a", "bcde"), ("ab", "cde"), ("abc", "de"), ("abcd", "e"),
    ]
    keys = {
        bare_metal_listing_key(site_id=site, physical_resource_id=resource)
        for site, resource in pairs
    }
    assert len(keys) == len(pairs)
