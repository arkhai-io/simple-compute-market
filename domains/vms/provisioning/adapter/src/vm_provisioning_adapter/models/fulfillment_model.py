"""VM fulfillment request, prepared operation, and provider metadata models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class VmConnectivitySettings(BaseModel):
    """Buyer-reachability configuration, forwarded to the provider as-is.

    Deliberately not part of ``VmFulfillmentRequirements``' flat field set:
    these aren't sizing/feasibility requirements the provisioning server
    (or, in principle, a future scheduler) would ever reason about — they're
    opaque connectivity metadata the VM provider forwards verbatim to
    Ansible. Storefront-configured for now; a negotiated, buyer-specified
    second source for this same field is a plausible future addition, not
    yet implemented.
    """

    frp_server_addr: str | None = None
    frp_domain: str | None = None
    frp_dashboard_password: str | None = None


class VmFulfillmentRequirements(BaseModel):
    vm_target: str = Field(min_length=1)
    image_setup_type: str = "scratch"
    vm_ram: int | None = Field(default=None, gt=0)
    vm_vcpus: int | None = Field(default=None, gt=0)
    vm_disk_size: str | None = Field(default=None, min_length=1)
    vm_os_variant: str | None = None
    ssh_pubkey: str = Field(min_length=1)
    gpu_provisioned: bool | None = None
    vm_gpu_count: int | None = Field(default=None, ge=0)
    vm_gpu_device: str | None = None
    vm_gpu_devices: list[str] | None = None
    vm_gpu_partition_size: str | None = None
    connectivity: VmConnectivitySettings | None = None


class AnsiblePoolConfig(BaseModel):
    """Validated, snapshotted Ansible provider configuration."""

    playbook_path: str = Field(min_length=1)
    requirement_delegate: str = "vm_management_v1"
    extra_vars: dict[str, Any] = Field(default_factory=dict)
    default_vm_ram: int | None = Field(default=None, gt=0)
    default_vm_vcpus: int | None = Field(default=None, gt=0)
    default_vm_disk_size: str | None = Field(default=None, min_length=1)


class AnsiblePreparedJobParameters(BaseModel):
    """Validated, JSON-safe snapshot passed to the Ansible executor."""

    vm_host: str = Field(min_length=1)
    vm_action: str = Field(min_length=1)
    vm_target: str | None = None
    executor_kind: str = Field(min_length=1)
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
