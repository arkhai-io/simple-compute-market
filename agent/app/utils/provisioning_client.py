"""
HTTP client for async provisioning service.

This module provides an HTTP client for submitting VM provisioning jobs
to the async provisioning service and polling for completion.
"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ProvisioningError(Exception):
    """Base exception for provisioning errors."""
    pass


class ProvisioningJobError(ProvisioningError):
    """Exception raised when a provisioning job fails."""
    pass


class ProvisioningTimeoutError(ProvisioningError):
    """Exception raised when provisioning job times out."""
    pass


async def provision_machine_async(
    provisioning_service_url: str,
    ssh_public_key: str,
    timeout: int = 3600,
    poll_interval: int = 15,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """
    Submit a provisioning job to the async provisioning service and wait for completion.

    This function:
    1. Submits a POST /provision request with the SSH public key
    2. Receives a job_id
    3. Polls GET /provision/{job_id} until status is 'succeeded' or 'failed'
    4. Returns the result on success, raises exception on failure

    Args:
        provisioning_service_url: Base URL of the provisioning service (e.g., "http://localhost:8081")
        ssh_public_key: SSH public key to authorize on the VM
        timeout: Maximum time to wait for job completion in seconds (default: 3600 = 1 hour)
        poll_interval: Interval between status checks in seconds (default: 15)
        agent_id: Optional agent ID to include in X-Agent-ID header for authentication

    Returns:
        Job result dictionary containing SSH connection details:
        {
            "ssh_port": int,
            "tenant_user": str,
            "vm_host_ip": str,
            "ssh_command": str
        }

    Raises:
        ProvisioningJobError: If the provisioning job fails
        ProvisioningTimeoutError: If the job doesn't complete within timeout
        ProvisioningError: For other errors (network, API errors, etc.)
    """
    # Normalize URL (remove trailing slash)
    base_url = provisioning_service_url.rstrip("/")

    # Build headers with optional agent ID for authentication
    headers = {}
    if agent_id:
        headers["X-Agent-ID"] = agent_id

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Submit provisioning job
        logger.info("[PROVISIONING] Submitting provisioning job to %s", base_url)
        try:
            response = await client.post(
                f"{base_url}/provision",
                json={"ssh_pubkey": ssh_public_key},
                headers=headers,
            )
            response.raise_for_status()
            submit_data = response.json()
            job_id = submit_data["job_id"]
            logger.info("[PROVISIONING] Job submitted: job_id=%s, status=%s", job_id, submit_data["status"])
        except httpx.HTTPStatusError as exc:
            logger.error("[PROVISIONING] Failed to submit job: %s %s", exc.response.status_code, exc.response.text)
            raise ProvisioningError(f"Failed to submit provisioning job: {exc}") from exc
        except Exception as exc:
            logger.error("[PROVISIONING] Unexpected error submitting job: %s", exc)
            raise ProvisioningError(f"Failed to submit provisioning job: {exc}") from exc

        # Step 2: Poll for completion
        start_time = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                logger.error("[PROVISIONING] Job %s timed out after %d seconds", job_id, timeout)
                raise ProvisioningTimeoutError(f"Provisioning job {job_id} timed out after {timeout} seconds")

            try:
                response = await client.get(f"{base_url}/provision/{job_id}")
                response.raise_for_status()
                status_data = response.json()

                status = status_data["status"]
                logger.debug("[PROVISIONING] Job %s status: %s (elapsed: %.1fs)", job_id, status, elapsed)

                if status == "succeeded":
                    result = status_data.get("result")
                    if not result:
                        raise ProvisioningError(f"Job {job_id} succeeded but no result returned")
                    logger.info("[PROVISIONING] Job %s succeeded: %s", job_id, result)
                    return result

                elif status == "failed":
                    error = status_data.get("error", "Unknown error")
                    logger.error("[PROVISIONING] Job %s failed: %s", job_id, error)

                    # Try to get logs for additional context
                    try:
                        logs_response = await client.get(f"{base_url}/provision/{job_id}/logs")
                        if logs_response.status_code == 200:
                            logs_data = logs_response.json()
                            logs = logs_data.get("logs")
                            if logs:
                                logger.error("[PROVISIONING] Job %s logs:\n%s", job_id, logs)
                    except Exception as logs_exc:
                        logger.warning("[PROVISIONING] Failed to fetch logs for job %s: %s", job_id, logs_exc)

                    raise ProvisioningJobError(f"Provisioning job {job_id} failed: {error}")

                elif status in ("queued", "running"):
                    # Continue polling
                    await asyncio.sleep(poll_interval)

                else:
                    logger.warning("[PROVISIONING] Job %s has unexpected status: %s", job_id, status)
                    await asyncio.sleep(poll_interval)

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.error("[PROVISIONING] Job %s not found", job_id)
                    raise ProvisioningError(f"Job {job_id} not found") from exc
                else:
                    logger.error("[PROVISIONING] Failed to get status for job %s: %s %s",
                                job_id, exc.response.status_code, exc.response.text)
                    raise ProvisioningError(f"Failed to get job status: {exc}") from exc
            except ProvisioningError:
                # Re-raise our own exceptions
                raise
            except Exception as exc:
                logger.error("[PROVISIONING] Unexpected error polling job %s: %s", job_id, exc)
                raise ProvisioningError(f"Failed to poll job status: {exc}") from exc


def format_connection_info(result: dict[str, Any]) -> str:
    """
    Format provisioning result into a connection info string.

    Args:
        result: Provisioning result dictionary from the service

    Returns:
        Formatted connection info string (e.g., "ssh tenant@host -p 2222")
    """
    ssh_command = result.get("ssh_command")
    if ssh_command:
        return ssh_command

    # Fallback: construct from individual fields
    # Handle both "ssh_port" and "external_port" for backward compatibility
    ssh_port = result.get("ssh_port") or result.get("external_port")
    tenant_user = result.get("tenant_user")
    vm_host_ip = result.get("vm_host_ip")

    if ssh_port and tenant_user and vm_host_ip:
        return f"ssh {tenant_user}@{vm_host_ip} -p {ssh_port}"

    # Last resort: return raw result as string
    logger.warning("[PROVISIONING] Could not format connection info, returning raw result")
    return str(result)
