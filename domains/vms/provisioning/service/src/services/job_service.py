"""Ansible job lifecycle management.

``AnsibleJobService`` owns:
  - Job submission (HTTP layer -> DB -> queue).
  - Job read operations (list, get, credentials, logs).
  - Job cancellation.
  - The ``_process_job`` coroutine: DB state transitions, playbook dispatch,
    retry logic, log streaming, and credential storage.

It does **not** own queue mechanics (concurrency, task dispatch).  That belongs
to ``AsyncJobQueue``, which is injected and started separately in the FastAPI
lifespan.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import logging
import os
import re
import signal
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from config import Settings
from db.models import (
    AnsibleJob,
    Credential,
    CredentialRole,
    JobStatus,
)
from models.jobs_model import (
    AnsibleJobParams,
    AnsibleRunResult,
    CredentialListResponse,
    CredentialResponse,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
    JobSubmitResponse,
)
from services.ansible_service import AnsibleError, AnsibleService

logger = logging.getLogger(__name__)


class AnsibleJobService:
    """Manages the full lifecycle of Ansible jobs.

    The in-process ``AsyncJobQueue`` is injected separately and started in the
    FastAPI lifespan via::

        await job_queue.start(job_service._process_job)

    ``AnsibleJobService`` does not hold a reference to the queue; the controller
    layer passes it into ``submit()`` for enqueuing.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        ansible_service: AnsibleService,
        host_service=None,  # services.host_service.HostService | None
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._ansible = ansible_service
        self._host_service = host_service

    # ------------------------------------------------------------------
    # HTTP-layer operations
    # ------------------------------------------------------------------

    async def submit(
        self,
        params: AnsibleJobParams,
        job_queue,
    ) -> JobSubmitResponse:
        """Persist a new job and place it on the in-process queue."""
        job_id = str(uuid.uuid4())
        max_retries = (
            params.max_retries
            if params.max_retries is not None
            else self._settings.default_max_retries
        )

        raw_params = dataclasses.asdict(params)

        with self._session_factory() as db:
            job = AnsibleJob(
                id=job_id,
                status=JobStatus.queued.value,
                params=raw_params,
                escrow_uid=params.escrow_uid,
                retry_count=0,
                max_retries=max_retries,
                next_retry_at=None,
            )
            db.add(job)
            db.commit()

        await job_queue.enqueue(job_id)
        return JobSubmitResponse(job_id=job_id, status=JobStatus.queued.value)

    # ------------------------------------------------------------------
    # Retry scheduler — re-enqueue jobs whose backoff delay has elapsed
    # ------------------------------------------------------------------

    async def requeue_due_retries(self, job_queue) -> int:
        """Re-enqueue queued jobs whose scheduled retry time has arrived.

        On a retryable failure ``_process_job`` flips the job back to
        ``queued`` and stamps ``next_retry_at`` for backoff, but does not
        put it back on the in-process queue (which is intentionally
        transient). This sweep finds those jobs once their delay elapses,
        clears ``next_retry_at`` to mark them claimed, and enqueues them.

        Clearing ``next_retry_at`` before enqueue is what prevents a
        double-enqueue: the row no longer matches the due-retry filter on
        the next sweep, and ``_process_job`` flips it to ``running`` when it
        picks it up. ``retry_count`` is untouched, so ``max_retries`` still
        bounds the attempts. Returns the number re-enqueued.
        """
        now = datetime.utcnow()
        with self._session_factory() as db:
            due = (
                db.query(AnsibleJob)
                .filter(
                    AnsibleJob.status == JobStatus.queued.value,
                    AnsibleJob.next_retry_at.isnot(None),
                    AnsibleJob.next_retry_at <= now,
                )
                .all()
            )
            job_ids = [job.id for job in due]
            for job in due:
                job.next_retry_at = None
            if job_ids:
                db.commit()

        for job_id in job_ids:
            await job_queue.enqueue(job_id)
            logger.info("Retry scheduler re-enqueued job %s", job_id)
        return len(job_ids)

    async def run_retry_scheduler(
        self, job_queue, poll_interval_seconds: float
    ) -> None:
        """Long-lived loop: sweep for due retries every poll interval.

        Started as an asyncio task in the FastAPI lifespan; exits cleanly on
        cancellation.
        """
        logger.info(
            "Retry scheduler started (interval=%.0fs)", poll_interval_seconds
        )
        while True:
            try:
                await asyncio.sleep(poll_interval_seconds)
                await self.requeue_due_retries(job_queue)
            except asyncio.CancelledError:
                logger.info("Retry scheduler cancelled")
                break
            except Exception as exc:
                logger.exception("Retry scheduler sweep failed: %s", exc)

    def list_jobs(
        self,
        offset: int = 0,
        limit: int = 20,
        status_filter: str | None = None,
        sort: str = "created_at_desc",
        escrow_uid: str | None = None,
    ) -> JobListResponse:
        sort_map = {
            "created_at_asc": AnsibleJob.created_at.asc(),
            "created_at_desc": AnsibleJob.created_at.desc(),
        }
        with self._session_factory() as db:
            query = db.query(AnsibleJob)
            if status_filter:
                query = query.filter(AnsibleJob.status == status_filter)
            if escrow_uid:
                query = query.filter(AnsibleJob.escrow_uid == escrow_uid)
            total = query.count()
            order_fn = sort_map.get(sort, sort_map["created_at_desc"])
            jobs = query.order_by(order_fn).offset(offset).limit(limit).all()
            return JobListResponse(
                jobs=[self._to_status_response(j) for j in jobs],
                total=total,
                offset=offset,
                limit=limit,
            )

    def get_job(self, job_id: str) -> JobStatusResponse:
        """Return full job status. Raises LookupError for 404."""
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")
            return self._to_status_response(job)

    def get_credentials(self, job_id: str) -> CredentialListResponse:
        """Return all credentials for a job. Raises LookupError for 404.

        The provisioning service trusts its caller (the storefront); the
        storefront decides which credentials to surface to which tenant.
        """
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")

            creds = (
                db.query(Credential)
                .filter(Credential.job_id == job_id)
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

    def get_logs(self, job_id: str) -> JobLogsResponse:
        """Return raw Ansible logs for a job."""
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")

            return JobLogsResponse(job_id=job.id, status=job.status, logs=job.logs)

    def cancel_job(self, job_id: str) -> dict:
        """Cancel a queued or running job. Sends SIGTERM if Ansible is running."""
        with self._session_factory() as db:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                raise LookupError(f"Job {job_id} not found")

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
                    logger.info("Sent SIGTERM to process %d for job %s", pid, job_id)
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
    # Job processor -- passed as handler to AsyncJobQueue.start()
    # ------------------------------------------------------------------

    async def _process_job(self, job_id: str) -> None:
        """Execute a single Ansible job end-to-end.

        This is the ``handler`` argument to ``AsyncJobQueue.start()``.
        ``AsyncJobQueue`` owns concurrency and task dispatch; this method
        owns all DB state transitions, playbook invocation, retry scheduling,
        log streaming, and credential storage.
        """
        db = self._session_factory()
        rendered_inv_path = None
        try:
            job = (
                db.query(AnsibleJob)
                .filter(AnsibleJob.id == job_id)
                .one_or_none()
            )
            if not job:
                logger.warning("Job %s not found", job_id)
                return

            # Respect scheduled retry delay: if the job's next_retry_at is in
            # the future just return; the retry scheduler (run_retry_scheduler)
            # re-enqueues it once the delay elapses.
            if job.next_retry_at and datetime.utcnow() < job.next_retry_at:
                return

            logger.info(
                "Processing job %s (attempt %d/%d)",
                job_id,
                job.retry_count + 1,
                job.max_retries + 1,
            )

            self._update_job(db, job, status=JobStatus.running.value)
            params = self._build_params(job.params)
            vars_path = self._ansible.build_vars_file(params)

            # Resolve inventory: prefer DB-backed rendering when HostService
            # is wired and has a row for this host. rendered_inv_path is
            # initialised before the try block so the outer finally block can
            # always clean it up, including early returns.
            host_public_host = None
            if self._host_service is not None:
                host = self._host_service.get_host(params.vm_host)
                if host is not None:
                    host_public_host = host.public_host
                    rendered_inv_path = self._ansible.write_inventory([host])
                    logger.debug(
                        "Job %s: using DB-rendered inventory at %s",
                        job_id,
                        rendered_inv_path,
                    )

            inventory_path = (
                rendered_inv_path
                if rendered_inv_path is not None
                else self._settings.resolved_inventory_path
            )

            run = self._ansible.start_playbook(
                playbook_path=self._settings.resolved_playbook_path,
                inventory_path=inventory_path,
                extra_vars_path=vars_path,
                limit=params.vm_host,
            )
            # Inject params onto the run handle so ProgrammableMockAnsibleService
            # can match rules in wait_for_playbook. Real AnsibleRun ignores it.
            run._params = params  # type: ignore[attr-defined]
            self._update_job(
                db, job, status=JobStatus.running.value, process_id=str(run.process_id)
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
                    logger.warning("Failed to update logs for job %s: %s", job_id, e)

            try:
                ansible_result = await self._ansible.wait_for_playbook(
                    run,
                    timeout_seconds=self._settings.ansible_timeout_seconds,
                    log_callback=log_callback,
                )
                run_result: AnsibleRunResult = self._ansible.parse_playbook_result(
                    ansible_result, params, public_host=host_public_host
                )
                logs = run_result.stdout + (
                    "\n\nSTDERR:\n" + run_result.stderr if run_result.stderr else ""
                )
                logs = self._redact_logs(logs)
                result_payload = self._build_result_payload(run_result)
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

            except AnsibleError as exc:
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
                    next_retry_at = datetime.utcnow() + timedelta(seconds=retry_delay)
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
                    # The job now sits in `queued` with next_retry_at set;
                    # run_retry_scheduler re-enqueues it once the delay elapses.
                    logger.warning(
                        "Job %s failed (attempt %d/%d), retry at %s: %s",
                        job_id,
                        job.retry_count,
                        job.max_retries + 1,
                        next_retry_at,
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
                # The error may have come from a failed flush/commit (e.g. an
                # IntegrityError while storing credentials), which leaves the
                # session in an aborted transaction. Roll back first so the
                # recovery query/update below can run instead of silently
                # re-raising and leaving the job stuck in `running`.
                db.rollback()
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
                logger.exception(
                    "Failed to mark job %s as failed after an unexpected error",
                    job_id,
                )
        finally:
            # Clean up the DB-rendered temp inventory file if one was created.
            if rendered_inv_path is not None:
                try:
                    rendered_inv_path.unlink(missing_ok=True)
                except Exception as _exc:
                    logger.warning("Failed to remove temp inventory %s: %s", rendered_inv_path, _exc)
            db.close()
            # Notify ProgrammableMockAnsibleService that this job has reached a
            # terminal state so wait_for_job can fire an event instead of polling.
            # No-op on the real AnsibleService which does not have this method.
            notify = getattr(self._ansible, "notify_job_done", None)
            if notify is not None:
                notify(job_id)

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

    def _build_params(self, params: dict) -> AnsibleJobParams:
        """Reconstruct an ``AnsibleJobParams`` from the DB JSON params column."""
        return AnsibleJobParams(
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
            max_retries=params.get("max_retries"),
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

        def _store_role(role_name: str, role_data: dict) -> None:
            if not role_data:
                return
            cred = Credential(
                job_id=job.id,
                role=role_name,
                password=role_data.get("password"),
                ssh_commands=role_data.get("ssh_commands"),
                ssh_key_path_host=role_data.get("ssh_key_path_host"),
                key_type=role_data.get("key_type"),
            )
            db.add(cred)

        _store_role(CredentialRole.root.value, auth.get("root", {}))
        _store_role(CredentialRole.tenant.value, auth.get("tenant", {}))

        sanitized.pop("authentication", None)
        if isinstance(sanitized.get("ansible_result"), dict):
            sanitized["ansible_result"].pop("authentication", None)

        return sanitized

    def _build_result_payload(self, result: AnsibleRunResult) -> dict:
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

        for key in ("gpu", "network", "vm_ip_internal", "vm_state",
                    "result_message", "note", "operation_initiated"):
            if ar.get(key):
                payload[key] = ar[key]

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
    def _to_status_response(job: AnsibleJob) -> JobStatusResponse:
        return JobStatusResponse(
            job_id=job.id,
            status=job.status,
            params=job.params,
            result=job.result,
            error=job.error,
            retry_count=job.retry_count,
            max_retries=job.max_retries,
            next_retry_at=job.next_retry_at,
            escrow_uid=job.escrow_uid,
        )