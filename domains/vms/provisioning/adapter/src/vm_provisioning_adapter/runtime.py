"""VM/Ansible runtime entry point consumed by service composition."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

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

    def fulfillment_provider(self):
        return AnsibleFulfillmentProvider(
            job_service=self.job_service,
            job_queue_provider=self.job_queue_provider,
        )

    def readiness(self) -> dict[str, bool]:
        return {"ansible_service": self.ansible_service is not None}

    def adapter_bundle(self, site_authority):
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
            fulfillment_provider=self.fulfillment_provider(),
            pool_config_handler=self.pool_config_handler,
            readiness_check=self.readiness,
        )

    def release_job_port(self) -> VmFulfillmentReleaseJobPort:
        return VmFulfillmentReleaseJobPort(self.teardown_port)

    def system_service(self, *, lease_lifecycle_service):
        from vm_provisioning_adapter.services.system_service import SystemService

        return SystemService(
            ansible_service=self.ansible_service,
            settings=self.config,
            host_service=self.host_service,
            session_factory=self.session_factory,
            job_queue_provider=self.job_queue_provider,
            lease_lifecycle_service=lease_lifecycle_service,
        )


def project_ansible_pool_defaults(raw_view: Mapping[str, Any]) -> dict[str, Any]:
    """Shape an Ansible pool's configured VM size defaults for the
    site-authority resource-pool projection's `pool_views` field.

    Mirrors `bare_metal_provisioning_adapter.runtime.project_bare_metal_resource`'s
    placement (the domain adapter shapes its own view; the generic
    composer only calls out to it) but not its pydantic-validation
    mechanism -- three optional scalars with no cross-field validation
    need (the handler already enforces value constraints at write time)
    don't warrant a dedicated model. Only present (non-`None`) fields are
    included, so a pool with no configured defaults produces an empty
    dict -- the caller omits `pool_views` entirely in that case rather
    than emitting an empty view.
    """
    return {
        key: raw_view[key]
        for key in ("default_vm_ram", "default_vm_vcpus", "default_vm_disk_size")
        if raw_view.get(key) is not None
    }


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
