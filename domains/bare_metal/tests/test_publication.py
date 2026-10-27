"""Parsing one site's resource-pool projection into a trusted generation.

Rows are built inline in the resource-pool projection's shape; the view inside
each comes from this package's contract fixture, which the producer's own test
validates what it serves against.
"""

from __future__ import annotations

from market_resource_pools_contracts.backing import BACKED, UNBACKED

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import (
    available_bare_metal_listings,
    trusted_bare_metal_projection,
)
from arkhai_bare_metal.fixtures.publication_view import (
    build_bare_metal_publication_view,
)


def _resource(view=None, *, physical_resource_id="resource-1", enabled=True, views=None):
    return {
        "physical_resource_id": physical_resource_id,
        "resource_type": "compute.bare-metal",
        "capacity": {"units": 1, "gpu_count": 8, "ram_gb": 512},
        "available": {"units": 1, "gpu_count": 8, "ram_gb": 512},
        "attributes": {"gpu_model": "H200", "physical_host_id": "physical-host-1"},
        "enabled": enabled,
        "publication_views": (
            views
            if views is not None
            else {
                "bare_metal.v2": view
                or build_bare_metal_publication_view(
                    physical_resource_id,
                    access_methods=["ssh", "serial-console"],
                    capacity={"units": 1, "gpu_count": 8, "ram_gb": 512},
                )
            }
        ),
    }


def _projection(*pools, revision=3, digest="generation-3"):
    return {"revision": revision, "digest": digest, "resource_pools": list(pools)}


def _pool(pool_id="pool-1", *resources):
    return {"pool_id": pool_id, "resources": list(resources or [_resource()])}


def _parse(projection, backings=None):
    """Parse ``projection``, every named pool backed unless ``backings`` says otherwise."""
    if backings is None:
        backings = {
            pool["pool_id"]: BACKED
            for pool in projection.get("resource_pools") or ()
            if pool.get("pool_id")
        }
    return trusted_bare_metal_projection(
        site_id="site-a", projection=projection, backings=backings
    )


def test_interpreter_preserves_distinct_identities_and_listing_semantics():
    generation = _parse(_projection(_pool()))

    (resource,) = generation.resources
    listings = available_bare_metal_listings([resource], backing=BACKED, region="us-west")

    assert (generation.site_id, generation.revision, generation.digest) == (
        "site-a",
        3,
        "generation-3",
    )
    assert resource.physical_resource_id == "resource-1"
    assert resource.pool_id == "pool-1"
    assert listings[0].host_id == "machine-1"
    assert listings[0].physical_host_id == "physical-host-1"
    assert listings[0].access_methods == ["ssh", "serial-console"]
    assert (listings[0].gpu_count, listings[0].gpu_model, listings[0].ram_gb) == (8, "H200", 512)
    assert listings[0].region == "us-west"


def test_the_declaration_is_carried_beside_the_view():
    """The shape is read from what admission matches, not from the view."""
    generation = _parse(_projection(_pool()))

    (resource,) = generation.resources
    assert resource.declared_capacity == {"units": 1, "gpu_count": 8, "ram_gb": 512}
    assert resource.declared_attributes["gpu_model"] == "H200"


def test_publication_only_capabilities_are_accepted_but_never_published():
    view = build_bare_metal_publication_view(
        capacity={"units": 1, "gpu_count": 8, "ram_gb": 512},
        capabilities={"gpu_model": "B200", "ram_gb": 4096},
    )
    generation = _parse(_projection(_pool("pool-1", _resource(view))))

    (listing,) = available_bare_metal_listings(
        generation.resources, backing=BACKED, region="us-west"
    )
    assert (listing.gpu_model, listing.ram_gb) == ("H200", 512)


def test_a_resource_whose_capacity_is_not_a_mapping_refuses_the_generation():
    resource = _resource()
    resource["capacity"] = [1]

    with pytest.raises(ValueError, match="mappings"):
        _parse(_projection(_pool("pool-1", resource)))


