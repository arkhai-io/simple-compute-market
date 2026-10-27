"""Classification and listing comparison, with no storefront state."""

from __future__ import annotations

import pytest
from market_resource_pools_contracts.backing import BACKED, UNBACKED

from arkhai_bare_metal import (
    CANDIDATE,
    HELD,
    BACKING_CHANGED,
    IDENTITY_CHANGED,
    POOL_ADMITTED,
    POOL_HELD,
    POOL_NOT_ADMITTED,
    REFRESH,
    UNAVAILABLE,
    UNCHANGED,
    WITHDRAWN,
    BareMetalResourceProjection,
    BareMetalViewProblems,
    TrustedBareMetalProjection,
    TrustedBareMetalResource,
    bare_metal_source_identity,
    classify_bare_metal_resources,
    compare_bare_metal_listing,
    listing_terms,
)
from arkhai_bare_metal.fixtures.publication_view import (
    DEFAULT_CAPACITY,
    build_bare_metal_publication_view,
)
from market_capability_shape import shape_digest

SHAPE = {"gpu": {"count": 8, "model": "H200"}, "memory": {"gib": 2048}}



class _EveryPoolBacked(dict):
    """Every pool these cases name declares capacity backing."""

    def get(self, key, default=None):
        return BACKED


_BACKED = _EveryPoolBacked()

def _resource(
    resource_id,
    *,
    pool_id="pool-1",
    enabled=True,
    available=True,
    capacity=None,
    attributes=None,
    capabilities=None,
    backing=BACKED,
):
    return TrustedBareMetalResource(
        pool_id=pool_id,
        enabled=enabled,
        view=BareMetalResourceProjection.model_validate(
            build_bare_metal_publication_view(
                resource_id,
                backing=backing,
                pool_id=pool_id,
                host_id=f"machine-{resource_id}",
                physical_host_id=f"physical-{resource_id}",
                available=available,
                capabilities=capabilities,
            )
        ),
        declared_capacity=dict(DEFAULT_CAPACITY if capacity is None else capacity),
        declared_attributes=dict(
            {"gpu_model": "H200"} if attributes is None else attributes
        ),
    )


def _regions(*pool_ids, region="us-west"):
    return {pool_id: region for pool_id in pool_ids}


def _generation(*resources):
    return TrustedBareMetalProjection(
        site_id="site-a", revision=4, digest="generation-4", resources=list(resources)
    )


def _classes(classification):
    return {
        item.physical_resource_id: item.classification
        for item in classification.resources
    }


def test_each_resource_falls_into_exactly_one_class():
    generation = _generation(
        _resource("free"),
        _resource("leased", available=False),
        _resource("disabled", enabled=False),
        # The site's view says unavailable for a disabled declaration too; the
        # declaration's own enablement decides, so this is withdrawn.
        _resource("disabled-and-busy", enabled=False, available=False),
        _resource("unknown-pool", pool_id="pool-unresolved"),
        _resource("not-advertised", pool_id="pool-vm-only"),
        _resource("unnamed-pool", pool_id="pool-missing"),
    )

    classification = classify_bare_metal_resources(
        generation,
        pool_backings=_BACKED,
        pool_admission={
            "pool-1": POOL_ADMITTED,
            "pool-unresolved": POOL_HELD,
            "pool-vm-only": POOL_NOT_ADMITTED,
        },
        pool_regions=_regions("pool-1", "pool-unresolved", "pool-vm-only"),
    )

    assert _classes(classification) == {
        "free": CANDIDATE,
        "leased": UNAVAILABLE,
        "disabled": WITHDRAWN,
        "disabled-and-busy": WITHDRAWN,
        "unknown-pool": HELD,
        "not-advertised": WITHDRAWN,
        "unnamed-pool": WITHDRAWN,
    }
    assert len(classification.resources) == len(generation.resources)
    assert [c["physical_resource_id"] for c in classification.candidates] == ["free"]


