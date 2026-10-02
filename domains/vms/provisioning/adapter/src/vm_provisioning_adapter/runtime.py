"""VM/Ansible runtime entry point consumed by service composition."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from compute_provisioning import JobExecutorResolver
from compute_provisioning.hosts import ConnectionCodecs
from compute_provisioning.hosts.service import HostAuthority
from compute_provisioning_ansible import SshConnectionCodec
from compute_provisioning_service.services.relay_rebinding import check_host_pool_change
from vm_provisioning_adapter.bundle import HOST_REQUIREMENT, build_vm_adapter_bundle
from vm_provisioning_adapter.compute_adapter import VmComputeAdapter
from vm_provisioning_adapter.release import VmFulfillmentReleaseJobPort, VmReleaseExecutor
from compute_provisioning_service.services.relay_port_allocator import (
    RelayPortAllocator,
)
from compute_provisioning_service.services.relay_execution import (
    RelayExecutionResolver,
)
from vm_provisioning_adapter.services.ansible_fulfillment_provider import (
    AnsibleFulfillmentProvider,
)
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)
from vm_provisioning_adapter.services.ansible_job_executor import AnsibleJobExecutor
from vm_provisioning_adapter.services.ansible_service import AnsibleService
from vm_provisioning_adapter.services.host_operations_service import (
    HostOperationsService,
)
from vm_provisioning_adapter.services.job_service import AnsibleJobService
from vm_provisioning_adapter.services.vm_operations_service import VmOperationsService


@dataclass
class VmProvisioningRuntime:
    config: Any
    session_factory: Any
    job_queue_provider: Callable[[], Any]
    ansible_service: Any
    host_service: HostAuthority
    pool_config_handler: AnsiblePoolConfigHandler
    job_service: AnsibleJobService
    vm_operations_service: VmOperationsService
    host_operations_service: HostOperationsService
    settlement_repository: Any
    teardown_port: Any
    job_executors: Any = None
    # Fills a referenced relay's address and token into a VM job's parameters
    # immediately before it runs; a deployment with no relay needs none.
    relay_resolver: Any = None

    def job_executor(self) -> AnsibleJobExecutor:
        """What runs every VM job action: this runtime's runner and playbook."""
        return AnsibleJobExecutor(
            self.ansible_service,
            self.config.resolved_playbook_path,
            settings=self.config,
            result_kind=vm_result_kind,
            relay_resolver=self.relay_resolver,
        )

    def fulfillment_provider(self):
        return AnsibleFulfillmentProvider(
            job_service=self.job_service,
            job_queue_provider=self.job_queue_provider,
            port_allocator=RelayPortAllocator(self.session_factory),
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
            job_executor=self.job_executor(),
            readiness_check=self.readiness,
        )

    def release_job_port(self) -> VmFulfillmentReleaseJobPort:
        return VmFulfillmentReleaseJobPort(self.teardown_port)

    def system_service(
        self,
        *,
        lease_lifecycle_service,
        fulfillment_convergence_watchdog=None,
    ):
        from vm_provisioning_adapter.services.system_service import SystemService

        return SystemService(
            ansible_service=self.ansible_service,
            settings=self.config,
            host_service=self.host_service,
            session_factory=self.session_factory,
            job_queue_provider=self.job_queue_provider,
            lease_lifecycle_service=lease_lifecycle_service,
            fulfillment_convergence_watchdog=fulfillment_convergence_watchdog,
            job_executors=self.job_executors,
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


def vm_result_kind(action: str) -> str:
    """The kind of the result a VM action's job produces."""
    return f"vm_{action}"


def _relay_pool_change(db, host_id: str, current_pool_id: str, new_pool_id: str) -> None:
    # A host moving to a pool on a different relay while it holds leases would
    # strand its VMs' buyers on the old address; the move is refused.
    check_host_pool_change(
        db,
        host_id=host_id,
        current_pool_id=current_pool_id,
        new_pool_id=new_pool_id,
    )


def build_vm_runtime(
    *,
    config,
    session_factory,
    job_queue_provider: Callable[[], Any],
    settlement_repository,
    teardown_port: Any,
    capacity_derivation: Any,
    job_executors: JobExecutorResolver,
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

    host_service = HostAuthority(
        session_factory,
        codecs=ConnectionCodecs([SshConnectionCodec(config.ssh_decryption_key)]),
        capacity_derivation=capacity_derivation,
        pool_change_hooks=(_relay_pool_change,),
    )
    job_service = AnsibleJobService(
        settings=config,
        session_factory=session_factory,
        executors=job_executors,
        host_service=host_service,
    )
    vm_operations_service = VmOperationsService(
        job_service=job_service,
        job_queue_provider=job_queue_provider,
    )
    return VmProvisioningRuntime(
        relay_resolver=RelayExecutionResolver(
            session_factory=session_factory, settings=config
        ),
        config=config,
        session_factory=session_factory,
        job_queue_provider=job_queue_provider,
        ansible_service=ansible_service,
        host_service=host_service,
        pool_config_handler=AnsiblePoolConfigHandler(settings=config),
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
        job_executors=job_executors,
    )
