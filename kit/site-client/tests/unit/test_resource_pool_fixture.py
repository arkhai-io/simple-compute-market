"""The resource-pool projection contract fixture accepts what it builds and
refuses what a consumer could not derive from."""

from __future__ import annotations

import pytest

from market_site_client.fixtures.resource_pools import (
    build_projected_resource,
    build_resource_pool_projection,
    build_resource_pool_row,
    validate_resource_pool_projection,
)


def _projection():
    return build_resource_pool_projection(
        [
            build_resource_pool_row("backed"),
            build_resource_pool_row(
                "broker",
                capacity_backing="unbacked",
                resources=[build_projected_resource("broker-1", capacity={"gpu_count": 8})],
            ),
        ]
    )


def test_what_the_builders_produce_validates():
    projection = _projection()

    validate_resource_pool_projection(projection)
    broker = projection["resource_pools"][1]["pool_metadata"]["policy_tags"]
    assert broker["deliverable_modes"] == []


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda row: row["pool_metadata"]["policy_tags"].pop("capacity_backing"), "backing"),
        (lambda row: row["pool_metadata"]["policy_tags"].pop("advertisable_modes"), "advertisable"),
        (lambda row: row["pool_metadata"].pop("enabled"), "enablement"),
        (lambda row: row.pop("pool_metadata"), "metadata"),
        (lambda row: row["resources"][0].pop("capacity"), "capacity"),
        (lambda row: row["resources"][0]["capacity"].update(gpu_count="8"), "capacity"),
        (lambda row: row["resources"][0].pop("resource_type"), "resource_type"),
        (lambda row: row["resources"][0].update(resource_type=None), "resource_type"),
        (lambda row: row["resources"][0].update(resource_type=" "), "resource_type"),
    ],
)
def test_a_response_a_consumer_could_not_derive_from_is_refused(damage, message):
    projection = _projection()
    damage(projection["resource_pools"][1])

    with pytest.raises(AssertionError, match=message):
        validate_resource_pool_projection(projection)
