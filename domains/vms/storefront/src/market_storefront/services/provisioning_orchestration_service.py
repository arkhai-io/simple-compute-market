"""Storefront orchestration over the versioned compute-provisioning contract."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from compute_provisioning import (
    ComputeProvisioningClient,
    CredentialEnvelope,
    ExecutorActionEnvelope,
)

logger = logging.getLogger(__name__)


def _credentials_auth_payload(
    credentials: list[CredentialEnvelope],
) -> dict[str, Any]:
    """Convert provisioning credentials into the storefront auth payload shape."""
    auth: dict[str, Any] = {}
    for credential in credentials:
        role = credential.credential_kind
        if role:
            auth[role] = dict(credential.value)
    return auth


async def create_vm_and_wait_with_credentials(
    *,
    service_url: str,
    admin_key: str | None,
    timeout: float,
    poll_interval: float,
    vm_host: str,
    allocation_id: str,
    deal_ref: dict[str, Any],
    parameters: dict[str, Any],
    on_job_submitted: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Submit a VM create job, poll it to completion, and merge credentials.

    The returned dictionary is the provisioning job result plus an optional
    ``authentication`` field keyed by credential role.  Callback failures and
    credential-fetch failures are logged but do not mask a successful VM create job.
    """
    async with ComputeProvisioningClient(
        service_url,
        admin_key=admin_key,
        timeout=timeout,
    ) as client:
        submit = await client.submit_action(ExecutorActionEnvelope(
            allocation_id=allocation_id,
            deal_ref=deal_ref,
            executor_kind="vm",
            action_kind="create",
            idempotency_key=f"{allocation_id}:create",
            parameters=parameters,
        ))
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
        result = dict(job.result.value) if job.result is not None else {}

        try:
            credentials = await client.get_job_credentials(submit.job_id)
            auth = _credentials_auth_payload(credentials)
            if auth:
                result["authentication"] = auth
        except Exception as exc:
            logger.warning(
                "[PROVISIONING] Failed to fetch credentials for job %s: %s",
                submit.job_id,
                exc,
            )

    return result
