"""Regression test: importing `domains.vms.listings` must never transitively
load `market_resource_pools`. Any consumer of this package that only needs
unrelated buyer-side helpers (e.g. `buy_cli.py`/`listing_cli.py`) has no
reason to depend on `kit/resource-pools` at all -- if a module-level import
anywhere in `domains.vms.listings.reconciler` (or anything it imports at
its own module level) ever pulls in `market_resource_pools`, this test
pins that as a regression rather than requiring the fragile "package
genuinely absent from the environment" setup that first caught this,
since `market_resource_pools` may legitimately be installed in this
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
