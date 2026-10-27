"""VM fulfillment requirements and Ansible pool configuration models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VmConnectivitySettings(BaseModel):
    """Buyer-reachability configuration a request may carry.

    Deliberately not part of ``VmFulfillmentRequirements``' flat field set:
    these aren't sizing/feasibility requirements the provisioning server or
    its scheduler reasons about. The fulfillment plan does not read them: a
    request cannot select a relay, because which relay a host dials comes
    from the relay its pool references, and the buyer's address and port
    come back in the fulfillment result.
    """

    # Relay-neutral names: the buyer receives a host and a port and has no
    # reason to learn which relay implementation produced them.
    relay_addr: str | None = None
    relay_port: int | None = None
    relay_token: str | None = None
    vm_remote_port: int | None = None


class VmFulfillmentRequirements(BaseModel):
    """What a storefront asks of a VM fulfillment.

    It never names the guest: provisioning names it from the capacity
    reservation (see ``vm_provisioning_adapter.guest_names``). Unknown fields
    are refused rather than ignored, so a request naming a guest fails loudly
    instead of being provisioned under a name its sender did not choose.
    """

    model_config = ConfigDict(extra="forbid")

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
    """Validated, snapshotted Ansible provider configuration.

    ``relay_id`` is the pool's own configuration. The four fields beneath it
    are the referenced relay's, present only when this was built from an
    execution read; a redacted read carries the reference alone. They are
    accepted here rather than fetched so that what a job runs against is
    snapshotted with it, as the playbook path and extra vars already are.

    ``playbook_path`` is absent when the pool leaves the playbook to the
    service; the fulfillment plan then freezes the service's configured one.
    """

    playbook_path: str | None = Field(default=None, min_length=1)
    requirement_delegate: str = "vm_management_v1"
    extra_vars: dict[str, Any] = Field(default_factory=dict)
    default_vm_ram: int | None = Field(default=None, gt=0)
    default_vm_vcpus: int | None = Field(default=None, gt=0)
    default_vm_disk_size: str | None = Field(default=None, min_length=1)
    relay_id: str | None = None
    relay_addr: str | None = None
    relay_port: int | None = None
    vm_port_range_start: int | None = None
    vm_port_range_count: int | None = None
    relay_token: str | None = None
