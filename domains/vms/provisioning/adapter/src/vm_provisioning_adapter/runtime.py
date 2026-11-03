"""VM/Ansible runtime entry point consumed by service composition."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from compute_provisioning.hosts import ConnectionCodecs
from compute_provisioning.hosts.service import HostAuthority
from compute_provisioning.job_fulfillment import JobFulfillmentProvider
from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning.jobs.submission import JobSubmissionService
from compute_provisioning.relays import RelayExecutionResolver, RelayPortAllocator
from compute_provisioning_ansible import AnsibleJobExecutor, MockAnsibleRunner
from compute_provisioning_ansible.runner import AnsibleRunner
from vm_provisioning_adapter.bundle import HOST_REQUIREMENT, build_vm_adapter_bundle
from vm_provisioning_adapter.codec import GoldenImageCredentials, VmAnsibleCodec
from vm_provisioning_adapter.services.mock_output import vm_mock_output
from vm_provisioning_adapter.services.vm_fulfillment_plan import VmFulfillmentPlan
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)
from vm_provisioning_adapter.services.host_operations_service import (
    HostOperationsService,
)
from vm_provisioning_adapter.services.vm_operations_service import VmOperationsService

logger = logging.getLogger(__name__)


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
    job_submission: JobSubmissionService
    vm_operations_service: VmOperationsService
    host_operations_service: HostOperationsService
    # The family's one allocator, which every domain's relay ports lease from;
    # VM's plan leases through it when a create is accepted.
    relay_port_allocator: RelayPortAllocator

    def job_executor(self) -> AnsibleJobExecutor:
        """What runs every VM job action: this runtime's runner, codec, and playbook."""
        return AnsibleJobExecutor(
            self.ansible_service,
            self.codec,
            self.config.resolved_vm_playbook_path,
            timeout_seconds=self.config.ansible_timeout_seconds,
            additional_non_retryable_errors=self.config.additional_non_retryable_errors,
        )

    def fulfillment_plan(self) -> VmFulfillmentPlan:
        return VmFulfillmentPlan(
            reserved_var_keys=self.codec.reserved_var_keys,
            vm_playbook_path=self.config.resolved_vm_playbook_path,
            port_allocator=self.relay_port_allocator,
        )

    def fulfillment_provider(self) -> JobFulfillmentProvider:
        return JobFulfillmentProvider(
            plan=self.fulfillment_plan(),
            submission=self.job_submission,
            jobs=self.job_engine,
        )

    def adapter_bundle(self):
        return build_vm_adapter_bundle(
            fulfillment_provider=self.fulfillment_provider(),
            pool_config_handler=self.pool_config_handler,
            job_executor=self.job_executor(),
        )


def build_vm_runtime(
    *,
    config,
    session_factory,
    job_queue_provider: Callable[[], Any],
    host_authority: HostAuthority,
    job_engine: JobEngine,
    job_submission: JobSubmissionService,
    relay_port_allocator: RelayPortAllocator,
    relay_resolver: RelayExecutionResolver,
    connection_codecs: ConnectionCodecs,
) -> VmProvisioningRuntime:
    active = [
        profile.strip()
        for profile in os.environ.get("ACTIVE_PROFILES", "").split(",")
        if profile.strip()
    ]
    if "mock" in active:
        ansible_service = MockAnsibleRunner(default_output=vm_mock_output)
    else:
        ansible_service = AnsibleRunner(config)

    codec = VmAnsibleCodec(
        golden_image=GoldenImageCredentials(
            root_ssh_filename=str(config.golden_root_ssh_filename or ""),
            root_ssh_password=str(config.golden_root_ssh_password or ""),
            image_name=str(config.golden_image_name or ""),
        ),
        # Fills a referenced relay's address and token into a VM job's
        # parameters immediately before it runs; a job naming no relay passes
        # through untouched.
        relay_resolver=relay_resolver,
    )
    return VmProvisioningRuntime(
        config=config,
        session_factory=session_factory,
        job_queue_provider=job_queue_provider,
        ansible_service=ansible_service,
        codec=codec,
        host_authority=host_authority,
        pool_config_handler=AnsiblePoolConfigHandler(
            settings=config, connection_codecs=connection_codecs
        ),
        job_engine=job_engine,
        job_submission=job_submission,
        vm_operations_service=VmOperationsService(submission=job_submission),
        host_operations_service=HostOperationsService(submission=job_submission),
        relay_port_allocator=relay_port_allocator,
    )


__all__ = ["HOST_REQUIREMENT", "VmProvisioningRuntime", "build_vm_runtime"]
