"""Bare-metal runtime entry point consumed by service composition."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from compute_provisioning.job_fulfillment import JobFulfillmentProvider
from compute_provisioning.jobs.submission import JobSubmissionService
from compute_provisioning_ansible import AnsibleJobExecutor, MockAnsibleRunner
from compute_provisioning_ansible.runner import AnsibleRunner

from bare_metal_provisioning_adapter.bundle import (
    HOST_REQUIREMENT,
    build_bare_metal_adapter_bundle,
)
from bare_metal_provisioning_adapter.codec import BareMetalAnsibleCodec
from bare_metal_provisioning_adapter.services.bare_metal_fulfillment_plan import (
    BareMetalFulfillmentPlan,
)
from bare_metal_provisioning_adapter.services.bare_metal_pool_config_handler import (
    BareMetalPoolConfigHandler,
)
from bare_metal_provisioning_adapter.services.mock_output import bare_metal_mock_output


@dataclass
class BareMetalProvisioningRuntime:
    fulfillment_provider: JobFulfillmentProvider
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

    @property
    def mock_executor(self):
        """This adapter's mock runner, or ``None`` outside the mock profile."""
        if isinstance(self.ansible_service, MockAnsibleRunner):
            return self.ansible_service
        return None

    def adapter_bundle(self):
        return build_bare_metal_adapter_bundle(
            fulfillment_provider=self.fulfillment_provider,
            pool_config_handler=self.pool_config_handler,
            job_executor=self.job_executor(),
        )


def build_bare_metal_runtime(
    *,
    job_engine,
    job_submission: JobSubmissionService,
    config,
) -> BareMetalProvisioningRuntime:
    active = [
        profile.strip()
        for profile in os.environ.get("ACTIVE_PROFILES", "").split(",")
        if profile.strip()
    ]
    if "mock" in active:
        ansible_service = MockAnsibleRunner(default_output=bare_metal_mock_output)
    else:
        ansible_service = AnsibleRunner(config)
    return BareMetalProvisioningRuntime(
        fulfillment_provider=JobFulfillmentProvider(
            plan=BareMetalFulfillmentPlan(
                reclaim_policy=getattr(config, "bare_metal_reclaim_policy", None),
            ),
            submission=job_submission,
            jobs=job_engine,
        ),
        pool_config_handler=BareMetalPoolConfigHandler(),
        ansible_service=ansible_service,
        playbook_path=config.resolved_bare_metal_playbook_path,
        settings=config,
    )
