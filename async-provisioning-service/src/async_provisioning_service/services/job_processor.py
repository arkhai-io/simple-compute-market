import asyncio
import logging
from datetime import datetime, timedelta
from typing import Set

from sqlalchemy.orm import Session

from async_provisioning_service.config import settings
from async_provisioning_service.db.database import SessionLocal, init_db
from async_provisioning_service.db.models import JobStatus, ProvisioningJob
from async_provisioning_service.services.provisioning import (
    PlaybookError,
    ProvisioningParams,
    ProvisioningResult,
    start_playbook,
    wait_for_playbook,
)
from async_provisioning_service.services.queue import dequeue_job, enqueue_job


logger = logging.getLogger(__name__)

# Track running tasks to prevent unbounded growth
running_tasks: Set[asyncio.Task] = set()


_UNSET = object()  # Sentinel to distinguish "not passed" from None


def _update_job(
    db: Session,
    job: ProvisioningJob,
    *,
    status: str,
    result: object = _UNSET,
    error: object = _UNSET,
    logs: object = _UNSET,
    process_id: str | None = None,
) -> None:
    job.status = status
    if result is not _UNSET:
        job.result = result
    if error is not _UNSET:
        job.error = error
    if logs is not _UNSET:
        job.logs = logs
    if process_id is not None:
        job.process_id = process_id
    db.add(job)
    db.commit()


def _calculate_retry_delay(retry_count: int) -> int:
    """Calculate exponential backoff delay for retry."""
    delay = settings.retry_backoff_initial_seconds * (settings.retry_backoff_multiplier ** retry_count)
    return min(int(delay), settings.retry_backoff_max_seconds)


def _should_retry_error(error_message: str) -> bool:
    """Check if error is retryable (circuit breaker)."""
    error_lower = error_message.lower()
    for non_retryable in settings.non_retryable_errors:
        if non_retryable.lower() in error_lower:
            return False
    return True


def _build_params(params: dict) -> ProvisioningParams:
    return ProvisioningParams(
        vm_host=params.get("vm_host", "ww1"),
        vm_target=params.get("vm_target"),
        vm_action=params.get("vm_action", "create"),
        image_setup_type=params.get("image_setup_type", "scratch"),
        vm_ram=params.get("vm_ram"),
        vm_vcpus=params.get("vm_vcpus"),
        vm_disk_size=params.get("vm_disk_size"),
        vm_os_variant=params.get("vm_os_variant"),
        ssh_pubkey=params.get("ssh_pubkey"),
        gpu_provisioned=params.get("gpu_provisioned"),
        vm_gpu_count=params.get("vm_gpu_count"),
        vm_gpu_device=params.get("vm_gpu_device"),
        vm_gpu_devices=params.get("vm_gpu_devices"),
        vm_gpu_partition_size=params.get("vm_gpu_partition_size"),
        frp_server_addr=params.get("frp_server_addr") or settings.frp_server_addr,
        frp_domain=params.get("frp_domain") or settings.frp_domain,
        frp_dashboard_password=params.get("frp_dashboard_password") or settings.frp_dashboard_password,
        golden_image_name=params.get("golden_image_name"),
        gcs_bucket_url=params.get("gcs_bucket_url"),
        gcs_image_path=params.get("gcs_image_path"),
        vm_lease_end=params.get("vm_lease_end"),
    )


