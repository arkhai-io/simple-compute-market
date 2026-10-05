"""VM/Ansible operator surfaces contributed to the compute service.

Each surface is a router factory taking zero-argument accessors for its
collaborators: the service mounts the routers when it builds the app, and
composes the collaborators later, at startup.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from compute_provisioning import ComputeProvisioningRouterMount


def vm_route_contracts():
    """The signed contracts of every route VM mounts, test routes included."""
    from vm_provisioning_operator.routes import VM_PROVISIONING_ROUTES

    return VM_PROVISIONING_ROUTES


def vm_mock_router(
    *,
    vm_runner: Callable[[], Any],
    host_authority: Callable[[], Any],
):
    """VM's mock control routes, mounted only under the mock profile."""
    from vm_provisioning_adapter.controllers.test_controller import make_mock_router

    return make_mock_router(vm_runner=vm_runner, host_authority=host_authority)


def vm_router_mounts(
    *,
    vm_operations: Callable[[], Any],
    host_operations: Callable[[], Any],
) -> tuple[ComputeProvisioningRouterMount, ...]:
    """VM's operator routes: VM operations and the host capacity check."""
    from vm_provisioning_adapter.controllers.hosts_controller import (
        make_host_capacity_router,
    )
    from vm_provisioning_adapter.controllers.vms_controller import make_vms_router

    return (
        ComputeProvisioningRouterMount(make_host_capacity_router(host_operations), "/api/v1"),
        ComputeProvisioningRouterMount(make_vms_router(vm_operations), "/api/v1"),
    )
