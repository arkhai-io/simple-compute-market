from __future__ import annotations

import asyncio
import copy
import logging
import os
import re
import signal
import uuid
from datetime import datetime, timedelta
from typing import Set

from sqlalchemy import or_, text
from sqlalchemy.orm import Session, sessionmaker

from config import Settings
from db.models import (
    AnsibleJob,
    Credential,
    CredentialRole,
    JobStatus,
)
from models.jobs import (
    CredentialListResponse,
    CredentialResponse,
    JobListResponse,
    ProvisionLogsResponse,
    ProvisionRequest,
    ProvisionResponse,
    ProvisionStatusResponse,
)
from services.provisioning_service import (
    PlaybookError,
    ProvisioningParams,
    ProvisioningService,
)


logger = logging.getLogger(__name__)


class AnsibleJobService:
    """Manages the full lifecycle of Ansible jobs.

    Responsibilities:
    - Accept job submissions from the HTTP layer and enqueue them.
    - Run the background job processing loop (replaces the former separate
      worker process and Redis queue).
    - Expose read/write operations used by the HTTP layer (list, status,
      credentials, logs, cancel).

    The in-process ``asyncio.Queue`` passed via the container replaces the
    Redis-backed queue from the previous two-process design.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        job_queue: asyncio.Queue,
        provisioning_service: ProvisioningService,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._queue = job_queue
        self._provisioning = provisioning_service

        self._running_tasks: Set[asyncio.Task] = set()
        self._semaphore: asyncio.Semaphore | None = None
        self._processing_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Processing loop health
    # ------------------------------------------------------------------

    def is_processing_loop_alive(self) -> bool:
        """Return True if the background processing task is running."""
        return (
            self._processing_task is not None
            and not self._processing_task.done()
        )

    # ------------------------------------------------------------------
    # HTTP-layer operations
    # ------------------------------------------------------------------

    async def submit(
        self, request: ProvisionRequest, agent_id: str | None
    ) -> ProvisionResponse:
        """Persist a new job and place it on the in-process queue."""
        job_id = str(uuid.uuid4())
        max_retries = (
            request.max_retries
            if request.max_retries is not None
            else self._settings.default_max_retries
        )

        with self._session_factory() as db:
            job = AnsibleJob(
                id=job_id,
                status=JobStatus.queued.value,
                params=request.model_dump(),
                agent_id=agent_id,
                buyer_agent_id=request.buyer_agent_id,
                retry_count=0,
                max_retries=max_retries,
                next_retry_at=None,
            )
            db.add(job)
            db.commit()

        # Enqueue after the commit so the worker always finds the row.
        await self._queue.put(job_id)
        return ProvisionResponse(job_id=job_id, status=JobStatus.queued.value)

    def list_jobs(
        self,
        agent_id: str | None,
        offset: int = 0,
        limit: int = 20,
        status_filter: str | None = None,
        sort: str = "created_at_desc",
    ) -> JobListResponse:
        sort_map = {
            "created_at_asc": AnsibleJob.created_at.asc(),
            "created_at_desc": AnsibleJob.created_at.desc(),
        }
        with self._session_factory() as db:
            query = db.query(AnsibleJob)
            if agent_id:
                query = query.filter(
                    or_(
                        AnsibleJob.agent_id == agent_id,
                        AnsibleJob.buyer_agent_id == agent_id,
                    )
                )
            if status_filter:
                query = query.filter(AnsibleJob.status == status_filter)
            total = query.count()
            order_fn = sort_map.get(sort, sort_map["created_at_desc"])
            jobs = query.order_by(order_fn).offset(offset).limit(limit).all()
            return JobListResponse(
                jobs=[self._to_status_response(j) for j in jobs],
                total=total,
                offset=offset,
                limit=limit,
            )

    def get_job(self, job_id: str, agent_id: str | None) -> ProvisionStatusResponse:
        """Return full job status. Raises ValueError for 403, LookupError for 404."""
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")

            if job.agent_id:
                is_seller = job.agent_id == agent_id
                is_buyer = job.buyer_agent_id and job.buyer_agent_id == agent_id
                if not is_seller and not is_buyer:
                    raise PermissionError(
                        f"Job {job_id} belongs to another agent"
                    )

            return self._to_status_response(job)

    def get_credentials(
        self, job_id: str, agent_id: str
    ) -> CredentialListResponse:
        """Return credentials for the requesting agent. Raises on auth failures."""
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")

            is_seller = job.agent_id and job.agent_id == agent_id
            is_buyer = job.buyer_agent_id and job.buyer_agent_id == agent_id
            if not is_seller and not is_buyer:
                raise PermissionError(
                    "Access denied: you are not the seller or buyer of this job"
                )

            creds = (
                db.query(Credential)
                .filter(
                    Credential.job_id == job_id,
                    Credential.granted_to == agent_id,
                )
                .all()
            )
            return CredentialListResponse(
                job_id=job_id,
                credentials=[
                    CredentialResponse(
                        role=c.role,
                        password=c.password,
                        ssh_commands=c.ssh_commands,
                        ssh_key_path_host=c.ssh_key_path_host,
                        key_type=c.key_type,
                    )
                    for c in creds
                ],
            )

    def get_logs(self, job_id: str, agent_id: str | None) -> ProvisionLogsResponse:
        """Return raw Ansible logs for a job."""
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")

            if job.agent_id and agent_id:
                is_seller = job.agent_id == agent_id
                is_buyer = job.buyer_agent_id and job.buyer_agent_id == agent_id
                if not is_seller and not is_buyer:
                    raise PermissionError(
                        f"Job {job_id} belongs to another agent"
                    )

            return ProvisionLogsResponse(
                job_id=job.id, status=job.status, logs=job.logs
            )

    def cancel_job(self, job_id: str, agent_id: str | None) -> dict:
        """Cancel a queued or running job. Sends SIGTERM if Ansible is running."""
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")

            if agent_id and job.agent_id and job.agent_id != agent_id:
                raise PermissionError("Cannot cancel another agent's job")

            if job.status not in (JobStatus.queued.value, JobStatus.running.value):
                return {
                    "job_id": job.id,
                    "status": job.status,
                    "message": f"Job cannot be cancelled (current status: {job.status})",
                }

            if job.status == JobStatus.running.value and job.process_id:
                try:
                    pid = int(job.process_id)
                    os.kill(pid, signal.SIGTERM)
                    logger.info(
                        "Sent SIGTERM to process %d for job %s", pid, job_id
                    )
                except ProcessLookupError:
                    logger.warning(
                        "Process %d for job %s not found (already terminated)",
                        int(job.process_id),
                        job_id,
                    )
                except (ValueError, Exception) as exc:
                    logger.error(
                        "Failed to terminate process for job %s: %s", job_id, exc
                    )

            job.status = JobStatus.cancelled.value
            job.error = "Job cancelled by user"
            db.add(job)
            db.commit()

        return {
            "job_id": job_id,
            "status": JobStatus.cancelled.value,
            "message": "Job cancelled successfully",
        }

    # ------------------------------------------------------------------
    # Background processing loop (replaces separate worker process)
    # ------------------------------------------------------------------

    async def start_processing_loop(self) -> None:
        """Dequeue and process jobs concurrently.

        This coroutine is intended to run as a long-lived ``asyncio.Task``
        started in the FastAPI lifespan.  It replaces the former separate
        worker process and Redis ``BRPOP`` loop.
        """
        self._processing_task = asyncio.current_task()
        self._semaphore = asyncio.Semaphore(self._settings.max_concurrent_jobs)

        logger.info(
            "Job processing loop started (max_concurrent_jobs=%d, max_retries=%d)",
            self._settings.max_concurrent_jobs,
            self._settings.default_max_retries,
        )

        while True:
            try:
                try:
                    job_id = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._cleanup_done_tasks()
                    continue

                task = asyncio.create_task(
                    self._process_with_semaphore(job_id),
                    name=f"job-{job_id[:8]}",
                )
                self._running_tasks.add(task)
                self._cleanup_done_tasks()

                if self._running_tasks:
                    logger.debug(
                        "Worker concurrency: %d active jobs",
                        len(self._running_tasks),
                    )

            except asyncio.CancelledError:
                logger.info("Job processing loop cancelled")
                break
            except Exception as exc:
                logger.exception("Error in job processing loop: %s", exc)
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Private processing helpers
    # ------------------------------------------------------------------

    def _cleanup_done_tasks(self) -> None:
        done = {t for t in self._running_tasks if t.done()}
        self._running_tasks.difference_update(done)

    async def _process_with_semaphore(self, job_id: str) -> None:
        assert self._semaphore is not None  # set before loop starts
        async with self._semaphore:
            await self._process_job(job_id)

    async def _process_job(self, job_id: str) -> None:
        """Execute a single provisioning job end-to-end."""
        db = self._session_factory()
        try:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                logger.warning("Job %s not found", job_id)
                return

            # Respect scheduled retry delay.
            if job.next_retry_at and datetime.utcnow() < job.next_retry_at:
                await asyncio.sleep(1)
                await self._queue.put(job_id)
                return

            logger.info(
                "Processing job %s (attempt %d/%d)",
                job_id,
                job.retry_count + 1,
                job.max_retries + 1,
            )

            self._update_job(db, job, status=JobStatus.running.value)
            params = self._build_params(job.params)
            run = self._provisioning.start_playbook(params)
            self._update_job(
                db,
                job,
                status=JobStatus.running.value,
                process_id=str(run.process_id),
            )
            logger.info("Job %s running with PID=%d", job_id, run.process_id)

            def log_callback(stdout: str, stderr: str) -> None:
                try:
                    callback_db = self._session_factory()
                    try:
                        with callback_db.begin():
                            callback_job = (
                                callback_db.query(AnsibleJob)
                                .filter(AnsibleJob.id == job_id)
                                .one_or_none()
                            )
                            if callback_job:
                                logs = stdout + (
                                    "\n\nSTDERR:\n" + stderr if stderr else ""
                                )
                                callback_job.logs = self._redact_logs(logs)
                    finally:
                        callback_db.close()
                except Exception as e:
                    logger.warning(
                        "Failed to update logs for job %s: %s", job_id, e
                    )

            try:
                result = await self._provisioning.wait_for_playbook(
                    run, params, log_callback=log_callback
                )
                logs = result.stdout + (
                    "\n\nSTDERR:\n" + result.stderr if result.stderr else ""
                )
                logs = self._redact_logs(logs)
                result_payload = self._build_result_payload(result)
                sanitized_payload = self._extract_and_store_credentials(
                    db, job, result_payload
                )
                self._update_job(
                    db,
                    job,
                    status=JobStatus.succeeded.value,
                    result=sanitized_payload,
                    error=None,
                    logs=logs,
                )
                logger.info("Job %s succeeded", job_id)

            except PlaybookError as exc:
                logs = exc.stdout + (
                    "\n\nSTDERR:\n" + exc.stderr if exc.stderr else ""
                )
                logs = self._redact_logs(logs)
                error_message = str(exc)

                should_retry = (
                    job.retry_count < job.max_retries
                    and self._should_retry_error(error_message)
                )

                if should_retry:
                    retry_delay = self._calculate_retry_delay(job.retry_count)
                    next_retry_at = datetime.utcnow() + timedelta(
                        seconds=retry_delay
                    )
                    job.retry_count += 1
                    job.next_retry_at = next_retry_at
                    job.status = JobStatus.queued.value
                    job.error = (
                        f"Attempt {job.retry_count} failed: {error_message}. "
                        f"Retrying at {next_retry_at}"
                    )
                    job.logs = logs
                    db.add(job)
                    db.commit()
                    await self._queue.put(job_id)
                    logger.warning(
                        "Job %s failed (attempt %d/%d), retrying in %ds: %s",
                        job_id,
                        job.retry_count,
                        job.max_retries + 1,
                        retry_delay,
                        error_message,
                    )
                else:
                    reason = (
                        "max retries exceeded"
                        if job.retry_count >= job.max_retries
                        else "non-retryable error"
                    )
                    self._update_job(
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
                job = (
                    db.query(AnsibleJob)
                    .filter(AnsibleJob.id == job_id)
                    .one_or_none()
                )
                if job:
                    self._update_job(
                        db,
                        job,
                        status=JobStatus.failed.value,
                        error=f"Internal error: {exc}",
                    )
            except Exception:
                pass
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Private utilities
    # ------------------------------------------------------------------

    _UNSET = object()

    def _update_job(
        self,
        db: Session,
        job: AnsibleJob,
        *,
        status: str,
        result: object = _UNSET,
        error: object = _UNSET,
        logs: object = _UNSET,
        process_id: str | None = None,
    ) -> None:
        job.status = status
        if result is not self._UNSET:
            job.result = result
        if error is not self._UNSET:
            job.error = error
        if logs is not self._UNSET:
            job.logs = logs
        if process_id is not None:
            job.process_id = process_id
        db.add(job)
        db.commit()

    def _calculate_retry_delay(self, retry_count: int) -> int:
        delay = self._settings.retry_backoff_initial_seconds * (
            self._settings.retry_backoff_multiplier ** retry_count
        )
        return min(int(delay), self._settings.retry_backoff_max_seconds)

    def _should_retry_error(self, error_message: str) -> bool:
        error_lower = error_message.lower()
        for pattern in self._settings.non_retryable_errors:
            if pattern.lower() in error_lower:
                return False
        return True

    def _build_params(self, params: dict) -> ProvisioningParams:
        return ProvisioningParams(
            vm_host=params.get("vm_host", self._settings.default_vm_host),
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
            frp_server_addr=params.get("frp_server_addr") or str(self._settings.frp_server_addr or ""),
            frp_domain=params.get("frp_domain") or str(self._settings.frp_domain or ""),
            frp_dashboard_password=params.get("frp_dashboard_password") or str(self._settings.frp_dashboard_password or ""),
            golden_image_name=params.get("golden_image_name"),
            gcs_bucket_url=params.get("gcs_bucket_url"),
            gcs_image_path=params.get("gcs_image_path"),
            vm_lease_end=params.get("vm_lease_end"),
        )

    def _redact_logs(self, logs: str) -> str:
        if not logs:
            return logs
        redacted = re.sub(
            r'("(?:password|ssh_key_path_host)":\s*)"[^"]*"',
            r'\1"[REDACTED]"',
            logs,
        )
        redacted = re.sub(
            r"(password:\s*)(?!\[REDACTED\]).+",
            r"\1[REDACTED]",
            redacted,
        )
        redacted = re.sub(r"-i\s+\S+\.ssh/\S+", "-i [REDACTED]", redacted)
        redacted = re.sub(r"sshpass\s+-p\s+\S+", "sshpass -p [REDACTED]", redacted)
        return redacted

    def _extract_and_store_credentials(
        self, db: Session, job: AnsibleJob, result_payload: dict
    ) -> dict:
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

        if job.agent_id:
            if root_data:
                _store_role(CredentialRole.root.value, root_data, job.agent_id)
            if tenant_data:
                _store_role(CredentialRole.tenant.value, tenant_data, job.agent_id)

        if job.buyer_agent_id and tenant_data:
            _store_role(CredentialRole.tenant.value, tenant_data, job.buyer_agent_id)

        sanitized.pop("authentication", None)
        if isinstance(sanitized.get("ansible_result"), dict):
            sanitized["ansible_result"].pop("authentication", None)

        return sanitized

    def _build_result_payload(self, result: ProvisioningResult) -> dict:
        ar = result.ansible_result or {}
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

        if ar.get("gpu"):
            payload["gpu"] = ar["gpu"]
        if ar.get("network"):
            payload["network"] = ar["network"]
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

    @staticmethod
    def _to_status_response(job: AnsibleJob) -> ProvisionStatusResponse:
        return ProvisionStatusResponse(
            job_id=job.id,
            status=job.status,
            params=job.params,
            result=job.result,
            error=job.error,
            retry_count=job.retry_count,
            max_retries=job.max_retries,
            next_retry_at=job.next_retry_at,
            agent_id=job.agent_id,
            buyer_agent_id=job.buyer_agent_id,
        )
