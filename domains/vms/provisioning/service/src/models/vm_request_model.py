"""Server-side helpers for building internal AnsibleJobParams from VM request models.

``CreateVmRequest`` and ``VmActionRequest`` have moved to
``arkhai-vms-provisioning-client`` (``provisioning_client.models``).

This file retains the server-side conversion helpers that produce the
internal ``AnsibleJobParams`` DTO consumed by ``AnsibleJobService``.
These helpers take path parameters (``host``, ``vm_name``) that come from
URL routing and are never part of the request body.

File naming: ``_model`` suffix marks this as a model definition file.
"""

from __future__ import annotations

from typing import Optional

from models.jobs_model import AnsibleJobParams
from provisioning_client.models import CreateVmRequest, VmActionRequest


def build_create_params(host: str, body: CreateVmRequest) -> AnsibleJobParams:
    """Build ``AnsibleJobParams`` for a VM create action.

    Replaces ``CreateVmRequest.to_ansible_job_params()`` — conversion from
    HTTP request model to server-internal DTO lives here, not on the model,
    because ``AnsibleJobParams`` is a server-private type.
    """
    return AnsibleJobParams(
        vm_host=host,
        vm_action="create",
        vm_target=body.vm_target,
        image_setup_type=body.image_setup_type,
        vm_ram=body.vm_ram,
        vm_vcpus=body.vm_vcpus,
        vm_disk_size=body.vm_disk_size,
        vm_os_variant=body.vm_os_variant,
        ssh_pubkey=body.ssh_pubkey,
        gpu_provisioned=body.gpu_provisioned,
        vm_gpu_count=body.vm_gpu_count,
        vm_gpu_device=body.vm_gpu_device,
        vm_gpu_devices=body.vm_gpu_devices,
        vm_gpu_partition_size=body.vm_gpu_partition_size,
        frp_server_addr=body.frp_server_addr,
        frp_domain=body.frp_domain,
        frp_dashboard_password=body.frp_dashboard_password,
        golden_image_name=body.golden_image_name,
        gcs_bucket_url=body.gcs_bucket_url,
        gcs_image_path=body.gcs_image_path,
        max_retries=body.max_retries,
    )


def build_simple_params(
    action: str,
    host: str,
    body: VmActionRequest,
    vm_name: Optional[str] = None,
) -> AnsibleJobParams:
    """Produce ``AnsibleJobParams`` for actions whose only inputs are the
    path parameters and the shared optional overrides in ``VmActionRequest``.

    ``vm_name`` is ``None`` for host-level actions (list, check).
    """
    return AnsibleJobParams(
        vm_host=host,
        vm_action=action,
        vm_target=vm_name,
        max_retries=body.max_retries,
    )
