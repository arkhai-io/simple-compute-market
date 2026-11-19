"""What an override's terms admit, and how its lease bounds combine with configuration.

Seller details are the shared listing-details model. Each bound
replaces its configured counterpart, as configuration overlays do; the
effective pair must be ordered.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arkhai_bare_metal_storefront.pool_overrides import (
    BareMetalPoolOverrideTerms,
    effective_duration_problems,
    positive_lease_bound,
)


@pytest.mark.parametrize(
    ("terms", "configured", "conflict"),
    [
        pytest.param({"min_duration_seconds": 7200}, 3600, True,
                     id="override min above configured max"),
        pytest.param({"min_duration_seconds": 1800}, 3600, False,
                     id="override min below configured max"),
        pytest.param({"min_duration_seconds": 7200, "max_duration_seconds": 10800}, 3600, False,
                     id="override raises the max it needs"),
        pytest.param({"max_duration_seconds": 600}, 3600, False,
                     id="override max alone, no minimum anywhere"),
        pytest.param({"min_duration_seconds": 3600}, 3600, False, id="equal bounds"),
        pytest.param({"min_duration_seconds": 7200}, None, False, id="no configured max"),
    ],
)
def test_the_effective_pair_must_be_ordered(terms, configured, conflict):
    problems = effective_duration_problems(
        BareMetalPoolOverrideTerms.model_validate(terms), configured
    )
    assert bool(problems) is conflict


def test_stated_details_are_terms():
    details = {
        "title": "A whole H100 machine",
        "description": "Dedicated host; no oversubscription.",
        "metadata": {"acme.tier": "gold", "nvlink": True, "max_jobs": 4},
    }

    terms = BareMetalPoolOverrideTerms.model_validate({"details": details})

    assert terms.details is not None and terms.details.model_dump() == details


@pytest.mark.parametrize(
    ("details", "location"),
    [
        ({"description": "d" * 100_000}, ("details", "description")),
        ({"metadata": {"acme.tier": None}}, ("details", "metadata", "acme.tier")),
    ],
)
def test_details_the_shared_model_refuses_are_refused(details, location):
    """The term is the shared listing-details model, whose limits are tested
    at their edges with it; these show only that an override refuses through it."""
    with pytest.raises(ValidationError) as refused:
        BareMetalPoolOverrideTerms.model_validate({"details": details})

    assert {error["loc"][: len(location)] for error in refused.value.errors()} == {location}


@pytest.mark.parametrize(
    ("configured", "bound"),
    [(3600, 3600), (1, 1), (None, None), (0, None), (-60, None)],
)
def test_only_a_positive_configured_maximum_bounds_a_lease(configured, bound):
    assert positive_lease_bound(configured) == bound
