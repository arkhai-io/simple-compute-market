"""Storefront-specific orchestration around the provisioning service client.

The ``provisioning_client`` wheel owns the inter-service HTTP contract and low-level
client methods.  This module owns storefront workflow glue: submit a VM create job,
optionally persist the job id through a callback, wait for completion, and merge the
credential response into the fulfillment payload shape expected by storefront callers.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

import provisioning_client
from provisioning_client import CreateVmRequest

logger = logging.getLogger(__name__)


def _credentials_auth_payload(
    credentials: provisioning_client.CredentialListResponse,
) -> dict[str, Any]:
    """Convert provisioning credentials into the storefront auth payload shape."""
    auth: dict[str, Any] = {}
    for credential in credentials.credentials:
        if credential.role:
            auth[credential.role] = {
                "password": credential.password,
                "ssh_commands": credential.ssh_commands,
                "ssh_key_path_host": credential.ssh_key_path_host,
                "key_type": credential.key_type,
            }
    return auth


async def create_vm_and_wait_with_credentials(
    *,
    service_url: str,
    admin_key: str | None,
    timeout: float,
    poll_interval: float,
    vm_host: str,
    request: CreateVmRequest,
    on_job_submitted: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Submit a VM create job, poll it to completion, and merge credentials.

    The returned dictionary is the provisioning job result plus an optional
    ``authentication`` field keyed by credential role.  Callback failures and
    credential-fetch failures are logged but do not mask a successful VM create job.
    """
    async with provisioning_client.ProvisioningClient(
        service_url,
        admin_key=admin_key,
        timeout=timeout,
    ) as client:
        submit = await client.create_vm(vm_host, request)

        if on_job_submitted is not None:
            try:
                await on_job_submitted(submit.job_id)
            except Exception as exc:
                logger.warning(
                    "[PROVISIONING] on_job_submitted callback failed for job %s: %s",
                    submit.job_id,
                    exc,
                )

        job = await client.poll_until_complete(
            submit.job_id,
            timeout=timeout,
            poll_interval=poll_interval,
        )
        result = job.result or {}

        try:
            creds_resp = await client.get_job_credentials(submit.job_id)
            auth = _credentials_auth_payload(creds_resp)
            if auth:
                result["authentication"] = auth
        except Exception as exc:
            logger.warning(
                "[PROVISIONING] Failed to fetch credentials for job %s: %s",
                submit.job_id,
                exc,
            )

    return result
