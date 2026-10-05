"""Bare-metal runtime entry point consumed by service composition."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from arkhai_bare_metal import BareMetalResourceProjection
from compute_provisioning_ansible import AnsibleJobExecutor, MockAnsibleRunner
from compute_provisioning_ansible.runner import AnsibleRunner

from bare_metal_provisioning_adapter.bundle import (
    HOST_REQUIREMENT,
    build_bare_metal_adapter_bundle,
)
from bare_metal_provisioning_adapter.codec import BareMetalAnsibleCodec
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
    # Runs the bare-metal access playbook: the real Ansible runner, or under
    # the mock profile this adapter's own mock.
    ansible_service: Any
    playbook_path: Any
    settings: Any

    def job_executor(self) -> AnsibleJobExecutor:
        """What runs both bare-metal access actions."""
        return AnsibleJobExecutor(
            self.ansible_service,
            BareMetalAnsibleCodec(),
            self.playbook_path,
            timeout_seconds=self.settings.ansible_timeout_seconds,
            additional_non_retryable_errors=self.settings.additional_non_retryable_errors,
        )

    def readiness(self) -> dict[str, bool]:
        return {"operations_service": self.operations_service is not None}

    @property
    def mock_executor(self):
        """This adapter's mock runner, or ``None`` outside the mock profile."""
        if isinstance(self.ansible_service, MockAnsibleRunner):
            return self.ansible_service
        return None

    def adapter_bundle(self):
        return build_bare_metal_adapter_bundle(
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


def project_bare_metal_resource(raw_view: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and serialize the public bare-metal resource projection."""
    return BareMetalResourceProjection.model_validate(raw_view).model_dump(mode="json")


def build_bare_metal_runtime(
    *,
    site_authority,
    job_engine,
    job_queue_provider: Callable[[], Any],
    config,
    host_authority,
) -> BareMetalProvisioningRuntime:
    active = [
        profile.strip()
        for profile in os.environ.get("ACTIVE_PROFILES", "").split(",")
        if profile.strip()
    ]
    if "mock" in active:
        from bare_metal_provisioning_adapter.services.mock_output import (
            bare_metal_mock_output,
        )

        ansible_service = MockAnsibleRunner(default_output=bare_metal_mock_output)
    else:
        ansible_service = AnsibleRunner(config)
    operations_service = BareMetalOperationsService(
        jobs=job_engine,
        job_queue_provider=job_queue_provider,
        host_service=host_authority,
        reclaim_policy=getattr(config, "bare_metal_reclaim_policy", None),
    )
    return BareMetalProvisioningRuntime(
        lease_service=BareMetalLeaseService(site_authority=site_authority),
        operations_service=operations_service,
        fulfillment_provider=BareMetalFulfillmentProvider(
            operations_service=operations_service,
            job_service=job_engine,
        ),
        pool_config_handler=BareMetalPoolConfigHandler(),
        ansible_service=ansible_service,
        playbook_path=config.resolved_bare_metal_playbook_path,
        settings=config,
    )
