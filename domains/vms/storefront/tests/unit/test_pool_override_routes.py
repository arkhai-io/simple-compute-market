"""The VM storefront application serves its pool-override routes once each, at
the pool-override kit's path.

How the administrator middleware binds that path is `test_identity_dispatch.py`'s.
"""

from __future__ import annotations

from collections import Counter

from fastapi.routing import APIRoute
from market_pool_overrides import POOL_OVERRIDES_PATH

import market_storefront.server as server


def test_each_override_route_is_mounted_once_at_the_kits_path() -> None:
    mounted = Counter(
        (method, route.path)
        for route in server.app.routes
        if isinstance(route, APIRoute) and route.path.endswith("/pool-overrides")
        for method in route.methods
    )

    assert mounted == Counter(
        (method, POOL_OVERRIDES_PATH) for method in ("PUT", "GET", "DELETE")
    )
