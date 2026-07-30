"""Bare-metal operator surfaces contributed to the compute service."""

from __future__ import annotations

from compute_provisioning import ComputeProvisioningRouterMount


def bare_metal_router_mounts() -> tuple[ComputeProvisioningRouterMount, ...]:
    from bare_metal_provisioning_adapter.controllers.bare_metal_leases_controller import (
        BareMetalLeasesController,
    )

    return (
        ComputeProvisioningRouterMount(
            BareMetalLeasesController.make_router(),
            "/api/v1",
        ),
    )
