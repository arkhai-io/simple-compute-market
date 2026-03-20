import asyncio
import copy
import logging
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Set

from sqlalchemy.orm import Session

from async_provisioning_service.config import settings
from async_provisioning_service.db.database import SessionLocal, init_db
from async_provisioning_service.db.models import Credential, CredentialRole, JobStatus, ProvisioningJob
from async_provisioning_service.services.provisioning import (
    PlaybookError,
    ProvisioningParams,
    ProvisioningResult,
    start_playbook,
    wait_for_playbook,
)
from async_provisioning_service.services.queue import dequeue_job, enqueue_job


logger = logging.getLogger(__name__)

running_tasks: Set[asyncio.Task] = set()


_UNSET = object()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

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
    """Return False if the error matches a non-retryable pattern."""
    error_lower = error_message.lower()
    for non_retryable in settings.non_retryable_errors:
        if non_retryable.lower() in error_lower:
            return False
    return True


def _build_params(params: dict) -> ProvisioningParams:
    """Convert a job params dict to a ProvisioningParams dataclass."""
    return ProvisioningParams(
        vm_host=params.get("vm_host", settings.default_vm_host),
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


def _redact_logs(logs: str) -> str:
    """Scrub sensitive credential data from log output."""
    if not logs:
        return logs
    # JSON-style: "password": "value" or "ssh_key_path_host": "value"
    redacted = re.sub(
        r'("(?:password|ssh_key_path_host)":\s*)"[^"]*"',
        r'\1"[REDACTED]"',
        logs,
    )
    # YAML-style: password: value (not already quoted/redacted)
    redacted = re.sub(
        r'(password:\s*)(?!\[REDACTED\]).+',
        r'\1[REDACTED]',
        redacted,
    )
    # SSH key paths in commands: -i /path/to/key
    redacted = re.sub(
        r'-i\s+\S+\.ssh/\S+',
        '-i [REDACTED]',
        redacted,
    )
    # sshpass -p arguments
    redacted = re.sub(
        r'sshpass\s+-p\s+\S+',
        'sshpass -p [REDACTED]',
        redacted,
    )
    return redacted


def _extract_and_store_credentials(
    db: Session,
    job: ProvisioningJob,
    result_payload: dict,
) -> dict:
    """Extract credentials from result, store as Credential rows, return sanitized payload.

    Does NOT commit — the caller's _update_job() commits atomically.
    """
    auth = result_payload.get("authentication")
    if not auth:
        return result_payload

    sanitized = copy.deepcopy(result_payload)

    def _store_role(role_name: str, role_data: dict, granted_to: str) -> None:
        if not role_data or not granted_to:
            return
        cred = Credential(
            job_id=job.id,
            role=role_name,
            granted_to=granted_to,
            password=role_data.get("password"),
            ssh_commands=role_data.get("ssh_commands"),
            ssh_key_path_host=role_data.get("ssh_key_path_host"),
            key_type=role_data.get("key_type"),
        )
        db.add(cred)

    tenant_data = auth.get("tenant", {})
    root_data = auth.get("root", {})

    # Seller (job.agent_id) gets root + tenant
    if job.agent_id:
        if root_data:
            _store_role(CredentialRole.root.value, root_data, job.agent_id)
        if tenant_data:
            _store_role(CredentialRole.tenant.value, tenant_data, job.agent_id)

    # Buyer gets tenant only
    if job.buyer_agent_id:
        if tenant_data:
            _store_role(CredentialRole.tenant.value, tenant_data, job.buyer_agent_id)

    # Strip authentication from the sanitized payload
    sanitized.pop("authentication", None)

    # Also strip from nested ansible_result if present
    if isinstance(sanitized.get("ansible_result"), dict):
        sanitized["ansible_result"].pop("authentication", None)

    return sanitized


def _build_result_payload(result: ProvisioningResult) -> dict:
    """Build a structured result payload, preferring ansible_result over regex-extracted fields."""
    ar = result.ansible_result or {}

    # Regex-extracted fields as fallback when ansible_result is missing
    payload: dict = {
        "ssh_port": result.ssh_port,
        "tenant_user": result.tenant_user,
        "vm_host_ip": result.vm_host_ip,
        "ssh_command": result.ssh_command,
    }

    if not ar:
        payload["ansible_result"] = None
        return payload

    payload["status"] = ar.get("status")
    payload["action"] = ar.get("action")
    payload["vm_name"] = ar.get("vm_name")
    payload["host"] = ar.get("host")
    payload["timestamp"] = ar.get("timestamp")

    if ar.get("tenant_user"):
        payload["tenant_user"] = ar["tenant_user"]

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
        tenant_cmds = tenant_auth.get("ssh_commands", {})
        if tenant_cmds.get("external"):
            payload["ssh_command"] = tenant_cmds["external"]

    frp = ar.get("frp")
    if frp:
        payload["frp"] = frp
        if frp.get("remote_port"):
            payload["ssh_port"] = frp["remote_port"]

    gpu = ar.get("gpu")
    if gpu:
        payload["gpu"] = gpu

    network = ar.get("network")
    if network:
        payload["network"] = network

    if ar.get("vm_ip_internal"):
        payload["vm_ip_internal"] = ar["vm_ip_internal"]

    if ar.get("vm_state"):
        payload["vm_state"] = ar["vm_state"]

    if ar.get("result_message"):
        payload["result_message"] = ar["result_message"]
    if ar.get("note"):
        payload["note"] = ar["note"]
    if ar.get("operation_initiated"):
        payload["operation_initiated"] = ar["operation_initiated"]

    if ar.get("vms"):
        payload["vms"] = ar["vms"]
        payload["vm_count"] = ar.get("vm_count")

    if ar.get("resources"):
        payload["resources"] = ar["resources"]
    elif ar.get("cpu_usage_percent") is not None or ar.get("memory_used_mb") is not None:
        # Monitor output has resource fields at root level instead of nested
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

    payload["ansible_result"] = ar

    return payload


def _should_cleanup_stale_vm(params: ProvisioningParams, logs: str) -> bool:
    if params.vm_action != "create" or not params.vm_target:
        return False
    stale_vm_pattern = rf"VM '{re.escape(params.vm_target)}' already exists"
    return re.search(stale_vm_pattern, logs) is not None


async def _cleanup_stale_vm_before_retry(params: ProvisioningParams, logs: str) -> None:
    if not _should_cleanup_stale_vm(params, logs):
        return

    destroy_params = replace(params, vm_action="destroy")
    cleanup_params = replace(params, vm_action="undefine")
    logger.warning(
        "Retrying create for %s after stopping and cleaning up stale VM target %s",
        params.vm_host,
        params.vm_target,
    )

    try:
        destroy_running = await start_playbook(destroy_params)
        await wait_for_playbook(destroy_running)
    except PlaybookError as exc:
        logger.warning(
            "Destroy step for stale VM target %s on %s did not complete cleanly: %s",
            params.vm_target,
            params.vm_host,
            exc,
        )

    cleanup_running = await start_playbook(cleanup_params)
    await wait_for_playbook(cleanup_running)


async def _process_job(job_id: str) -> None:
    """Process a single provisioning job: start playbook, track PID, handle retries."""
    db = SessionLocal()
    try:
        job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
        if not job:
            logger.warning("Job %s not found", job_id)
            return

        next_retry_at = _normalize_utc_datetime(job.next_retry_at)
        if next_retry_at and _utc_now() < next_retry_at:
            await asyncio.sleep(1)
            await enqueue_job(job_id)
            return

        logger.info("Processing job %s (attempt %d/%d)", job_id, job.retry_count + 1, job.max_retries + 1)

        _update_job(db, job, status=JobStatus.running.value)

        params = _build_params(job.params)
        if job.retry_count > 0:
            try:
                await _cleanup_stale_vm_before_retry(params, job.logs or "")
            except PlaybookError as cleanup_exc:
                logger.warning(
                    "Pre-attempt cleanup of stale VM target %s failed: %s",
                    params.vm_target,
                    cleanup_exc,
                )

        running = await start_playbook(params)

        # Store PID immediately so the job can be cancelled while running
        _update_job(db, job, status=JobStatus.running.value, process_id=str(running.process_id))
        logger.info("Job %s running with PID=%d", job_id, running.process_id)

        def log_callback(stdout: str, stderr: str):
            try:
                # Needs its own session — called from a different thread.
                # Use begin() to ensure an active transaction (SQLite + StaticPool
                # shares one connection, so the implicit transaction may already
                # have been consumed by the main thread's session).
                callback_db = SessionLocal()
                try:
                    with callback_db.begin():
                        callback_job = callback_db.query(ProvisioningJob).filter(
                            ProvisioningJob.id == job_id
                        ).one_or_none()
                        if callback_job:
                            logs = stdout + ("\n\nSTDERR:\n" + stderr if stderr else "")
                            callback_job.logs = _redact_logs(logs)
                            logger.debug("Updated logs for job %s (%d bytes)", job_id, len(logs))
                finally:
                    callback_db.close()
            except Exception as e:
                logger.warning("Failed to update logs for job %s: %s", job_id, e)

        try:
            result = await wait_for_playbook(running, log_callback=log_callback)

            logs = result.stdout + ("\n\nSTDERR:\n" + result.stderr if result.stderr else "")
            logs = _redact_logs(logs)
            result_payload = _build_result_payload(result)
            sanitized_payload = _extract_and_store_credentials(db, job, result_payload)
            _update_job(
                db,
                job,
                status=JobStatus.succeeded.value,
                result=sanitized_payload,
                error=None,
                logs=logs,
            )
            logger.info("Job %s succeeded", job_id)

        except PlaybookError as exc:
            logs = exc.stdout + ("\n\nSTDERR:\n" + exc.stderr if exc.stderr else "")
            logs = _redact_logs(logs)
            error_message = str(exc)

            should_retry = (
                job.retry_count < job.max_retries
                and _should_retry_error(error_message)
            )

            if should_retry:
                try:
                    await _cleanup_stale_vm_before_retry(params, logs)
                except PlaybookError as cleanup_exc:
                    logger.warning(
                        "Cleanup of stale VM target %s before retry failed: %s",
                        params.vm_target,
                        cleanup_exc,
                    )
                retry_delay = _calculate_retry_delay(job.retry_count)
                next_retry_at = _utc_now() + timedelta(seconds=retry_delay)

                job.retry_count += 1
                job.next_retry_at = next_retry_at
                job.status = JobStatus.queued.value
                job.error = f"Attempt {job.retry_count} failed: {error_message}. Retrying at {next_retry_at}"
                job.logs = logs
                db.add(job)
                db.commit()

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
    """Main job processing loop with concurrent execution via semaphore."""
    init_db()
    logger.info(
        "Provisioning worker started (max_concurrent_jobs=%d, max_retries=%d)",
        settings.max_concurrent_jobs,
        settings.default_max_retries,
    )

    semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)

    async def _process_with_semaphore(job_id: str) -> None:
        async with semaphore:
            await _process_job(job_id)

    while True:
        try:
            job_id = await dequeue_job(timeout_seconds=5)

            if not job_id:
                done_tasks = {task for task in running_tasks if task.done()}
                running_tasks.difference_update(done_tasks)
                await asyncio.sleep(0.1)
                continue

            task = asyncio.create_task(_process_with_semaphore(job_id))
            running_tasks.add(task)

            done_tasks = {task for task in running_tasks if task.done()}
            running_tasks.difference_update(done_tasks)

            if len(running_tasks) > 0:
                logger.debug("Worker concurrency: %d active jobs", len(running_tasks))

        except Exception as exc:
            logger.exception("Error in worker loop: %s", exc)
            await asyncio.sleep(1)
