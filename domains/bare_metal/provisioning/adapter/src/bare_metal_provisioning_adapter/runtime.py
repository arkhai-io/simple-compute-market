"""Bare-metal runtime entry point consumed by service composition."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from arkhai_bare_metal import BareMetalResourceProjection
from vm_provisioning_adapter.services.ansible_job_executor import AnsibleJobExecutor

from bare_metal_provisioning_adapter.bundle import (
    HOST_REQUIREMENT,
    build_bare_metal_adapter_bundle,
)
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
    # Runs the bare-metal access playbook: the real Ansible service, or under
    # the mock profile this adapter's own mock.
    ansible_service: Any
    playbook_path: Any
    settings: Any

    def job_executor(self) -> AnsibleJobExecutor:
        """What runs both bare-metal access actions."""
        return AnsibleJobExecutor(
            self.ansible_service,
            self.playbook_path,
            settings=self.settings,
            result_kind=bare_metal_result_kind,
        )

    def readiness(self) -> dict[str, bool]:
        return {"operations_service": self.operations_service is not None}

    @property
    def mock_executor(self):
        """This adapter's mock runner, or ``None`` outside the mock profile."""
        from bare_metal_provisioning_adapter.services.bare_metal_mock_executor import (
            BareMetalMockAnsibleService,
        )

        if isinstance(self.ansible_service, BareMetalMockAnsibleService):
            return self.ansible_service
        return None

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
            job_executor=self.job_executor(),
            readiness_check=self.readiness,
        )


def bare_metal_result_kind(action: str) -> str:
    """Both bare-metal access actions produce the access result."""
    return "bare_metal_access"


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
    active = [
        profile.strip()
        for profile in os.environ.get("ACTIVE_PROFILES", "").split(",")
        if profile.strip()
    ]
    if "mock" in active:
        from bare_metal_provisioning_adapter.services.bare_metal_mock_executor import (
            BareMetalMockAnsibleService,
        )

        ansible_service = BareMetalMockAnsibleService(config)
    else:
        from vm_provisioning_adapter.services.ansible_service import AnsibleService

        ansible_service = AnsibleService(config)
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
        ansible_service=ansible_service,
        playbook_path=config.resolved_bare_metal_playbook_path,
        settings=config,
    )
