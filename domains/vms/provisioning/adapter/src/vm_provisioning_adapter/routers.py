"""VM/Ansible operator surfaces contributed to the compute service."""

from __future__ import annotations

from compute_provisioning import ComputeProvisioningRouterMount


def vm_mock_router():
    from vm_provisioning_adapter.controllers.test_controller import make_router

    return make_router()


def vm_router_mounts() -> tuple[ComputeProvisioningRouterMount, ...]:
    from vm_provisioning_adapter.controllers.hosts_controller import HostController
    from vm_provisioning_adapter.controllers.jobs_controller import (
        AnsibleJobsController,
    )
    from vm_provisioning_adapter.controllers.leases_controller import (
        AdminLeasesController,
        LeasesController,
    )
    from vm_provisioning_adapter.controllers.system_controller import SystemController
    from vm_provisioning_adapter.controllers.vms_controller import VmController

    return (
        ComputeProvisioningRouterMount(SystemController.make_health_router()),
        ComputeProvisioningRouterMount(
            SystemController.make_system_router(),
            "/api/v1",
        ),
        ComputeProvisioningRouterMount(
            AnsibleJobsController.make_router(),
            "/api/v1",
        ),
        ComputeProvisioningRouterMount(HostController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(VmController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(LeasesController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(
            AdminLeasesController.make_router(),
            "/api/v1",
        ),
    )
