import asyncio
import logging

from sqlalchemy.orm import Session

from async_provisioning_service.db.database import SessionLocal, init_db
from async_provisioning_service.db.models import JobStatus, ProvisioningJob
from async_provisioning_service.services.provisioning import PlaybookError, ProvisioningParams, run_playbook
from async_provisioning_service.services.queue import dequeue_job


logger = logging.getLogger(__name__)


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


def _build_params(params: dict) -> ProvisioningParams:
    return ProvisioningParams(
        ssh_pubkey=params["ssh_pubkey"],
        vm_host=params.get("vm_host", "vm1"),
        vm_target=params.get("vm_target", "tenant-vm"),
        vm_action=params.get("vm_action", "create"),
        vm_ram=params.get("vm_ram", 2048),
        vm_vcpus=params.get("vm_vcpus", 2),
        vm_disk_size=params.get("vm_disk_size", "25G"),
    )


async def worker_loop() -> None:
    init_db()
    logger.info("Provisioning worker started")
    while True:
        job_id = await dequeue_job()
        if not job_id:
            await asyncio.sleep(1)
            continue

        db = SessionLocal()
        try:
            job = db.query(ProvisioningJob).filter(ProvisioningJob.id == job_id).one_or_none()
            if not job:
                logger.warning("Job %s not found", job_id)
                continue

            _update_job(db, job, status=JobStatus.running.value)

            params = _build_params(job.params)
            try:
                result = await asyncio.to_thread(run_playbook, params)

                # Store process ID for potential cancellation
                if result.process_id:
                    _update_job(db, job, status=JobStatus.running.value, process_id=str(result.process_id))

            except PlaybookError as exc:
                logs = exc.stdout + ("\n\nSTDERR:\n" + exc.stderr if exc.stderr else "")
                _update_job(
                    db,
                    job,
                    status=JobStatus.failed.value,
                    error=str(exc),
                    logs=logs,
                )
                continue

            logs = result.stdout + ("\n\nSTDERR:\n" + result.stderr if result.stderr else "")
            result_payload = {
                "external_port": result.external_port,
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
        finally:
            db.close()
