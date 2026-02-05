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
    start_playbook,
    wait_for_playbook,
)
from async_provisioning_service.services.queue import dequeue_job, enqueue_job


logger = logging.getLogger(__name__)

# Track running tasks to prevent unbounded growth
running_tasks: Set[asyncio.Task] = set()


def _update_job(
    db: Session,
    job: ProvisioningJob,
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
    logs: str | None = None,
    process_id: str | None = None,
) -> None:
    job.status = status
    job.result = result
    job.error = error
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
        ssh_pubkey=params["ssh_pubkey"],
        vm_host=params.get("vm_host", "vm1"),
        vm_target=params.get("vm_target", "tenant-vm"),
        vm_action=params.get("vm_action", "create"),
        vm_ram=params.get("vm_ram", 2048),
        vm_vcpus=params.get("vm_vcpus", 2),
        vm_disk_size=params.get("vm_disk_size", "25G"),
        vm_lease_end=params.get("vm_lease_end"),
        image_setup_type=params.get("image_setup_type", "scratch"),
        root_ssh_filename=params.get("root_ssh_filename"),
        root_ssh_password=params.get("root_ssh_password"),
    )


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

            # Success - store results
            logs = result.stdout + ("\n\nSTDERR:\n" + result.stderr if result.stderr else "")
            result_payload = {
                "ssh_port": result.ssh_port,
                "tenant_user": result.tenant_user,
                "vm_host_ip": result.vm_host_ip,
                "ssh_command": result.ssh_command,
            }
            _update_job(
                db,
                job,
                status=JobStatus.succeeded.value,
                result=result_payload,
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
