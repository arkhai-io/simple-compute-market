"""VM executor and Ansible provider contribution bundle."""

from __future__ import annotations

from types import MappingProxyType

from compute_provisioning_service import (
    ExecutorAdapterBundle,
    ExecutorAdapterContribution,
)

from vm_provisioning_adapter.compute_adapter import VmComputeAdapter
from vm_provisioning_adapter.release import VmReleaseExecutor
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


def build_vm_adapter_bundle(
    *,
    compute_adapter: VmComputeAdapter,
    release_executor: VmReleaseExecutor,
    fulfillment_provider: AnsibleFulfillmentProvider,
    pool_config_handler: AnsiblePoolConfigHandler,
    readiness_check=None,
) -> ExecutorAdapterBundle:
    checks = {"ansible": readiness_check} if readiness_check is not None else {}
    return ExecutorAdapterBundle(
        name="vm",
        executors=(
            ExecutorAdapterContribution(
                adapter=compute_adapter,
                action_kinds=frozenset({"create"}),
                release_executor=release_executor,
            ),
        ),
        fulfillment_providers={ANSIBLE_PROVIDER: fulfillment_provider},
        pool_config_handlers={ANSIBLE_PROVIDER: pool_config_handler},
        router_mounts=vm_router_mounts(),
        readiness_checks=checks,
    )
