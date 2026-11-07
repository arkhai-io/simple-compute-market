"""Where bare metal mounts the compute family's mock routes.

Bare metal mounts only those routes on the provisioning service; its leases are
the compute family's, and access is granted only through fulfillment. The
family's template builds the routes' contracts from these two values, so they
are the path prefix and operation names every caller of bare metal's mock
routes signs against.
"""

from __future__ import annotations

from arkhai_bare_metal import (
    BARE_METAL_MOCK_OPERATION_PREFIX,
    BARE_METAL_MOCK_ROUTE_PREFIX,
)


def test_bare_metal_mounts_its_mock_routes_under_its_own_prefix() -> None:
    assert BARE_METAL_MOCK_ROUTE_PREFIX == "/test/bare-metal"
    assert BARE_METAL_MOCK_OPERATION_PREFIX == "provisioning_test_bare_metal"
