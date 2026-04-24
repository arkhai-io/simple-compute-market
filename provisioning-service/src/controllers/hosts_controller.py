"""KVM host controller.

Handles all host-level operations:

    GET    /api/v1/hosts/                      List registered KVM hosts
    POST   /api/v1/hosts/                      Register a new host
    POST   /api/v1/hosts/import                Bulk-import hosts from an Ansible INI block
    GET    /api/v1/hosts/{host}                Host details
    PUT    /api/v1/hosts/{host}                Update host connection details
    POST   /api/v1/hosts/{host}/enable         Re-enable a disabled host
    POST   /api/v1/hosts/{host}/disable        Disable a host (soft-delete)
    GET    /api/v1/hosts/{host}/capacity       Submit a host capacity check job
    GET    /api/v1/hosts/{host}/connectivity   Run ansible -m ping

VM operations scoped to a host live in ``VmController``
(``/api/v1/hosts/{host}/vms/...``), registered independently in ``main.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_utils.cbv import cbv

import container as _container_module
from models.host_model import (
    HostCreate,
    HostImportRequest,
    HostListResponse,
    HostResponse,
    HostUpdate,
)
from models.ansible import ConnectivityResult
from models.jobs_model import JobSubmitResponse
from models.vm_request_model import VmActionRequest, build_simple_params
from services.ansible_service import AnsibleService
from services.host_service import HostNotFoundError, HostService
from services.job_service import AnsibleJobService

router = APIRouter(prefix="/hosts", tags=["hosts"])

_POLL_NOTE = (
    "Poll ``GET /api/v1/jobs/{job_id}`` for status. "
    "Terminal statuses: ``succeeded``, ``failed``, ``cancelled``."
)


@cbv(router)
class HostController:
    def __init__(
        self,
        ansible_service: AnsibleService = Depends(
            lambda: _container_module.resolved_ansible_service
        ),
        job_service: AnsibleJobService = Depends(
            lambda: _container_module.resolved_job_service
        ),
        host_service: HostService = Depends(
            lambda: _container_module.resolved_host_service
        ),
    ) -> None:
        self._ansible = ansible_service
        self._job_service = job_service
        self._host_service = host_service

    # ------------------------------------------------------------------
    # Host list
    # ------------------------------------------------------------------

    @router.get(
        "/",
        response_model=HostListResponse,
        summary="List registered KVM hosts",
    )
    def list_hosts(
        self,
        search: str | None = None,
        include_disabled: bool = False,
    ) -> HostListResponse:
        """Return all KVM hosts from the host registry database.

        ``search`` is an optional case-insensitive substring filter on the
        host alias. ``include_disabled`` includes disabled hosts when True.
        """
        hosts = self._host_service.list_hosts(
            search=search,
            enabled_only=not include_disabled,
        )
        return HostListResponse(hosts=[HostResponse.model_validate(h) for h in hosts])

    # ------------------------------------------------------------------
    # Host registration
    # ------------------------------------------------------------------

    @router.post(
        "/",
        response_model=HostResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Register a new KVM host",
    )
    def register_host(self, body: HostCreate) -> HostResponse:
        """Register a new KVM host in the host registry.

        ``ssh_key_type='path'``: ``ssh_key_value`` is stored as-is (a
        filesystem path to the private key file).

        ``ssh_key_type='embedded'``: ``ssh_key_value`` must be the raw PEM
        private key content; it is encrypted with ``SSH_DECRYPTION_KEY``
        before storage. ``SSH_DECRYPTION_KEY`` must be set.
        """
        try:
            host = self._host_service.register_host(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            # Catch IntegrityError (duplicate name / PK conflict) and any other
            # DB-level error so they surface as 409 rather than 500.
            err = str(exc).lower()
            if "unique" in err or "primary key" in err or "duplicate" in err or "integrity" in err:
                raise HTTPException(
                    status_code=409,
                    detail=f"Host '{body.name}' already exists. Use PUT /hosts/{body.name} to update or POST /hosts/{body.name}/enable to re-enable.",
                )
            raise
        return HostResponse.model_validate(host)

    # ------------------------------------------------------------------
    # INI import
    # ------------------------------------------------------------------

    @router.post(
        "/import",
        response_model=HostListResponse,
        status_code=status.HTTP_200_OK,
        summary="Bulk-import hosts from an Ansible INI inventory block",
    )
    def import_hosts(self, body: HostImportRequest) -> HostListResponse:
        """Parse an Ansible INI inventory block and upsert host rows.

        Upsert semantics (append-only): hosts present in the INI are inserted
        or updated; hosts absent from the INI are not touched.

        The ``[kvm_hosts]`` group and any ungrouped lines are parsed.
        Lines missing ``ansible_host`` or ``ansible_user`` are skipped.

        Returns the full list of upserted hosts.
        """
        try:
            hosts = self._host_service.seed_from_ini(
                body.ini_content, ssh_key_type=body.ssh_key_type
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return HostListResponse(hosts=[HostResponse.model_validate(h) for h in hosts])

    # ------------------------------------------------------------------
    # Single host operations
    # ------------------------------------------------------------------

    @router.get(
        "/{host}",
        response_model=HostResponse,
        summary="Get host details",
    )
    def get_host(self, host: str) -> HostResponse:
        """Return details for a single registered host.

        Returns **404** if the host is not found.
        """
        h = self._host_service.get_host(host)
        if h is None:
            raise HTTPException(status_code=404, detail=f"Host '{host}' not found")
        return HostResponse.model_validate(h)

    @router.put(
        "/{host}",
        response_model=HostResponse,
        summary="Update host connection details",
    )
    def update_host(self, host: str, body: HostUpdate) -> HostResponse:
        """Update mutable fields on a registered host.

        All fields are optional; only supplied fields are updated.
        Returns **404** if the host is not found.
        """
        try:
            h = self._host_service.update_host(host, body)
        except HostNotFoundError:
            raise HTTPException(status_code=404, detail=f"Host '{host}' not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return HostResponse.model_validate(h)

    @router.post(
        "/{host}/enable",
        response_model=HostResponse,
        summary="Re-enable a disabled host",
    )
    def enable_host(self, host: str) -> HostResponse:
        """Set ``enabled=True`` on a host, making it visible in inventory again."""
        try:
            h = self._host_service.enable_host(host)
        except HostNotFoundError:
            raise HTTPException(status_code=404, detail=f"Host '{host}' not found")
        return HostResponse.model_validate(h)

    @router.post(
        "/{host}/disable",
        response_model=HostResponse,
        summary="Disable a host (soft-delete)",
    )
    def disable_host(self, host: str) -> HostResponse:
        """Set ``enabled=False`` on a host.

        Disabled hosts are excluded from inventory rendering and ``GET /hosts/``
        by default. They are never hard-deleted so that job history references
        remain resolvable.
        """
        try:
            h = self._host_service.disable_host(host)
        except HostNotFoundError:
            raise HTTPException(status_code=404, detail=f"Host '{host}' not found")
        return HostResponse.model_validate(h)

    # ------------------------------------------------------------------
    # Capacity
    # ------------------------------------------------------------------

    @router.get(
        "/{host}/capacity",
        response_model=JobSubmitResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Check host resource capacity",
    )
    async def check_capacity(
        self,
        host: str,
        body: VmActionRequest = Depends(),
        request: Request = None,
    ) -> JobSubmitResponse:
        """Submit a job to report total, allocated, and available resources on ``host``.

        Reports vCPU, RAM, and GPU inventory. Useful for pre-flight capacity
        checking before submitting a ``create`` job.

        Returns **404** if the host is not registered.

        """ + _POLL_NOTE + """

        ``result.resources`` contains the capacity breakdown on success.
        """
        if self._host_service.get_host(host) is None:
            raise HTTPException(status_code=404, detail=f"Host '{host}' not found")
        agent_id: str | None = getattr(request.state, "agent_id", None) if request else None
        params = build_simple_params("check", host, body)
        return await self._job_service.submit(
            params, agent_id, _container_module.resolved_job_queue
        )

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    @router.get(
        "/{host}/connectivity",
        response_model=ConnectivityResult,
        summary="Test Ansible connectivity to a host",
    )
    async def check_connectivity(self, host: str) -> ConnectivityResult:
        """Run ``ansible -m ping`` against ``host``.

        Exercises the full Ansible auth path: inventory is correct, the SSH
        key is valid, and Ansible can execute on the target.

        Returns **200** with ``reachable: false`` if the host is unreachable.
        Returns **404** if ``host`` is not registered in the host registry.
        """
        h = self._host_service.get_host(host)
        if h is None:
            raise HTTPException(status_code=404, detail=f"Host '{host}' not found")

        # Render a temp inventory from the DB row so Ansible uses the
        # correct connection details, then run the ping.
        inv_path = self._ansible.write_inventory([h])
        try:
            # Temporarily override the inventory path via a per-call ping
            # using the rendered file.
            return await self._ansible.check_connectivity_with_inventory(host, inv_path)
        finally:
            try:
                inv_path.unlink(missing_ok=True)
            except Exception:
                pass

    @classmethod
    def make_router(cls) -> APIRouter:
        return router