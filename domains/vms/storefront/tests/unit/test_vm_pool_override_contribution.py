"""The VM market judges the vocabulary of its pool overrides.

Feasibility judging reads the storefront database, so it is proven through the
application in ``tests/integration/test_pool_overrides_api.py``.
"""

from __future__ import annotations

import pytest
from market_pool_overrides import PoolOverrideRecord

from market_storefront.services.vm_pool_override_contribution import (
    VmPoolOverrideContribution,
)
from market_storefront.services.shape_feasibility import vm_shape_feasibility

SHAPE = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 64}}


def _problems(**fields) -> list[str]:
    record = PoolOverrideRecord.model_validate(
        {"site_id": "a", "pool_id": "gpu", "offering_mode": "vm", **fields}
    )
    contribution = VmPoolOverrideContribution(
        db_path=":memory:", shape_feasible=vm_shape_feasibility()
    )
    return list(contribution.vocabulary_problems(record))


def test_it_serves_the_vm_mode():
    assert VmPoolOverrideContribution.offering_mode == "vm"


def test_complete_vm_terms_and_shapes_are_readable():
    assert _problems(
        listing_shapes=[SHAPE],
        terms={"sla": 99.5, "min_price": "3", "token": "0xtoken", "max_duration_seconds": 3600},
    ) == []


@pytest.mark.parametrize(
    ("terms", "field"),
    [
        ({"sla": -1}, "sla"),
        ({"max_duration_seconds": 0}, "max_duration_seconds"),
        ({"max_duration_seconds": "60"}, "max_duration_seconds"),
        ({"min_price": 3}, "min_price"),
        ({"region": "us-east"}, "region"),
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