def test_availability_bounds_only_backed_supply():
    """An unbacked view states no availability, and its resource is a candidate
    without one."""
    classification = classify_bare_metal_resources(
        _generation(_resource("unbacked", backing=UNBACKED)),
        pool_backings={"pool-1": UNBACKED},
        pool_admission={"pool-1": POOL_ADMITTED},
        pool_regions=_regions("pool-1"),
    )

    assert _classes(classification) == {"unbacked": CANDIDATE}
    (candidate,) = classification.candidates
    assert candidate["listing_resource"]["capacity_backing"] == "unbacked"


def test_an_unbacked_candidate_carries_no_host_fields():
    """The declaration names a host, which an unbacked view and its candidate
    never carry: nothing delivers a machine behind it."""
    classification = classify_bare_metal_resources(
        _generation(_resource("unbacked", backing=UNBACKED)),
        pool_backings={"pool-1": UNBACKED},
        pool_admission={"pool-1": POOL_ADMITTED},
        pool_regions=_regions("pool-1"),
    )

    (candidate,) = classification.candidates
    assert "host_id" not in candidate and "physical_host_id" not in candidate
    published = candidate["listing_resource"]
    for term in ("host_id", "physical_host_id", "access_methods", "available"):
        assert term not in published


@pytest.mark.parametrize(
    ("admission", "enabled", "expected"),
    [
        pytest.param(POOL_ADMITTED, True, HELD, id="admitted"),
        pytest.param(POOL_HELD, True, HELD, id="pool-held"),
        pytest.param(POOL_ADMITTED, False, WITHDRAWN, id="declaration-disabled"),
        pytest.param(POOL_NOT_ADMITTED, True, WITHDRAWN, id="pool-not-admitted"),
    ],
)
def test_a_resource_the_site_built_no_view_for_is_held_unless_withdrawn(
    admission, enabled, expected
):
    """A declaration the site cannot build a view from is unreadable, so its
    resource is held; a disabled declaration or a pool that no longer admits
    bare metal is still a withdrawal."""
    generation = TrustedBareMetalProjection(
        site_id="site-a",
        revision=4,
        digest="generation-4",
        view_problems=[
            BareMetalViewProblems(
                pool_id="pool-1",
                physical_resource_id="r1",
                enabled=enabled,
                problems=("access_methods: required",),
            )
        ],
    )

    classification = classify_bare_metal_resources(
        generation,
        pool_backings=_BACKED,
        pool_admission={"pool-1": admission},
        pool_regions=_regions("pool-1"),
    )

    (item,) = classification.resources
    assert (item.physical_resource_id, item.classification) == ("r1", expected)
    assert item.view_unbuildable is True
    assert item.problems == ("access_methods: required",)
    assert classification.candidates == ()


def test_a_disabled_unbacked_declaration_is_withdrawn():
    classification = classify_bare_metal_resources(
        _generation(_resource("unbacked", backing=UNBACKED, enabled=False)),
        pool_backings={"pool-1": UNBACKED},
        pool_admission={"pool-1": POOL_ADMITTED},
        pool_regions=_regions("pool-1"),
    )

    assert _classes(classification) == {"unbacked": WITHDRAWN}
    assert classification.candidates == ()


def test_a_held_pool_holds_even_a_disabled_or_busy_resource():
    classification = classify_bare_metal_resources(
        _generation(
            _resource("a", pool_id="p", enabled=False),
            _resource("b", pool_id="p", available=False),
        ),
        pool_backings=_BACKED,
        pool_admission={"p": POOL_HELD},
        pool_regions=_regions("p"),
    )

    assert set(_classes(classification).values()) == {HELD}


def test_a_candidate_carries_its_source_and_listing():
    classification = classify_bare_metal_resources(
        _generation(_resource("r1")),
        pool_backings=_BACKED,
        pool_admission={"pool-1": POOL_ADMITTED},
        pool_regions=_regions("pool-1"),
    )

    (candidate,) = classification.candidates
    assert {
        key: candidate[key]
        for key in (
            "site_id",
            "pool_id",
            "physical_resource_id",
            "host_id",
            "physical_host_id",
            "projection_revision",
            "projection_digest",
        )
    } == {
        "site_id": "site-a",
        "pool_id": "pool-1",
        "physical_resource_id": "r1",
        "host_id": "machine-r1",
        "physical_host_id": "physical-r1",
        "projection_revision": 4,
        "projection_digest": "generation-4",
    }
    assert candidate["listing_resource"]["capacity_backing"] == "backed"
    assert candidate["listing"].host_id == "machine-r1"
    assert candidate["shape_digest"] == shape_digest(SHAPE)
    published = candidate["listing_resource"]
    assert (published["gpu_count"], published["gpu_model"], published["ram_gb"]) == (
        8, "H200", 2048,
    )
    assert published["region"] == "us-west"
    assert "capabilities" not in published and "site" not in published


