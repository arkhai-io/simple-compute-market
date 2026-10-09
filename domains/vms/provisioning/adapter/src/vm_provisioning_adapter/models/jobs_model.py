"""The parameters of a VM job.

``VmJobParams`` is what every VM job, however submitted, stores with the job
authority as its opaque parameters, and what the VM codec turns into the
VM-operations playbook's variables. It is never serialised into the OpenAPI
schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class VmJobParams:
    """One VM job's parameters.

    Typed HTTP request models (in ``vm_request_model.py``) and the VM
    fulfillment provider each build one of these.
    """

    host_id: str
    vm_action: str
    offering_mode: str
    vm_target: Optional[str] = None

    # Domain-neutral executor contract.  ``vm_*`` remains the compatibility
    # alias for the existing VM playbook, mock API, and persisted jobs.
    executor_action: Optional[str] = None
    executor_target: Optional[str] = None
    executor_ref: Optional[dict[str, Any]] = None

    # VM sizing (create only)
    image_setup_type: str = "scratch"
    vm_ram: Optional[int] = None
    vm_vcpus: Optional[int] = None
    vm_disk_size: Optional[str] = None
    vm_os_variant: Optional[str] = None

    # Tenant access
    ssh_pubkey: Optional[str] = None

    # GPU (create only)
    gpu_provisioned: Optional[bool] = None
    vm_gpu_count: Optional[int] = None
    vm_gpu_device: Optional[str] = None
    vm_gpu_devices: Optional[list[str]] = field(default=None)
    vm_gpu_partition_size: Optional[str] = None

    # FRP tunnelling (create only)
    # relay_id and vm_remote_port are what an accepted operation persists.
    # relay_addr/relay_port/relay_token are filled in at execution and are
    # never written to the job's stored parameters — those are returned by the
    # job endpoints, and a rotated token must reach a retry of a job accepted
    # before the rotation. See the relay execution resolver.
    relay_id: Optional[str] = None
    vm_remote_port: Optional[int] = None
    relay_addr: Optional[str] = None
    relay_port: Optional[int] = None
    relay_token: Optional[str] = None

    # Golden image (create + golden mode)
    golden_image_name: Optional[str] = None
    gcs_bucket_url: Optional[str] = None
    gcs_image_path: Optional[str] = None

    # Deal linkage — on-chain escrow UID for recovery queries
    escrow_uid: Optional[str] = None

    # Retry policy (per-job override)
    max_retries: Optional[int] = None

    playbook_path: Optional[str] = None
    provider_extra_vars: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.executor_action:
            self.executor_action = self.vm_action
        if self.executor_target is None:
            self.executor_target = self.vm_target or self.host_id
        if not self.vm_action:
            self.vm_action = self.executor_action

