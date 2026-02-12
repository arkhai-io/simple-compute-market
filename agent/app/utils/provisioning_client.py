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
    params: dict[str, Any],
    timeout: int = 3600,
    poll_interval: int = 15,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """
    Submit a provisioning job to the async provisioning service and wait for completion.

    This function:
    1. Submits a POST /provision request with the provisioning parameters
    2. Receives a job_id
    3. Polls GET /provision/{job_id} until status is 'succeeded' or 'failed'
    4. Returns the result on success, raises exception on failure

    Args:
        provisioning_service_url: Base URL of the provisioning service (e.g., "http://localhost:8081")
        params: Provisioning parameters dict (vm_target, vm_action, vm_host, ssh_pubkey, etc.)
        timeout: Maximum time to wait for job completion in seconds (default: 3600 = 1 hour)
        poll_interval: Interval between status checks in seconds (default: 15)
        agent_id: Optional agent ID to include in X-Agent-ID header for authentication

    Returns:
        Job result dictionary containing SSH connection details, authentication,
        GPU, FRP, and full ansible_result.

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
                json=params,
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


async def schedule_vm_shutdown_async(
    provisioning_service_url: str,
    lease_end_utc: str,
    vm_host: str = "ww1",
    vm_target: str = "tenant-vm",
    timeout: int = 300,
    poll_interval: int = 5,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """
    Schedule VM shutdown via the async provisioning service.

    This function:
    1. Submits a POST /provision request with vm_action='lease_end' and vm_lease_end time
    2. Receives a job_id
    3. Polls GET /provision/{job_id} until status is 'succeeded' or 'failed'
    4. Returns the result on success, raises exception on failure

    Args:
        provisioning_service_url: Base URL of the provisioning service (e.g., "http://localhost:8081")
        lease_end_utc: UTC time string for VM shutdown (format: 'YYYY-MM-DD HH:MM')
        vm_host: The host where the VM is located (default: "vm1")
        vm_target: The name of the VM to schedule for shutdown (default: "tenant-vm")
        timeout: Max time to wait for completion (seconds, default: 300)
        poll_interval: How often to poll for status (seconds, default: 5)
        agent_id: Optional agent ID to include in X-Agent-ID header for authentication

    Returns:
        Result dictionary with status and details

    Raises:
        ProvisioningJobError: If the shutdown scheduling job fails
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
        # Step 1: Submit shutdown scheduling job
        logger.info("[SHUTDOWN] Scheduling VM shutdown for %s on %s at %s UTC", vm_target, vm_host, lease_end_utc)
        try:
            response = await client.post(
                f"{base_url}/provision",
                json={
                    "vm_host": vm_host,
                    "vm_target": vm_target,
                    "vm_action": "lease_end",
                    "vm_lease_end": lease_end_utc,
                },
                headers=headers,
            )
            response.raise_for_status()
            submit_data = response.json()
            job_id = submit_data["job_id"]
            logger.info("[SHUTDOWN] Job submitted: job_id=%s, status=%s", job_id, submit_data["status"])
        except httpx.HTTPStatusError as exc:
            logger.error("[SHUTDOWN] Failed to submit job: %s %s", exc.response.status_code, exc.response.text)
            raise ProvisioningError(f"Failed to submit shutdown scheduling job: {exc}") from exc
        except Exception as exc:
            logger.error("[SHUTDOWN] Unexpected error submitting job: %s", exc)
            raise ProvisioningError(f"Failed to submit shutdown scheduling job: {exc}") from exc

        # Step 2: Poll for completion
        start_time = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                logger.error("[SHUTDOWN] Job %s timed out after %d seconds", job_id, timeout)
                raise ProvisioningTimeoutError(f"Shutdown scheduling job {job_id} timed out after {timeout} seconds")

            try:
                response = await client.get(f"{base_url}/provision/{job_id}")
                response.raise_for_status()
                status_data = response.json()

                status = status_data["status"]
                logger.debug("[SHUTDOWN] Job %s status: %s (elapsed: %.1fs)", job_id, status, elapsed)

                if status == "succeeded":
                    result = status_data.get("result", {})
                    logger.info("[SHUTDOWN] Job %s succeeded: VM shutdown scheduled for %s", job_id, lease_end_utc)
                    return result

                elif status == "failed":
                    error = status_data.get("error", "Unknown error")
                    logger.error("[SHUTDOWN] Job %s failed: %s", job_id, error)

                    # Try to get logs for additional context
                    try:
                        logs_response = await client.get(f"{base_url}/provision/{job_id}/logs")
                        if logs_response.status_code == 200:
                            logs_data = logs_response.json()
                            logs = logs_data.get("logs")
                            if logs:
                                logger.error("[SHUTDOWN] Job %s logs:\n%s", job_id, logs)
                    except Exception as logs_exc:
                        logger.warning("[SHUTDOWN] Failed to fetch logs for job %s: %s", job_id, logs_exc)

                    raise ProvisioningJobError(f"Shutdown scheduling job {job_id} failed: {error}")

                elif status in ("queued", "running"):
                    # Continue polling
                    await asyncio.sleep(poll_interval)

                else:
                    logger.warning("[SHUTDOWN] Job %s has unexpected status: %s", job_id, status)
                    await asyncio.sleep(poll_interval)

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.error("[SHUTDOWN] Job %s not found", job_id)
                    raise ProvisioningError(f"Job {job_id} not found") from exc
                else:
                    logger.error("[SHUTDOWN] Failed to get status for job %s: %s %s",
                                job_id, exc.response.status_code, exc.response.text)
                    raise ProvisioningError(f"Failed to get job status: {exc}") from exc
            except ProvisioningError:
                # Re-raise our own exceptions
                raise
            except Exception as exc:
                logger.error("[SHUTDOWN] Unexpected error polling job %s: %s", job_id, exc)
                raise ProvisioningError(f"Failed to poll job status: {exc}") from exc


async def get_vm_available_resources(
    provisioning_service_url: str,
    vm_host: str = "ww1",
    timeout: int = 120,
    poll_interval: int = 5,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Query available resources on a KVM host.

    Submits a 'check' action via the provisioning service and returns
    host capacity data (total/allocated/available CPU, RAM, GPU).

    Returns:
        Dict with keys: vm_host, status, total, allocated,
        available, gpu_details, utilization, and full ansible_result.
    """
    result = await provision_machine_async(
        provisioning_service_url=provisioning_service_url,
        params={"vm_host": vm_host, "vm_action": "check"},
        timeout=timeout,
        poll_interval=poll_interval,
        agent_id=agent_id,
    )
    # The check action returns capacity data in ansible_result
    ansible_result = result.get("ansible_result", {})
    return {
        "vm_host": vm_host,
        "status": ansible_result.get("status", "unknown"),
        "total": ansible_result.get("total", {}),
        "allocated": ansible_result.get("allocated", {}),
        "available": ansible_result.get("available", {}),
        "gpu_details": ansible_result.get("gpu_details", []),
        "utilization": ansible_result.get("utilization", {}),
        "ansible_result": ansible_result,
    }


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
    ssh_port = result.get("ssh_port")
    tenant_user = result.get("tenant_user")
    vm_host_ip = result.get("vm_host_ip")

    if ssh_port and ssh_port.isdigit() and tenant_user and vm_host_ip:
        return f"ssh {tenant_user}@{vm_host_ip} -p {ssh_port}"

    # No valid connection info found
    raise ProvisioningError(
        f"Could not format connection info: missing ssh_command and ssh_port/tenant_user/vm_host_ip in result"
    )
