"""Admin/operator VM operations controller.

All VM operations are scoped to a KVM host identified in the URL:

    /api/v1/hosts/{host}/vms/...

``host`` is the Ansible inventory alias for the KVM host (e.g. ``kvm1``).
``vm_name`` is the libvirt domain name of the target VM.

Direct VM operations are admin/operator APIs. Every mutating endpoint
submits an Ansible job and returns a ``JobSubmitResponse`` containing a
``job_id``.  Callers poll
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

from fastapi import APIRouter, Depends, status
from fastapi_utils.cbv import cbv

import container as _container_module
from models.jobs_model import JobSubmitResponse
from models.vm_request_model import CreateVmRequest, VmActionRequest
from services.vm_operations_service import VmOperationsService

router = APIRouter(prefix="/hosts/{host}/vms", tags=["vms"])

_POLL_NOTE = (
    "Poll ``GET /api/v1/jobs/{job_id}`` for status. "
    "Terminal statuses: ``succeeded``, ``failed``, ``cancelled``."
)


@cbv(router)
class VmController:
    def __init__(
        self,
        vm_operations: VmOperationsService = Depends(
            lambda: _container_module.resolved_vm_operations_service
        ),
    ) -> None:
        self._vm_operations = vm_operations

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
    ) -> JobSubmitResponse:
        """Provision a new KVM virtual machine on ``host``.

        Clones from a golden image (``image_setup_type='golden'``) or boots
        from the base Ubuntu cloud image (``'scratch'``, default).

        """ + _POLL_NOTE + """

        On success, ``result`` contains SSH connection details.
        Credentials are stored separately — fetch with
        ``GET /api/v1/jobs/{job_id}/credentials``.
        """
        return await self._vm_operations.create_vm(host=host, body=body)

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
    ) -> JobSubmitResponse:
        """Submit a job to list all KVM virtual machines on ``host``.

        """ + _POLL_NOTE + """

        On success, ``result`` contains the list of VM names and their states.
        """
        return await self._vm_operations.list_vms(host=host, body=body)

    # ------------------------------------------------------------------
    # Single-VM lifecycle actions
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
    ) -> JobSubmitResponse:
        """Start a stopped KVM virtual machine.

        """ + _POLL_NOTE
        return await self._vm_operations.submit_action(
            action="start",
            host=host,
            vm_name=vm_name,
            body=body,
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
    ) -> JobSubmitResponse:
        """Send an ACPI shutdown signal to the VM (graceful).

        Use ``/destroy`` for an immediate force-kill.

        """ + _POLL_NOTE
        return await self._vm_operations.submit_action(
            action="shutdown",
            host=host,
            vm_name=vm_name,
            body=body,
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
    ) -> JobSubmitResponse:
        """Send an ACPI reboot signal to the VM.

        """ + _POLL_NOTE
        return await self._vm_operations.submit_action(
            action="reboot",
            host=host,
            vm_name=vm_name,
            body=body,
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
    ) -> JobSubmitResponse:
        """Force-kill (``virsh destroy``) a running VM.

        This is a libvirt-only power-off.  It does **not** clean up FRP proxy
        entries, iptables rules, GPU passthrough config, disk images, or the
        libvirt domain definition.  Market-managed teardown will be exposed
        through the lease lifecycle API.

        """ + _POLL_NOTE
        return await self._vm_operations.submit_action(
            action="destroy",
            host=host,
            vm_name=vm_name,
            body=body,
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
    ) -> JobSubmitResponse:
        """Remove the VM definition from libvirt.

        Typically paired with ``/destroy`` for libvirt cleanup.  Does not
        remove FRP proxy entries, iptables rules, or disk images on its own.
        Market-managed teardown will be exposed through the lease lifecycle API.

        """ + _POLL_NOTE
        return await self._vm_operations.submit_action(
            action="undefine",
            host=host,
            vm_name=vm_name,
            body=body,
        )

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
    ) -> JobSubmitResponse:
        """Submit a job to collect CPU, memory, disk, and network stats.

        The VM must be in the ``running`` state.

        """ + _POLL_NOTE + """

        On success, ``result.resources`` contains the stats.
        """
        return await self._vm_operations.submit_action(
            action="monitor",
            host=host,
            vm_name=vm_name,
            body=body,
        )

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
    ) -> JobSubmitResponse:
        """Reset the tenant user's SSH password inside the VM.

        Fetch updated credentials via
        ``GET /api/v1/jobs/{job_id}/credentials`` once the job succeeds.
        """
        return await self._vm_operations.submit_action(
            action="reset_password",
            host=host,
            vm_name=vm_name,
            body=body,
        )

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
