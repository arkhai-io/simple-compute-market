"""The VM market judges the vocabulary of its pool overrides.

Feasibility judging reads the storefront database, so it is proven through the
application in ``tests/integration/test_pool_overrides_api.py``.
"""

from __future__ import annotations

import pytest
from arkhai_vms import VM_CAPABILITY_SCHEMA
from market_capability_admissibility import parse_declaration
from market_pool_overrides import PoolOverrideRecord

from market_storefront.services.vm_pool_override_contribution import (
    VmPoolOverrideContribution,
)
from market_storefront.services.shape_feasibility import vm_shape_feasibility

SHAPE = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 64}}


def _default(raw):
    return parse_declaration(
        raw, tier="configured_default", schema=VM_CAPABILITY_SCHEMA
    ).declaration


def _problems(*, admissibility_default=None, **fields) -> list[str]:
    record = PoolOverrideRecord.model_validate(
        {"site_id": "a", "pool_id": "gpu", "offering_mode": "vm", **fields}
    )
    contribution = VmPoolOverrideContribution(
        db_path=":memory:",
        shape_feasible=vm_shape_feasibility(),
        admissibility_default=admissibility_default,
    )
    return list(contribution.vocabulary_problems(record))


def test_it_serves_the_vm_mode():
    assert VmPoolOverrideContribution.offering_mode == "vm"


def test_complete_vm_terms_and_shapes_are_readable():
    assert _problems(
        listing_shapes=[SHAPE],
        terms={
            "sla": 99.5,
            "max_duration_seconds": 3600,
            "pricing": {
                "gpu": {"H100": {"rates": [{"asset": "usd", "rate": "2", "per": "hour"}]}},
                "memory": {"rates": [{"asset": "usd", "rate": "0.01", "per": "hour"}]},
            },
        },
    ) == []


@pytest.mark.parametrize(
    ("terms", "field"),
    [
        ({"sla": -1}, "sla"),
        ({"max_duration_seconds": 0}, "max_duration_seconds"),
        ({"max_duration_seconds": "60"}, "max_duration_seconds"),
        ({"min_price": "3"}, "min_price"),
        ({"token": "0xtoken"}, "token"),
        ({"region": "us-east"}, "region"),
        ({"pricing": {"bandwidth": {"rates": []}}}, "pricing"),
        ({"pricing": {"gpu": {"rates": []}}}, "pricing"),
        (
            {"pricing": {"cpu": {"rates": [{"asset": "usd", "rate": "0", "per": "hour"}]}}},
            "pricing",
        ),
    ],
)
def test_terms_outside_the_vm_vocabulary_are_named(terms, field):
    (problem,) = _problems(terms=terms)

    assert problem.startswith(f"terms.{field}")


def test_a_shape_outside_the_vm_vocabulary_is_named_by_index():
    problems = _problems(
        listing_shapes=[SHAPE, {"gpu": {"count": 1, "model": "H100"}, "fpga": {"count": 1}}]
    )

    assert problems and all(problem.startswith("listing_shapes[1]") for problem in problems)


def test_constrained_shapes_within_the_configured_default_are_readable():
    assert _problems(
        listing_shapes=[
            {"gpu": {"count": {"offer": 1, "max": 4}, "model": "H100"}, "memory": {"gib": {"max": 512}}},
            {"gpu": {"count": 8, "model": "H100"}},
        ],
        admissibility_default=_default({"gpu": {"count": {"min": 1, "max": 16}}}),
    ) == []


def test_identical_entries_collapse_and_are_accepted():
    constrained = {"gpu": {"count": {"offer": 1, "max": 4}, "model": "H100"}}

    assert _problems(listing_shapes=[constrained, constrained]) == []
    assert _problems(
        listing_shapes=[
            {"gpu": {"count": 1, "model": "H100"}},
            {"gpu": {"count": {"offer": 1}, "model": "H100"}},
        ]
    ) == []


def test_an_empty_merged_range_is_refused_naming_both_tiers():
    (problem,) = _problems(
        listing_shapes=[{"gpu": {"count": {"offer": 2, "max": 2}, "model": "H100"}}],
        admissibility_default=_default({"gpu": {"count": {"min": 4}}}),
    )

    assert problem.startswith("listing_shapes[0] gpu.count:")
    assert "storefront_override" in problem and "configured_default" in problem


def test_an_offer_the_configured_default_excludes_is_refused_naming_its_tier():
    (problem,) = _problems(
        listing_shapes=[SHAPE, {"gpu": {"count": 8, "model": "H100"}}],
        admissibility_default=_default({"gpu": {"count": {"max": 4}}}),
    )

    assert problem.startswith("listing_shapes[1] gpu.count:")
    assert problem.endswith("(bound set by configured_default)")


def test_a_shape_widening_the_configured_default_admits_its_offer():
    assert _problems(
        listing_shapes=[{"gpu": {"count": {"offer": 4, "max": 8}, "model": "H100"}}],
        admissibility_default=_default({"gpu": {"count": {"max": 2}}}),
    ) == []


def test_one_base_shape_stated_with_different_constraints_is_refused_naming_both():
    problems = _problems(
        listing_shapes=[
            {"gpu": {"count": {"offer": 1, "max": 4}, "model": "H100"}},
            SHAPE,
            {"gpu": {"count": {"offer": 1, "max": 8}, "model": "H100"}},
        ]
    )

    assert problems == [problems[0]]
    assert problems[0].startswith("listing_shapes[0, 2] gpu.count:")


@pytest.mark.parametrize(
    ("shape", "path"),
    [
        ({"gpu": {"count": 1, "model": {"max": 4}}}, "gpu.model"),
        ({"gpu": {"count": {"min": 2, "max": 8}, "model": "H100"}}, "gpu.count"),
        ({"gpu": {"count": {"offer": 1, "step": 2}, "model": "H100"}}, "gpu.count"),
        ({"gpu": {"count": 1, "model": "H100"}, "memory": {"foo": {"max": 4}}}, "memory.foo"),
    ],
)
def test_an_unreadable_shape_or_constraint_is_refused_naming_its_path(shape, path):
    problems = _problems(listing_shapes=[SHAPE, shape])

    assert problems
    assert all(problem.startswith(f"listing_shapes[1] {path}") for problem in problems)
