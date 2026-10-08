"""The publication source the storefront composes from its own callbacks."""

from __future__ import annotations

from unittest.mock import MagicMock

from arkhai_bare_metal.storefront_adapter import (
    bare_metal_candidate_skip_keys,
    bare_metal_publication_adapter,
)


def _source(**overrides):
    callbacks = {
        "open_keys": MagicMock(return_value={"k1"}),
        "close_stale": MagicMock(return_value=["listing-1"]),
        "available_candidates": MagicMock(return_value=[]),
        "record_published": MagicMock(return_value=None),
        "reopen_existing": MagicMock(return_value=None),
    }
    callbacks.update(overrides)
    return bare_metal_publication_adapter(**callbacks), callbacks


def test_every_database_callback_is_the_storefronts_own():
    source, callbacks = _source()

    assert source.name == "bare_metal"
    for name in (
        "open_keys",
        "close_stale",
        "available_candidates",
        "record_published",
        "reopen_existing",
    ):
        assert getattr(source, name) is callbacks[name]


def test_a_candidate_is_skipped_by_its_common_derivation_key_alone():
    candidate = {
        "derivation_key": "storefront-derivation.v1:abc",
        "site_id": "site-a",
        "physical_resource_id": "resource-1",
    }

    assert bare_metal_candidate_skip_keys(candidate) == {
        "storefront-derivation.v1:abc"
    }


def test_listing_resource_is_a_copy_of_the_candidates():
    source, _ = _source()
    candidate = {"derivation_key": "k", "listing_resource": {"kind": "bare_metal.v2"}}

    resource = source.listing_resource(candidate)
    resource["offering_mode"] = "bare_metal"

    assert candidate["listing_resource"] == {"kind": "bare_metal.v2"}
    assert source.pricing_resource(candidate, resource) is resource
