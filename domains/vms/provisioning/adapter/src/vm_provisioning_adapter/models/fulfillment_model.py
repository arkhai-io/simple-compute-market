"""VM fulfillment request, prepared operation, and provider metadata models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class VmFulfillmentRequirements(BaseModel):
    vm_target: str = Field(min_length=1)
    image_setup_type: str = "scratch"
    vm_ram: int = Field(gt=0)
    vm_vcpus: int = Field(gt=0)
    vm_disk_size: str = Field(min_length=1)
    vm_os_variant: str | None = None
    ssh_pubkey: str = Field(min_length=1)
    gpu_provisioned: bool | None = None
    vm_gpu_count: int | None = Field(default=None, ge=0)
    vm_gpu_device: str | None = None
    vm_gpu_devices: list[str] | None = None
    vm_gpu_partition_size: str | None = None


class AnsiblePoolConfig(BaseModel):
    """Provider-owned execution config, deliberately excluding placement.

    ``inventory_group`` is not consumed here: concrete placement belongs to
    ``PhysicalSettlementScheduler``. Treating an inventory group as placement
    would create a second, conflicting scheduler inside the Ansible adapter.
    """

    playbook_path: str = Field(min_length=1)
    extra_vars: dict[str, Any] = Field(default_factory=dict)


class AnsiblePreparedJobParameters(BaseModel):
    """Validated, JSON-safe snapshot passed to the Ansible executor."""

    vm_host: str = Field(min_length=1)
    vm_action: str = Field(min_length=1)
    vm_target: str | None = None
    executor_kind: str = "vm"
    executor_action: str | None = None
    executor_target: str | None = None
    executor_ref: dict[str, Any] | None = None
    image_setup_type: str = "scratch"
    vm_ram: int | None = None
    vm_vcpus: int | None = None
    vm_disk_size: str | None = None
    vm_os_variant: str | None = None
    ssh_pubkey: str | None = None
    gpu_provisioned: bool | None = None
    vm_gpu_count: int | None = None
    vm_gpu_device: str | None = None
    vm_gpu_devices: list[str] | None = None
    vm_gpu_partition_size: str | None = None
    frp_server_addr: str | None = None
    frp_domain: str | None = None
    frp_dashboard_password: str | None = None
    golden_image_name: str | None = None
    gcs_bucket_url: str | None = None
    gcs_image_path: str | None = None
    escrow_uid: str | None = None
    physical_host_id: str | None = None
    ssh_user: str | None = None
    ssh_public_key: str | None = None
    access_ref: dict[str, Any] | None = None
    bare_metal_reclaim_policy: str | None = None
    max_retries: int | None = None
    playbook_path: str | None = None
    provider_extra_vars: dict[str, Any] = Field(default_factory=dict)


class AnsiblePreparedOperation(BaseModel):
    capacity_reservation_id: str = Field(min_length=1)
    action: Literal["create", "teardown"]
    parameters: AnsiblePreparedJobParameters


class AnsibleFulfillmentMetadata(BaseModel):
    create_job_id: str
    vm_host: str
    vm_target: str
    teardown_job_id: str | None = None
    current_job_id: str
    operation: Literal["create", "teardown"]
