"""Internal-only data models for the Ansible job system.

This file retains only the server-internal DTOs that are never exposed
in the OpenAPI schema.

Naming conventions:
  - ``AnsibleJobParams``  — internal DTO built from any typed request and passed
    to ``AnsibleService``.  Not exposed in the OpenAPI schema.
  - ``AnsibleRunResult``  — parsed Ansible playbook output; also internal only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Internal DTO — replaces ProvisionRequest + ProvisioningParams
# ---------------------------------------------------------------------------


@dataclass
class AnsibleJobParams:
    """Structured representation of any Ansible job request for internal use.

    This is the single internal type that flows from ``AnsibleJobService``
    through to ``AnsibleService``.  Typed HTTP request models (in
    ``vm_request_model.py``) each expose a conversion function that
    produces one of these.

    Never serialised directly into the OpenAPI schema.
    """

    vm_host: str
    vm_action: str
    vm_target: Optional[str] = None

    # Domain-neutral executor contract.  ``vm_*`` remains the compatibility
    # alias for the existing VM playbook, mock API, and persisted jobs.
    executor_kind: str = "vm"
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
    frp_server_addr: Optional[str] = None
    frp_domain: Optional[str] = None
    frp_dashboard_password: Optional[str] = None

    # Golden image (create + golden mode)
    golden_image_name: Optional[str] = None
    gcs_bucket_url: Optional[str] = None
    gcs_image_path: Optional[str] = None

    # Deal linkage — on-chain escrow UID for recovery queries
    escrow_uid: Optional[str] = None

    # Bare-metal access jobs (server-internal, used by node_* actions)
    physical_host_id: Optional[str] = None
    ssh_user: Optional[str] = None
    ssh_public_key: Optional[str] = None
    access_ref: Optional[dict[str, Any]] = None
    bare_metal_reclaim_policy: Optional[str] = None

    # Retry policy (per-job override)
    max_retries: Optional[int] = None

    playbook_path: Optional[str] = None
    provider_extra_vars: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.executor_action:
            self.executor_action = self.vm_action
        if self.executor_target is None:
            self.executor_target = self.vm_target or self.vm_host
        if not self.vm_action:
            self.vm_action = self.executor_action


# ---------------------------------------------------------------------------
# Parsed result returned to AnsibleJobService after a playbook completes.
# ---------------------------------------------------------------------------


@dataclass
class AnsibleRunResult:
    """Parsed result returned to AnsibleJobService after a playbook completes."""

    stdout: str
    stderr: str
    ssh_port: Optional[str]
    tenant_user: Optional[str]
    vm_host_ip: Optional[str]
    ssh_command: Optional[str]
    ansible_result: Optional[dict] = None
    process_id: Optional[int] = None
