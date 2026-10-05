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
``make_vms_router`` builds the router, with the prefix ``/hosts/{host}/vms``,
over an accessor for the VM operations service; the provisioning service mounts
it under ``/api/v1`` when it builds the app, before startup composes the
service, so each request resolves the service through the accessor.
"""

from __future__ import annotations

import hashlib

from collections.abc import Callable

from fastapi import APIRouter, Depends, Request, status
from fastapi_utils.cbv import cbv

from vm_provisioning_operator.models import CreateVmRequest, VmActionRequest
from compute_provisioning_contracts import JobSubmitResponse
from vm_provisioning_adapter.controllers.route_binding import dependency
from vm_provisioning_adapter.services.vm_operations_service import VmOperationsService

_POLL_NOTE = (
    "Poll ``GET /api/v1/jobs/{job_id}`` for status. "
    "Terminal statuses: ``succeeded``, ``failed``, ``cancelled``."
)


def _request_operation_id(
    request: Request,
    *,
    action: str,
    host: str,
    vm_name: str | None = None,
) -> str | None:
    principal = getattr(request.state, "marketplace_principal", None)
    request_id = getattr(request.state, "marketplace_request_id", None)
    if principal is None or not isinstance(request_id, str) or not request_id:
        return None
    material = "\0".join(
        (
            principal.scheme.value,
            principal.identifier,
            request_id,
            action,
            host,
            vm_name or "",
        )
    )
    return "market-request:" + hashlib.sha256(material.encode()).hexdigest()

def make_vms_router(
    vm_operations: Callable[[], VmOperationsService | None],
) -> APIRouter:
    """VM operations over the service ``vm_operations`` resolves per request."""
    router = APIRouter(prefix="/hosts/{host}/vms", tags=["vms"])
    resolve_operations = dependency(vm_operations, "VM operations")

    @cbv(router)
    class VmController:
        def __init__(
            self,
            vm_operations: VmOperationsService = Depends(resolve_operations),
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
            request: Request,
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
            return await self._vm_operations.create_vm(
                host=host,
                body=body,
                operation_id=_request_operation_id(
                    request,
                    action="create",
                    host=host,
                ),
            )

        @router.get(
            "/",
            response_model=JobSubmitResponse,
            status_code=status.HTTP_202_ACCEPTED,
            summary="List VMs on a host",
        )
        async def list_vms(
            self,
            request: Request,
            host: str,
            body: VmActionRequest = Depends(),
        ) -> JobSubmitResponse:
            """Submit a job to list all KVM virtual machines on ``host``.

            """ + _POLL_NOTE + """

            On success, ``result`` contains the list of VM names and their states.
            """
            return await self._vm_operations.list_vms(
                host=host,
                body=body,
                operation_id=_request_operation_id(
                    request,
                    action="list",
                    host=host,
                ),
            )

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
            request: Request,
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
                operation_id=_request_operation_id(
                    request,
                    action="start",
                    host=host,
                    vm_name=vm_name,
                ),
            )

        @router.post(
            "/{vm_name}/shutdown",
            response_model=JobSubmitResponse,
            status_code=status.HTTP_202_ACCEPTED,
            summary="Gracefully shut down a running VM",
        )
        async def shutdown_vm(
            self,
            request: Request,
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
                operation_id=_request_operation_id(
                    request,
                    action="shutdown",
                    host=host,
                    vm_name=vm_name,
                ),
            )

        @router.post(
            "/{vm_name}/reboot",
            response_model=JobSubmitResponse,
            status_code=status.HTTP_202_ACCEPTED,
            summary="Reboot a running VM",
        )
        async def reboot_vm(
            self,
            request: Request,
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
                operation_id=_request_operation_id(
                    request,
                    action="reboot",
                    host=host,
                    vm_name=vm_name,
                ),
            )

        @router.post(
            "/{vm_name}/destroy",
            response_model=JobSubmitResponse,
            status_code=status.HTTP_202_ACCEPTED,
            summary="Force-kill a running VM",
        )
        async def destroy_vm(
            self,
            request: Request,
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
                operation_id=_request_operation_id(
                    request,
                    action="destroy",
                    host=host,
                    vm_name=vm_name,
                ),
            )

        @router.post(
            "/{vm_name}/undefine",
            response_model=JobSubmitResponse,
            status_code=status.HTTP_202_ACCEPTED,
            summary="Remove a VM definition from libvirt",
        )
        async def undefine_vm(
            self,
            request: Request,
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
                operation_id=_request_operation_id(
                    request,
                    action="undefine",
                    host=host,
                    vm_name=vm_name,
                ),
            )

        @router.get(
            "/{vm_name}/monitor",
            response_model=JobSubmitResponse,
            status_code=status.HTTP_202_ACCEPTED,
            summary="Collect resource stats for a running VM",
        )
        async def monitor_vm(
            self,
            request: Request,
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
                operation_id=_request_operation_id(
                    request,
                    action="monitor",
                    host=host,
                    vm_name=vm_name,
                ),
            )

        @router.post(
            "/{vm_name}/reset-password",
            response_model=JobSubmitResponse,
            status_code=status.HTTP_202_ACCEPTED,
            summary="Reset the tenant user password",
        )
        async def reset_password(
            self,
            request: Request,
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
                operation_id=_request_operation_id(
                    request,
                    action="reset_password",
                    host=host,
                    vm_name=vm_name,
                ),
            )

    return router
