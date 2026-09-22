"""Bare-metal executor contribution bundle."""

from __future__ import annotations

from types import MappingProxyType

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


#: The provider identity this bundle registers.
BARE_METAL_PROVIDER = "bare_metal.ansible"

#: What this bundle's providers declare about needing a host, keyed by
#: provider identity. Read from the provider classes so composition can hand it
#: to the site ledger, which is built before any provider instance exists;
#: composition refuses to start if it disagrees with the registered instances.
HOST_REQUIREMENT = MappingProxyType(
    {BARE_METAL_PROVIDER: BareMetalFulfillmentProvider.needs_host}
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
        fulfillment_providers={BARE_METAL_PROVIDER: fulfillment_provider},
        pool_config_handlers={BARE_METAL_PROVIDER: pool_config_handler},
        router_mounts=bare_metal_router_mounts(),
        readiness_checks=checks,
    )
