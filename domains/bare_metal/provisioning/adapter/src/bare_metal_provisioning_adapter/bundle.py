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
from bare_metal_provisioning_adapter.services.bare_metal_fulfillment_provider import (
    BareMetalFulfillmentProvider,
)
from bare_metal_provisioning_adapter.services.bare_metal_pool_config_handler import (
    BareMetalPoolConfigHandler,
)


def build_bare_metal_adapter_bundle(
    *,
    compute_adapter: BareMetalComputeAdapter,
    release_executor: BareMetalReleaseExecutor,
    fulfillment_provider: BareMetalFulfillmentProvider,
    pool_config_handler: BareMetalPoolConfigHandler,
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
        fulfillment_providers={"bare_metal.ansible": fulfillment_provider},
        pool_config_handlers={"bare_metal.ansible": pool_config_handler},
        router_mounts=bare_metal_router_mounts(),
        readiness_checks=checks,
    )
