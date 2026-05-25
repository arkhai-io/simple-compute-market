"""VM lifecycle controller.

All VM operations are scoped to a KVM host identified in the URL:

    /api/v1/hosts/{host}/vms/...

``host`` is the Ansible inventory alias for the KVM host (e.g. ``kvm1``).
``vm_name`` is the libvirt domain name of the target VM.

Every mutating endpoint submits an Ansible job and returns a
``JobSubmitResponse`` containing a ``job_id``.  Callers poll
``GET /api/v1/jobs/{job_id}`` for status.

The provisioning service may sit behind an API gateway — callers must
construct polling URLs from the ``job_id`` alone, not from any URL
embedded in the response.

Router registration
-------------------
This router uses the prefix ``/hosts/{host}/vms`` and is registered in
``main.py`` alongside ``HostController`` under ``/api/v1``::

    app.include_router(VmController.make_router(), prefix="/api/v1")
    app.include_router(HostController.make_router(), prefix="/api/v1")

The resulting URL hierarchy is assembled in ``main.py``, which is the
single explicit source of truth for how the two controllers compose into
the ``/hosts/{host}/...`` tree.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_utils.cbv import cbv

import container as _container_module
from models.jobs_model import JobSubmitResponse
from models.vm_request_model import (
    CreateVmRequest,
    ScheduleVmExpiryRequest,
    VmActionRequest,
    build_simple_params,
)
from services.job_service import AnsibleJobService

router = APIRouter(prefix="/hosts/{host}/vms", tags=["vms"])

_POLL_NOTE = (
    "Poll ``GET /api/v1/jobs/{job_id}`` for status. "
    "Terminal statuses: ``succeeded``, ``failed``, ``cancelled``."
)


@cbv(router)
class VmController:
    def __init__(
        self,
        job_service: AnsibleJobService = Depends(
            lambda: _container_module.resolved_job_service
        ),
    ) -> None:
        self._job_service = job_service

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    @router.post(
        "/",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Create a VM",
    )
    async def create_vm(
        self,
        host: str,
        body: CreateVmRequest,
        request: Request,
    ) -> JobSubmitResponse:
        """Provision a new KVM virtual machine on ``host``.

        Clones from a golden image (``image_setup_type='golden'``) or boots
        from the base Ubuntu cloud image (``'scratch'``, default).

        """ + _POLL_NOTE + """

        On success, ``result`` contains SSH connection details.
        Credentials are stored separately — fetch with
        ``GET /api/v1/jobs/{job_id}/credentials``.
        """
        agent_id: str | None = getattr(request.state, "agent_id", None)
        params = body.to_ansible_job_params(host)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    @router.get(
        "/",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="List VMs on a host",
    )
    async def list_vms(
        self,
        host: str,
        body: VmActionRequest = Depends(),
        request: Request = None,
    ) -> JobSubmitResponse:
        """Submit a job to list all VMs on ``host``.

        NYI(Item 3): will return a synchronous list from the ``vms`` DB
        cache once VM lifecycle tracking is implemented.  Currently submits
        an Ansible ``list`` job.

        """ + _POLL_NOTE + """

        ``result.vms`` contains the list of VM names and states on success.
        """
        agent_id: str | None = getattr(request.state, "agent_id", None) if request else None
        params = build_simple_params("list", host, body)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    # ------------------------------------------------------------------
    # Instance lifecycle
    # ------------------------------------------------------------------

    @router.post(
        "/{vm_name}/start",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Start a stopped VM",
    )
    async def start_vm(
        self,
        host: str,
        vm_name: str,
        body: VmActionRequest,
        request: Request,
    ) -> JobSubmitResponse:
        """Start a stopped VM. """ + _POLL_NOTE
        agent_id: str | None = getattr(request.state, "agent_id", None)
        params = build_simple_params("start", host, body, vm_name)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    @router.post(
        "/{vm_name}/shutdown",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Gracefully shut down a running VM",
    )
    async def shutdown_vm(
        self,
        host: str,
        vm_name: str,
        body: VmActionRequest,
        request: Request,
    ) -> JobSubmitResponse:
        """Send an ACPI shutdown signal to ``vm_name``. """ + _POLL_NOTE
        agent_id: str | None = getattr(request.state, "agent_id", None)
        params = build_simple_params("shutdown", host, body, vm_name)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    @router.post(
        "/{vm_name}/reboot",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Reboot a running VM",
    )
    async def reboot_vm(
        self,
        host: str,
        vm_name: str,
        body: VmActionRequest,
        request: Request,
    ) -> JobSubmitResponse:
        """Reboot ``vm_name``. """ + _POLL_NOTE
        agent_id: str | None = getattr(request.state, "agent_id", None)
        params = build_simple_params("reboot", host, body, vm_name)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    @router.post(
        "/{vm_name}/destroy",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Force-kill a running VM",
    )
    async def destroy_vm(
        self,
        host: str,
        vm_name: str,
        body: VmActionRequest,
        request: Request,
    ) -> JobSubmitResponse:
        """Force-kill ``vm_name`` (equivalent to pulling the power cord).

        Does **not** remove storage or the libvirt definition.
        Use ``POST /{vm_name}/undefine`` to remove the definition afterwards.

        """ + _POLL_NOTE
        agent_id: str | None = getattr(request.state, "agent_id", None)
        params = build_simple_params("destroy", host, body, vm_name)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    @router.post(
        "/{vm_name}/undefine",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Remove a VM definition from libvirt",
    )
    async def undefine_vm(
        self,
        host: str,
        vm_name: str,
        body: VmActionRequest,
        request: Request,
    ) -> JobSubmitResponse:
        """Remove ``vm_name``'s libvirt definition.

        Typically run after ``destroy``.  Does not clean up storage — use
        the lease cleanup script for full VM teardown.

        """ + _POLL_NOTE
        agent_id: str | None = getattr(request.state, "agent_id", None)
        params = build_simple_params("undefine", host, body, vm_name)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @router.get(
        "/{vm_name}/monitor",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Collect resource stats for a running VM",
    )
    async def monitor_vm(
        self,
        host: str,
        vm_name: str,
        body: VmActionRequest = Depends(),
        request: Request = None,
    ) -> JobSubmitResponse:
        """Submit a job to collect CPU, memory, storage, and network stats.

        Requires ``qemu-guest-agent`` inside the VM for guest-side storage
        metrics; host-side metrics are always available.

        NYI(Item 3): future implementations may expose a live stats stream
        (potentially via gRPC) or read from a time-series cache, removing
        the need to submit an Ansible job.

        """ + _POLL_NOTE + """

        ``result.resources`` contains the stats snapshot on success.
        """
        agent_id: str | None = getattr(request.state, "agent_id", None) if request else None
        params = build_simple_params("monitor", host, body, vm_name)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    # ------------------------------------------------------------------
    # Tenant access
    # ------------------------------------------------------------------

    @router.post(
        "/{vm_name}/reset-password",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Reset the tenant user password",
    )
    async def reset_password(
        self,
        host: str,
        vm_name: str,
        body: VmActionRequest,
        request: Request,
    ) -> JobSubmitResponse:
        """Reset the tenant user password on a running VM.

        """ + _POLL_NOTE + """

        New credentials are available via
        ``GET /api/v1/jobs/{job_id}/credentials`` once the job succeeds.
        """
        agent_id: str | None = getattr(request.state, "agent_id", None)
        params = build_simple_params("reset_password", host, body, vm_name)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    # ------------------------------------------------------------------
    # Expiry / lease
    # ------------------------------------------------------------------

    @router.post(
        "/{vm_name}/expiry",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Schedule VM expiry",
    )
    async def schedule_expiry(
        self,
        host: str,
        vm_name: str,
        body: ScheduleVmExpiryRequest,
        request: Request,
    ) -> JobSubmitResponse:
        """Schedule automatic VM destruction at a future UTC datetime.

        NYI(Item 2): will write directly to the ``vm_leases`` DB table once
        the DB-driven lease watchdog is implemented.  Currently submits a
        ``lease_end`` Ansible job that delegates to the KVM host's ``at``
        daemon.

        """ + _POLL_NOTE
        agent_id: str | None = getattr(request.state, "agent_id", None)
        params = body.to_ansible_job_params(host, vm_name)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    @router.delete(
        "/{vm_name}/expiry",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Cancel a scheduled VM expiry",
    )
    async def cancel_expiry(
        self,
        host: str,
        vm_name: str,
        body: VmActionRequest,
        request: Request,
    ) -> JobSubmitResponse:
        """Cancel a previously scheduled VM expiry.

        Finds and removes the ``at`` daemon job on the KVM host tagged
        ``LEASE:<vm_name>``.  Returns a failed job if no pending expiry
        exists (the expiry time has already passed).

        NYI(Item 2): will delete from the ``vm_leases`` DB table once the
        DB-driven lease watchdog is implemented.

        """ + _POLL_NOTE
        agent_id: str | None = getattr(request.state, "agent_id", None)
        params = build_simple_params("lease_remove", host, body, vm_name)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    @classmethod
    def make_router(cls) -> APIRouter:
        return router