def _build_result_payload(result: ProvisioningResult) -> dict:
    """Build a structured result payload from the provisioning result.

    Uses the parsed ansible_result JSON as the primary source of truth,
    falling back to regex-extracted fields for backward compatibility.
    """
    ar = result.ansible_result or {}

    # Start with backward-compatible fields (regex-extracted)
    payload: dict = {
        "ssh_port": result.ssh_port,
        "tenant_user": result.tenant_user,
        "vm_host_ip": result.vm_host_ip,
        "ssh_command": result.ssh_command,
    }

    if not ar:
        payload["ansible_result"] = None
        return payload

    # Enrich from ansible_result — override regex values with structured data
    payload["status"] = ar.get("status")
    payload["action"] = ar.get("action")
    payload["vm_name"] = ar.get("vm_name")
    payload["host"] = ar.get("host")
    payload["timestamp"] = ar.get("timestamp")

    # Tenant user from structured data
    if ar.get("tenant_user"):
        payload["tenant_user"] = ar["tenant_user"]

    # Authentication (create action — passwords, SSH commands)
    auth = ar.get("authentication")
    if auth:
        tenant_auth = auth.get("tenant", {})
        root_auth = auth.get("root", {})
        payload["authentication"] = {
            "tenant": {
                "password": tenant_auth.get("password"),
                "key_type": tenant_auth.get("key_type"),
                "ssh_commands": tenant_auth.get("ssh_commands"),
            },
            "root": {
                "password": root_auth.get("password"),
                "ssh_commands": root_auth.get("ssh_commands"),
                "ssh_key_path_host": root_auth.get("ssh_key_path_host"),
            },
        }
        # Prefer external SSH command from structured data
        tenant_cmds = tenant_auth.get("ssh_commands", {})
        if tenant_cmds.get("external"):
            payload["ssh_command"] = tenant_cmds["external"]

    # FRP tunneling details
    frp = ar.get("frp")
    if frp:
        payload["frp"] = frp
        # Override ssh_port with FRP remote port
        if frp.get("remote_port"):
            payload["ssh_port"] = frp["remote_port"]

    # GPU details
    gpu = ar.get("gpu")
    if gpu:
        payload["gpu"] = gpu

    # Network info
    network = ar.get("network")
    if network:
        payload["network"] = network

    # VM internal IP
    if ar.get("vm_ip_internal"):
        payload["vm_ip_internal"] = ar["vm_ip_internal"]

    # VM state
    if ar.get("vm_state"):
        payload["vm_state"] = ar["vm_state"]

    # For non-create actions, include action-specific fields
    if ar.get("result_message"):
        payload["result_message"] = ar["result_message"]
    if ar.get("note"):
        payload["note"] = ar["note"]
    if ar.get("operation_initiated"):
        payload["operation_initiated"] = ar["operation_initiated"]

    # List action — VM inventory
    if ar.get("vms"):
        payload["vms"] = ar["vms"]
        payload["vm_count"] = ar.get("vm_count")

    # Monitor action — resource data (fields are at root level of ansible_result)
    if ar.get("resources"):
        payload["resources"] = ar["resources"]
    elif ar.get("cpu_usage_percent") is not None or ar.get("memory_used_mb") is not None:
        # Monitor output has resource fields at root — collect them
        payload["resources"] = {
            "cpu": {
                "usage_percent": ar.get("cpu_usage_percent"),
                "vcpus_provisioned": ar.get("cpu_vcpus_provisioned"),
            },
            "memory": {
                "used_mb": ar.get("memory_used_mb"),
                "available_mb": ar.get("memory_available_mb"),
                "usage_percent": ar.get("memory_usage_percent"),
            },
            "storage": {
                "allocation_gb": ar.get("host_storage_allocation_gb"),
                "capacity_gb": ar.get("host_storage_capacity_gb"),
                "usage_percent": ar.get("host_storage_usage_percent"),
                "guest_total": ar.get("guest_storage_total"),
                "guest_used": ar.get("guest_storage_used"),
                "guest_available": ar.get("guest_storage_available"),
            },
            "network_interfaces": ar.get("network_interfaces"),
            "error": ar.get("error") or None,
        }

    # Full ansible_result preserved for any fields we didn't extract
    payload["ansible_result"] = ar

    return payload


