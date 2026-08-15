"""Bare-metal runtime entry point consumed by service composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from arkhai_bare_metal import BareMetalResourceProjection

from bare_metal_provisioning_adapter.bundle import build_bare_metal_adapter_bundle
from bare_metal_provisioning_adapter.compute_adapter import BareMetalComputeAdapter
from bare_metal_provisioning_adapter.release import BareMetalReleaseExecutor
from bare_metal_provisioning_adapter.services.bare_metal_lease_service import (
    BareMetalLeaseService,
)
from bare_metal_provisioning_adapter.services.bare_metal_operations_service import (
    BareMetalOperationsService,
)
from bare_metal_provisioning_adapter.services.bare_metal_fulfillment_provider import (
    BareMetalFulfillmentProvider,
)
from bare_metal_provisioning_adapter.services.bare_metal_pool_config_handler import (
    BareMetalPoolConfigHandler,
)


@dataclass
class BareMetalProvisioningRuntime:
    lease_service: BareMetalLeaseService
    operations_service: BareMetalOperationsService
    fulfillment_provider: BareMetalFulfillmentProvider
    pool_config_handler: BareMetalPoolConfigHandler

    def readiness(self) -> dict[str, bool]:
        return {"operations_service": self.operations_service is not None}

    def adapter_bundle(self, site_authority):
        return build_bare_metal_adapter_bundle(
            compute_adapter=BareMetalComputeAdapter(
                site_authority,
                self.operations_service,
            ),
            release_executor=BareMetalReleaseExecutor(
                release_delegate=(
                    self.operations_service.reclaim_access_for_reservation
                ),
            ),
            fulfillment_provider=self.fulfillment_provider,
            pool_config_handler=self.pool_config_handler,
            readiness_check=self.readiness,
        )


def project_bare_metal_resource(raw_view: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and serialize the public bare-metal resource projection."""
    return BareMetalResourceProjection.model_validate(raw_view).model_dump(mode="json")


def build_bare_metal_runtime(
    *,
    site_authority,
    job_service,
    job_queue_provider: Callable[[], Any],
    config,
    host_service,
) -> BareMetalProvisioningRuntime:
    operations_service = BareMetalOperationsService(
        job_service=job_service,
        job_queue_provider=job_queue_provider,
        settings=config,
        host_service=host_service,
    )
    return BareMetalProvisioningRuntime(
        lease_service=BareMetalLeaseService(site_authority=site_authority),
        operations_service=operations_service,
        fulfillment_provider=BareMetalFulfillmentProvider(
            operations_service=operations_service,
            job_service=job_service,
        ),
        pool_config_handler=BareMetalPoolConfigHandler(),
    )
