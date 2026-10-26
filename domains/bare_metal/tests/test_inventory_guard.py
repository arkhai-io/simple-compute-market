"""Rechecking a bare-metal listing against its own source."""

from __future__ import annotations

from market_resource_pools_contracts.backing import BACKED, UNBACKED

import pytest
from market_capability_shape import shape_digest

from arkhai_bare_metal import (
    POOL_ADMITTED,
    POOL_HELD,
    POOL_NOT_ADMITTED,
    SOURCE_ABSENT,
    SOURCE_MATCHES,
    SOURCE_MISMATCH,
    SOURCE_UNAVAILABLE,
    BareMetalResourceProjection,
    BareMetalViewProblems,
    TrustedBareMetalProjection,
    TrustedBareMetalResource,
    recheck_bare_metal_listing_source,
)
from arkhai_bare_metal.fixtures.publication_view import (
    DEFAULT_CAPACITY,
    build_bare_metal_publication_view,
)

PUBLISHED = shape_digest({"gpu": {"count": 8, "model": "H200"}, "memory": {"gib": 2048}})


def _generation(
    *, capacity=None, attributes=None, enabled=True, available=True, pool_id="pool-1",
    backing=BACKED,
):
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
                        "r1",
                        backing=backing,
                        pool_id=pool_id,
                        available=enabled and available,
                    )
                ),
                capacity_backing=backing.label,
                declared_capacity=dict(DEFAULT_CAPACITY if capacity is None else capacity),
                declared_attributes={"gpu_model": "H200"} if attributes is None else attributes,
            )
        ],
    )


def _check(generation, *, admission=POOL_ADMITTED, region="us-west", published_region="us-west",
           digest=PUBLISHED, backing=BACKED):
    return recheck_bare_metal_listing_source(
        generation,
        pool_admission={"pool-1": admission},
        pool_backings={"pool-1": backing},
        pool_regions={"pool-1": region},
        pool_id="pool-1",
        physical_resource_id="r1",
        shape_digest=digest,
        region=published_region,
    )


def test_an_unchanged_source_matches():
    assert _check(_generation()).outcome == SOURCE_MATCHES


def test_a_leased_machine_matches_its_declaration_but_is_unavailable():
    check = _check(_generation(available=False))
    assert check.outcome == SOURCE_UNAVAILABLE
    assert not check.matches


def test_a_declared_mismatch_is_reported_before_availability():
    check = _check(_generation(available=False, attributes={"gpu_model": "other"}))
    assert check.outcome == SOURCE_MISMATCH


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


def test_a_resource_the_site_built_no_view_for_is_a_declared_mismatch_naming_why():
    """The listing's declaration no longer yields a view, so the recheck refuses
    it as no longer matching, naming the site's problem."""
    generation = TrustedBareMetalProjection(
        site_id="site-a",
        revision=1,
        digest="d1",
        view_problems=[
            BareMetalViewProblems(
                pool_id="pool-1",
                physical_resource_id="r1",
                enabled=True,
                problems=("access_methods: required",),
            )
        ],
    )

    check = _check(generation)

    assert check.outcome == SOURCE_MISMATCH
    assert "builds no bare-metal view" in check.reason
    assert "access_methods: required" in check.reason


def test_unbacked_supply_matches_on_its_declaration_with_no_availability_read():
    """An unbacked view states no availability, and none is asked of it."""
    generation = _generation(backing=UNBACKED)

    assert generation.resources[0].view.available is None
    assert _check(generation, backing=UNBACKED).outcome == SOURCE_MATCHES


def test_an_unbacked_machine_reported_taken_still_matches():
    """Spec scenario "An unbacked listing's resource reads as unavailable": the
    site carries no availability for unbacked supply, whatever its ledger
    says, so the recheck has nothing to refuse it for."""
    generation = _generation(backing=UNBACKED, available=False)

    assert _check(generation, backing=UNBACKED).outcome == SOURCE_MATCHES


@pytest.mark.parametrize(
    ("changes", "kwargs", "outcome"),
    [
        pytest.param(
            {"capacity": {"units": 1, "gpu_count": 4, "ram_gb": 2048}}, {},
            SOURCE_MISMATCH, id="fewer GPUs declared",
        ),
        pytest.param({}, {"published_region": "eu-central"}, SOURCE_MISMATCH,
                     id="region moved"),
        pytest.param({"enabled": False}, {}, SOURCE_ABSENT, id="declaration disabled"),
        # Spec scenario "An unbacked listing's resource moves to another pool":
        # found by its bound pool, it is no longer projected there.
        pytest.param({"pool_id": "pool-2"}, {}, SOURCE_ABSENT, id="moved to another pool"),
    ],
)
def test_an_unbacked_listing_is_refused_only_by_its_declaration(changes, kwargs, outcome):
    generation = _generation(backing=UNBACKED, **changes)

    assert _check(generation, backing=UNBACKED, **kwargs).outcome == outcome
