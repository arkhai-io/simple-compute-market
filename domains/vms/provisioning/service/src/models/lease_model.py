"""Pydantic models for the VM lease API.

LeaseCreate  — request body for POST /api/v1/leases
LeaseUpdate  — request body for PATCH /api/v1/leases/{id}
LeaseResponse — serialised view returned by all lease endpoints
LeaseListResponse — wraps a list of LeaseResponse for list queries

The storefront calls POST /api/v1/leases after a VM has been provisioned and
the lease window is known. The provisioning service's LeaseWatchdog enforces
lease expiry by submitting the concrete release operation for this service
(``vm_remove``) and releases capacity only after that job succeeds.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LeaseCreate(BaseModel):
    """Body accepted by ``POST /api/v1/leases``."""

    resource_id: str = Field(
        description=(
            "Storefront-assigned resource identifier (e.g. 'compute-kvm1-001'). "
            "Treated as an opaque string; the provisioning service does not "
            "validate it against any local table."
        )
    )
    allocation_id: Optional[str] = Field(
        default=None,
        description=(
            "Storefront compute allocation identifier when the lease consumes "
            "part of a larger resource pool. Omitted for legacy whole-resource leases."
        ),
    )
    escrow_uid: str = Field(
        description="On-chain escrow UID from the deal. Unique per lease."
    )
    vm_host: str = Field(
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
    allocation.  State transitions (e.g. cancellation) are performed via
    dedicated action endpoints, not via this model.
    """

    vm_host: Optional[str] = Field(
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
    vm_remove_job_id: Optional[str] = Field(
        default=None,
        description="Provisioning job_id for the most recent vm_remove teardown job.",
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
    allocation_id: Optional[str] = None
    escrow_uid: str
    vm_host: str
    vm_target: str
    lease_start_utc: Optional[datetime] = None
    lease_end_utc: datetime
    status: str
    create_job_id: Optional[str] = None
    vm_remove_job_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeaseListResponse(BaseModel):
    """Response body for ``GET /api/v1/leases``."""

    leases: list[LeaseResponse]
    total: int
