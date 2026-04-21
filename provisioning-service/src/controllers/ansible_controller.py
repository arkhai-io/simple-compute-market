from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_utils.cbv import cbv

import container as _container_module
from models.ansible import ConnectivityResult, InventoryResponse
from services.ansible_service import AnsibleService

router = APIRouter(prefix="/ansible", tags=["ansible"])


@cbv(router)
class AnsibleController:
    """Diagnostic endpoints for the Ansible layer.

    Unified into the main API on port 8081 under ``/api/v1/ansible``.
    """

    def __init__(
        self,
        ansible_service: AnsibleService = Depends(lambda: _container_module.resolved_ansible_service),
    ) -> None:
        self._ansible = ansible_service

    @router.get(
        "/inventory",
        response_model=InventoryResponse,
        summary="Search Ansible inventory",
    )
    def get_inventory(
        self,
        search: str | None = Query(
            default=None,
            description=(
                "Filter hosts by name (case-insensitive substring match). "
                "Omit to return all hosts."
            ),
        ),
    ) -> InventoryResponse:
        """Return hosts from the Ansible inventory file.

        Returns **404** if the inventory file does not exist.
        """
        try:
            return self._ansible.get_inventory(search=search)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get(
        "/inventory/{host}/connectivity",
        response_model=ConnectivityResult,
        summary="Check Ansible connectivity to an inventory host",
    )
    async def check_connectivity(self, host: str) -> ConnectivityResult:
        """Run ``ansible -m ping`` against a single inventory host.

        Returns **404** if the host is not found in the inventory.
        Returns **200** with ``reachable: false`` if the host is unreachable.
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