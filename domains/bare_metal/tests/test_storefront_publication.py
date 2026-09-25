"""Classification and listing comparison, with no storefront state."""

from __future__ import annotations

import pytest

from arkhai_bare_metal import (
    CANDIDATE,
    HELD,
    IDENTITY_CHANGED,
    POOL_ADMITTED,
    POOL_HELD,
    POOL_NOT_ADMITTED,
    REFRESH,
    UNAVAILABLE,
    UNCHANGED,
    WITHDRAWN,
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
    TrustedBareMetalResource,
    bare_metal_source_identity,
    classify_bare_metal_resources,
    compare_bare_metal_listing,
    listing_terms,
)
from arkhai_bare_metal.fixtures.publication_view import (
    build_bare_metal_publication_view,
)


def _resource(resource_id, *, pool_id="pool-1", enabled=True, available=True):
    return TrustedBareMetalResource(
        pool_id=pool_id,
        enabled=enabled,
        view=BareMetalResourceProjection.model_validate(
            build_bare_metal_publication_view(
                resource_id,
                pool_id=pool_id,
                host_id=f"machine-{resource_id}",
                physical_host_id=f"physical-{resource_id}",
                available=available,
            )
        ),
    )


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
        pool_admission={
            "pool-1": POOL_ADMITTED,
            "pool-unresolved": POOL_HELD,
            "pool-vm-only": POOL_NOT_ADMITTED,
        },
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


def test_a_held_pool_holds_even_a_disabled_or_busy_resource():
    classification = classify_bare_metal_resources(
        _generation(
            _resource("a", pool_id="p", enabled=False),
            _resource("b", pool_id="p", available=False),
        ),
        pool_admission={"p": POOL_HELD},
    )

    assert set(_classes(classification).values()) == {HELD}


def test_a_candidate_carries_its_source_and_listing():
    classification = classify_bare_metal_resources(
        _generation(_resource("r1")), pool_admission={"pool-1": POOL_ADMITTED}
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


def test_a_changed_pool_is_a_different_source_identity():
    """The pool is part of the source identity a listing is keyed by, so a
    Physical Resource moved to another pool derives a different listing."""
    assert bare_metal_source_identity(
        pool_id="pool-1", physical_resource_id="r1"
    ) != bare_metal_source_identity(pool_id="pool-2", physical_resource_id="r1")


def _stored():
    resource = {
        "kind": "bare_metal.v2",
        "offering_mode": "bare_metal",
        "capacity_backing": "backed",
        "host_id": "machine-1",
        "physical_host_id": "physical-1",
        "access_methods": ["ssh"],
        "capabilities": {"gpu_count": 8},
        "max_duration_seconds": 3600,
    }
    terms = {
        "accepted_escrows": [],
        "settlement_options": [{"option_id": "o1"}],
        "demands": [],
        "max_duration_seconds": 3600,
    }
    return resource, terms


def _compare(fresh_resource, fresh_terms):
    resource, terms = _stored()
    return compare_bare_metal_listing(
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
        {"capabilities": {"gpu_count": 4}},
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
    del stored["capabilities"]

    comparison = compare_bare_metal_listing(
        stored_resource=stored,
        stored_terms=terms,
        fresh_resource=resource,
        fresh_terms=terms,
    )

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
