"""Bare-metal executor contribution bundle."""

from __future__ import annotations

from types import MappingProxyType

from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION
from compute_provisioning import (
    ExecutorAdapterBundle,
    ExecutorAdapterContribution,
    JobExecutor,
)
from compute_provisioning.job_fulfillment import JobFulfillmentProvider

from bare_metal_provisioning_adapter.inventory_views import BareMetalPublicationViews
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
    {BARE_METAL_PROVIDER: JobFulfillmentProvider.needs_host}
)


def build_bare_metal_adapter_bundle(
    *,
    fulfillment_provider: JobFulfillmentProvider,
    pool_config_handler: BareMetalPoolConfigHandler,
    job_executor: JobExecutor,
) -> ExecutorAdapterBundle:
    return ExecutorAdapterBundle(
        name="bare-metal",
        executors=(
            ExecutorAdapterContribution(
                offering_mode="bare_metal",
                job_executors={
                    NODE_GRANT_ACCESS_ACTION: job_executor,
                    NODE_RECLAIM_ACCESS_ACTION: job_executor,
                },
            ),
        ),
        fulfillment_providers={BARE_METAL_PROVIDER: fulfillment_provider},
        pool_config_handlers={BARE_METAL_PROVIDER: pool_config_handler},
        inventory_views=(BareMetalPublicationViews(),),
    )
