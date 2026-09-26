"""Rechecking a bare-metal listing against its own source."""

from __future__ import annotations

import pytest
from market_capability_shape import shape_digest

from arkhai_bare_metal import (
    POOL_ADMITTED,
    POOL_HELD,
    POOL_NOT_ADMITTED,
    SOURCE_ABSENT,
    SOURCE_MATCHES,
    SOURCE_MISMATCH,
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
    TrustedBareMetalResource,
    recheck_bare_metal_listing_source,
)
from arkhai_bare_metal.fixtures.publication_view import (
    DEFAULT_CAPACITY,
    build_bare_metal_publication_view,
)

PUBLISHED = shape_digest({"gpu": {"count": 8, "model": "H200"}, "memory": {"gib": 2048}})


def _generation(*, capacity=None, attributes=None, enabled=True, available=True, pool_id="pool-1"):
    return TrustedBareMetalProjection(
        site_id="site-a",
        revision=1,
        digest="d1",
        resources=[
            TrustedBareMetalResource(
                pool_id=pool_id,
                enabled=enabled,
                view=BareMetalResourceProjection.model_validate(
                    build_bare_metal_publication_view(
                        "r1", pool_id=pool_id, available=enabled and available
                    )
                ),
                declared_capacity=dict(DEFAULT_CAPACITY if capacity is None else capacity),
                declared_attributes={"gpu_model": "H200"} if attributes is None else attributes,
            )
        ],
    )


def _check(generation, *, admission=POOL_ADMITTED, region="us-west", published_region="us-west",
           digest=PUBLISHED):
    return recheck_bare_metal_listing_source(
        generation,
        pool_admission={"pool-1": admission},
        pool_regions={"pool-1": region},
        pool_id="pool-1",
        physical_resource_id="r1",
        shape_digest=digest,
        region=published_region,
    )


def test_an_unchanged_source_matches():
    assert _check(_generation()).outcome == SOURCE_MATCHES


def test_a_leased_machine_still_matches_its_declaration():
    """Availability is not the guard's question."""
    assert _check(_generation(available=False)).outcome == SOURCE_MATCHES


@pytest.mark.parametrize(
    ("generation", "kwargs", "reason"),
    [
        pytest.param(_generation(capacity={"units": 1, "gpu_count": 4, "ram_gb": 2048}), {},
                     "shape", id="fewer GPUs declared"),
        pytest.param(_generation(), {"published_region": "eu-central"}, "region",
                     id="region moved"),
        pytest.param(_generation(attributes={}), {}, "gpu.model", id="model withdrawn"),
        pytest.param(_generation(), {"region": None}, "region", id="region removed"),
        pytest.param(_generation(), {"admission": POOL_HELD}, "resolve", id="pool unresolvable"),
    ],
)
def test_a_source_that_no_longer_supports_the_listing_is_a_declared_mismatch(
    generation, kwargs, reason
):
    check = _check(generation, **kwargs)

    assert check.outcome == SOURCE_MISMATCH
    assert reason in check.reason


@pytest.mark.parametrize(
    ("generation", "kwargs"),
    [
        pytest.param(_generation(enabled=False), {}, id="declaration disabled"),
        pytest.param(_generation(), {"admission": POOL_NOT_ADMITTED}, id="pool stops admitting"),
        pytest.param(_generation(pool_id="pool-2"), {}, id="moved to another pool"),
    ],
)
def test_a_source_that_no_longer_offers_the_resource_is_absent(generation, kwargs):
    assert _check(generation, **kwargs).outcome == SOURCE_ABSENT
