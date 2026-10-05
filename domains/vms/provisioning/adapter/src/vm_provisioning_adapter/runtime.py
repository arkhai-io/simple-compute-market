"""VM/Ansible runtime entry point consumed by service composition."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from compute_provisioning import JobExecutorResolver
from compute_provisioning.hosts.service import HostAuthority, PoolChangeRefusedError
from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning_ansible import AnsibleJobExecutor
from compute_provisioning_ansible.runner import AnsibleRunner
from compute_provisioning_service.services.relay_rebinding import (
    RelayRebindingRefused,
    check_host_pool_change,
)
from vm_provisioning_adapter.bundle import HOST_REQUIREMENT, build_vm_adapter_bundle
from vm_provisioning_adapter.codec import GoldenImageCredentials, VmAnsibleCodec
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
from vm_provisioning_adapter.services.host_operations_service import (
    HostOperationsService,
)
from vm_provisioning_adapter.services.job_submitter import VmJobSubmitter
from vm_provisioning_adapter.services.vm_operations_service import VmOperationsService


@dataclass
class VmProvisioningRuntime:
    config: Any
    session_factory: Any
    job_queue_provider: Callable[[], Any]
    # The Ansible runner VM jobs and connectivity checks use: the real one, or
    # under the mock profile the programmable mock.
    ansible_service: Any
    codec: VmAnsibleCodec
    host_authority: HostAuthority
    pool_config_handler: AnsiblePoolConfigHandler
    job_engine: JobEngine
    job_submitter: VmJobSubmitter
    vm_operations_service: VmOperationsService
    host_operations_service: HostOperationsService
    job_executors: Any = None

    def job_executor(self) -> AnsibleJobExecutor:
        """What runs every VM job action: this runtime's runner, codec, and playbook."""
        return AnsibleJobExecutor(
            self.ansible_service,
            self.codec,
            self.config.resolved_playbook_path,
            timeout_seconds=self.config.ansible_timeout_seconds,
            additional_non_retryable_errors=self.config.additional_non_retryable_errors,
        )

    def fulfillment_provider(self):
        return AnsibleFulfillmentProvider(
            job_submitter=self.job_submitter,
            jobs=self.job_engine,
            job_queue_provider=self.job_queue_provider,
            reserved_var_keys=self.codec.reserved_var_keys,
            port_allocator=RelayPortAllocator(self.session_factory),
        )

    def readiness(self) -> dict[str, bool]:
        return {"ansible_service": self.ansible_service is not None}

    def adapter_bundle(self):
        return build_vm_adapter_bundle(
            fulfillment_provider=self.fulfillment_provider(),
            pool_config_handler=self.pool_config_handler,
            job_executor=self.job_executor(),
            readiness_check=self.readiness,
        )

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
            host_service=self.host_authority,
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


def _relay_pool_change(db, host_id: str, current_pool_id: str, new_pool_id: str) -> None:
    # A host moving to a pool on a different relay while it holds leases would
    # strand its VMs' buyers on the old address; the move is refused, in the
    # host authority's own refusal so every host route answers it alike.
    try:
        check_host_pool_change(
            db,
            host_id=host_id,
            current_pool_id=current_pool_id,
            new_pool_id=new_pool_id,
        )
    except RelayRebindingRefused as exc:
        raise PoolChangeRefusedError(str(exc)) from exc


#: The host pool-change checks VM contributes to the one host authority the
#: composition root builds, which exists before any runtime does; the root
#: merges each adapter's declaration as it merges ``HOST_REQUIREMENT``.
HOST_POOL_CHANGE_HOOKS = (_relay_pool_change,)


def build_vm_runtime(
    *,
    config,
    session_factory,
    job_queue_provider: Callable[[], Any],
    host_authority: HostAuthority,
    job_engine: JobEngine,
    job_executors: JobExecutorResolver,
) -> VmProvisioningRuntime:
    active = [
        profile.strip()
        for profile in os.environ.get("ACTIVE_PROFILES", "").split(",")
        if profile.strip()
    ]
    if "mock" in active:
        from compute_provisioning_ansible import MockAnsibleRunner
        from vm_provisioning_adapter.services.mock_output import vm_mock_output

        ansible_service = MockAnsibleRunner(default_output=vm_mock_output)
    else:
        ansible_service = AnsibleRunner(config)

    job_submitter = VmJobSubmitter(
        job_engine, default_host_id=config.default_host_id
    )
    vm_operations_service = VmOperationsService(
        job_submitter=job_submitter,
        job_queue_provider=job_queue_provider,
    )
    codec = VmAnsibleCodec(
        golden_image=GoldenImageCredentials(
            root_ssh_filename=str(config.golden_root_ssh_filename or ""),
            root_ssh_password=str(config.golden_root_ssh_password or ""),
            image_name=str(config.golden_image_name or ""),
        ),
        # Fills a referenced relay's address and token into a VM job's
        # parameters immediately before it runs; a job naming no relay passes
        # through untouched.
        relay_resolver=RelayExecutionResolver(
            session_factory=session_factory, settings=config
        ),
    )
    return VmProvisioningRuntime(
        config=config,
        session_factory=session_factory,
        job_queue_provider=job_queue_provider,
        ansible_service=ansible_service,
        codec=codec,
        host_authority=host_authority,
        pool_config_handler=AnsiblePoolConfigHandler(settings=config),
        job_engine=job_engine,
        job_submitter=job_submitter,
        vm_operations_service=vm_operations_service,
        host_operations_service=HostOperationsService(
            host_service=host_authority,
            job_submitter=job_submitter,
            job_queue_provider=job_queue_provider,
        ),
        job_executors=job_executors,
    )