def test_two_identical_declarations_publish_two_listings_with_one_shape():
    classification = classify_bare_metal_resources(
        _generation(_resource("r1"), _resource("r2")),
        pool_backings=_BACKED,
        pool_admission={"pool-1": POOL_ADMITTED},
        pool_regions=_regions("pool-1"),
    )

    first, second = classification.candidates
    assert first["physical_resource_id"] != second["physical_resource_id"]
    assert first["shape_digest"] == second["shape_digest"]


def test_a_pool_without_a_region_holds_its_resources():
    classification = classify_bare_metal_resources(
        _generation(_resource("r1"), _resource("r2", available=False)),
        pool_backings=_BACKED,
        pool_admission={"pool-1": POOL_ADMITTED},
        pool_regions={"pool-1": None},
    )

    assert set(_classes(classification).values()) == {HELD}
    assert classification.candidates == ()


@pytest.mark.parametrize(
    ("capacity", "attributes", "problem"),
    [
        pytest.param({"units": 1, "gpu_count": 8}, {}, "gpu.model", id="no model"),
        pytest.param({"units": 1}, {"gpu_model": "H200"}, "gpu.count", id="no count"),
        pytest.param({"gpu_count": 8}, {"gpu_model": "H200"}, "units", id="no units"),
        pytest.param({"units": 2, "gpu_count": 8}, {"gpu_model": "H200"}, "units", id="two units"),
        pytest.param({"units": 1, "gpu_count": 8, "fpga_count": 1}, {"gpu_model": "H200"},
                     "fpga_count", id="outside the schema"),
        pytest.param({"units": 1, "gpu_count": "8"}, {"gpu_model": "H200"}, "gpu.count",
                     id="not an integer"),
    ],
)
def test_an_unreadable_declaration_holds_only_its_own_resource(capacity, attributes, problem):
    classification = classify_bare_metal_resources(
        _generation(_resource("bad", capacity=capacity, attributes=attributes), _resource("good")),
        pool_backings=_BACKED,
        pool_admission={"pool-1": POOL_ADMITTED},
        pool_regions=_regions("pool-1"),
    )

    assert _classes(classification) == {"bad": HELD, "good": CANDIDATE}
    (bad,) = classification.of(HELD)
    assert bad.shape_digest is None
    assert any(problem in reason for reason in bad.problems), bad.problems


def test_accounting_attributes_are_not_shape_input():
    classification = classify_bare_metal_resources(
        _generation(
            _resource(
                "r1",
                attributes={"gpu_model": "H200", "physical_host_id": "p", "rack": "7"},
            )
        ),
        pool_backings=_BACKED,
        pool_admission={"pool-1": POOL_ADMITTED},
        pool_regions=_regions("pool-1"),
    )

    (candidate,) = classification.candidates
    assert candidate["shape_digest"] == shape_digest(SHAPE)


def test_publication_only_capabilities_are_flagged_as_ignored():
    classification = classify_bare_metal_resources(
        _generation(_resource("r1", capabilities={"gpu_model": "B200"})),
        pool_backings=_BACKED,
        pool_admission={"pool-1": POOL_ADMITTED},
        pool_regions=_regions("pool-1"),
    )

    (item,) = classification.resources
    assert item.publication_capabilities_ignored is True
    assert classification.candidates[0]["listing"].gpu_model == "H200"


def test_a_changed_pool_is_a_different_source_identity():
    """The pool is part of the source identity a listing is keyed by, so a
    Physical Resource moved to another pool derives a different listing."""
    digest = shape_digest(SHAPE)
    assert bare_metal_source_identity(
        pool_id="pool-1", physical_resource_id="r1", shape_digest=digest
    ) != bare_metal_source_identity(
        pool_id="pool-2", physical_resource_id="r1", shape_digest=digest
    )


