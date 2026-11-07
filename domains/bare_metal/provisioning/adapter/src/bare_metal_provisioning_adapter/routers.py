"""Bare-metal operator surfaces contributed to the compute service.

Bare metal mounts no operator routes: its leases are the family's, and access
is granted only through fulfillment. Its mock control routes are a router
factory taking zero-argument accessors, because the service mounts them when it
builds the app and composes their collaborators later, at startup.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bare_metal_provisioning_adapter.controllers.test_controller import (
    BARE_METAL_MOCK_ROUTE_MOUNT,
    make_mock_router,
)


def bare_metal_route_contracts():
    """The signed contracts of every route bare metal mounts: its mock routes."""
    return BARE_METAL_MOCK_ROUTE_MOUNT.route_declarations()


def bare_metal_mock_router(
    *,
    mock_executor: Callable[[], Any],
    host_authority: Callable[[], Any],
):
    """Bare metal's mock control routes, mounted only under the mock profile."""
    return make_mock_router(mock_executor=mock_executor, host_authority=host_authority)
