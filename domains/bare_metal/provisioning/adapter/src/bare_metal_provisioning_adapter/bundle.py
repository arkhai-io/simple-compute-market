"""Bare-metal executor contribution bundle."""

from __future__ import annotations

from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION
from compute_provisioning_service import (
    ExecutorAdapterBundle,
    ExecutorAdapterContribution,
)

from bare_metal_provisioning_adapter.compute_adapter import BareMetalComputeAdapter
from bare_metal_provisioning_adapter.release import BareMetalReleaseExecutor
from bare_metal_provisioning_adapter.routers import bare_metal_router_mounts
from bare_metal_provisioning_adapter.services.ansible_fulfillment_provider import (
    BareMetalAnsibleFulfillmentProvider,
)


def build_bare_metal_adapter_bundle(
    *,
    compute_adapter: BareMetalComputeAdapter,
    release_executor: BareMetalReleaseExecutor,
    fulfillment_provider: BareMetalAnsibleFulfillmentProvider,
    readiness_check=None,
) -> ExecutorAdapterBundle:
    checks = (
        {"bare-metal": readiness_check}
        if readiness_check is not None
        else {}
    )
    return ExecutorAdapterBundle(
        name="bare-metal",
        executors=(
            ExecutorAdapterContribution(
                adapter=compute_adapter,
                action_kinds=frozenset({NODE_GRANT_ACCESS_ACTION}),
                release_executor=release_executor,
            ),
        ),
        fulfillment_providers={
            ("ansible", "bare_metal"): fulfillment_provider,
        },
        router_mounts=bare_metal_router_mounts(),
        readiness_checks=checks,
    )