def test_a_changed_shape_is_a_different_source_identity():
    """A corrected declaration derives a new listing rather than one that can
    never reopen under an unchanged key."""
    assert bare_metal_source_identity(
        pool_id="pool-1", physical_resource_id="r1", shape_digest=shape_digest(SHAPE)
    ) != bare_metal_source_identity(
        pool_id="pool-1",
        physical_resource_id="r1",
        shape_digest=shape_digest({"gpu": {"count": 8, "model": "H200"}}),
    )


def _stored():
    resource = {
        "kind": "bare_metal.v2",
        "offering_mode": "bare_metal",
        "capacity_backing": "backed",
        "host_id": "machine-1",
        "physical_host_id": "physical-1",
        "access_methods": ["ssh"],
        "region": "us-west",
        "gpu_count": 8,
        "gpu_model": "H200",
        "max_duration_seconds": 3600,
    }
    terms = {
        "accepted_escrows": [],
        "settlement_options": [{"option_id": "o1"}],
        "demands": [],
        "max_duration_seconds": 3600,
    }
    return resource, terms


def _compare(fresh_resource, fresh_terms, *, backing_changed=False):
    resource, terms = _stored()
    return compare_bare_metal_listing(
        backing_changed=backing_changed,
        stored_resource=resource,
        stored_terms=terms,
        fresh_resource=fresh_resource,
        fresh_terms=fresh_terms,
    )


def test_an_identical_listing_is_unchanged():
    resource, terms = _stored()

    assert _compare(dict(resource), dict(terms)).outcome == UNCHANGED


@pytest.mark.parametrize(
    ("resource_change", "term_change", "field"),
    [
        ({"access_methods": ["ssh", "serial-console"]}, {}, "access_methods"),
        ({"max_duration_seconds": 7200}, {"max_duration_seconds": 7200}, "max_duration_seconds"),
        ({}, {"settlement_options": [{"option_id": "o2"}]}, "listing.settlement_options"),
    ],
)
def test_a_changed_term_refreshes_in_place(resource_change, term_change, field):
    resource, terms = _stored()

    comparison = _compare({**resource, **resource_change}, {**terms, **term_change})

    assert comparison.outcome == REFRESH
    assert field in comparison.differing_fields


@pytest.mark.parametrize(
    "change",
    [
        {"host_id": "machine-2"},
        {"physical_host_id": "physical-2"},
        {"gpu_count": 4},
        {"gpu_model": "B200"},
        {"region": "eu-central"},
        {"kind": "bare_metal.v3"},
    ],
)
def test_a_changed_identity_is_refused(change):
    resource, terms = _stored()

    comparison = _compare({**resource, **change}, terms)

    assert comparison.outcome == IDENTITY_CHANGED
    assert set(comparison.differing_fields) == set(change)


def test_a_field_the_stored_listing_never_published_is_no_commitment():
    resource, terms = _stored()
    stored = dict(resource)
    del stored["gpu_model"]

    comparison = compare_bare_metal_listing(
        backing_changed=False,
        stored_resource=stored,
        stored_terms=terms,
        fresh_resource=resource,
        fresh_terms=terms,
    )

    assert comparison.outcome == UNCHANGED


def test_a_changed_backing_is_decided_before_any_other_field():
    resource, terms = _stored()

    comparison = _compare(
        {**resource, "host_id": "machine-2"}, terms, backing_changed=True
    )

    assert comparison.outcome == BACKING_CHANGED


def test_backing_is_not_a_term_refreshed_in_place():
    resource, terms = _stored()

    comparison = _compare({**resource, "capacity_backing": "unbacked"}, terms)

    assert comparison.outcome == UNCHANGED


def test_an_absent_list_term_equals_an_empty_one():
    resource, terms = _stored()

    comparison = _compare(resource, {**terms, "demands": None})

    assert comparison.outcome == UNCHANGED


def test_listing_terms_reads_only_term_fields():
    assert listing_terms(
        {"accepted_escrows": [], "status": "open", "max_duration_seconds": 5}
    ) == {
        "accepted_escrows": [],
        "settlement_options": None,
        "demands": None,
        "max_duration_seconds": 5,
    }
