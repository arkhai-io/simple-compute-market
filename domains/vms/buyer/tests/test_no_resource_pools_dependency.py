"""Importing `domains.vms.listings` must never transitively load
`market_resource_pools`. Buyer-side consumers of this package (e.g.
`buy_cli.py`/`listing_cli.py`) use unrelated listing helpers and have no
reason to depend on `kit/resource-pools` at all -- if a module-level
import anywhere in `domains.vms.listings.reconciler` (or anything it
imports at its own module level) pulls in `market_resource_pools`, this
test fails.
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

    # Local import, not module-level: this test's own subject is a fresh
    # import after the `sys.modules` clear above, so it cannot be imported
    # at file scope without defeating the thing being tested.
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
