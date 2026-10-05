"""Bare-metal operator surfaces contributed to the compute service."""

from __future__ import annotations

from compute_provisioning import ComputeProvisioningRouterMount


def bare_metal_route_contracts():
    """The signed contracts of every route bare metal mounts, test routes included."""
    from arkhai_bare_metal.provisioning_client import BARE_METAL_PROVISIONING_ROUTES

    return BARE_METAL_PROVISIONING_ROUTES


def bare_metal_mock_router():
    from bare_metal_provisioning_adapter.controllers.test_controller import make_router

    return make_router()


def bare_metal_router_mounts() -> tuple[ComputeProvisioningRouterMount, ...]:
    """Bare metal mounts no operator routes: its leases are the family's, and
    access is granted only through fulfillment."""
    return ()
