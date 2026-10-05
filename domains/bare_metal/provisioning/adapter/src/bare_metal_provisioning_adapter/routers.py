"""Bare-metal operator surfaces contributed to the compute service.

Bare metal mounts no operator routes: its leases are the family's, and access
is granted only through fulfillment. Its mock control routes are a router
factory taking zero-argument accessors, because the service mounts them when it
builds the app and composes their collaborators later, at startup.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def bare_metal_route_contracts():
    """The signed contracts of every route bare metal mounts, test routes included."""
    from arkhai_bare_metal.provisioning_client import BARE_METAL_PROVISIONING_ROUTES

    return BARE_METAL_PROVISIONING_ROUTES


def bare_metal_mock_router(
    *,
    mock_executor: Callable[[], Any],
    host_authority: Callable[[], Any],
):
    """Bare metal's mock control routes, mounted only under the mock profile."""
    from bare_metal_provisioning_adapter.controllers.test_controller import make_mock_router

    return make_mock_router(mock_executor=mock_executor, host_authority=host_authority)
