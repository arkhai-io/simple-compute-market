"""A stored listing against a fresh derivation of its own source."""

from __future__ import annotations

from domains.vms.listings.listing_comparison import (
    BACKING_DISAGREES,
    BACKING_UNDISCLOSED,
    IDENTITY_DIFFERS,
    TERMS_DIFFER,
    UNCHANGED,
    compare_listing,
    refreshed_listing_resource,
)

_RESOURCE = {
    "offering_mode": "vm",
    "pool_id": "broker-a",
    "gpu_model": "H100",
    "gpu_count": 4,
    "region": "us-east",
    "sla": 99.0,
    "capacity_backing": "unbacked",
}
_TERMS = {"settlement_options": [{"option_id": "o1"}], "max_duration_seconds": 3600}


def _compare(stored=None, fresh=None, stored_terms=None, fresh_terms=None, **kw):
    return compare_listing(
        stored_resource=stored or dict(_RESOURCE),
        stored_terms=stored_terms or dict(_TERMS),
        fresh_resource=fresh or dict(_RESOURCE),
        fresh_terms=fresh_terms or dict(_TERMS),
        binding_backing=kw.get("binding_backing", "unbacked"),
        source_backing=kw.get("source_backing", "unbacked"),
    )


def test_an_unchanged_listing_is_unchanged():
    assert _compare().outcome == UNCHANGED


def test_a_changed_term_is_refreshed_in_place():
    comparison = _compare(fresh_terms={**_TERMS, "max_duration_seconds": 7200})

    assert comparison.outcome == TERMS_DIFFER
    assert comparison.differing_fields == ("max_duration_seconds",)


def test_a_changed_published_identity_field_is_refused():
    comparison = _compare(fresh={**_RESOURCE, "region": "eu-west"})

    assert comparison.outcome == IDENTITY_DIFFERS
    assert comparison.differing_fields == ("region",)


def test_a_field_the_listing_does_not_publish_is_no_commitment():
    fresh = {**_RESOURCE, "ram_gb": 256}

    assert _compare(fresh=fresh).outcome == UNCHANGED


def test_a_listing_that_does_not_disclose_backing_is_refreshed():
    stored = {k: v for k, v in _RESOURCE.items() if k != "capacity_backing"}

    assert _compare(stored=stored).outcome == BACKING_UNDISCLOSED


def test_a_source_whose_backing_disagrees_with_the_binding_is_refused():
    comparison = _compare(source_backing="backed")

    assert comparison.outcome == BACKING_DISAGREES


def test_a_refresh_keeps_stored_identity_and_takes_fresh_terms():
    stored = {k: v for k, v in _RESOURCE.items() if k != "capacity_backing"}
    fresh = {**_RESOURCE, "sla": 99.9, "ram_gb": 256}

    refreshed = refreshed_listing_resource(
        stored_resource=stored,
        fresh_resource=fresh,
        binding_backing="unbacked",
    )

    assert refreshed["sla"] == 99.9
    assert refreshed["capacity_backing"] == "unbacked"
    assert "ram_gb" not in refreshed
    assert refreshed["gpu_model"] == "H100"


def test_a_field_the_source_does_not_resolve_is_not_a_divergence():
    """A region the pool does not tag and no fallback supplies is not contradicted."""
    fresh = {**_RESOURCE, "region": None}

    assert _compare(fresh=fresh).outcome == UNCHANGED


def test_a_field_the_source_resolves_differently_still_diverges():
    fresh = {**_RESOURCE, "gpu_model": "A100"}

    comparison = _compare(fresh=fresh)

    assert comparison.outcome == IDENTITY_DIFFERS
    assert comparison.differing_fields == ("gpu_model",)


def test_every_vm_dimension_is_an_identity_field():
    from arkhai_vms import DIMENSION_KEYS

    from domains.vms.listings.listing_comparison import IDENTITY_FIELDS

    assert set(DIMENSION_KEYS) <= set(IDENTITY_FIELDS)
    # Identity is what a listing is and where; the dimensions are listed once,
    # from the domain vocabulary.
    assert len(IDENTITY_FIELDS) == len(set(IDENTITY_FIELDS))
