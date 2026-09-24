"""Every stored override is in exactly one state."""

from __future__ import annotations

import pytest

from market_pool_overrides import (
    OVERRIDE_APPLIED,
    OVERRIDE_INACTIVE,
    OVERRIDE_ORPHANED,
    OVERRIDE_SITE_UNCONFIGURED,
    OVERRIDE_UNKNOWN,
    override_state,
)


@pytest.mark.parametrize(
    ("site_id", "projection", "state"),
    [
        ("site-a", None, OVERRIDE_INACTIVE),
        # Local-table derivation applies no override, whatever its site.
        ("site-zz", None, OVERRIDE_INACTIVE),
        ("site-zz", {"site-a": []}, OVERRIDE_SITE_UNCONFIGURED),
        ("site-b", {"site-a": [{"resource_pool_id": "gpu"}]}, OVERRIDE_UNKNOWN),
        ("site-a", {"site-a": [{"resource_pool_id": "other"}]}, OVERRIDE_ORPHANED),
        # An authoritative empty generation is an answer: the pool is absent.
        ("site-a", {"site-a": []}, OVERRIDE_ORPHANED),
        ("site-a", {"site-a": [{"resource_pool_id": "gpu"}]}, OVERRIDE_APPLIED),
    ],
)
def test_an_override_is_in_exactly_one_state(site_id, projection, state):
    assert override_state(
        site_id=site_id, pool_id="gpu", site_ids=("site-a", "site-b"), projection=projection
    ) == state
