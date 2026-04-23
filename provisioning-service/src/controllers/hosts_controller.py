"""KVM host controller.

Handles host-level operations:

    GET  /api/v1/hosts                       List inventory hosts
    GET  /api/v1/hosts/{host}/capacity       Submit a host capacity check job
    GET  /api/v1/hosts/{host}/connectivity   Run ansible -m ping

VM operations scoped to a host live in ``VmController``
(``/api/v1/hosts/{host}/vms/...``), which is registered independently in
``main.py``.  The two routers compose into the ``/hosts/{host}/...``
hierarchy there.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_utils.cbv import cbv

import container as _container_module
from models.ansible import ConnectivityResult, InventoryResponse
from models.jobs_model import JobSubmitResponse
from models.vm_request_model import VmActionRequest, build_simple_params
from services.ansible_service import AnsibleService
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
    ) -> None:
        self._ansible = ansible_service
        self._job_service = job_service

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    @router.get(
        "/",
        response_model=InventoryResponse,
        summary="List KVM hosts from inventory",
    )
    def list_hosts(
        self,
        search: str | None = None,
    ) -> InventoryResponse:
        """Return all KVM hosts from the Ansible inventory file.

        ``search`` is an optional case-insensitive substring filter on the
        host alias.

        Returns **404** if the inventory file does not exist at the
        configured path.

        NYI(Item 2 long-term): once the database-backed host registry is
        implemented, this endpoint will query the ``hosts`` table instead
        of parsing the inventory file.  The response shape will remain
        compatible.
        """
        try:
            return self._ansible.get_inventory(search=search)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

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

        Reports vCPU, RAM, and GPU inventory.  Useful for pre-flight capacity
        checking before submitting a ``create`` job.

        NYI(Item 2 long-term): once the database-backed host registry is
        implemented, capacity data will be cached per host and this endpoint
        will return a synchronous snapshot with a ``last_updated`` timestamp,
        falling back to a fresh Ansible job if the cache is stale.

        """ + _POLL_NOTE + """

        ``result.resources`` contains the capacity breakdown on success.
        """
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

        Exercises the full Ansible auth path: inventory parses correctly,
        the host exists, the SSH key is valid, and Ansible can execute on
        the target.

        Returns **200** with ``reachable: false`` if the host is unreachable
        (not a 4xx error — the result itself is diagnostic information).
        Returns **404** if ``host`` is not found in the inventory.
        """
        try:
            hosts = self._ansible.parse_inventory(search=host)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        if not any(h.name == host for h in hosts):
            raise HTTPException(
                status_code=404,
                detail=f"Host '{host}' not found in inventory",
            )

        return await self._ansible.check_connectivity(host)

    @classmethod
    def make_router(cls) -> APIRouter:
        return router