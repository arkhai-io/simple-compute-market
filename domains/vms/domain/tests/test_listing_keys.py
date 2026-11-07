"""Structural keys of VM listings: exact byte form and identity rules."""

from __future__ import annotations

import pytest

from arkhai_vms import listing_pool_key, listing_resource_key, listing_shape_key

DIGEST = "capability-shape.v1:abc"


def test_pre_shape_keys_are_byte_identical_to_stored_keys():
    # Stored listings are found by these exact strings.
    assert listing_pool_key("site-a", "b:c", 2) == "pool:6:site-a:3:b:c:gpus:2"
    assert listing_resource_key("s", "r:1", 1) == "1:s:3:r:1:gpus:1"


def test_shape_keys_name_the_source_and_the_digest():
    assert listing_shape_key("s", shape_digest=DIGEST, pool_id="p") == f"pool:1:s:1:p:shape:{DIGEST}"
    assert listing_shape_key("s", shape_digest=DIGEST, resource_id="r") == f"1:s:1:r:shape:{DIGEST}"


def test_a_resource_takes_precedence_over_its_pool():
    assert listing_shape_key("s", shape_digest=DIGEST, pool_id="p", resource_id="r") == (
        listing_shape_key("s", shape_digest=DIGEST, resource_id="r")
    )


def test_delimiter_bearing_identifiers_do_not_collide():
    assert listing_shape_key("a", shape_digest=DIGEST, pool_id="b:c") != listing_shape_key(
        "a:b", shape_digest=DIGEST, pool_id="c"
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda: listing_shape_key("", shape_digest=DIGEST, pool_id="p"),
        lambda: listing_shape_key("s", shape_digest="", pool_id="p"),
        lambda: listing_shape_key("s", shape_digest=DIGEST),
        lambda: listing_pool_key("s", "p", 0),
        lambda: listing_resource_key("s", "r", True),
    ],
)
def test_incomplete_keys_are_refused(call):
    with pytest.raises(ValueError):
        call()
