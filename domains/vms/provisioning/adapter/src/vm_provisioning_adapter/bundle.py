"""VM executor and Ansible provider contribution bundle."""

from __future__ import annotations

from types import MappingProxyType

from compute_provisioning import (
    ExecutorAdapterBundle,
    ExecutorAdapterContribution,
    JobExecutor,
)

from vm_provisioning_adapter.routers import vm_router_mounts
from vm_provisioning_adapter.services.ansible_fulfillment_provider import (
    AnsibleFulfillmentProvider,
)
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)


#: The provider identity this bundle registers.
ANSIBLE_PROVIDER = "ansible"

#: What this bundle's providers declare about needing a host, keyed by
#: provider identity. Read from the provider classes so composition can hand it
#: to the site ledger, which is built before any provider instance exists;
#: composition refuses to start if it disagrees with the registered instances.
HOST_REQUIREMENT = MappingProxyType(
    {ANSIBLE_PROVIDER: AnsibleFulfillmentProvider.needs_host}
)

#: Every action a VM job runs, whether submitted through the operator VM and
#: host routes or by fulfillment create and teardown.
VM_JOB_ACTIONS = frozenset(
    {
        "create",
        "list",
        "start",
        "shutdown",
        "destroy",
        "reboot",
        "undefine",
        "monitor",
        "reset_password",
        "vm_remove",
        "check",
    }
)


def build_vm_adapter_bundle(
    *,
    fulfillment_provider: AnsibleFulfillmentProvider,
    pool_config_handler: AnsiblePoolConfigHandler,
    job_executor: JobExecutor,
    readiness_check=None,
) -> ExecutorAdapterBundle:
    checks = {"ansible": readiness_check} if readiness_check is not None else {}
    return ExecutorAdapterBundle(
        name="vm",
        executors=(
            ExecutorAdapterContribution(
                offering_mode="vm",
                job_executors={action: job_executor for action in VM_JOB_ACTIONS},
            ),
        ),
        fulfillment_providers={ANSIBLE_PROVIDER: fulfillment_provider},
        pool_config_handlers={ANSIBLE_PROVIDER: pool_config_handler},
        router_mounts=vm_router_mounts(),
        readiness_checks=checks,
    )
