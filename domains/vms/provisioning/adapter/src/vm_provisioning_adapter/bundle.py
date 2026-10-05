"""VM executor and Ansible provider contribution bundle."""

from __future__ import annotations

from types import MappingProxyType

from compute_provisioning import (
    ComputeProvisioningBackgroundTask,
    DefinitionDocumentContribution,
    ExecutorAdapterBundle,
    ExecutorAdapterContribution,
    JobExecutor,
)

from vm_provisioning_adapter.inventory_views import AnsiblePoolDefaultsViews
from vm_provisioning_adapter.services.ansible_fulfillment_provider import (
    AnsibleFulfillmentProvider,
)
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)
from vm_provisioning_adapter.services.relay_port_allocator import (
    release_fulfillment_ports,
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
    definition_documents: tuple[DefinitionDocumentContribution, ...] = (),
    background_tasks: tuple[ComputeProvisioningBackgroundTask, ...] = (),
) -> ExecutorAdapterBundle:
    """VM's contribution. Its relay ports are returned whenever a fulfillment
    record becomes terminal; the relay document and the port reconciliation
    are built by the runtime from its configuration."""
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
        inventory_views=(AnsiblePoolDefaultsViews(provider=ANSIBLE_PROVIDER),),
        fulfillment_terminal_hooks=(release_fulfillment_ports,),
        definition_documents=definition_documents,
        background_tasks=background_tasks,
    )
