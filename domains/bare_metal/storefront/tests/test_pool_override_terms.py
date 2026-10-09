"""How an override's lease bounds combine with configuration.

Each bound replaces its configured counterpart, as configuration overlays do;
the effective pair must be ordered.
"""

from __future__ import annotations

import pytest

from arkhai_bare_metal_storefront.pool_overrides import (
    BareMetalPoolOverrideTerms,
    configured_max_duration_seconds,
    effective_duration_problems,
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


def test_the_configured_maximum_is_read_from_its_environment_name():
    assert configured_max_duration_seconds(
        {"BARE_METAL_STOREFRONT_MAX_DURATION_SECONDS": "3600"}
    ) == 3600
    assert configured_max_duration_seconds({}) is None