def test_unavailable_resource_is_not_listed():
    view = build_bare_metal_publication_view(available=False)
    generation = _parse(_projection(_pool("pool-1", _resource(view))))

    assert available_bare_metal_listings(
        generation.resources, backing=BACKED, region="us-west"
    ) == []


def test_a_disabled_resource_keeps_its_enablement_beside_its_view():
    """The view's ``available`` folds enablement in; the generation keeps the
    declaration's own enablement so a withdrawn declaration is not read as a
    leased machine."""
    view = build_bare_metal_publication_view(available=False)
    generation = _parse(_projection(_pool("pool-1", _resource(view, enabled=False))))

    (resource,) = generation.resources
    assert resource.enabled is False
    assert resource.view.available is False


def test_a_resource_without_a_bare_metal_view_is_not_carried():
    generation = _parse(_projection(_pool("pool-1", _resource(views={}))))

    assert generation.resources == []


def test_authoritative_empty_generation_is_empty():
    assert _parse(_projection()).resources == []


def test_the_containing_pool_is_the_resources_pool():
    view = build_bare_metal_publication_view(pool_id=None)
    generation = _parse(_projection(_pool("pool-2", _resource(view))))

    assert generation.resources[0].pool_id == "pool-2"


def test_a_view_naming_another_pool_refuses_the_generation():
    view = build_bare_metal_publication_view(pool_id="pool-advertising")

    with pytest.raises(ValueError, match="containing pool"):
        _parse(_projection(_pool("pool-not-advertising", _resource(view))))


def test_a_bare_metal_view_under_an_unnamed_pool_refuses_the_generation():
    with pytest.raises(ValueError, match="pool_id"):
        _parse(_projection({"resources": [_resource()]}))


def test_an_unnamed_pool_without_bare_metal_views_is_ignored():
    generation = _parse(
        _projection({"resources": [_resource(views={})]}, _pool("pool-1"))
    )

    assert [item.pool_id for item in generation.resources] == ["pool-1"]


def test_a_resource_without_declared_enablement_refuses_the_generation():
    resource = _resource()
    del resource["enabled"]

    with pytest.raises(ValueError, match="enablement"):
        _parse(_projection(_pool("pool-1", resource)))


def test_interpreter_rejects_conflicting_containing_resource_identity():
    with pytest.raises(ValueError, match="conflicts"):
        _parse(
            _projection(
                _pool(
                    "pool-1",
                    _resource(
                        build_bare_metal_publication_view("resource-1"),
                        physical_resource_id="different-resource",
                    ),
                )
            )
        )


def test_interpreter_requires_explicit_machine_identity():
    view = build_bare_metal_publication_view()
    view.pop("host_id")

    with pytest.raises(ValidationError):
        _parse(_projection(_pool("pool-1", _resource(view))))


def test_a_backed_view_without_availability_refuses_the_generation():
    view = build_bare_metal_publication_view()
    view.pop("available")

    with pytest.raises(ValueError, match="available"):
        _parse(_projection(_pool("pool-1", _resource(view))))


def test_one_view_contradicting_its_pools_backing_refuses_the_generation():
    """A host-bearing view in an unbacked pool is as malformed as a view naming
    another pool: the whole generation is refused, its consistent pool too."""
    unbacked = _pool(
        "pool-unbacked",
        _resource(
            build_bare_metal_publication_view("resource-2", pool_id="pool-unbacked"),
            physical_resource_id="resource-2",
        ),
    )

    with pytest.raises(ValueError, match="host_id"):
        _parse(
            _projection(_pool("pool-1"), unbacked),
            backings={"pool-1": BACKED, "pool-unbacked": UNBACKED},
        )


def test_an_unbacked_view_yields_a_listing_with_no_delivery_terms():
    view = build_bare_metal_publication_view(backing=UNBACKED)
    generation = _parse(
        _projection(_pool("pool-1", _resource(view))), backings={"pool-1": UNBACKED}
    )

    (listing,) = available_bare_metal_listings(
        generation.resources, backing=UNBACKED, region="us-west"
    )

    assert listing.capacity_backing == "unbacked"
    assert (listing.host_id, listing.physical_host_id, listing.access_methods) == (
        None,
        None,
        None,
    )
    assert (listing.gpu_count, listing.gpu_model) == (8, "H200")


