"""Host import from an Ansible inventory, bound to the Ansible route service."""

from __future__ import annotations

from compute_provisioning_ansible.host_import import AnsibleHostImportRouteService
from compute_provisioning_contracts import HostListResponse
from fastapi import APIRouter, Depends, File, Form, UploadFile

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.controllers.route_errors import routed

router = APIRouter(prefix="/hosts", tags=["hosts"])


def _service() -> AnsibleHostImportRouteService:
    return AnsibleHostImportRouteService(_container_module.resolved_host_authority)


@router.post("/import", response_model=HostListResponse, summary="Import hosts from an Ansible inventory")
async def import_hosts(
    file: UploadFile = File(..., description="Ansible INI inventory file."),
    ssh_key_type: str = Form(
        default="path",
        description=(
            "'path': each host's key file path is stored. 'embedded': the key the "
            "file names is read now and protected before storage."
        ),
    ),
    service: AnsibleHostImportRouteService = Depends(_service),
) -> HostListResponse:
    """Upsert every host the file lists; hosts it does not list are untouched."""
    content = await file.read()
    return routed(lambda: service.import_hosts(content, ssh_key_type))
