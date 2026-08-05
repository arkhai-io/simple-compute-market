"""Regression test for a real bug found during POOLS-8 Section 6 review:
`domains.vms.listings.reconciler` eagerly constructed a
`PoolHintResolutionSettings()` default at its own module-import time,
whose `__post_init__` imported `domains.vms.listings.pricing_resolution`,
which imported `market_resource_pools.hints` at *its* module level --
so merely importing `domains.vms.listings` (which this package's own
`buy_cli.py`/`listing_cli.py` do, for unrelated helpers) transitively
loaded `market_resource_pools`, even though nothing in the buyer
distribution needs a resource-pools dependency at all. Confirmed by a
real failure with `market_resource_pools` genuinely absent from the
path before the fix; this test pins it going forward using a directly
observable signal (the module was never loaded) rather than requiring
that fragile absent-dependency setup in every future test run, since
`market_resource_pools` may legitimately be installed in this
environment for other reasons.
"""

from __future__ import annotations

import sys


def test_importing_domains_vms_listings_does_not_load_market_resource_pools():
    for name in list(sys.modules):
        if name == "market_resource_pools" or name.startswith(
            "market_resource_pools.",
        ):
            del sys.modules[name]
        if name == "domains.vms.listings" or name.startswith(
            "domains.vms.listings.",
        ):
            del sys.modules[name]

    import domains.vms.listings  # noqa: F401

    loaded = [
        name for name in sys.modules
        if name == "market_resource_pools" or name.startswith(
            "market_resource_pools.",
        )
    ]
    assert loaded == [], (
        f"importing domains.vms.listings loaded market_resource_pools "
        f"modules it should not need: {loaded}"
    )
