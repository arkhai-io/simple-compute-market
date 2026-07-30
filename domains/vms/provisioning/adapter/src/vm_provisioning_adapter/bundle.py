"""VM executor and Ansible provider contribution bundle."""

from __future__ import annotations

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


def build_vm_adapter_bundle(
    *,
    compute_adapter: VmComputeAdapter,
    release_executor: VmReleaseExecutor,
    fulfillment_provider: AnsibleFulfillmentProvider,
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
        fulfillment_providers={"ansible": fulfillment_provider},
        router_mounts=vm_router_mounts(),
        readiness_checks=checks,
    )
