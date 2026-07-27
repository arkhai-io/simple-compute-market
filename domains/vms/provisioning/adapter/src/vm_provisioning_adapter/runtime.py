"""VM/Ansible runtime entry point consumed by service composition."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from vm_provisioning_adapter.bundle import build_vm_adapter_bundle
from vm_provisioning_adapter.compute_adapter import VmComputeAdapter
from vm_provisioning_adapter.release import VmFulfillmentReleaseJobPort, VmReleaseExecutor
from vm_provisioning_adapter.services.ansible_fulfillment_provider import (
    AnsibleFulfillmentProvider,
)
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)
from vm_provisioning_adapter.services.ansible_service import AnsibleService
from vm_provisioning_adapter.services.host_operations_service import (
    HostOperationsService,
)
from vm_provisioning_adapter.services.host_service import HostService
from vm_provisioning_adapter.services.job_service import AnsibleJobService
from vm_provisioning_adapter.services.vm_operations_service import VmOperationsService


@dataclass
class VmProvisioningRuntime:
    config: Any
    session_factory: Any
    job_queue_provider: Callable[[], Any]
    ansible_service: Any
    host_service: HostService
    pool_config_handler: AnsiblePoolConfigHandler
    job_service: AnsibleJobService
    vm_operations_service: VmOperationsService
    host_operations_service: HostOperationsService
    settlement_repository: Any
    teardown_port: Any

    def fulfillment_provider(self, resource_pool_service):
        return AnsibleFulfillmentProvider(
            job_service=self.job_service,
            job_queue_provider=self.job_queue_provider,
        )

    def readiness(self) -> dict[str, bool]:
        return {"ansible_service": self.ansible_service is not None}

    def adapter_bundle(self, site_authority, resource_pool_service):
        return build_vm_adapter_bundle(
            compute_adapter=VmComputeAdapter(
                site_authority,
                self.vm_operations_service,
            ),
            release_executor=VmReleaseExecutor(
                settlement_repository=self.settlement_repository,
                session_factory=self.session_factory,
                teardown_port=self.teardown_port,
            ),
            fulfillment_provider=self.fulfillment_provider(resource_pool_service),
            readiness_check=self.readiness,
        )

    def release_job_port(self) -> VmFulfillmentReleaseJobPort:
        return VmFulfillmentReleaseJobPort(self.teardown_port)

    def system_service(self, *, lease_lifecycle_service, fulfillment_convergence_watchdog):
        from vm_provisioning_adapter.services.system_service import SystemService

        return SystemService(
            ansible_service=self.ansible_service,
            settings=self.config,
            host_service=self.host_service,
            session_factory=self.session_factory,
            job_queue_provider=self.job_queue_provider,
            lease_lifecycle_service=lease_lifecycle_service,
            fulfillment_convergence_watchdog=fulfillment_convergence_watchdog,
        )


def build_vm_runtime(
    *,
    config,
    session_factory,
    job_queue_provider: Callable[[], Any],
    settlement_repository,
    teardown_port: Any,
) -> VmProvisioningRuntime:
    active = [
        profile.strip()
        for profile in os.environ.get("ACTIVE_PROFILES", "").split(",")
        if profile.strip()
    ]
    if "mock" in active:
        from vm_provisioning_adapter.services.mock_ansible_service import (
            ProgrammableMockAnsibleService,
        )

        ansible_service = ProgrammableMockAnsibleService(config)
    else:
        ansible_service = AnsibleService(config)

    host_service = HostService(
        session_factory=session_factory,
        settings=config,
    )
    job_service = AnsibleJobService(
        settings=config,
        session_factory=session_factory,
        ansible_service=ansible_service,
        host_service=host_service,
    )
    vm_operations_service = VmOperationsService(
        job_service=job_service,
        job_queue_provider=job_queue_provider,
    )
    return VmProvisioningRuntime(
        config=config,
        session_factory=session_factory,
        job_queue_provider=job_queue_provider,
        ansible_service=ansible_service,
        host_service=host_service,
        pool_config_handler=AnsiblePoolConfigHandler(),
        job_service=job_service,
        vm_operations_service=vm_operations_service,
        host_operations_service=HostOperationsService(
            ansible_service=ansible_service,
            host_service=host_service,
            job_service=job_service,
            job_queue_provider=job_queue_provider,
        ),
        settlement_repository=settlement_repository,
        teardown_port=teardown_port,
    )
