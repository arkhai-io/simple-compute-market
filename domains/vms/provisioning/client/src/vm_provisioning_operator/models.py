"""Typed request and response models for the Arkhai provisioning service REST API.

These models are the direct VM operator HTTP contract. The host, job, and
aggregate health and version models are compute provisioning's and are
re-exported here, so existing imports receive the compute-owned models and the
wire shapes do not change.

Internal server-only types (``AnsibleJobParams``, ``AnsibleRunResult``,
``build_simple_params``, ``EvaluateJobRequest``, ``EvaluateJobResponse``) remain
in the service wheel and are not part of this public surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from compute_provisioning.hosts import (
    HostCreate,
    HostListResponse,
    HostResponse,
    HostUpdate,
)
from compute_provisioning.jobs import (
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
    JobSubmitResponse,
)
from compute_provisioning.system_models import HealthResponse, VersionResponse
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Host registry
# ---------------------------------------------------------------------------


class HostConnectivityResponse(BaseModel):
    """Response from ``GET /api/v1/hosts/{host}/connectivity``.

    The endpoint always returns 200 — ``reachable`` carries the actual
    result.  Returns 404 if ``host`` is not registered.
    """

    host: str = Field(description="Host alias that was tested.")
    reachable: bool = Field(
        description="True if Ansible could authenticate and execute on the host."
    )
    detail: str = Field(
        description="Ansible stdout on success, or the error message on failure."
    )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class CredentialResponse(BaseModel):
    """A single credential (one role) for a job."""

    role: str = Field(description="Credential role: 'root' or 'tenant'")
    password: Optional[str] = Field(default=None, description="Login password")
    ssh_commands: Optional[dict] = Field(
        default=None, description="SSH connection commands (external/internal)"
    )
    ssh_key_path_host: Optional[str] = Field(
        default=None, description="Path to SSH key on the host"
    )
    key_type: Optional[str] = Field(
        default=None, description="SSH key type (e.g. 'provided')"
    )


class CredentialListResponse(BaseModel):
    """All credentials for a job, one entry per role."""

    job_id: str = Field(description="Unique job identifier")
    credentials: list[CredentialResponse] = Field(
        description="Every role's credentials for the job"
    )


# ---------------------------------------------------------------------------
# VM operations — request models
# ---------------------------------------------------------------------------


class VmActionRequest(BaseModel):
    """Optional body fields shared by all single-target VM operations.

    ``host`` and ``vm_name`` come from the URL path; this model contains
    only the override/metadata fields that have no path equivalent.
    """

    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        le=10,
        description="Per-job retry limit override (default from service config)",
    )


class CreateVmRequest(BaseModel):
    """Provision a new KVM virtual machine on the host identified in the URL.

    ``POST /api/v1/hosts/{host}/vms``

    Returns a ``JobSubmitResponse`` containing a ``job_id``.
    Poll ``GET /api/v1/jobs/{job_id}`` for status.

    On success, ``result`` contains SSH connection details and, if FRP is
    configured, the external tunnel address.

    Credentials (root + tenant) are stored separately and accessible via
    ``GET /api/v1/jobs/{job_id}/credentials``.
    """

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vm_target": "agent-vm-01",
                    "vm_ram": 4096,
                    "vm_vcpus": 2,
                    "vm_disk_size": "20G",
                    "ssh_pubkey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...",
                    "gpu_provisioned": True,
                    "relay_id": "site-a",
                    "vm_remote_port": 6100,
                }
            ]
        }
    }

    vm_target: str = Field(description="VM name to assign (libvirt domain name)")
    image_setup_type: Literal["scratch", "golden"] = Field(
        default="scratch",
        description=(
            "'scratch' boots from the base Ubuntu cloud image. "
            "'golden' clones from a pre-built qcow2 image stored in GCS — "
            "requires golden_* config keys to be set in the service config."
        ),
    )

    # Sizing
    vm_ram: Optional[int] = Field(
        default=None, ge=512, le=32768, description="RAM in MB"
    )
    vm_vcpus: Optional[int] = Field(
        default=None, ge=1, le=20, description="Virtual CPUs"
    )
    vm_disk_size: Optional[str] = Field(
        default=None, pattern=r"^\d+[GMTgmt]$", description="Disk size e.g. '20G'"
    )
    vm_os_variant: Optional[str] = Field(
        default=None,
        description="OS variant hint for virt-install (e.g. 'ubuntu22.04')",
    )

    # Tenant SSH
    ssh_pubkey: Optional[str] = Field(
        default=None,
        description=(
            "Tenant SSH public key injected into the VM at creation. "
            "If omitted, an SSH keypair is generated and the private key "
            "stored in the job credentials."
        ),
    )

    # GPU passthrough
    gpu_provisioned: Optional[bool] = Field(
        default=None, description="Enable GPU passthrough"
    )
    vm_gpu_count: Optional[int] = Field(
        default=None, ge=1, description="Number of GPUs to auto-select"
    )
    vm_gpu_device: Optional[str] = Field(
        default=None, description="Single GPU PCI address (e.g. '0000:03:00.0')"
    )
    vm_gpu_devices: Optional[list[str]] = Field(
        default=None,
        description="Multiple GPU PCI addresses for multi-GPU passthrough",
    )
    vm_gpu_partition_size: Optional[str] = Field(
        default=None, description="MIG or SR-IOV partition size (e.g. '1g.5gb')"
    )

    # Relay tunnelling. Relay-neutral names: the buyer receives a host and a
    # port and has no reason to learn which relay implementation produced them.
    relay_id: Optional[str] = Field(
        default=None,
        description=(
            "Which registered relay this VM is reached through. A reference, "
            "not an endpoint: the address and the admission token are resolved "
            "from the relay at execution, so a token rotated after this request "
            "was accepted still reaches the job, and no credential is written "
            "into the job's persisted parameters — which the job endpoints "
            "return. Requires vm_remote_port."
        ),
    )
    vm_remote_port: Optional[int] = Field(
        default=None,
        description=(
            "Remote port to bind on the relay for this VM. Leased by the "
            "provisioning service before dispatch; the playbook applies what "
            "it is given and selects nothing, because a port binds a listening "
            "socket on the relay and only one authority can avoid collisions."
        ),
    )

    # Golden image overrides (create + golden mode only)
    golden_image_name: Optional[str] = Field(
        default=None,
        description=(
            "Override the golden image name from service config. "
            "Only used when image_setup_type='golden'."
        ),
    )
    gcs_bucket_url: Optional[str] = Field(
        default=None, description="GCS bucket URL to download the golden image from"
    )
    gcs_image_path: Optional[str] = Field(
        default=None,
        description="Path within the GCS bucket to the golden image",
    )

    # Shared overrides
    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        le=10,
        description="Per-job retry limit override (default from service config)",
    )

    @model_validator(mode="after")
    def _validate_relay(self) -> "CreateVmRequest":
        """A relay address with nothing to go with it produces an unreachable VM.

        The failure being prevented is a partial relay configuration that
        selects neither access path: the VM is created, no external route
        exists, and the job reports success.
        """
        if not self.relay_id:
            return self
        if not self.vm_remote_port:
            raise ValueError("vm_remote_port is required when relay_id is set")
        return self


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------


class LeaseCreate(BaseModel):
    """Body accepted by ``POST /api/v1/leases``."""

    resource_id: str = Field(
        description=(
            "Storefront-assigned resource identifier (e.g. 'compute-kvm1-001'). "
            "Treated as an opaque string; the provisioning service does not "
            "validate it against any local table."
        )
    )
    capacity_reservation_id: Optional[str] = Field(
        default=None,
        description=(
            "Storefront compute reservation identifier when the lease consumes "
            "part of a larger resource pool. Omitted for legacy whole-resource leases."
        ),
    )
    escrow_uid: str = Field(
        description="On-chain escrow UID from the deal. Unique per lease."
    )
    host_id: str = Field(
        description="KVM host alias (Ansible inventory name, e.g. 'kvm1')."
    )
    vm_target: str = Field(
        description="Libvirt domain name of the provisioned VM (e.g. 'tenant-a3f2')."
    )
    lease_start_utc: Optional[datetime] = Field(
        default=None,
        description=(
            "UTC datetime when the lease becomes active. "
            "None means the lease is active immediately on creation."
        ),
    )
    lease_end_utc: datetime = Field(
        description="UTC datetime when the lease expires and the VM should be torn down."
    )
    create_job_id: Optional[str] = Field(
        default=None,
        description=(
            "Provisioning job_id of the VM creation job. "
            "Allows tracing from lease back to the original create job."
        ),
    )


class LeaseUpdate(BaseModel):
    """Body accepted by ``PATCH /api/v1/leases/{lease_id}``.

    All fields are optional; only non-None fields are written to the
    reservation.  State transitions are performed via dedicated action endpoints.
    """

    host_id: Optional[str] = Field(
        default=None,
        description="KVM host alias — update when a VM migrates to a different host.",
    )
    vm_target: Optional[str] = Field(
        default=None,
        description="Libvirt domain name — update if the VM was renamed.",
    )
    lease_start_utc: Optional[datetime] = Field(
        default=None,
        description="Override the lease start time.",
    )
    lease_end_utc: Optional[datetime] = Field(
        default=None,
        description=(
            "Override the lease expiry time (extend or shorten).  "
            "Setting this to the past causes the watchdog to begin teardown "
            "on its next cycle; combine with "
            "``POST /api/v1/system/check-leases`` for an immediate trigger."
        ),
    )
    release_job_id: Optional[str] = Field(
        default=None,
        description=(
            "The reservation's release handle. For a VM this is the durable "
            "fulfillment_id of the teardown, which is what teardown status is "
            "read by."
        ),
    )
    create_job_id: Optional[str] = Field(
        default=None,
        description="Provisioning job_id of the VM creation job.",
    )


class LeaseTerminateRequest(BaseModel):
    """Body accepted by ``POST /api/v1/leases/{lease_id}/terminate``."""

    reason: Optional[str] = Field(
        default=None,
        description="Optional operator reason for terminating the lease early.",
    )
    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional retry override reserved for the vm_remove job.",
    )


class LeaseReleaseOversightRequest(BaseModel):
    """Body accepted by ``POST /api/v1/leases/{lease_id}/release-oversight``."""

    reason: str = Field(
        min_length=1,
        description=(
            "Required operator reason. Releases provisioning-service lifecycle "
            "oversight without deleting the VM or releasing capacity."
        ),
    )


class LeaseRetryReleaseRequest(BaseModel):
    """Body accepted by ``POST /api/v1/admin/leases/{lease_id}/retry-release``."""

    reason: Optional[str] = Field(
        default=None,
        description=(
            "Optional admin reason for retrying teardown after release_failed. "
            "Retries submit the provisioning service release operation again."
        ),
    )
    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional retry override reserved for the release job.",
    )


class LeaseForceReleaseRequest(BaseModel):
    """Body accepted by ``POST /api/v1/admin/leases/{lease_id}/force-release``."""

    reason: str = Field(
        min_length=1,
        description=(
            "Required admin reason. Force-release bypasses teardown proof and "
            "asserts capacity is safe to resell."
        ),
    )
    evidence: Optional[str] = Field(
        default=None,
        description=(
            "Optional operational evidence such as host inspected, VM absent, "
            "or disks manually removed."
        ),
    )


class LeaseResponse(BaseModel):
    """Serialised lease row returned by all lease endpoints."""

    id: str
    resource_id: str
    capacity_reservation_id: Optional[str] = None
    escrow_uid: str
    host_id: str
    vm_target: str
    lease_start_utc: Optional[datetime] = None
    lease_end_utc: datetime
    status: str
    create_job_id: Optional[str] = None
    #: The reservation's release handle, set once release begins. For a VM
    #: this is the durable ``fulfillment_id`` of the teardown aggregate, which
    #: is what a caller needs to read teardown status -- not an Ansible queue
    #: job id.
    release_job_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeaseListResponse(BaseModel):
    """Response body for ``GET /api/v1/leases``."""

    leases: list[LeaseResponse]
    total: int


# ---------------------------------------------------------------------------
# System diagnostics
# ---------------------------------------------------------------------------


class FileInfo(BaseModel):
    path: str = Field(description="Absolute (expanded) filesystem path")
    exists: bool
    sha256: Optional[str] = Field(
        default=None,
        description="SHA-256 hex digest of the file contents (None if file absent)",
    )


class InventoryInfo(BaseModel):
    """Host inventory diagnostics.

    ``source`` is ``'database'`` when inventory is read from the ``hosts``
    table (normal operation) or ``'file'`` for a legacy INI path.
    ``host_count`` is the number of enabled hosts found.
    ``path`` is the DB URL or file path, for informational purposes.
    """

    source: str = Field(description="'database' or 'file'")
    path: str = Field(description="DB URL or inventory file path")
    exists: bool = Field(description="True if the source is reachable")
    host_count: Optional[int] = Field(
        default=None,
        description="Number of enabled hosts (None if source is unreadable)",
    )


class SshKeyInfo(BaseModel):
    key_type: str = Field(description="'path' or 'embedded'")
    raw_path: str = Field(
        description=(
            "For 'path': the configured key path. "
            "For 'embedded': '<encrypted>' sentinel."
        ),
    )
    path: str = Field(description="Expanded path (path-type) or '<encrypted>'")
    exists: bool = Field(
        description=(
            "For 'path': whether the key file exists on disk. "
            "For 'embedded': always True (key is stored in DB)."
        )
    )
    sha256: Optional[str] = Field(
        default=None,
        description=(
            "SHA-256 of the key file (path-type only; None for embedded or absent files)."
        ),
    )
    referenced_by: list[str] = Field(
        description="Host aliases that use this key configuration.",
    )


class AnsibleReadinessResponse(BaseModel):
    ansible_version: Optional[str] = Field(
        default=None,
        description="ansible --version first line (None if ansible not on PATH)",
    )
    ansible_mode: str = Field(
        default="real",
        description=(
            "'mock' when ACTIVE_PROFILES includes 'mock' (ProgrammableMockAnsibleService); "
            "'real' otherwise (AnsibleService). Used by e2e tests to gate on mock mode."
        ),
    )
    executor_modes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "'mock' or 'real' per offering mode, from the job executors compute "
            "provisioning composed. Empty before composition."
        ),
    )
    inventory: InventoryInfo
    playbook: FileInfo
    ssh_keys: list[SshKeyInfo] = Field(
        description=(
            "SSH key diagnostics per unique key reference across all enabled hosts."
        )
    )


__all__ = [
    "AnsibleReadinessResponse",
    "CreateVmRequest",
    "CredentialListResponse",
    "CredentialResponse",
    "FileInfo",
    "HealthResponse",
    "HostConnectivityResponse",
    "HostCreate",
    "HostListResponse",
    "HostResponse",
    "HostUpdate",
    "InventoryInfo",
    "JobListResponse",
    "JobLogsResponse",
    "JobStatusResponse",
    "JobSubmitResponse",
    "LeaseCreate",
    "LeaseForceReleaseRequest",
    "LeaseListResponse",
    "LeaseReleaseOversightRequest",
    "LeaseResponse",
    "LeaseRetryReleaseRequest",
    "LeaseTerminateRequest",
    "LeaseUpdate",
    "SshKeyInfo",
    "VersionResponse",
    "VmActionRequest",
]