def test_an_unbacked_view_stating_an_empty_term_yields_a_listing_without_it():
    """Empty is absent to the delegate, so the carrier accepts it; the listing
    carries none of an unbacked view's terms all the same."""
    view = build_bare_metal_publication_view(backing=UNBACKED)
    view["access_methods"] = []
    generation = _parse(
        _projection(_pool("pool-1", _resource(view))), backings={"pool-1": UNBACKED}
    )

    (listing,) = available_bare_metal_listings(
        generation.resources, backing=UNBACKED, region="us-west"
    )

    assert "access_methods" not in listing.model_dump(exclude_none=True)


def test_a_pool_absent_from_its_backings_is_carried_unchecked():
    """A pool whose declarations do not resolve has no backing to hold its
    views to; it is carried for its reader to hold."""
    view = build_bare_metal_publication_view(backing=UNBACKED)

    generation = _parse(_projection(_pool("pool-1", _resource(view))), backings={})

    (resource,) = generation.resources
    assert resource.capacity_backing is None
    assert resource.view.host_id is None


def _unbuildable(problems, *, physical_resource_id="resource-2", view=None):
    """A resource the site built no bare-metal view for, naming why."""
    resource = _resource(physical_resource_id=physical_resource_id, views={})
    if view is not None:
        resource["publication_views"] = {"bare_metal.v2": view}
    resource["publication_view_problems"] = {"bare_metal.v2": problems}
    return resource


def test_a_resource_the_site_built_no_view_for_is_named_with_its_problems():
    generation = _parse(
        _projection(_pool("pool-1", _resource(), _unbuildable(["host_id: required"])))
    )

    assert [item.physical_resource_id for item in generation.resources] == ["resource-1"]
    (unbuildable,) = generation.view_problems
    assert (
        unbuildable.pool_id,
        unbuildable.physical_resource_id,
        unbuildable.enabled,
        unbuildable.problems,
    ) == ("pool-1", "resource-2", True, ("host_id: required",))


def test_another_views_problem_is_not_bare_metals():
    resource = _resource()
    resource["publication_view_problems"] = {"vm.v1": ["not a VM"]}

    assert _parse(_projection(_pool("pool-1", resource))).view_problems == []


@pytest.mark.parametrize(
    "resource",
    [
        pytest.param(
            _unbuildable(["host_id: required"], view=build_bare_metal_publication_view(
                "resource-2"
            )),
            id="view-and-problem",
        ),
        pytest.param(_unbuildable("host_id: required"), id="problems-not-a-list"),
        pytest.param(_unbuildable([]), id="no-problem-named"),
        pytest.param(_unbuildable(["  "]), id="blank-problem"),
    ],
)
def test_a_malformed_view_problem_refuses_the_generation(resource):
    with pytest.raises(ValueError):
        _parse(_projection(_pool("pool-1", resource)))


@pytest.mark.parametrize(
    "first",
    [
        pytest.param(lambda: _resource(), id="viewed-and-unbuildable"),
        pytest.param(
            lambda: _unbuildable(["access_methods: required"], physical_resource_id="resource-1"),
            id="unbuildable-twice",
        ),
    ],
)
def test_a_resource_reported_twice_refuses_the_generation(first):
    """One Physical Resource the site reported in two pools, viewed in one and
    unbuildable in the other or unbuildable in both, would be classified twice."""
    projection = _projection(
        _pool("pool-1", first()),
        _pool("pool-2", _unbuildable(["host_id: required"], physical_resource_id="resource-1")),
    )

    with pytest.raises(ValueError, match="unique within a site"):
        _parse(projection)


def test_a_projection_without_a_generation_identity_is_refused():
    with pytest.raises(ValidationError):
        _parse({"resource_pools": []})


def test_a_projection_without_pools_is_refused():
    with pytest.raises(ValueError, match="resource_pools"):
        _parse({"revision": 1, "digest": "d"})