async def _process_job(job_id: str) -> None:
    """
    Process a single provisioning job asynchronously.

    This function handles the complete job lifecycle:
    1. Start ansible playbook
    2. Store process_id immediately (enables cancellation)
    3. Wait for completion
    4. Handle success/failure/retry
    """
    db = SessionLocal()
    try:
        # Fetch job
        job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
        if not job:
            logger.warning("Job %s not found", job_id)
            return

        # Check if job should be retried (delayed retry)
        if job.next_retry_at and datetime.utcnow() < job.next_retry_at:
            # Not time to retry yet, re-enqueue for later
            await asyncio.sleep(1)  # Brief delay
            await enqueue_job(job_id)
            return

        logger.info("Processing job %s (attempt %d/%d)", job_id, job.retry_count + 1, job.max_retries + 1)

        # Update status to running
        _update_job(db, job, status=JobStatus.running.value)

        # Build parameters
        params = _build_params(job.params)

        # START PLAYBOOK (non-blocking)
        running = await start_playbook(params)

        # STORE PROCESS ID IMMEDIATELY (critical for cancellation)
        _update_job(db, job, status=JobStatus.running.value, process_id=str(running.process_id))
        logger.info("Job %s running with PID=%d", job_id, running.process_id)

        # Create log callback to update database in real-time
        def log_callback(stdout: str, stderr: str):
            """Update job logs in database as ansible output streams in."""
            try:
                # Create new session for this callback
                callback_db = SessionLocal()
                try:
                    callback_job = callback_db.query(ProvisioningJob).filter(
                        ProvisioningJob.id == job_id
                    ).one_or_none()
                    if callback_job:
                        logs = stdout + ("\n\nSTDERR:\n" + stderr if stderr else "")
                        callback_job.logs = logs
                        callback_db.commit()
                        logger.debug("Updated logs for job %s (%d bytes)", job_id, len(logs))
                finally:
                    callback_db.close()
            except Exception as e:
                logger.warning("Failed to update logs for job %s: %s", job_id, e)

        # WAIT FOR COMPLETION (blocking, but in dedicated task with streaming logs)
        try:
            result = await wait_for_playbook(running, log_callback=log_callback)

            # Success - store results and clear any previous error
            logs = result.stdout + ("\n\nSTDERR:\n" + result.stderr if result.stderr else "")
            result_payload = _build_result_payload(result)
            _update_job(
                db,
                job,
                status=JobStatus.succeeded.value,
                result=result_payload,
                error=None,
                logs=logs,
            )
            logger.info("Job %s succeeded", job_id)

        except PlaybookError as exc:
            # Failure - decide whether to retry
            logs = exc.stdout + ("\n\nSTDERR:\n" + exc.stderr if exc.stderr else "")
            error_message = str(exc)

            # Check if we should retry
            should_retry = (
                job.retry_count < job.max_retries
                and _should_retry_error(error_message)
            )

            if should_retry:
                # Calculate retry delay with exponential backoff
                retry_delay = _calculate_retry_delay(job.retry_count)
                next_retry_at = datetime.utcnow() + timedelta(seconds=retry_delay)

                # Update job for retry
                job.retry_count += 1
                job.next_retry_at = next_retry_at
                job.status = JobStatus.queued.value  # Back to queued for retry
                job.error = f"Attempt {job.retry_count} failed: {error_message}. Retrying at {next_retry_at}"
                job.logs = logs
                db.add(job)
                db.commit()

                # Re-enqueue for retry
                await enqueue_job(job_id)
                logger.warning(
                    "Job %s failed (attempt %d/%d), retrying in %ds: %s",
                    job_id,
                    job.retry_count,
                    job.max_retries + 1,
                    retry_delay,
                    error_message,
                )
            else:
                # No retry - mark as permanently failed
                reason = "max retries exceeded" if job.retry_count >= job.max_retries else "non-retryable error"
                _update_job(
                    db,
                    job,
                    status=JobStatus.failed.value,
                    error=f"Job failed ({reason}): {error_message}",
                    logs=logs,
                )
                logger.error("Job %s failed permanently: %s", job_id, error_message)

    except Exception as exc:
        # Unexpected error - log and mark failed
        logger.exception("Unexpected error processing job %s: %s", job_id, exc)
        try:
            job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
            if job:
                _update_job(
                    db,
                    job,
                    status=JobStatus.failed.value,
                    error=f"Internal error: {exc}",
                )
        except Exception:
            pass
    finally:
        db.close()


async def process_jobs() -> None:
    """
    Main job processing loop with concurrent execution.

    Changes from previous implementation:
    - Processes multiple jobs concurrently (up to max_concurrent_jobs)
    - Uses asyncio.Semaphore to limit concurrency
    - Each job runs in a separate task
    - Tasks are tracked and cleaned up properly
    """
    init_db()
    logger.info(
        "Provisioning worker started (max_concurrent_jobs=%d, max_retries=%d)",
        settings.max_concurrent_jobs,
        settings.default_max_retries,
    )

    # Semaphore to limit concurrent jobs
    semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)

    async def _process_with_semaphore(job_id: str) -> None:
        """Wrapper to enforce concurrency limit."""
        async with semaphore:
            await _process_job(job_id)

    while True:
        try:
            # Dequeue next job (blocks for up to 5 seconds)
            job_id = await dequeue_job(timeout_seconds=5)

            if not job_id:
                # No jobs available - clean up completed tasks
                done_tasks = {task for task in running_tasks if task.done()}
                running_tasks.difference_update(done_tasks)
                await asyncio.sleep(0.1)  # Brief yield
                continue

            # Create task for this job
            task = asyncio.create_task(_process_with_semaphore(job_id))
            running_tasks.add(task)

            # Clean up completed tasks
            done_tasks = {task for task in running_tasks if task.done()}
            running_tasks.difference_update(done_tasks)

            # Log current concurrency
            if len(running_tasks) > 0:
                logger.debug("Worker concurrency: %d active jobs", len(running_tasks))

        except Exception as exc:
            logger.exception("Error in worker loop: %s", exc)
            await asyncio.sleep(1)  # Brief pause on error
